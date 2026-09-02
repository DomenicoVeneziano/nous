# engine/runner.py
import asyncio
import os
import shutil
import signal
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
import re

# Strict domain validation — prevents command injection
DOMAIN_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')
# Marker a script prefixes to lines meant for the job log only. Diagnostics are
# per-host and high volume: streaming them would drown the live scan UI, and
# accumulating them would grow the returned stdout for no consumer, so they are
# written to the log file and dropped here. scripts/tech_analysis.py repeats the
# same literal deliberately — scripts/ is not importable from the engine's import
# root, so the two copies must be kept in sync by hand.
DIAG_PREFIX = "[diag] "
GRACEFUL_SHUTDOWN_TIMEOUT = int(os.environ.get("GRACEFUL_SHUTDOWN_TIMEOUT", "5"))
# Grace given to processes that escaped the group kill before they are forced.
ESCAPEE_SHUTDOWN_TIMEOUT = float(os.environ.get("ESCAPEE_SHUTDOWN_TIMEOUT", "2"))


def _proc_stat(pid: int) -> tuple[int, int] | None:
    """Return (ppid, starttime) for a pid, or None if it is gone.

    The comm field can contain spaces and parentheses, so parsing resumes
    after the final ')' where the layout is fixed again.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except (OSError, ValueError):
        return None
    tail = data[data.rfind(")") + 2:].split()
    try:
        return int(tail[1]), int(tail[19])
    except (IndexError, ValueError):
        return None


def _descendants(root_pid: int) -> list[tuple[int, int]]:
    """Snapshot (pid, starttime) for every descendant of root_pid.

    Camoufox starts each browser in its own process group *and* session, so the
    killpg in terminate_proc never reaches them: they are orphaned, linger until
    their driver pipe closes, and are left for PID 1 to reap. The parent/child
    chain is still intact while the tree is alive, so it is walked here — before
    any signal is sent — and the survivors are signalled directly afterwards.

    Each pid is paired with its start time so a pid recycled by an unrelated
    process between the snapshot and the kill is never signalled.
    """
    try:
        pids = [int(e) for e in os.listdir("/proc") if e.isdigit()]
    except OSError:
        return []
    info: dict[int, tuple[int, int]] = {}
    for pid in pids:
        stat = _proc_stat(pid)
        if stat is not None:
            info[pid] = stat
    children: dict[int, list[int]] = {}
    for pid, (ppid, _) in info.items():
        children.setdefault(ppid, []).append(pid)
    found: list[tuple[int, int]] = []
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append((child, info[child][1]))
            stack.append(child)
    return found


def _signal_survivors(snapshot: list[tuple[int, int]], sig: int) -> int:
    """Signal pids from a descendant snapshot that are still the same process."""
    signalled = 0
    for pid, starttime in snapshot:
        if pid <= 1:
            continue
        stat = _proc_stat(pid)
        if stat is None or stat[1] != starttime:
            continue  # already exited, or the pid now belongs to something else
        try:
            os.kill(pid, sig)
            signalled += 1
        except (ProcessLookupError, PermissionError):
            pass
    return signalled


@dataclass
class ScriptResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


def validate_domain(domain: str) -> bool:
    """Validate domain name against strict pattern to prevent injection."""
    return bool(DOMAIN_RE.match(domain)) and len(domain) <= 253


def proxy_env(proxy_url: str | None) -> dict[str, str]:
    """Return env vars routing CLI tools' HTTP(S) traffic through the proxy.

    Empty dict when no proxy is configured, so callers pass it unconditionally.
    """
    if not proxy_url:
        return {}
    return {
        "HTTP_PROXY": proxy_url, "HTTPS_PROXY": proxy_url,
        "http_proxy": proxy_url, "https_proxy": proxy_url,
        "ALL_PROXY": proxy_url, "all_proxy": proxy_url,
    }


def validate_path_within(path: Path, base: Path) -> bool:
    """Ensure a path stays within the base directory."""
    try:
        return path.resolve().is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


async def run_script(
    script_path: str,
    args: list[str],
    job_id: str,
    timeout_seconds: int,
    ws_broadcast: Callable[[str], Awaitable[None]] | None = None,
    log_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> ScriptResult:
    """
    Execute a canonical script via subprocess with timeout, logging, and WS streaming.
    Never uses shell=True.

    `env`, if provided, is merged on top of the current process environment for
    the child process (used to inject proxy variables such as HTTP_PROXY).
    """
    start_time = time.time()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    timed_out = False

    # Determine command based on script extension
    script = Path(script_path)
    if script.suffix == ".sh":
        cmd = ["bash", str(script)] + args
    elif script.suffix == ".py":
        cmd = ["python3", str(script)] + args
    else:
        cmd = [str(script)] + args

    # Prepare log file
    log_file = None
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{job_id}.log"
        log_file = open(log_path, "w", encoding="utf-8")

    # Give the script its own TMPDIR so anything it leaves behind — most of all
    # the Playwright/camoufox profile and artifact trees, which survive a hard
    # kill — is removed wholesale in the finally block below rather than
    # accumulating in a shared /tmp for the lifetime of the container.
    run_tmpdir = tempfile.mkdtemp(prefix="nous_run_")
    child_env = {**os.environ, "TMPDIR": run_tmpdir}
    if env:
        child_env.update(env)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            # Detach stdin explicitly. Some tools (e.g. puredns) read their input
            # from stdin whenever it is a non-TTY pipe, which would make them
            # ignore their file arguments (puredns would treat the wordlist path
            # as the domain and bruteforce an empty stdin list). /dev/null gives
            # deterministic behaviour regardless of how the engine is launched.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
            # Run the script as the leader of its own process group/session so we
            # can signal the entire tree on timeout/cancel. The shell scripts
            # spawn long-running children (puredns -> massdns, subfinder, gau,
            # waymore); signalling only the bash PID would leave those grandchild
            # processes orphaned and still running after the job is stopped.
            start_new_session=True,
        )

        async def read_stdout():
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith(DIAG_PREFIX):
                    # Log-only: never accumulated, never broadcast.
                    if log_file:
                        log_file.write(f"[DIAG] {line}\n")
                        log_file.flush()
                    continue
                stdout_lines.append(line)
                if log_file:
                    log_file.write(f"[STDOUT] {line}\n")
                    log_file.flush()
                if ws_broadcast:
                    try:
                        await ws_broadcast(line)
                    except Exception:
                        pass

        async def read_stderr():
            assert proc.stderr is not None
            async for raw_line in proc.stderr:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                stderr_lines.append(line)
                if log_file:
                    log_file.write(f"[STDERR] {line}\n")
                    log_file.flush()

        def _signal_group(sig: int):
            """Signal the script's whole process group, falling back to the
            single process if the group is already gone."""
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except ProcessLookupError:
                pass
            except OSError:
                # Process group unavailable (e.g. leader already reaped) —
                # signal the process directly as a best effort.
                try:
                    proc.send_signal(sig)
                except ProcessLookupError:
                    pass

        async def terminate_proc():
            # Graceful stop of the entire process tree, then force-kill the
            # group if it does not exit within the grace period. The descendant
            # snapshot is taken first, while the parent/child links still exist.
            escapees = _descendants(proc.pid)
            _signal_group(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=GRACEFUL_SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                _signal_group(signal.SIGKILL)
                await proc.wait()
            # Anything that put itself in its own process group outlived the
            # killpg above; signal those directly so no browser survives the job.
            if _signal_survivors(escapees, signal.SIGTERM):
                await asyncio.sleep(ESCAPEE_SHUTDOWN_TIMEOUT)
                _signal_survivors(escapees, signal.SIGKILL)

        try:
            gather = asyncio.gather(read_stdout(), read_stderr(), proc.wait())
            if timeout_seconds > 0:
                await asyncio.wait_for(gather, timeout=timeout_seconds)
            else:
                # 0 means no timeout — run until completion
                await gather
        except asyncio.TimeoutError:
            timed_out = True
            await terminate_proc()
        except asyncio.CancelledError:
            await terminate_proc()
            raise

        exit_code = proc.returncode if proc.returncode is not None else -1

    except FileNotFoundError:
        exit_code = 127
        stderr_lines.append(f"Script not found: {script_path}")
    except Exception as e:
        exit_code = -1
        stderr_lines.append(f"Runner error: {str(e)}")
    finally:
        if log_file:
            log_file.close()
        shutil.rmtree(run_tmpdir, ignore_errors=True)

    duration = time.time() - start_time

    return ScriptResult(
        exit_code=exit_code,
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
        duration_seconds=round(duration, 2),
        timed_out=timed_out,
    )
