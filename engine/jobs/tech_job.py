# engine/jobs/tech_job.py
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from runner import run_script, validate_path_within
from parsers.tech_parser import parse_tech_output
from dns_precheck import dns_precheck
from sqlalchemy import text
from queue_manager import (
    get_session, transition_status, get_asset_details,
    get_all_project_asset_details, update_asset_record, refresh_project_counts,
    get_project_domains, get_project_asset_hostnames,
    insert_asset_if_absent, enqueue_tech_scan, SOURCE_REDIRECT, utc_now_str,
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
TCP_PRECHECK_CONCURRENCY = int(os.environ.get("TECH_TCP_PRECHECK_CONCURRENCY", "100"))


async def _probe_port(hostname: str, port: int) -> int | None:
    """Open and immediately close a TCP connection to (hostname, port).
    Returns the port when it accepts, None otherwise. The writer is closed on
    every path — including the losing branch of a concurrent probe — so no
    socket is left behind."""
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port),
            timeout=TCP_PRECHECK_TIMEOUT,
        )
        return port
    except Exception:
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def _tcp_reachable(
    hostname: str,
    ports: tuple[int, ...] = (80, 443),
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[int, ...]:
    """Return the open ports among `ports` (in the given order), or an empty
    tuple when none answered within the timeout.

    Both ports are probed concurrently, so an unreachable host still costs a
    single timeout instead of one per port, and the caller learns the full set
    rather than just the first hit — a host with 80 and 443 both open must be
    scanned over TLS, not plaintext.

    `semaphore` bounds how many hosts are in flight at once; each holder owns at
    most len(ports) sockets."""
    async def _probe_all() -> tuple[int, ...]:
        results = await asyncio.gather(
            *[_probe_port(hostname, port) for port in ports],
            return_exceptions=True,
        )
        return tuple(r for r in results if isinstance(r, int))

    if semaphore is None:
        return await _probe_all()
    async with semaphore:
        return await _probe_all()


def _remove_screenshot(screenshots_dir: Path | None, safe_domain: str) -> None:
    """Delete an asset's screenshot, confining the path under `screenshots_dir`
    before touching the filesystem so a crafted hostname cannot escape it.

    Only for hosts this run demonstrably handled. Every other failure path
    detaches the screenshot (screenshot_path=None) and leaves the file alone."""
    if screenshots_dir is None:
        return
    shot_file = screenshots_dir / f"{safe_domain}.png"
    if not validate_path_within(shot_file, screenshots_dir):
        return
    try:
        shot_file.unlink(missing_ok=True)
    except OSError:
        pass


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

    # Cutoff for "was this screenshot written by THIS run": the -1 absorbs
    # filesystem mtime granularity. Preferred over pre-deleting the batch's
    # PNGs, which would destroy a good screenshot even when the script never
    # starts; the cutoff only discards a file this run demonstrably did not write.
    run_started = time.time() - 1

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
        safe_domain = hostname.replace(".", "_")
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
            _remove_screenshot(screenshots_dir, safe_domain)
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
            extra_fields = {}
            if screenshots_dir is not None:
                shot_file = screenshots_dir / f"{safe_domain}.png"
                # A capture that never completed leaves the previous run's PNG
                # untouched, so existence alone is not proof this result has a
                # screenshot — only an mtime at or after the run start is. One
                # stat per asset in the batch (batch size TECH_BATCH_SIZE).
                try:
                    fresh = shot_file.stat().st_mtime >= run_started
                except OSError:
                    fresh = False
                if fresh:
                    # Overwritten in place by the script, so the path is stable
                    # across re-scans — only the latest screenshot is retained.
                    # Stored relative to the projects dir (the convention the
                    # /files/image endpoint expects).
                    extra_fields["screenshot_path"] = f"{project_id}/screenshots/{safe_domain}.png"
                else:
                    # No image from this run: drop any older one rather than
                    # attributing it to this result.
                    _remove_screenshot(screenshots_dir, safe_domain)
                    extra_fields["screenshot_path"] = None
                    if line_broadcast:
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
                # Detach, but do NOT delete: run_script's timeout covers the
                # whole batch, so a missing entry cannot distinguish "this host
                # failed" from "the batch aborted before reaching it". Deleting
                # here would destroy a still-good screenshot for every host the
                # run never got to.
                screenshot_path=None,
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
        now = utc_now_str()
        for asset in dead_assets:
            reason = asset.get("dns_fail_reason", "NO_RECORDS")
            update_asset_record(
                session, asset["hostname"], project_id,
                status_code=0,
                title=reason,
                dns_records=json.dumps(asset.get("dns_records") or []),
                # Same policy as an in-batch failure: detach the stale image so
                # the two paths do not present the same condition differently.
                # The file itself stays — this run never handled the host.
                screenshot_path=None,
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

        # One semaphore for the whole pass: still a single fully parallel sweep,
        # but at most TCP_PRECHECK_CONCURRENCY hosts are in flight, so a project
        # with thousands of assets cannot open a socket per asset at once and
        # exhaust the container's file-descriptor limit.
        tcp_semaphore = asyncio.Semaphore(TCP_PRECHECK_CONCURRENCY)
        tcp_results = await asyncio.gather(*[
            _tcp_reachable(a["hostname"], semaphore=tcp_semaphore) for a in live_assets
        ])

        scannable_assets = []
        for asset, open_ports in zip(live_assets, tcp_results):
            if open_ports:
                # Prefer TLS whenever 443 answers. A host serving both commonly
                # rejects plaintext with 426 Upgrade Required, which would
                # otherwise be recorded as the asset's status and tech.
                scheme = "https" if 443 in open_ports else "http"
                asset["url"] = f"{scheme}://{asset['hostname']}"
                scannable_assets.append(asset)
            else:
                update_asset_record(
                    session, asset["hostname"], project_id,
                    status_code=0,
                    title="TCP_UNREACHABLE",
                    screenshot_path=None,  # detach only; the file is left alone
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
                new_id = insert_asset_if_absent(
                    session, project_id, dest,
                    source=SOURCE_REDIRECT, scan_job_id=job_id,
                )
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
