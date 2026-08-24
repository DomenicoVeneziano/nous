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
    refresh_project_counts, set_last_crawl_at, SOURCE_CRAWLING,
    attach_tag, detach_tag, job_is_cancelled, SYSTEM_TAG_PROXIED,
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "./scripts"))
CRAWL_TIMEOUT = int(os.environ.get("CRAWL_TIMEOUT", "1200"))
CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
CRAWL_RATE_LIMIT_DELAY = float(os.environ.get("CRAWL_RATE_LIMIT_DELAY", "0"))

# Deliberately narrow: only outcomes a different exit IP can plausibly change.
# Blocks (403), throttling (429) and edge/origin errors (5xx) qualify. 404, 401,
# redirects and ordinary 2xx never do — no vantage point turns those into a
# different answer, so retrying them is pure cost on metered proxy traffic.
RETRY_STATUSES = frozenset({403, 429, 503, 520, 521, 522, 523, 524})

# Crawling gets exactly TWO passes — direct, then a proxied retry — and
# deliberately NOT the intermediate direct-retry pass tech analysis performs.
# A tech probe is a single navigation; a crawl is up to CRAWL_MAX_PAGES
# navigations under a CRAWL_TIMEOUT of 1200s per host, with a fresh browser
# each time. A WAF deny on the datacenter IP is deterministic — a second direct
# crawl fingerprints the same IP and is served the same 403 — so a blanket
# direct re-crawl would trade up to 20 minutes of wall clock per host for a
# near-zero recovery rate.
PASS_LABELS = ("direct crawl", "proxy retry")


def _is_retry_candidate(parsed: dict | None) -> bool:
    """True when a host's direct crawl should be re-attempted through the proxy.

    The `#status` marker written by scripts/crawler.py is the sole authority on
    this decision:

      * parsed is None      — no output file at all (killed before any response)
      * status is None      — the run ended without ever observing a response
      * status in RETRY_STATUSES — blocked, throttled, or an edge/origin error

    A 200 with zero paths is NOT a candidate: that is an empty single-page app,
    not a block, and the proxy would return the same empty crawl.

    `ScriptResult.timed_out` is deliberately not consulted. Before the marker
    existed a timeout produced no file and merely looked retry-worthy; now a
    crawl that timed out after a 200 on the start URL still writes
    `#status 200`, which correctly reads as "we were not blocked, we just ran
    long" — pushing that through a metered proxy is wasted traffic. A timeout
    whose marker shows 403 or 429 is still a candidate, because the status says so.
    """
    if parsed is None:
        return True
    status = parsed.get("status")
    if status is None:
        return True
    return status in RETRY_STATUSES


def _contributed_endpoints(parsed: dict | None) -> bool:
    """True when this pass actually added to the stored endpoint set.

    Deliberately NOT the inverse of `_is_retry_candidate` — that answers
    "should the proxy try again", a question about the HTTP status. This one
    answers "did this pass produce the data now on record", and only the
    endpoint count can answer it.

    A merging writer is what forces the two apart. `merge_crawled_urls_bulk`
    unions into whatever is already stored, so a pass that yields no endpoints
    changes nothing: the endpoints on record still came from some earlier pass,
    possibly through a different vantage point. Several outcomes reach that
    state without being retry-worthy — a 404 start URL, or a 200 single-page app
    with zero crawlable paths — and each must leave the Proxied tag untouched
    rather than rewrite it to describe a crawl that stored nothing.
    """
    return parsed is not None and len(parsed["endpoints"]) > 0


