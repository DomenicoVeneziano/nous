# engine/runner.py
import asyncio
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
import re

# Strict domain validation — prevents command injection
DOMAIN_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')
GRACEFUL_SHUTDOWN_TIMEOUT = int(os.environ.get("GRACEFUL_SHUTDOWN_TIMEOUT", "5"))


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

    child_env = None
    if env:
        child_env = {**os.environ, **env}

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
        )

        async def read_stdout():
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
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

        async def terminate_proc():
            try:
                proc.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=GRACEFUL_SHUTDOWN_TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass

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

    duration = time.time() - start_time

    return ScriptResult(
        exit_code=exit_code,
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
        duration_seconds=round(duration, 2),
        timed_out=timed_out,
    )
