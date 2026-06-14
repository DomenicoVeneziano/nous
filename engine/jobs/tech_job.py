# engine/jobs/tech_job.py
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from runner import run_script
from parsers.tech_parser import parse_tech_output
from dns_precheck import dns_precheck
from sqlalchemy import text
from queue_manager import (
    get_session, transition_status, get_asset_details,
    get_all_project_asset_details, update_asset_record, refresh_project_counts,
    get_project_domains, get_project_asset_hostnames,
    insert_asset_if_absent, enqueue_tech_scan,
)


def _in_scope(host: str, root_domains: list[str]) -> bool:
    """True if host equals or is a subdomain of any project root domain.
    Root domains may carry a leading '*.' wildcard (e.g. '*.sisal.com'), which
    is normalised to the apex before matching."""
    host = (host or "").lower().strip(".")
    for d in root_domains:
        d = (d or "").lower().strip()
        if d.startswith("*."):
            d = d[2:]
        d = d.strip(".")
        if d and (host == d or host.endswith("." + d)):
            return True
    return False

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./scripts"))
PER_DOMAIN_TIMEOUT = int(os.environ.get("TECH_PER_DOMAIN_TIMEOUT", "120"))
TCP_PRECHECK_TIMEOUT = float(os.environ.get("TECH_TCP_PRECHECK_TIMEOUT", "5"))
TECH_BATCH_SIZE = int(os.environ.get("TECH_BATCH_SIZE", "10"))
TECH_RATE_LIMIT_DELAY = float(os.environ.get("TECH_RATE_LIMIT_DELAY", "0"))
DNS_RATE_LIMIT_DELAY = float(os.environ.get("DNS_RATE_LIMIT_DELAY", "0"))


async def _tcp_reachable(hostname: str, ports: tuple[int, ...] = (80, 443)) -> int | None:
    """Return the first open port, or None if unreachable within timeout."""
    for port in ports:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, port),
                timeout=TCP_PRECHECK_TIMEOUT,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return port
        except Exception:
            continue
    return None


async def _scan_batch(
    assets: list[dict],
    project_id: str,
    session,
    job_id: str,
    batch_num: int,
    responses_dir: Path,
    log_dir: Path,
    now: str,
    ws_broadcast=None,
    line_broadcast=None,
    per_domain_timeout: int = PER_DOMAIN_TIMEOUT,
    tech_rate_limit_delay: float = TECH_RATE_LIMIT_DELAY,
    proxy_url: str | None = None,
    screenshots_dir: Path | None = None,
    redirect_targets: set | None = None,
) -> int:
    """
    Run tech analysis on a batch of assets in a single script invocation.
    Each asset must have 'hostname' and 'url' (scheme://hostname).
    Returns count of assets successfully analyzed.
    """
    if redirect_targets is None:
        redirect_targets = set()
    batch_summary = responses_dir / f"batch_{batch_num}_summary.log"
    if batch_summary.is_file():
        batch_summary.unlink()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(asset["url"] for asset in assets))
        tmp_path = tmp.name

    script_args = ["-o", str(batch_summary), "-f", str(responses_dir),
                   "--delay", str(tech_rate_limit_delay)]
    if screenshots_dir is not None:
        script_args += ["-s", str(screenshots_dir)]
    if proxy_url:
        script_args += ["--proxy", proxy_url]
    script_args.append(tmp_path)

    try:
        result = await run_script(
            script_path=str(SCRIPTS_DIR / "tech_analysis.py"),
            args=script_args,
            job_id=f"{job_id}_batch_{batch_num}",
            timeout_seconds=int((per_domain_timeout + tech_rate_limit_delay) * len(assets)) if per_domain_timeout > 0 else 0,
            ws_broadcast=line_broadcast,
            log_dir=log_dir,
        )
    finally:
        os.unlink(tmp_path)

    parsed = []
    if batch_summary.is_file():
        log_content = batch_summary.read_text(encoding="utf-8", errors="replace")
        parsed = parse_tech_output(log_content)
        batch_summary.unlink(missing_ok=True)
    elif result.stdout:
        parsed = parse_tech_output(result.stdout)

    parsed_by_domain = {entry["domain"]: entry for entry in parsed}

    success_count = 0
    for asset in assets:
        hostname = asset["hostname"]
        entry = parsed_by_domain.get(hostname)
        if entry and entry.get("redirects_to"):
            # Cross-host redirect: record the redirect itself (3xx status +
            # destination host), not the destination page. Clear any stale page
            # data/screenshot so the asset faithfully reflects "redirects away".
            dest = entry["redirects_to"]
            update_asset_record(
                session, hostname, project_id,
                status_code=entry["status_code"],
                title=None,
                content_length=None,
                technologies=json.dumps([]),
                redirects_to=dest,
                response_file_path=None,
                screenshot_path=None,
                date_scanned=now,
            )
            redirect_targets.add(dest)
            if ws_broadcast:
                await ws_broadcast("asset_update", {
                    "job_id": job_id,
                    "domain": hostname,
                    "status_code": entry["status_code"],
                    "title": None,
                    "technologies": [],
                    "redirects_to": dest,
                })
            success_count += 1
        elif entry:
            safe_domain = hostname.replace(".", "_")
            extra_fields = {}
            if screenshots_dir is not None:
                shot_file = screenshots_dir / f"{safe_domain}.png"
                if shot_file.is_file():
                    # Overwritten in place by the script, so the path is stable
                    # across re-scans — only the latest screenshot is retained.
                    # Stored relative to the projects dir (the convention the
                    # /files/image endpoint expects).
                    extra_fields["screenshot_path"] = f"{project_id}/screenshots/{safe_domain}.png"
                elif line_broadcast:
                    await line_broadcast(f"[!] Screenshot capture failed for {hostname} (continuing)")
            update_asset_record(
                session, hostname, project_id,
                status_code=entry["status_code"],
                title=entry["title"],
                content_length=entry["content_length"],
                technologies=json.dumps(entry["technologies"]),
                redirects_to=None,  # clear any prior cross-host redirect marker
                response_file_path=f"projects/{project_id}/responses/{safe_domain}.txt",
                date_scanned=now,
                **extra_fields,
            )
            if ws_broadcast:
                await ws_broadcast("asset_update", {
                    "job_id": job_id,
                    "domain": hostname,
                    "status_code": entry["status_code"],
                    "title": entry["title"],
                    "technologies": entry["technologies"],
                })
            success_count += 1
        else:
            reason = "TIMEOUT" if result.timed_out else "SCAN_ERROR"
            update_asset_record(
                session, hostname, project_id,
                status_code=0,
                title=reason,
                date_scanned=now,
            )
            if ws_broadcast:
                await ws_broadcast("asset_update", {
                    "job_id": job_id,
                    "domain": hostname,
                    "status_code": 0,
                    "title": reason,
                    "technologies": [],
                })

    return success_count