async def run_crawler_job(job: dict, ws_broadcast=None):
    """
    Execute crawler on selected assets.
    Pipeline: runner → crawler_parser → DB write → WS emit

    Two passes: every host is crawled directly, then hosts whose direct crawl
    was blocked, throttled or never saw a response are re-crawled through the
    retry proxy.

    Result precedence needs no write-policy object of the kind the tech job
    requires: crawl is naturally additive. `merge_crawled_urls_bulk` merges into
    the stored endpoint set and `insert_assets_bulk` is idempotent, so a pass-2
    crawl that fails, times out, or returns nothing cannot destroy the endpoints
    pass 1 already committed. There is no "downgrade a good result" path to guard.
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
    retry_proxy_url = cfg.get("retry_proxy_url")

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
        pass_total = 2 if retry_proxy_url else 1

        # Asset-weighted progress. `assets_total` grows at the pass boundary,
        # once the retry set is known — before that the retry count is unknown
        # and guessing it would make the bar walk backwards.
        assets_done = 0
        assets_total = total

        async def line_broadcast(line: str):
            if ws_broadcast:
                await ws_broadcast("scan_line", {"job_id": job_id, "line": line})

        async def emit_progress(pass_index: int, pass_done: int, pass_size: int):
            if not ws_broadcast:
                return
            await ws_broadcast("scan_progress", {
                "job_id": job_id,
                "scan_type": "crawl",
                "pass_index": pass_index,
                "pass_total": pass_total,
                "pass_label": PASS_LABELS[pass_index - 1],
                "assets_done": assets_done,
                "assets_total": assets_total,
                "pass_assets_done": pass_done,
                "pass_assets_total": pass_size,
            })

        await line_broadcast(f"[*] Crawling {total} asset(s)")
        if proxy_url:
            await line_broadcast("[*] Routing crawler traffic through configured proxy")

        def persist_host(hostname: str, output_file: Path):
            """Commit one host's crawl results immediately so completed hosts
            survive a later timeout/cancel. Returns (created, parsed) where
            created is the count of new assets from discovered subdomains and
            parsed is the parsed crawl output (None if no output file exists).

            Tolerates output with or without a `#status` marker: nothing here
            reads parsed["status"], so a file written by an older crawler still
            persists exactly as before."""
            if not output_file.is_file():
                return 0, None
            content = output_file.read_text(encoding="utf-8", errors="replace")
            parsed = parse_crawler_output(content)
            merge_crawled_urls_bulk(session, project_id, {hostname: parsed["endpoints"]}, source="crawling")
            set_last_crawl_at(session, project_id, [hostname])
            # Hosts the crawler turned up are attributed to Crawling; the host
            # that was crawled keeps whatever source originally found it.
            created = insert_assets_bulk(
                session, project_id, parsed["subdomains"],
                source=SOURCE_CRAWLING, scan_job_id=job_id,
            ) if parsed["subdomains"] else 0
            refresh_project_counts(session, project_id)
            return created, parsed

        # Tracked for the cancellation flush below. Initialised here so a cancel
        # that lands before the first host has no loop variables to reference.
        current_hostname: str | None = None
        current_output_file: Path | None = None

        async def crawl_host(hostname: str, pass_proxy_url: str | None,
                             pass_index: int, position: int, pass_size: int) -> dict | None:
            """Run one crawl for one host and commit whatever it produced.

            Shared by both passes. Returns the parsed crawl output (including
            "status"), or None when the run produced no output file at all."""
            nonlocal new_count, total_duration, current_hostname, current_output_file

            asset_hash = hashlib.md5(hostname.encode()).hexdigest()[:12]
            output_file = crawl_dir / f"{asset_hash}_crawl.txt"
            url = f"https://{hostname}"

            current_hostname = hostname
            current_output_file = output_file

            label = PASS_LABELS[pass_index - 1]
            await line_broadcast(
                f"[*] [pass {pass_index}/{pass_total} {label}] [{position}/{pass_size}] Crawling {hostname}"
            )

            # The output path is stable across runs AND shared by both passes,
            # so a file left by an earlier job — or by this job's pass 1 — would
            # otherwise be read back as this run's result, and its stale
            # `#status` would decide the retry and the tag. Clearing it first
            # makes the marker authoritative; nothing is lost, because every
            # endpoint the old file held was merged into the DB when it was
            # written, and merges never drop what is already stored.
            try:
                output_file.unlink(missing_ok=True)
            except OSError:
                pass

            crawl_args = ["--start-url", url, "-o", str(output_file),
                          "--max-pages", str(crawl_max_pages),
                          "--delay", str(crawl_rate_limit_delay)]
            if pass_proxy_url:
                crawl_args += ["--proxy", pass_proxy_url]

            result = await run_script(
                script_path=str(SCRIPTS_DIR / "crawler.py"),
                args=crawl_args,
                job_id=f"{job_id}_p{pass_index}_{asset_hash}",
                timeout_seconds=int(crawl_timeout + crawl_rate_limit_delay * crawl_max_pages),
                ws_broadcast=line_broadcast,
                log_dir=log_dir,
            )

            total_duration += result.duration_seconds

            if result.timed_out:
                await line_broadcast(f"[!] {hostname}: TIMEOUT after {crawl_timeout}s")
            elif result.exit_code != 0:
                await line_broadcast(f"[!] {hostname}: script exited with code {result.exit_code}")

            # Persist whatever was written, timeout or not — a run that reached
            # some pages before being cut off still contributes those endpoints.
            created, parsed = persist_host(hostname, output_file)
            new_count += created

            if parsed is None:
                await line_broadcast(f"[!] {hostname}: no output produced")
                return None

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
            return parsed

        cancelled = False

        try:
            # ── Pass 1: direct ──────────────────────────────────────
            retry_hosts: list[str] = []
            direct_stored: list[str] = []

            for i, hostname in enumerate(hostnames, 1):
                parsed = await crawl_host(hostname, proxy_url, 1, i, total)
                if _is_retry_candidate(parsed):
                    retry_hosts.append(hostname)
                if _contributed_endpoints(parsed):
                    direct_stored.append(hostname)
                assets_done += 1
                await emit_progress(1, i, total)

            # One bulk tag call per pass, never per host. The tag must describe
            # the vantage point that produced the endpoints currently stored,
            # so pass 1 attaches when it ran through the configured proxy and
            # detaches when it ran directly.
            #
            # `direct_stored` is the set of hosts that CONTRIBUTED ENDPOINTS to
            # the merged set this pass — not the hosts that left an output file
            # behind, and not merely the hosts that avoided a retry. A blocked
            # host writes a marker-only file; a 404 or an empty single-page app
            # writes a file with a perfectly fine status and no paths. None of
            # those three stored anything.
            #
            # The merging writer is what forces that distinction, and it is
            # where crawl legitimately differs from tech analysis: tech
            # OVERWRITES the asset row, so even a bare 403 really is that pass's
            # result and detaching on it is correct. `merge_crawled_urls_bulk`
            # UNIONS, so a pass that merged nothing left the previously stored
            # endpoints — and the vantage point that found them — exactly as
            # they were. It must not claim or disclaim that result in either
            # direction. Do not harmonise the two.
            if direct_stored:
                if proxy_url:
                    attach_tag(session, project_id, direct_stored, SYSTEM_TAG_PROXIED)
                else:
                    detach_tag(session, project_id, direct_stored, SYSTEM_TAG_PROXIED)

            # ── Pass 2: proxied retry ───────────────────────────────
            # The worker only polls for cancellation between jobs, so a cancel
            # requested during pass 1 must be honoured here rather than letting
            # a second, expensive pass start. Checked unconditionally: with
            # retries off there is no pass 2 to skip, but the job must still not
            # report itself complete when the DB already says cancelled.
            cancelled = job_is_cancelled(session, job_id)

            if retry_proxy_url and retry_hosts and not cancelled:
                pass_size = len(retry_hosts)
                assets_total += pass_size
                await line_broadcast(
                    f"[*] Retrying {pass_size} blocked or unanswered asset(s) through the retry proxy"
                )
                await emit_progress(2, 0, pass_size)

                proxied_stored: list[str] = []
                for i, hostname in enumerate(retry_hosts, 1):
                    parsed = await crawl_host(hostname, retry_proxy_url, 2, i, pass_size)
                    # Same predicate as pass 1: a host that merged no endpoints
                    # through the proxy — still blocked, or simply empty — keeps
                    # whatever tag state the data on record already earned. Only
                    # endpoints the proxy actually contributed mark the stored
                    # result as proxied.
                    if _contributed_endpoints(parsed):
                        proxied_stored.append(hostname)
                    assets_done += 1
                    await emit_progress(2, i, pass_size)

                if proxied_stored:
                    attach_tag(session, project_id, proxied_stored, SYSTEM_TAG_PROXIED)
        except asyncio.CancelledError:
            # Manual cancellation — flush whatever the interrupted host produced
            # before propagating the cancel. The crawler checkpoints its
            # `#status` marker as soon as the start URL responds, but paths are
            # still written once at the end, so this recovers a partial file
            # only when the run got far enough to write one.
            if current_hostname is not None and current_output_file is not None:
                try:
                    persist_host(current_hostname, current_output_file)
                except Exception:
                    pass
            raise

        if cancelled:
            # The job already left "running" — leave its cancelled status and
            # timestamps exactly as the canceller wrote them. Everything pass 1
            # committed is already durable, host by host.
            await line_broadcast("[*] Cancelled — stopping after the direct crawl pass")
            return

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
