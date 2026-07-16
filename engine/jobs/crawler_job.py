# engine/jobs/crawler_job.py
import asyncio
import hashlib
import json
import os
from pathlib import Path

from runner import run_script
from parsers.crawler_parser import parse_crawler_output
from queue_manager import (
    get_session, transition_status, get_asset_hostnames,
    get_all_project_asset_details, insert_assets_bulk, merge_crawled_urls_bulk,
    refresh_project_counts,
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./scripts"))
CRAWL_TIMEOUT = int(os.environ.get("CRAWL_TIMEOUT", "1200"))
CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
CRAWL_RATE_LIMIT_DELAY = float(os.environ.get("CRAWL_RATE_LIMIT_DELAY", "0"))


async def run_crawler_job(job: dict, ws_broadcast=None):
    """
    Execute crawler on selected assets.
    Pipeline: runner → crawler_parser → DB write → WS emit
    """
    session = get_session()
    job_id = job["id"]
    project_id = job["project_id"]
    asset_ids = json.loads(job["asset_ids"]) if isinstance(job["asset_ids"], str) else (job["asset_ids"] or [])
    project_dir = DATA_DIR / "projects" / project_id
    log_dir = project_dir / "logs"
    crawl_dir = project_dir / "crawl"

    crawl_dir.mkdir(parents=True, exist_ok=True)

    # Read settings from job config (set at enqueue time), fall back to env vars
    cfg = job.get("config") or {}
    crawl_timeout = cfg.get("crawl_timeout", CRAWL_TIMEOUT)
    crawl_max_pages = cfg.get("crawl_max_pages", CRAWL_MAX_PAGES)
    crawl_rate_limit_delay = cfg.get("crawl_rate_limit_delay", CRAWL_RATE_LIMIT_DELAY)
    proxy_url = cfg.get("proxy_url")

    try:
        transition_status(session, job_id, "queued", "running")
        if ws_broadcast:
            await ws_broadcast("job_started", {"job_id": job_id, "scan_type": "crawl"})

        # If no specific asset_ids were supplied, crawl all assets in the project
        if asset_ids:
            hostnames = get_asset_hostnames(session, asset_ids)
        else:
            hostnames = [a["hostname"] for a in get_all_project_asset_details(session, project_id)]
        if not hostnames:
            transition_status(session, job_id, "running", "failed", error_msg="No assets to crawl")
            if ws_broadcast:
                await ws_broadcast("job_failed", {"job_id": job_id, "error": "No assets"})
            return

        new_count = 0
        total_duration = 0.0

        total = len(hostnames)
        async def line_broadcast(line: str):
            if ws_broadcast:
                await ws_broadcast("scan_line", {"job_id": job_id, "line": line})

        await line_broadcast(f"[*] Crawling {total} asset(s)")
        if proxy_url:
            await line_broadcast("[*] Routing crawler traffic through configured proxy")

        def persist_host(hostname: str, output_file: Path):
            """Commit one host's crawl results immediately so completed hosts
            survive a later timeout/cancel. Returns (created, parsed) where
            created is the count of new assets from discovered subdomains and
            parsed is the parsed crawl output (None if no output file exists)."""
            if not output_file.is_file():
                return 0, None
            content = output_file.read_text(encoding="utf-8", errors="replace")
            parsed = parse_crawler_output(content)
            merge_crawled_urls_bulk(session, project_id, {hostname: parsed["endpoints"]}, source="crawling")
            created = insert_assets_bulk(session, project_id, parsed["subdomains"]) if parsed["subdomains"] else 0
            refresh_project_counts(session, project_id)
            return created, parsed

        try:
            for i, hostname in enumerate(hostnames, 1):
                asset_hash = hashlib.md5(hostname.encode()).hexdigest()[:12]
                output_file = crawl_dir / f"{asset_hash}_crawl.txt"
                url = f"https://{hostname}"

                await line_broadcast(f"[*] [{i}/{total}] Crawling {hostname}")

                crawl_args = ["--start-url", url, "-o", str(output_file),
                              "--max-pages", str(crawl_max_pages),
                              "--delay", str(crawl_rate_limit_delay)]
                if proxy_url:
                    crawl_args += ["--proxy", proxy_url]

                result = await run_script(
                    script_path=str(SCRIPTS_DIR / "crawler.py"),
                    args=crawl_args,
                    job_id=f"{job_id}_{asset_hash}",
                    timeout_seconds=int(crawl_timeout + crawl_rate_limit_delay * crawl_max_pages),
                    ws_broadcast=line_broadcast,
                    log_dir=log_dir,
                )

                total_duration += result.duration_seconds

                if result.timed_out:
                    await line_broadcast(f"[!] {hostname}: TIMEOUT after {crawl_timeout}s")
                    # Persist any partial output the crawler wrote before timing out.
                    created, _ = persist_host(hostname, output_file)
                    new_count += created
                    continue  # Continue with other assets

                if result.exit_code != 0:
                    await line_broadcast(f"[!] {hostname}: script exited with code {result.exit_code}")

                # Parse crawl output
                if output_file.is_file():
                    created, parsed = persist_host(hostname, output_file)
                    new_count += created

                    await line_broadcast(
                        f"[+] {hostname}: {len(parsed['endpoints'])} endpoint(s), "
                        f"{len(parsed['subdomains'])} subdomain(s)"
                    )

                    if ws_broadcast:
                        await ws_broadcast("asset_update", {
                            "job_id": job_id,
                            "domain": hostname,
                            "endpoints_found": len(parsed["endpoints"]),
                            "subdomains_found": len(parsed["subdomains"]),
                        })
                else:
                    await line_broadcast(f"[!] {hostname}: no output produced")
        except asyncio.CancelledError:
            # Manual cancellation — flush whatever the interrupted host produced
            # (the crawler writes incrementally) before propagating the cancel.
            try:
                persist_host(hostname, output_file)
            except Exception:
                pass
            raise

        transition_status(session, job_id, "running", "done",
                          duration_s=total_duration,
                          log_path=str(log_dir / f"{job_id}.log"))

        if ws_broadcast:
            await ws_broadcast("job_complete", {
                "job_id": job_id,
                "scan_type": "crawl",
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
        session.close()
