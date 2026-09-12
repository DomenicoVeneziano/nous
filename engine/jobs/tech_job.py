# engine/jobs/tech_job.py
import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from runner import run_script, validate_path_within
from parsers.tech_parser import parse_tech_output, parse_screenshot_markers
from dns_precheck import dns_precheck
from sqlalchemy import text
from queue_manager import (
    get_session, transition_status, get_asset_details,
    get_all_project_asset_details, update_asset_record, refresh_project_counts,
    get_project_domains, get_project_asset_hostnames,
    insert_asset_if_absent, enqueue_scan, is_in_scope, SOURCE_REDIRECT, utc_now_str,
    attach_tag, detach_tag, job_is_cancelled, SYSTEM_TAG_PROXIED,
    SYSTEM_TAG_UNVERIFIED,
)


DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./scripts"))
PER_DOMAIN_TIMEOUT = int(os.environ.get("TECH_PER_DOMAIN_TIMEOUT", "120"))
TCP_PRECHECK_TIMEOUT = float(os.environ.get("TECH_TCP_PRECHECK_TIMEOUT", "5"))
TECH_BATCH_SIZE = int(os.environ.get("TECH_BATCH_SIZE", "10"))
TECH_RATE_LIMIT_DELAY = float(os.environ.get("TECH_RATE_LIMIT_DELAY", "0"))
DNS_RATE_LIMIT_DELAY = float(os.environ.get("DNS_RATE_LIMIT_DELAY", "0"))
TCP_PRECHECK_CONCURRENCY = int(os.environ.get("TECH_TCP_PRECHECK_CONCURRENCY", "100"))
# Upper bound on how many assets EITHER retry pass may touch. Proxy traffic is
# metered, and the direct retry runs at widened spacing, so a project whose whole
# DNS-live set fails pass 1 would otherwise push every asset through both passes
# and add hours of wall clock to a run least likely to benefit. 0 means unbounded.
TECH_RETRY_MAX_ASSETS = int(os.environ.get("TECH_RETRY_MAX_ASSETS", "1000"))

# Deliberately narrow: only outcomes a different vantage point can plausibly
# change. Blocks (403), throttling (429) and edge/origin errors (5xx) qualify.
# Redirects, 404, 401, malformed-URL 400s and ordinary 2xx/3xx never do — no
# exit IP turns those into a different answer, so retrying them is pure cost.
RETRY_STATUSES = frozenset({403, 429, 503, 520, 521, 522, 523, 524})


