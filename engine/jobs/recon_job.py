# engine/jobs/recon_job.py
import asyncio
import json
import os
import tempfile
from pathlib import Path

from runner import run_script, validate_domain, validate_path_within, proxy_env
from parsers.recon_parser import parse_recon_output, parse_archived_urls
from queue_manager import (
    get_session, transition_status, get_project_domains,
    get_project_asset_hostnames, insert_assets_bulk, merge_crawled_urls_bulk,
    refresh_project_counts,
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./scripts"))
RECON_TIMEOUT = int(os.environ.get("RECON_TIMEOUT", "3600"))
WORDLIST_PATH = os.environ.get("WORDLIST_PATH", str(DATA_DIR / "wordlists" / "dns_wordlist.txt"))
RESOLVERS_PATH = os.environ.get("RESOLVERS_PATH", str(DATA_DIR / "resolvers" / "resolvers.txt"))


async def run_recon_job(job: dict, ws_broadcast=None):
    """
    Execute recon for all root domains of a project.
    Pipeline: runner → recon_parser → DB write → WS emit
    """
    session = get_session()
    job_id = job["id"]
    project_id = job["project_id"]
    project_dir = DATA_DIR / "projects" / project_id
    log_dir = project_dir / "logs"

    try:
        # Mark running
        transition_status(session, job_id, "queued", "running")
        if ws_broadcast:
            await ws_broadcast("job_started", {"job_id": job_id, "scan_type": "recon"})

        # Get root domains — use explicit scope if provided, else all project domains
        scope = job.get("scope_domains")
        if scope:
            domains = scope
        else:
            domains = get_project_domains(session, project_id)
        if not domains:
            transition_status(session, job_id, "running", "failed", error_msg="No root domains configured")
            if ws_broadcast:
                await ws_broadcast("job_failed", {"job_id": job_id, "error": "No root domains"})
            return

        known_subs_path = None
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="nous_known_", delete=False
        ) as tmp:
            known_subs_path = tmp.name
            tmp.write("\n".join(get_project_asset_hostnames(session, project_id)))

        # Read settings from job config (set at enqueue time), fall back to env vars
        cfg = job.get("config") or {}
        recon_timeout = cfg.get("recon_timeout", RECON_TIMEOUT)
        wordlist_path = cfg.get("wordlist_path", WORDLIST_PATH)
        resolvers_path = cfg.get("resolvers_path", RESOLVERS_PATH)
        dns_bruteforce_enabled = cfg.get("dns_bruteforce_enabled", False)
        # Proxy env for HTTP-based recon tools (subfinder, gau, waymore, crt).
        # DNS tooling (puredns) is unaffected — DNS does not traverse an HTTP proxy.
        recon_env = proxy_env(cfg.get("proxy_url"))
        if recon_env and ws_broadcast:
            await ws_broadcast("scan_line", {
                "job_id": job_id,
                "line": "[*] Routing HTTP recon traffic through configured proxy",
            })

        for label, fpath in (("wordlist_path", wordlist_path), ("resolvers_path", resolvers_path)):
            if not validate_path_within(Path(fpath), DATA_DIR):
                transition_status(session, job_id, "running", "failed",
                                  error_msg=f"Unsafe {label}: {fpath}")
                if ws_broadcast:
                    await ws_broadcast("job_failed", {"job_id": job_id, "error": f"Unsafe {label}"})
                return

        output_file = project_dir / "subdomains.txt"
        archived_urls_file = project_dir / "archived_urls.txt"
        result = None
        new_count = 0

        def parse_outputs() -> tuple[list[str], dict[str, set[str]]]:
            """Parse whatever recon has written to disk so far.

            Best-effort: used both on the normal success path and when a run is
            interrupted (timeout/cancel), so it must tolerate missing or partial
            output files.
            """
            subs: list[str] = []
            if output_file.is_file():
                raw = output_file.read_text(encoding="utf-8", errors="replace")
                subs = parse_recon_output(raw)
            elif result is not None:
                subs = parse_recon_output(result.stdout)
            host_paths: dict[str, set[str]] = {}
            try:
                raw_urls = archived_urls_file.read_text(encoding="utf-8", errors="replace")
                for host, paths in parse_archived_urls(raw_urls).items():
                    host_paths.setdefault(host, set()).update(paths)
            except FileNotFoundError:
                pass
            return subs, host_paths

        def persist(subs: list[str], host_paths: dict[str, set[str]]) -> int:
            """Commit recon results immediately. Safe to call repeatedly so that
            assets survive a later timeout/cancel/failure."""
            count = insert_assets_bulk(session, project_id, subs) if subs else 0
            if host_paths:
                merge_crawled_urls_bulk(session, project_id, host_paths, source="archived")
            if subs or host_paths:
                refresh_project_counts(session, project_id)
            return count

        try:
            for raw_domain in domains:
                # Strip wildcard prefix
                domain = raw_domain.lstrip("*.")

                if not validate_domain(domain):
                    continue

                async def line_broadcast(line: str):
                    if ws_broadcast:
                        await ws_broadcast("scan_line", {"job_id": job_id, "line": line})

                script_args = ["-d", domain, "-o", str(output_file), "-w", wordlist_path,
                               "-r", resolvers_path, "-s", known_subs_path]
                if not dns_bruteforce_enabled:
                    script_args.append("-n")
                result = await run_script(
                    script_path=str(SCRIPTS_DIR / "recon.sh"),
                    args=script_args,
                    job_id=job_id,
                    timeout_seconds=recon_timeout,
                    ws_broadcast=line_broadcast,
                    log_dir=log_dir,
                    env=recon_env,
                )

                if result.timed_out:
                    # Persist whatever was found before the timeout fired.
                    new_count += persist(*parse_outputs())
                    transition_status(session, job_id, "running", "timed_out",
                                      duration_s=result.duration_seconds,
                                      log_path=str(log_dir / f"{job_id}.log"))
                    if ws_broadcast:
                        await ws_broadcast("job_failed", {"job_id": job_id, "error": "Timed out"})
                    return

                if result.exit_code != 0:
                    # Persist partial results for this domain before failing out.
                    new_count += persist(*parse_outputs())
                    transition_status(session, job_id, "running", "failed",
                                      error_msg=result.stderr[:500],
                                      duration_s=result.duration_seconds,
                                      log_path=str(log_dir / f"{job_id}.log"))
                    if ws_broadcast:
                        await ws_broadcast("job_failed", {"job_id": job_id, "error": result.stderr[:200]})
                    return

                # Domain finished cleanly — commit its results right away so a
                # cancel/timeout on a later domain cannot discard them.
                new_count += persist(*parse_outputs())
        except asyncio.CancelledError:
            # Manual cancellation — flush whatever the interrupted domain
            # produced before propagating the cancel to the worker.
            try:
                persist(*parse_outputs())
            except Exception:
                pass
            raise

        # Mark done
        transition_status(session, job_id, "running", "done",
                          duration_s=result.duration_seconds if result else None,
                          log_path=str(log_dir / f"{job_id}.log"))

        if ws_broadcast:
            await ws_broadcast("job_complete", {
                "job_id": job_id,
                "scan_type": "recon",
                "project_id": project_id,
                "new_assets": new_count,
            })

    except Exception as e:
        try:
            transition_status(session, job_id, "running", "failed", error_msg=str(e)[:500])
        except Exception:
            pass
        if ws_broadcast:
            await ws_broadcast("job_failed", {"job_id": job_id, "error": str(e)[:200]})
    finally:
        if known_subs_path:
            try:
                os.unlink(known_subs_path)
            except OSError:
                pass
        (project_dir / "archived_urls.txt").unlink(missing_ok=True)
        session.close()