async def run_tech_job(job: dict, ws_broadcast=None):
    """
    Execute tech analysis on selected assets.
    Pipeline: DNS pre-check → per-domain runner → tech_parser → DB write → WS emit
    """
    session = get_session()
    job_id = job["id"]
    project_id = job["project_id"]
    asset_ids = json.loads(job["asset_ids"]) if isinstance(job["asset_ids"], str) else (job["asset_ids"] or [])
    project_dir = DATA_DIR / "projects" / project_id
    log_dir = project_dir / "logs"
    responses_dir = project_dir / "responses"

    responses_dir.mkdir(parents=True, exist_ok=True)

    # Read settings from job config (set at enqueue time), fall back to env vars
    cfg = job.get("config") or {}
    per_domain_timeout = cfg.get("per_domain_timeout", PER_DOMAIN_TIMEOUT)
    tech_rate_limit_delay = cfg.get("tech_rate_limit_delay", TECH_RATE_LIMIT_DELAY)
    dns_rate_limit_delay = cfg.get("dns_rate_limit_delay", DNS_RATE_LIMIT_DELAY)
    resolvers_path = cfg.get("resolvers_path")
    proxy_url = cfg.get("proxy_url")
    screenshots_enabled = cfg.get("screenshots_enabled", False)

    screenshots_dir = None
    if screenshots_enabled:
        screenshots_dir = project_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

    try:
        transition_status(session, job_id, "queued", "running")
        if ws_broadcast:
            await ws_broadcast("job_started", {"job_id": job_id, "scan_type": "tech"})

        # Get full asset details (id, hostname, type, dns_records)
        # If no specific asset_ids were supplied, scan all assets in the project
        if asset_ids:
            assets = get_asset_details(session, asset_ids)
        else:
            assets = get_all_project_asset_details(session, project_id)
        if not assets:
            transition_status(session, job_id, "running", "failed", error_msg="No assets to analyze")
            if ws_broadcast:
                await ws_broadcast("job_failed", {"job_id": job_id, "error": "No assets"})
            return

        # ── DNS pre-check ────────────────────────────────────────
        async def line_broadcast(line: str):
            if ws_broadcast:
                await ws_broadcast("scan_line", {"job_id": job_id, "line": line})

        live_assets, dead_assets = await dns_precheck(
            assets, ws_broadcast=line_broadcast,
            dns_rate_limit_delay=dns_rate_limit_delay,
            resolvers_path=resolvers_path,
        )

        # Mark dead assets: status_code=0, set title to DNS failure reason
        now = datetime.now(timezone.utc).isoformat()
        for asset in dead_assets:
            reason = asset.get("dns_fail_reason", "NO_RECORDS")
            update_asset_record(
                session, asset["hostname"], project_id,
                status_code=0,
                title=reason,
                dns_records=json.dumps(asset.get("dns_records") or []),
                date_scanned=now,
            )
            if ws_broadcast:
                await ws_broadcast("asset_update", {
                    "job_id": job_id,
                    "domain": asset["hostname"],
                    "status_code": 0,
                    "title": reason,
                    "technologies": [],
                })

        # Persist DNS records for live assets before tech analysis
        for asset in live_assets:
            update_asset_record(
                session, asset["hostname"], project_id,
                dns_records=json.dumps(asset["dns_records"]),
            )

        if not live_assets:
            # All assets failed DNS — mark job done (nothing to scan)
            refresh_project_counts(session, project_id)
            transition_status(session, job_id, "running", "done",
                              duration_s=0,
                              log_path=str(log_dir / f"{job_id}.log"))
            if ws_broadcast:
                await ws_broadcast("job_complete", {
                    "job_id": job_id,
                    "scan_type": "tech",
                    "project_id": project_id,
                    "analyzed": 0,
                })
            return

        # ── TCP reachability check (parallel, fast-fail before browser) ──
        if ws_broadcast:
            await line_broadcast(f"[*] TCP pre-check: testing reachability of {len(live_assets)} asset(s)")

        tcp_results = await asyncio.gather(*[
            _tcp_reachable(a["hostname"]) for a in live_assets
        ])

        scannable_assets = []
        for asset, open_port in zip(live_assets, tcp_results):
            if open_port is not None:
                scheme = "https" if open_port == 443 else "http"
                asset["url"] = f"{scheme}://{asset['hostname']}"
                scannable_assets.append(asset)
            else:
                update_asset_record(
                    session, asset["hostname"], project_id,
                    status_code=0,
                    title="TCP_UNREACHABLE",
                    date_scanned=now,
                )
                if ws_broadcast:
                    await ws_broadcast("asset_update", {
                        "job_id": job_id,
                        "domain": asset["hostname"],
                        "status_code": 0,
                        "title": "TCP_UNREACHABLE",
                        "technologies": [],
                    })

        if ws_broadcast:
            await line_broadcast(
                f"[*] TCP pre-check complete: {len(scannable_assets)} reachable, "
                f"{len(live_assets) - len(scannable_assets)} unreachable"
            )

        # ── Batched tech analysis ───────────────────────────────────
        total = len(scannable_assets)
        analyzed = 0
        start_time = time.time()
        batches = [scannable_assets[i:i + TECH_BATCH_SIZE] for i in range(0, total, TECH_BATCH_SIZE)]

        if ws_broadcast:
            await line_broadcast(
                f"[*] Running tech analysis on {total} asset(s) in {len(batches)} batch(es) of up to {TECH_BATCH_SIZE}"
            )

        redirect_targets: set[str] = set()
        for batch_num, batch in enumerate(batches, 1):
            if ws_broadcast:
                domains = ", ".join(a["hostname"] for a in batch)
                await line_broadcast(f"[*] Batch {batch_num}/{len(batches)}: {domains}")

            analyzed += await _scan_batch(
                assets=batch,
                project_id=project_id,
                session=session,
                job_id=job_id,
                batch_num=batch_num,
                responses_dir=responses_dir,
                log_dir=log_dir,
                now=now,
                ws_broadcast=ws_broadcast,
                line_broadcast=line_broadcast,
                per_domain_timeout=per_domain_timeout,
                tech_rate_limit_delay=tech_rate_limit_delay,
                proxy_url=proxy_url,
                screenshots_dir=screenshots_dir,
                redirect_targets=redirect_targets,
            )

        # ── Follow in-scope cross-host redirects ────────────────────
        # For each new host an asset redirected to, if it is in project scope
        # and not already tracked, add it and queue a tech scan. Only brand-new
        # hosts are queued, which prevents redirect loops and redundant scans.
        if redirect_targets:
            root_domains = get_project_domains(session, project_id)
            existing = set(get_project_asset_hostnames(session, project_id))
            for dest in sorted(redirect_targets):
                dest = (dest or "").strip().lower()
                if not dest or dest in existing or not _in_scope(dest, root_domains):
                    continue
                new_id = insert_asset_if_absent(session, project_id, dest)
                if new_id:
                    existing.add(dest)
                    enqueue_tech_scan(session, project_id, new_id, cfg)
                    if ws_broadcast:
                        await line_broadcast(
                            f"[+] In-scope redirect target added and queued for tech scan: {dest}"
                        )

        total_duration = round(time.time() - start_time, 2)

        refresh_project_counts(session, project_id)
        session.execute(text(
            "UPDATE projects SET last_scan_date = :d, last_scan_duration_s = :dur WHERE id = :pid"
        ), {"d": now, "dur": total_duration, "pid": project_id})
        session.commit()

        transition_status(session, job_id, "running", "done",
                          duration_s=total_duration,
                          log_path=str(log_dir / f"{job_id}.log"))

        if ws_broadcast:
            await ws_broadcast("job_complete", {
                "job_id": job_id,
                "scan_type": "tech",
                "project_id": project_id,
                "analyzed": analyzed,
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