@dataclass(frozen=True)
class PassSpec:
    """Everything one tech-analysis pass is allowed to do.

    All write-policy branching reads from this object, so the rule "the last
    SUCCESSFUL pass wins" lives in exactly one place instead of being spread
    across pass-number conditionals at each write site. A later pass may add or
    replace a result; it may never downgrade a good earlier one to a failure.
    """
    index: int
    total: int
    label: str
    proxy_url: str | None
    delay: float
    write_failures: bool
    may_delete_stale_screenshot: bool
    tag_proxied: bool


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
    batch_id: str,
    spec: PassSpec,
    responses_dir: Path,
    log_dir: Path,
    now: str,
    ws_broadcast=None,
    line_broadcast=None,
    per_domain_timeout: int = PER_DOMAIN_TIMEOUT,
    screenshots_dir: Path | None = None,
    redirect_targets: set | None = None,
) -> dict[str, tuple[str, int | None]]:
    """
    Run tech analysis on a batch of assets in a single script invocation.
    Each asset must have 'hostname' and 'url' (scheme://hostname).

    Returns the per-asset outcome map {hostname: (kind, status_code)} where kind
    is "ok", "redirect" or "missing" (status_code None for "missing"). The
    caller builds retry candidate sets from this map alone — never by
    re-querying the assets table, which would not hold at project scale.

    `batch_id` must be unique across passes: it keys both the summary file and
    the runner log, so a later pass cannot clobber an earlier pass's artifacts.
    """
    if redirect_targets is None:
        redirect_targets = set()
    batch_summary = responses_dir / f"batch_{batch_id}_summary.log"
    if batch_summary.is_file():
        batch_summary.unlink()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(asset["url"] for asset in assets))
        tmp_path = tmp.name

    script_args = ["-o", str(batch_summary), "-f", str(responses_dir),
                   "--delay", str(spec.delay)]
    if screenshots_dir is not None:
        script_args += ["-s", str(screenshots_dir)]
    if spec.proxy_url:
        script_args += ["--proxy", spec.proxy_url]
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
            job_id=f"{job_id}_batch_{batch_id}",
            # Budget follows THIS pass's delay. A widened retry delay against
            # pass 1's budget would kill the process mid-pass and mislabel every
            # host it never reached.
            timeout_seconds=int((per_domain_timeout + spec.delay) * len(assets)) if per_domain_timeout > 0 else 0,
            ws_broadcast=line_broadcast,
            log_dir=log_dir,
        )
    finally:
        os.unlink(tmp_path)

    parsed = []
    # Screenshot verdicts ride along in the SAME text as the result lines, so
    # they cost no extra read and no second pass over disk. They explain a
    # missing image to the user, and a "blank"/"error" verdict is also the
    # engine's only evidence that the script unlinked the PNG.
    markers: dict[str, str] = {}
    if batch_summary.is_file():
        log_content = batch_summary.read_text(encoding="utf-8", errors="replace")
        parsed = parse_tech_output(log_content)
        markers = parse_screenshot_markers(log_content)
        batch_summary.unlink(missing_ok=True)
    elif result.stdout:
        parsed = parse_tech_output(result.stdout)
        markers = parse_screenshot_markers(result.stdout)

    parsed_by_domain = {entry["domain"]: entry for entry in parsed}

    outcomes: dict[str, tuple[str, int | None]] = {}
    for asset in assets:
        hostname = asset["hostname"]
        safe_domain = hostname.replace(".", "_")
        entry = parsed_by_domain.get(hostname)
        if entry and entry.get("redirects_to"):
            # Cross-host redirect: record the redirect itself (3xx status +
            # destination host), not the destination page. Clear any stale page
            # data/screenshot so the asset faithfully reflects "redirects away".
            dest = entry["redirects_to"]
            # A row that names a redirect destination must carry a redirect
            # status or none at all. The script has been seen reporting the
            # DESTINATION page's 200 here, which reads as "this host serves a
            # page" and hides the hop; drop anything outside 3xx rather than
            # publish a status the row's own redirects_to contradicts.
            redirect_status = entry["status_code"]
            if not (isinstance(redirect_status, int) and 300 <= redirect_status < 400):
                redirect_status = None
            update_asset_record(
                session, hostname, project_id, scan_id=job_id,
                status_code=redirect_status,
                title=None,
                content_length=None,
                technologies=json.dumps([]),
                redirects_to=dest,
                response_file_path=None,
                screenshot_path=None,
                date_scanned=now,
            )
            # Deleted on EVERY pass, retry passes included. This is not a
            # violation of the additive-only screenshot rule: it is part of a
            # write that SUCCEEDED. The row now states "redirects away", and
            # leaving a page screenshot attached to it would be a worse lie
            # than having no image at all.
            _remove_screenshot(screenshots_dir, safe_domain)
            redirect_targets.add(dest)
            if ws_broadcast:
                await ws_broadcast("asset_update", {
                    "job_id": job_id,
                    "domain": hostname,
                    "status_code": redirect_status,
                    "title": None,
                    "technologies": [],
                    "redirects_to": dest,
                })
            outcomes[hostname] = ("redirect", redirect_status)
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
                verdict = markers.get(hostname)
                if fresh:
                    # Overwritten in place by the script, so the path is stable
                    # across re-scans — only the latest screenshot is retained.
                    # Stored relative to the projects dir (the convention the
                    # /files/image endpoint expects).
                    extra_fields["screenshot_path"] = f"{project_id}/screenshots/{safe_domain}.png"
                elif spec.may_delete_stale_screenshot or verdict in ("blank", "error"):
                    # Detach on EVERY pass for a blank/error verdict: the script
                    # unlinked the PNG at this path, an earlier run's good image
                    # included, so a retry that left the row pointing at it
                    # would be pointing at nothing.
                    extra_fields["screenshot_path"] = None
                    if spec.may_delete_stale_screenshot:
                        # No image from this run: drop any older one rather than
                        # attributing it to this result. Pass 1 only, so a retry
                        # deletes nothing of its own and repeats no line.
                        _remove_screenshot(screenshots_dir, safe_domain)
                        if line_broadcast:
                            # A blank render, a capture error and a host the
                            # script never reached are three different problems
                            # with three different fixes; one shared sentence
                            # sent the user looking in the wrong place. The "ok"
                            # case should be unreachable — the script claims a
                            # capture the mtime test denies — so it reports the
                            # disagreement instead of asserting a cause nothing
                            # here can support.
                            if verdict == "blank":
                                await line_broadcast(
                                    f"[!] Page rendered blank for {hostname} - screenshot discarded (continuing)")
                            elif verdict == "error":
                                await line_broadcast(
                                    f"[!] Screenshot capture error for {hostname} - see scan log (continuing)")
                            elif verdict == "ok":
                                await line_broadcast(
                                    f"[!] Screenshot for {hostname} could not be attributed to this run (continuing)")
                            else:
                                await line_broadcast(
                                    f"[!] No screenshot attempted for {hostname} (continuing)")
                else:
                    # Retry pass, no fresh capture: screenshot handling here is
                    # additive-only. Omit screenshot_path from the update
                    # entirely — neither detach nor delete — so this pass can
                    # only ever REPLACE an image with a newer one, never destroy
                    # one an earlier pass legitimately captured.
                    pass
            update_asset_record(
                session, hostname, project_id, scan_id=job_id,
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
            outcomes[hostname] = ("ok", entry["status_code"])
        else:
            outcomes[hostname] = ("missing", None)
            if not spec.write_failures:
                # A retry pass that also failed says nothing new. Writing the
                # failure here would overwrite whatever an earlier pass stored,
                # so record the outcome in memory only: no DB write, no
                # broadcast. The caller uses it to build the next candidate set.
                continue
            reason = "TIMEOUT" if result.timed_out else "SCAN_ERROR"
            update_asset_record(
                session, hostname, project_id, scan_id=job_id,
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

    return outcomes


def _retry_candidates(outcomes: dict[str, tuple[str, int | None]]) -> set[str]:
    """Hostnames worth another pass: nothing came back at all, or the response
    was a block/throttle/edge error. Everything else is a settled answer that a
    different exit IP would return identically."""
    return {
        host for host, (kind, status) in outcomes.items()
        if kind == "missing" or (kind == "ok" and status in RETRY_STATUSES)
    }


def _stored_hosts(outcomes: dict[str, tuple[str, int | None]]) -> list[str]:
    """Hostnames whose result this pass actually wrote to the DB."""
    return [h for h, (kind, _) in outcomes.items() if kind in ("ok", "redirect")]


def _merge_stored(
    prior: dict[str, tuple[str, int | None]],
    newer: dict[str, tuple[str, int | None]],
) -> dict[str, tuple[str, int | None]]:
    """What is STORED after `newer` ran on top of `prior`.

    Not a plain dict merge, because a retry pass carries write_failures=False: a
    "missing" in `newer` wrote nothing, so the earlier pass's row is still what
    the asset holds. Only outcomes that actually reached the DB — "ok" and
    "redirect" — may displace a prior entry.
    """
    merged = dict(prior)
    merged.update({h: o for h, o in newer.items() if o[0] in ("ok", "redirect")})
    return merged


def _unverified_hosts(
    outcomes: dict[str, tuple[str, int | None]],
    prior: dict[str, tuple[str, int | None]],
) -> list[str]:
    """Hosts whose stored block this pass attempted and failed to confirm.

    One predicate, and every exclusion falls out of it with no special cases:

    - this pass produced no result line at all for the host ("missing"), so the
      second vantage never got an answer to compare;
    - and what is already stored is a real response whose status is retry-worthy
      (403/429/5xx), i.e. a block or throttle that another exit IP plausibly
      changes.

    So a host that failed pass 1 with SCAN_ERROR or TIMEOUT has prior kind
    "missing" and is not tagged; the unreachable_assets injected into the proxy
    pass have no prior entry at all, so TCP_UNREACHABLE stays untagged; and a
    stored redirect — a settled answer, never retry-worthy — is never tagged.

    Known limitation, accepted: when a batch's script invocation hits its own
    timeout, every host it never reached comes back "missing" alongside the ones
    it genuinely failed on, so a host can be tagged without a single proxy
    request having been issued for it. The wording survives that — the block
    really was not confirmed — and _scan_batch does not surface result.timed_out
    per host, so distinguishing the two would mean new plumbing for no change in
    the verdict. Note that per_domain_timeout=0 disables the batch timeout
    outright, which removes the case entirely.
    """
    hosts = []
    for host, (kind, _) in outcomes.items():
        stored = prior.get(host)
        if kind == "missing" and stored is not None and stored[0] == "ok" and stored[1] in RETRY_STATUSES:
            hosts.append(host)
    return hosts


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
    retry_proxy_url = cfg.get("retry_proxy_url")
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
                session, asset["hostname"], project_id, scan_id=job_id,
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
                session, asset["hostname"], project_id, scan_id=job_id,
                dns_records=json.dumps(asset["dns_records"]),
            )

        if not live_assets:
            # All assets failed DNS — mark job done (nothing to scan)
            #
            # This return is upstream of the job-level Unverified reconciliation,
            # so the one contradiction reachable here has to be settled on the
            # spot: the loop above just rewrote every one of these rows to
            # status_code=0 / NO_RECORDS, which no longer says "blocked", and a
            # tag left from an earlier job would still claim otherwise. Reached
            # by a single-asset rescan of a host whose DNS has since gone away as
            # readily as by a resolver outage. Nothing is attached: no pass ran,
            # so no second vantage was attempted and nothing was learned about
            # any host that is still blocked.
            detach_tag(
                session, project_id,
                [a["hostname"] for a in dead_assets], SYSTEM_TAG_UNVERIFIED,
            )
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
        unreachable_assets = []
        for asset, open_ports in zip(live_assets, tcp_results):
            if open_ports:
                # Prefer TLS whenever 443 answers. A host serving both commonly
                # rejects plaintext with 426 Upgrade Required, which would
                # otherwise be recorded as the asset's status and tech.
                scheme = "https" if 443 in open_ports else "http"
                asset["url"] = f"{scheme}://{asset['hostname']}"
                scannable_assets.append(asset)
            else:
                unreachable_assets.append(asset)
                update_asset_record(
                    session, asset["hostname"], project_id, scan_id=job_id,
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

        # ── Multi-pass tech analysis ────────────────────────────────
        start_time = time.time()
        redirect_targets: set[str] = set()
        # A host that fails in pass 1 and recovers in pass 3 must count ONCE, so
        # the reported total can never exceed the asset count.
        succeeded: set[str] = set()
        asset_by_host = {a["hostname"]: a for a in scannable_assets}
        pass_total = 4 if retry_proxy_url else 2

        # Progress is ASSET-weighted: assets_total starts at the pass-1 sweep
        # size and GROWS at each pass boundary, as each candidate set becomes
        # known. Tradeoff, accepted deliberately: the bar can tick backwards by
        # the retry-set fraction at a boundary. Retry sets are small by
        # construction, and this beats pass-count weighting, which would stall
        # through the long first pass and then jump.
        progress = {"done": 0, "total": len(scannable_assets)}

        async def emit_progress(spec: PassSpec, pass_done: int, pass_size: int):
            if not ws_broadcast:
                return
            await ws_broadcast("scan_progress", {
                "job_id": job_id,
                "scan_type": "tech",
                "pass_index": spec.index,
                "pass_total": spec.total,
                "pass_label": spec.label,
                "assets_done": progress["done"],
                "assets_total": progress["total"],
                "pass_assets_done": pass_done,
                "pass_assets_total": pass_size,
            })

        # Set by the pass-boundary checks below AND by the in-pass batch
        # checkpoint in _run_pass. One flag, one cancelled exit path.
        cancelled = False

        async def _run_pass(spec: PassSpec, pass_assets: list[dict]) -> dict[str, tuple[str, int | None]]:
            """Run one full pass over `pass_assets`, batched, and return the
            merged per-asset outcome map.

            Stops at the next batch boundary if the job is cancelled: the
            returned map then covers only the batches that actually ran, and
            everything already written stays written."""
            nonlocal cancelled
            outcomes: dict[str, tuple[str, int | None]] = {}
            batches = [
                pass_assets[i:i + TECH_BATCH_SIZE]
                for i in range(0, len(pass_assets), TECH_BATCH_SIZE)
            ]
            # Label and count only. This line must never carry a proxy URL —
            # those embed credentials.
            await line_broadcast(
                f"[*] Pass {spec.index}/{spec.total} - {spec.label}: {len(pass_assets)} asset(s)"
            )
            await emit_progress(spec, 0, len(pass_assets))

            pass_done = 0
            for batch_num, batch in enumerate(batches, 1):
                domains = ", ".join(a["hostname"] for a in batch)
                await line_broadcast(f"[*] Batch {batch_num}/{len(batches)}: {domains}")
                outcomes.update(await _scan_batch(
                    assets=batch,
                    project_id=project_id,
                    session=session,
                    job_id=job_id,
                    # Unique per pass: batch 1 of pass 2 must not overwrite
                    # batch 1 of pass 1's summary file or runner log.
                    batch_id=f"p{spec.index}_b{batch_num}",
                    spec=spec,
                    responses_dir=responses_dir,
                    log_dir=log_dir,
                    now=now,
                    ws_broadcast=ws_broadcast,
                    line_broadcast=line_broadcast,
                    per_domain_timeout=per_domain_timeout,
                    screenshots_dir=screenshots_dir,
                    redirect_targets=redirect_targets,
                ))
                pass_done += len(batch)
                progress["done"] += len(batch)
                await emit_progress(spec, pass_done, len(pass_assets))

                # The batch boundary is the in-pass checkpoint. job_is_cancelled
                # commits and runs a SELECT, so it is polled once per batch and
                # never per asset — per-asset polling would be per-row work that
                # scales with the project's asset count. Skipped on the final
                # batch, where the pass is over either way.
                if batch_num < len(batches) and job_is_cancelled(session, job_id):
                    cancelled = True
                    await line_broadcast(
                        f"[!] Cancellation requested - stopping pass {spec.index} "
                        f"after batch {batch_num}/{len(batches)}"
                    )
                    break

            # Runs on the cancelled path too: the hosts this pass DID store are
            # committed, so their proxied-vantage tag must match what is stored.
            stored = _stored_hosts(outcomes)
            succeeded.update(stored)
            # One bulk call per pass, never per asset. The tag must always
            # describe the vantage point of the CURRENTLY STORED result, so a
            # host that recovers on a direct pass loses it again. detach_tag
            # early-returns after a single SELECT for projects that have never
            # used a proxy, so this is cheap in the common case.
            if spec.tag_proxied:
                attach_tag(session, project_id, stored, SYSTEM_TAG_PROXIED)
            else:
                detach_tag(session, project_id, stored, SYSTEM_TAG_PROXIED)
            # SYSTEM_TAG_UNVERIFIED is deliberately NOT reconciled here. Proxied
            # is a fact about one pass — which vantage wrote the row — so it
            # settles as soon as that pass writes. Whether a block went
            # unconfirmed is a conclusion about the whole job: it is not knowable
            # until the proxy pass has had its chance, and a per-pass detach
            # would make the tag a function of which hosts survived the retry
            # truncation. run_tech_job reconciles it once, after the last
            # proxy pass.
            return outcomes

        # ── Pass 1: direct sweep over everything reachable ──────────
        outcomes_1 = await _run_pass(
            PassSpec(
                index=1, total=pass_total, label="direct sweep",
                proxy_url=proxy_url, delay=tech_rate_limit_delay,
                write_failures=True, may_delete_stale_screenshot=True,
                tag_proxied=bool(proxy_url),
            ),
            scannable_assets,
        )

        # ── Pass 2: direct retry at wider spacing ───────────────────
        # TCP_UNREACHABLE hosts are excluded: they never entered
        # scannable_assets, and the precheck already proved the direct path
        # fails, so re-probing them directly is guaranteed-useless work.
        retry_1 = _retry_candidates(outcomes_1)
        outcomes_2: dict[str, tuple[str, int | None]] = {}
        if retry_1 and not cancelled:
            # Pass boundary is the checkpoint: the worker only polls for
            # cancellation every POLL_INTERVAL, so without this a whole extra
            # pass could start after a cancel was already requested.
            if job_is_cancelled(session, job_id):
                cancelled = True
            else:
                # Bounded exactly like the proxy pass. This pass runs at widened
                # spacing (>= 2s/host), so an unbounded set turns a wholesale
                # pass-1 failure into hours of added wall clock.
                #
                # Ordering is deterministic, and priority-ordered rather than
                # arbitrary: hosts that ANSWERED with a block/throttle/edge error
                # come first, then hosts nothing came back from. Wider spacing is
                # precisely the remedy for 403/429/5xx, while a "missing" host is
                # the wholesale-failure case a slower direct retry rarely fixes.
                # Within each group, hostname order — the same tie-break the
                # proxy pass uses — so the cut is stable run to run.
                pass_2_hosts = sorted(
                    retry_1,
                    key=lambda h: (0 if outcomes_1.get(h, ("missing", None))[0] == "ok" else 1, h),
                )
                if TECH_RETRY_MAX_ASSETS > 0 and len(pass_2_hosts) > TECH_RETRY_MAX_ASSETS:
                    await line_broadcast(
                        f"[!] Direct retry set truncated to {TECH_RETRY_MAX_ASSETS} "
                        f"of {len(pass_2_hosts)} asset(s)"
                    )
                    pass_2_hosts = pass_2_hosts[:TECH_RETRY_MAX_ASSETS]
                progress["total"] += len(pass_2_hosts)
                outcomes_2 = await _run_pass(
                    PassSpec(
                        index=2, total=pass_total, label="direct retry",
                        proxy_url=None,
                        delay=max(2.0, 3 * tech_rate_limit_delay),
                        write_failures=False, may_delete_stale_screenshot=False,
                        tag_proxied=False,
                    ),
                    [asset_by_host[h] for h in pass_2_hosts],
                )

        # ── Pass 3: proxy retry ─────────────────────────────────────
        # Skipped entirely without a retry proxy — no candidate set is even
        # built. Rotating exit IPs make per-IP throttling a non-issue, so this
        # pass runs at the NORMAL delay rather than the widened one.
        outcomes_3: dict[str, tuple[str, int | None]] = {}
        # Distinct from "outcomes_3 is empty": a pass that ran and reached every
        # host it was given returns entries for all of them, while a pass that
        # never ran must not be allowed to conclude anything. The Unverified
        # attach below is gated on this flag, never on the map being non-empty.
        pass_3_ran = False
        # The exact asset dicts pass 3 was handed, keyed by hostname. Pass 4
        # resolves its hosts through this and not through asset_by_host, so the
        # injected unreachable assets below stay resolvable.
        pass_3_by_host: dict[str, dict] = {}
        if retry_proxy_url and not cancelled:
            if job_is_cancelled(session, job_id):
                cancelled = True
            else:
                pass_3_hosts = _retry_candidates(outcomes_2) | (retry_1 - set(outcomes_2))
                candidates = [asset_by_host[h] for h in sorted(pass_3_hosts)]
                for asset in unreachable_assets:
                    # Included on purpose: the TCP precheck measures this
                    # container's own egress — exactly the vantage point this
                    # pass exists to replace, and a datacenter-range SYN drop is
                    # the canonical "reachable only from residential" case. The
                    # local precheck is BYPASSED here because it cannot probe
                    # through an HTTP proxy; let the proxy do the connecting.
                    asset["url"] = f"https://{asset['hostname']}"
                    candidates.append(asset)

                if TECH_RETRY_MAX_ASSETS > 0 and len(candidates) > TECH_RETRY_MAX_ASSETS:
                    await line_broadcast(
                        f"[!] Proxy retry set truncated to {TECH_RETRY_MAX_ASSETS} "
                        f"of {len(candidates)} asset(s)"
                    )
                    candidates = candidates[:TECH_RETRY_MAX_ASSETS]

                if candidates:
                    progress["total"] += len(candidates)
                    pass_3_ran = True
                    # Captured AFTER the truncation, so pass 4 can only ever see
                    # hosts pass 3 actually attempted.
                    pass_3_by_host = {a["hostname"]: a for a in candidates}
                    outcomes_3 = await _run_pass(
                        PassSpec(
                            index=3, total=pass_total, label="proxy retry",
                            proxy_url=retry_proxy_url, delay=tech_rate_limit_delay,
                            write_failures=False, may_delete_stale_screenshot=False,
                            tag_proxied=True,
                        ),
                        candidates,
                    )

        # ── Pass 4: second proxy attempt for hosts pass 3 missed ────
        # A pass-3 "missing" is overwhelmingly a REFUSED proxy connection: on a
        # measured 997-asset run pass 3 attempted 642 assets and produced no
        # result line for 367 of them, 344 of those NS_ERROR_PROXY_CONNECTION_
        # REFUSED and 23 timeouts. Each host got exactly one attempt. A refused
        # connection transfers no bytes, so a second attempt costs essentially
        # nothing against metered proxy traffic — which is the constraint that
        # bounds every other retry decision in this job.
        #
        # Deliberately NOT narrowed to the refusals, though that is what the
        # pass is for. The error class exists only inside the script's
        # "[diag] nav-failed" line, which runner.py filters out of
        # ScriptResult.stdout on purpose, so selecting on it would take a new
        # contracted marker in scripts/tech_analysis.py, a parser for it in
        # engine/parsers/tech_parser.py and a wider _scan_batch return type.
        # With 344 of 367 costing no traffic, re-attempting all 367 is the
        # cheaper trade. Should metered traffic ever become the binding
        # constraint, that marker route is the follow-up.
        #
        # Bounded: exactly one extra pass, over a strict subset of a pass-3 set
        # TECH_RETRY_MAX_ASSETS has already clipped, so the worst case adds one
        # pass-3 duration and no new env var.
        outcomes_4: dict[str, tuple[str, int | None]] = {}
        if retry_proxy_url and not cancelled:
            # Same pass-boundary checkpoint passes 2 and 3 use: the worker only
            # polls every POLL_INTERVAL, so without this a whole extra pass
            # could start after a cancel was already requested.
            if job_is_cancelled(session, job_id):
                cancelled = True
            else:
                pass_4_hosts = sorted(
                    host for host, (kind, _) in outcomes_3.items() if kind == "missing"
                )
                # No TECH_RETRY_MAX_ASSETS cut here: this pass INHERITS pass 3's.
                # pass_4_hosts keys ⊆ outcomes_3 keys ⊆ pass_3_by_host, which
                # pass 3 clipped to the bound before running, so re-applying it
                # could never shrink anything. It is the same subset
                # relationship last_proxy's plain dict merge relies on below.
                assert len(pass_4_hosts) <= len(pass_3_by_host)

                # Nothing to do: skip the pass outright rather than run it
                # empty — no _run_pass call, so no "Pass 4/4" line, no batch
                # artifacts and no progress accounting for a pass that is not
                # happening.
                if pass_4_hosts:
                    # Resolved through pass 3's OWN candidate list, never
                    # asset_by_host: pass 3 deliberately injects the
                    # TCP-unreachable assets, which never entered
                    # scannable_assets and so are absent from asset_by_host.
                    # Both their https:// URL and their claim to a proxied
                    # attempt have to survive into this pass.
                    progress["total"] += len(pass_4_hosts)
                    outcomes_4 = await _run_pass(
                        PassSpec(
                            index=4, total=pass_total, label="proxy retry (refused)",
                            proxy_url=retry_proxy_url, delay=tech_rate_limit_delay,
                            write_failures=False, may_delete_stale_screenshot=False,
                            tag_proxied=True,
                        ),
                        [pass_3_by_host[h] for h in pass_4_hosts],
                    )

        # ── Reconcile the Unverified tag, once for the whole job ────
        # Placed here, not inside _run_pass, because "the stored block could not
        # be confirmed" is a conclusion about the job: it is only true once the
        # proxy pass has had its chance at the host. Runs on the cancelled path
        # too — everything below the passes is kept on that path by design, and
        # the conclusion is sound for the batches that did run.
        #
        # Two bulk calls total, one detach and one attach, never per pass and
        # never per asset: detach_tag/attach_tag each end in a chunked
        # sync_tags_text, which is a correlated-subquery UPDATE over the ids
        # handed to them, so the number of those sweeps is what has to stay
        # bounded, not just their batching.
        final = _merge_stored(
            _merge_stored(_merge_stored(outcomes_1, outcomes_2), outcomes_3),
            outcomes_4,
        )

        # The LAST proxy outcome per host, which is what both halves of the
        # reconciliation below key on. A host pass 4 recovered was confirmed from
        # the second vantage after all. A plain dict merge is correct here
        # precisely because pass 4's key set is by construction a subset of pass
        # 3's — every host pass 4 touched is described by pass 4's result, and a
        # host pass 3 missed that pass 4 never covered keeps pass 3's "missing".
        # _merge_stored is needed for `final` for the opposite reason: there a
        # later pass's "missing" wrote nothing to the DB and so must not displace
        # an earlier pass's stored row, whereas here "missing" is the very signal
        # being carried forward. Empty when no proxy pass ran, which is what
        # keeps the terms that read it inert on a proxyless run.
        last_proxy = {**outcomes_3, **outcomes_4}

        # The detach is applied on EVERY run, proxy or not: it names the hosts
        # whose current state CONTRADICTS the tag, and a contradiction has to be
        # cleared whether or not a second vantage was available this time.
        # Anything else lets the tag outlive the result it describes.
        contradicted = [
            host for host, (kind, status) in final.items()
            # Answered with something that is not a block or throttle, or
            # redirects away — settled answers, nothing left to confirm.
            if kind == "redirect" or (kind == "ok" and status not in RETRY_STATUSES)
        ]
        # A host gone DNS-dead was rewritten to status_code=0 / NO_RECORDS
        # without ever entering a pass, so it produced no result line and is
        # absent from `final`. The row no longer says "blocked", so a tag left
        # over from an earlier run would describe a row that is gone.
        contradicted += [a["hostname"] for a in dead_assets]
        # A host that failed the TCP precheck detaches for a different reason,
        # and NOT because its row must read status_code=0: the proxy pass takes
        # these hosts on deliberately, bypassing the local precheck, so one it
        # reached has a fresh result stored and IS in `final` — a 403 among them.
        # Either way the second vantage got its answer. It either corroborated
        # the block or replaced it, and a corroborated block is confirmed, which
        # is exactly what the tag denies.
        contradicted += [a["hostname"] for a in unreachable_assets]
        # The pass-1 failure only counts as a contradiction while it is still
        # what the row holds: a host that failed pass 1 and then answered 403 on
        # a retry has a block stored again, and belongs to the attach set below
        # rather than this one.
        contradicted += [
            host for host, (kind, _) in outcomes_1.items()
            if kind == "missing" and final[host][0] == "missing"
        ]
        # Every host a proxy pass actually got an answer for, whatever that
        # answer was. An answer settles the question in BOTH directions: a
        # non-block replaces the stored block, and a repeated 403 from a
        # different exit IP is the second vantage CORROBORATING the block, which
        # is confirmation — the precise opposite of what the tag asserts. Term 1
        # cannot cover this, because it rejects exactly the retry-worthy statuses
        # a still-blocked host comes back with; without this term every genuinely
        # blocked host keeps a tag from any earlier run whose proxy was
        # unreachable. Scoped to the proxy passes' own outcome map, never to "some
        # pass reached it" — that was the bug this whole block was restructured
        # to fix.
        contradicted += _stored_hosts(last_proxy)
        # The terms overlap — a TCP-unreachable host a proxy pass then answered
        # for hits several of them — and a repeat would cost a second
        # no-op chunk through detach_tag's sweep. dict.fromkeys drops it in one
        # pass and keeps insertion order, so the call sees each host once.
        detach_tag(
            session, project_id,
            list(dict.fromkeys(contradicted)), SYSTEM_TAG_UNVERIFIED,
        )

        # Attached only when the proxy pass actually ran. Without it no second
        # vantage was attempted, so this run has learned nothing about the hosts
        # that are still blocked: leave their tags exactly as the last run left
        # them. This is what keeps a proxyless run inert rather than destructive,
        # and it keeps the tag from becoming a function of which hosts happened
        # to survive the TECH_RETRY_MAX_ASSETS cut.
        if pass_3_ran:
            # Reads the same last_proxy map the detach term above does, and the
            # two can never overlap: _unverified_hosts requires kind "missing",
            # _stored_hosts requires kind "ok" or "redirect".
            unverified = _unverified_hosts(last_proxy, final)
            if unverified:
                attach_tag(session, project_id, unverified, SYSTEM_TAG_UNVERIFIED)
                # One line for the whole job. Never one per host: the per-host
                # detail is already in the batch log as the script's own
                # nav-failed diagnostic, and 367 extra lines would bury it.
                await line_broadcast(
                    f"[!] {len(unverified)} asset(s) tagged {SYSTEM_TAG_UNVERIFIED} - "
                    f"stored block could not be confirmed from a second vantage"
                )

        analyzed = len(succeeded)

        # ── Follow in-scope cross-host redirects ────────────────────
        # For each new host an asset redirected to, if it is in project scope
        # and not already tracked, add it and queue a tech scan. Only brand-new
        # hosts are queued, which prevents redirect loops and redundant scans.
        if redirect_targets:
            root_domains = get_project_domains(session, project_id)
            existing = set(get_project_asset_hostnames(session, project_id))
            for dest in sorted(redirect_targets):
                dest = (dest or "").strip().lower()
                if not dest or dest in existing or not is_in_scope(dest, root_domains):
                    continue
                new_id = insert_asset_if_absent(
                    session, project_id, dest,
                    source=SOURCE_REDIRECT, scan_job_id=job_id,
                )
                if new_id:
                    existing.add(dest)
                    enqueue_scan(session, project_id, "tech", [new_id], cfg)
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

        if cancelled:
            # The API already wrote the cancelled status; overwriting it with
            # "done" would erase the user's action. Everything above this point
            # (counts, redirect follow-up, project timestamps) still runs so the
            # work the passes DID complete is not lost.
            await line_broadcast("[!] Scan cancelled - stopped early; completed results kept")
            return

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
