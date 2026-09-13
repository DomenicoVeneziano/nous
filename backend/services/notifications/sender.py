# backend/services/notifications/sender.py
"""Delivery: one canonical event out to every enabled channel.

Three properties this module is responsible for, all of them load-bearing:

* No secret ever reaches a log line, an exception message or a return value. A
  webhook URL is itself a credential — anyone holding it can post to the
  channel — so failures are reported as a channel name plus an HTTP status or
  an exception class name, and nothing else. That holds for the libraries we
  call as well as for our own lines: see _HttpxTraceFilter below.
* No leak. The HTTP client used on the notification path is owned by the caller
  and reused across sends; every attempt carries the configured timeout on the
  request itself, with asyncio.wait_for behind it as a hard backstop, so a hung
  target cannot pin a task forever, and cancellation propagates.
* No channel can starve another. Channels are attempted in sequence, each
  wrapped so a raised exception is recorded and the next channel still runs.
"""
import asyncio
import contextlib
import json
import logging
import math
import re
import tempfile
import threading
import time

import httpx

from config import settings as cfg
from database import SessionLocal
from services.settings_store import validate_webhook_url

from . import render
from .summary import clamped, is_failure, is_success, iter_report_rows

log = logging.getLogger("backend.notifications")


class _HttpxTraceFilter(logging.Filter):
    """Drops httpx's own request tracing before it can reach a handler.

    httpx logs the full request line — method, URL, status — at INFO from its
    own "httpx" logger, and on this path that URL *is* the credential: a Slack
    or Discord incoming webhook is usable in full by anyone holding it, and
    Telegram's send URL carries the bot token in its path. Left alone, every
    successful delivery writes a working secret into the container logs, where
    `docker compose logs`, any log shipper and every archive of them picks it
    up — which is the whole point of storing these values write-only, undone by
    the library on the way out.

    A filter rather than a level, because a level is only a number and anyone
    can put it back: uvicorn's log config, a later dictConfig, a setLevel left
    behind after a debugging session. A filter attached to the logger runs on
    every record that logger handles, whatever its level and whatever handlers
    are configured, and it is installed on logging.getLogger("httpx") — the
    same object whether or not httpx has been imported yet, so this does not
    depend on import order.

    Everything below WARNING is dropped, not just the request line, because
    httpx's DEBUG output traces the same requests. WARNING and above still get
    through, and this filter does not touch our own lines: those name a channel
    and an HTTP status or an exception class, never a URL or a token, and they
    are how an operator sees what was delivered.

    This applies to httpx everywhere in the backend, not only to notifications.
    That is deliberate: httpx has no other caller today, and a second one added
    later inherits the same protection instead of quietly re-opening this hole.

    DO NOT swap this for a level to debug a delivery. What it prints is the
    webhook itself. Reproduce against a local endpoint instead.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


def _install_httpx_trace_filter() -> None:
    """Install the filter once, whichever send path imports this module first."""
    httpx_log = logging.getLogger("httpx")
    if not any(isinstance(f, _HttpxTraceFilter) for f in httpx_log.filters):
        httpx_log.addFilter(_HttpxTraceFilter())


# At import, so it is in place before either send path — the notifier's shared
# client or send_test's own — can build a request.
_install_httpx_trace_filter()

CHANNELS = ("slack", "discord", "webhook", "telegram")

# Fixed backoff, deliberately not exponential and deliberately not jittered: the
# retry budget is at most 5, so the worst case is bounded at a few seconds. The
# last value repeats if the budget is larger than the schedule.
_BACKOFF_SECONDS = (1.0, 2.0)

# Retry only these: a rate limit, a server-side error, or a transport failure
# that happened before any byte of the request could have been accepted. Every
# other 4xx is a permanent fault in the stored configuration (revoked webhook,
# wrong chat) and retrying it only burns the budget.
#
# A read timeout is deliberately NOT in this set, and neither is a write timeout
# or the wait_for backstop: by then the request has been written to a target
# that simply has not answered yet, so the message may already have been
# accepted and a retry would post it twice. Delivery here is at-most-once by
# design (see notifier._claim_one), so an ambiguous outcome is reported as a
# failure rather than replayed. A connect or pool timeout is unambiguous —
# nothing was ever sent — so those do retry.
_RETRYABLE_STATUS = (429,)
_RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

# Telegram's token is placed in the URL path, so it is checked against a strict
# shape before use. Nothing that fails this can introduce a path segment, a
# query string or a host change.
TELEGRAM_TOKEN_RE = re.compile(r"\A[0-9]{1,20}:[A-Za-z0-9_-]{20,256}\Z")
# Both patterns anchor with \A and \Z rather than ^ and $, because $ also
# matches just before a trailing newline and both values are placed in a URL —
# the token in the path, the chat id in the body. The chat-id shape itself is
# owned by backend/routers/settings.py, which rejects a bad value at save time;
# this copy re-checks what was stored and must accept exactly the same set of
# values, so keep the two in step when either changes.
_TELEGRAM_CHAT_ID_RE = re.compile(r"\A(-?[0-9]{1,32}|@[A-Za-z0-9_]{5,32})\Z")

_MESSAGE_CHARS = 200

# Head start the request's own timeout is given over the asyncio backstop, so
# httpx reports the precise transport fault (a connect timeout retries, a read
# timeout does not) instead of both firing at once and collapsing into an
# indistinguishable asyncio.TimeoutError.
_TIMEOUT_GRACE_SECONDS = 1.0

_USER_AGENT = "Nous/1.0"

# Slack allows about one message per second on an incoming webhook.
SLACK_SPACING_SECONDS = 1.1

# Report parts come after a delivered summary and the notifier sends one event
# after another, so they get at most one retry and the Slack follow-ups a time
# budget: a slow target must not stall every notification queued behind it.
REPORT_PART_RETRIES = 1
REPORT_PARTS_BUDGET_SECONDS = 120

# An upload's asyncio backstop grows with its size at an assumed floor of
# 128 KiB/s, by at most 64 seconds. httpx applies its own timeout per chunk and
# needs no scaling; the fixed backstop alone would cut a large report off on a
# slow link as an ambiguous, unretried timeout.
UPLOAD_MIN_BPS = 128 * 1024
_UPLOAD_BACKSTOP_MAX_SECONDS = 64


def _timeout_seconds() -> float:
    return float(clamped("NOTIFY_TIMEOUT_SECONDS"))


def _retries() -> int:
    return clamped("NOTIFY_RETRIES")


def _stored(key: str) -> str:
    value = getattr(cfg, key, "") or ""
    return value.strip() if isinstance(value, str) else ""


def _safe_url(key: str) -> str | None:
    """A stored webhook URL, or None when it is unset or not a usable http(s) URL.

    validate_webhook_url raises with a message that describes the fault without
    echoing the value, so nothing here can put a secret into a log line.
    """
    raw = _stored(key)
    if not raw:
        return None
    try:
        return validate_webhook_url(raw)
    except ValueError as exc:
        log.warning("notification target rejected: %s", exc)
        return None


def _channel_enabled(channel: str) -> bool:
    return bool(getattr(cfg, f"NOTIFY_{channel.upper()}_ENABLED", False))


def _build_target(channel: str, event: dict) -> tuple[str, dict, dict] | None:
    """Return (url, headers, json_body) for a channel, or None if it cannot send."""
    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}

    if channel == "slack":
        url = _safe_url("NOTIFY_SLACK_WEBHOOK_URL")
        if not url:
            return None
        return url, headers, render.build_slack_payload(event)

    if channel == "discord":
        url = _safe_url("NOTIFY_DISCORD_WEBHOOK_URL")
        if not url:
            return None
        return url, headers, render.build_discord_payload(event)

    if channel == "webhook":
        url = _safe_url("NOTIFY_WEBHOOK_URL")
        if not url:
            return None
        token = _stored("NOTIFY_WEBHOOK_TOKEN")
        if token:
            headers = dict(headers)
            headers["Authorization"] = f"Bearer {token}"
        # The canonical event IS the generic webhook body; nothing to render.
        return url, headers, event

    if channel == "telegram":
        token = _stored("NOTIFY_TELEGRAM_BOT_TOKEN")
        chat_id = _stored("NOTIFY_TELEGRAM_CHAT_ID")
        if not TELEGRAM_TOKEN_RE.match(token) or not _TELEGRAM_CHAT_ID_RE.match(chat_id):
            return None
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return url, headers, render.build_telegram_payload(event, chat_id)

    return None


async def _post_once(
    client: httpx.AsyncClient, url: str, headers: dict, body: dict | None, timeout: float,
    data: dict | None = None, files: dict | None = None,
) -> httpx.Response:
    # The configured timeout is applied to the request, not to the client: the
    # client is supplied by the caller (the notifier's shared one, or the test
    # send's own), and a per-request timeout overrides whatever that client was
    # built with. Without it httpx's own 5s default would silently govern the
    # notification path while the test path used the operator's value, so the
    # two could disagree about the same setting.
    #
    # follow_redirects is False on every channel, not only the generic webhook:
    # a 30x from a target would re-send the body, and on the generic webhook the
    # Authorization bearer token, to a host the operator never configured.
    #
    # A retried upload must start again from the file's first byte.
    for _name, fh, _ctype in (files or {}).values():
        fh.seek(0)
    return await client.post(
        url, json=body, data=data, files=files, headers=headers,
        follow_redirects=False, timeout=timeout,
    )


async def _deliver(
    client: httpx.AsyncClient, channel: str, url: str, headers: dict, body: dict | None = None,
    *, data: dict | None = None, files: dict | None = None, upload_bytes: int = 0,
    retries: int | None = None,
) -> tuple[bool, str]:
    """Send one payload with a per-attempt timeout and a bounded retry.

    Returns (ok, detail) where detail carries a status code or an exception
    class name — never a URL, a token, or an exception message that might quote
    one back.
    """
    attempts = (_retries() if retries is None else retries) + 1
    timeout = _timeout_seconds()
    backstop = timeout + _TIMEOUT_GRACE_SECONDS + min(
        _UPLOAD_BACKSTOP_MAX_SECONDS, math.ceil(upload_bytes / UPLOAD_MIN_BPS)
    )
    detail = "not attempted"

    for attempt in range(attempts):
        retryable = False
        try:
            # httpx enforces the configured timeout per phase; wait_for bounds
            # the whole attempt so a target that trickles bytes forever, or a
            # client whose timeout was somehow disabled, still cannot pin the
            # task. The grace keeps httpx's more precise error the usual one.
            response = await asyncio.wait_for(
                _post_once(client, url, headers, body, timeout, data, files),
                timeout=backstop,
            )
        except asyncio.TimeoutError:
            # Same reasoning as a read timeout: by here the request was sent and
            # the outcome is unknown, so it is reported, not replayed.
            detail = f"timeout after {timeout:.0f}s"
        except _RETRYABLE_EXCEPTIONS as exc:
            detail = type(exc).__name__
            retryable = True
        except httpx.HTTPError as exc:
            detail = type(exc).__name__
        else:
            status = response.status_code
            detail = f"HTTP {status}"
            if 200 <= status < 300:
                return True, detail
            retryable = status in _RETRYABLE_STATUS or status >= 500

        log.warning("notification to %s failed (%s)", channel, detail)
        if not retryable or attempt >= attempts - 1:
            return False, detail
        backoff = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
        await asyncio.sleep(backoff)

    return False, detail


def _item_total(event: dict) -> int:
    summary = event.get("summary") or {}
    return int(summary.get("new_assets") or 0) + int(summary.get("total_changes") or 0)


def _build_sync(fh, event: dict, stop: threading.Event, lock: threading.Lock, state: dict,
                want_lists: bool, want_file: bool, rows) -> dict | None:
    """Write the full report into `fh`. Runs on a worker thread.

    Without given `rows`, the event's rows are read page by page through a
    session this function owns.
    """
    with lock:
        if stop.is_set():
            return None
        state["started"] = True
    db = None
    try:
        if rows is None:
            job = event.get("job") or {}
            db = SessionLocal()
            rows = iter_report_rows(db, job.get("project_id"), job.get("id"), stop)
        meta = render.write_report(
            fh, event, rows, _item_total(event), want_lists=want_lists, want_file=want_file, stop=stop
        )
        # Load-bearing: httpx sizes a multipart file from the descriptor, which
        # sees only what has left the write buffer.
        fh.flush()
        return meta
    finally:
        if db is not None:
            db.close()
        # A cancelled _report stops waiting for this thread but must not close
        # the file under a write still in progress here: the descriptor number
        # could be reused and receive report bytes. So whichever side finishes
        # last closes it, exactly once.
        with lock:
            state["done"] = True
            if stop.is_set():
                fh.close()


@contextlib.asynccontextmanager
async def _report(event: dict, *, want_lists: bool, want_file: bool, rows=None):
    """Yield (file, meta) for the event's full report, or None without one.

    None means there is nothing to report or it could not be built; channels
    then send the summary alone. The file is anonymous, so even a crash leaves
    nothing on disk, and it is closed exactly once on every exit: here, or by
    the build thread when it is still running at that point (see _build_sync).
    """
    if _item_total(event) <= 0:
        yield None
        return
    stop = threading.Event()
    lock = threading.Lock()
    state = {"started": False, "done": False}
    fh = None
    try:
        meta = None
        try:
            fh = tempfile.TemporaryFile("w+b")
            meta = await asyncio.to_thread(
                _build_sync, fh, event, stop, lock, state, want_lists, want_file, rows
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the summary still goes out without it
            log.warning("notification report could not be built (%s)", type(exc).__name__)
        yield None if meta is None else (fh, meta)
    finally:
        with lock:
            stop.set()
            # Not started means the executor never ran the build, and now never
            # will: it checks `stop` first.
            if fh is not None and (state["done"] or not state["started"]):
                fh.close()


def _with_lists(event: dict, report) -> dict:
    """A copy of the event with the full lists in its summary: the webhook body.

    Without a report the lists are empty and every item counts as omitted, so a
    receiver never mistakes a failed build for an empty scan.
    """
    lists = report[1]["lists"] if report is not None else None
    if lists is None:
        total = _item_total(event)
        lists = {"new_assets_all": [], "changes_all": [], "lists_omitted": total}
    return dict(event, summary=dict(event.get("summary") or {}, **lists))


async def _send_channel(client: httpx.AsyncClient, channel: str, event: dict, report) -> tuple[bool, str] | None:
    """Send the summary, then this channel's part of the full report.

    Returns None when the channel cannot be built from its stored settings. The
    summary goes first and is never sent twice; report parts stop at the first
    failure. A channel counts as delivered only when every part was, and the
    detail names the part that was not.
    """
    target = _build_target(channel, _with_lists(event, report) if channel == "webhook" else event)
    if target is None:
        return None
    url, headers, body = target
    # The webhook body carries the lists, up to WEBHOOK_LISTS_BYTES, so its
    # backstop scales like an upload's.
    list_bytes = report[1]["list_bytes"] if channel == "webhook" and report is not None else 0
    ok, detail = await _deliver(client, channel, url, headers, body, upload_bytes=list_bytes)
    if report is None:
        return ok, f"{detail}; no report" if _item_total(event) > 0 else detail
    if channel == "webhook":
        return ok, detail
    detail = f"summary {detail}"
    if not ok:
        return False, detail
    fh, meta = report

    if channel == "slack":
        fh.seek(meta["body_offset"])
        lines = (raw.decode("utf-8", "replace") for raw in fh)
        chunks = render.slack_followups(lines, _item_total(event), meta["labels"], meta["body_lines"])
        deadline = time.monotonic() + REPORT_PARTS_BUDGET_SECONDS
        # Longest one attempt can take; a retry is only allowed while the time
        # left still holds this attempt, the backoff and the retry itself.
        attempt = _timeout_seconds() + _TIMEOUT_GRACE_SECONDS
        for number, chunk in enumerate(chunks, 1):
            if time.monotonic() + SLACK_SPACING_SECONDS > deadline:
                return False, f"{detail}; followups stopped after {number - 1} (time budget)"
            await asyncio.sleep(SLACK_SPACING_SECONDS)
            remaining = deadline - time.monotonic()
            retries = min(_retries(), REPORT_PART_RETRIES) if remaining >= 2 * attempt + _BACKOFF_SECONDS[0] else 0
            ok, part = await _deliver(client, channel, url, headers, {"text": chunk}, retries=retries)
            if not ok:
                return False, f"{detail}; followup {number} {part}"
        return True, f"{detail}; {len(chunks)} followups"

    name = render.report_filename((event.get("job") or {}).get("id"))
    if channel == "discord":
        data = {"payload_json": json.dumps(render.DISCORD_REPORT_PAYLOAD)}
        files = {"files[0]": (name, fh, "text/plain")}
    else:
        # Telegram. _build_target has already checked the token this URL carries.
        url = url.rsplit("/", 1)[0] + "/sendDocument"
        data = {"chat_id": body["chat_id"]}
        files = {"document": (name, fh, "text/plain")}
    # No JSON Content-Type on a multipart request: httpx sets its own, with the
    # boundary in it.
    ok, part = await _deliver(
        client, channel, url, {"User-Agent": _USER_AGENT},
        data=data, files=files, upload_bytes=meta["size"],
        retries=min(_retries(), REPORT_PART_RETRIES),
    )
    return ok, f"{detail}; report {part}"


def should_notify(status: str | None) -> bool:
    """Whether a terminal job status should produce a notification at all."""
    if not getattr(cfg, "NOTIFY_ENABLED", False):
        return False
    if is_success(status):
        return bool(getattr(cfg, "NOTIFY_ON_SUCCESS", False))
    if is_failure(status):
        return bool(getattr(cfg, "NOTIFY_ON_FAILURE", False))
    return False


async def dispatch(client: httpx.AsyncClient, event: dict) -> dict[str, bool]:
    """Deliver one canonical event to every enabled channel.

    `client` is an httpx.AsyncClient owned by the caller and reused across
    notifications: a client created per send would open a fresh connection pool
    every time and leak sockets on the hot path.

    Returns {channel: delivered}. Never raises for a delivery failure; only
    cancellation propagates.
    """
    results: dict[str, bool] = {}
    status = ((event or {}).get("job") or {}).get("status")
    if not should_notify(status):
        return results

    enabled = [channel for channel in CHANNELS if _channel_enabled(channel)]
    if not enabled:
        return results

    # One report serves every channel of this dispatch, and is gone once the
    # last channel has been attempted.
    want_file = any(channel != "webhook" for channel in enabled)
    async with _report(event, want_lists="webhook" in enabled, want_file=want_file) as report:
        for channel in enabled:
            # One channel's failure must never skip the next, so every channel —
            # including payload construction — is wrapped.
            try:
                outcome = await _send_channel(client, channel, event, report)
                if outcome is None:
                    log.warning("notification channel %s enabled but not configured", channel)
                    results[channel] = False
                    continue
                ok, detail = outcome
                results[channel] = ok
                if ok:
                    log.info("notification to %s delivered (%s)", channel, detail)
                else:
                    log.warning("notification to %s not fully delivered (%s)", channel, detail)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — one channel must not stop the rest
                results[channel] = False
                log.warning("notification to %s raised %s", channel, type(exc).__name__)

    return results


def _synthetic_event() -> dict:
    """A representative event for a test send, with no real scan data in it."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return {
        "event": "scan_job_finished",
        "job": {
            "id": "00000000-0000-0000-0000-000000000000",
            "scan_type": "recon",
            "status": "done",
            "project_id": "00000000-0000-0000-0000-000000000000",
            "project_title": "Nous test notification",
            "started_at": now,
            "finished_at": now,
            "duration_s": 12.3,
            "error_msg": None,
        },
        "summary": {"new_assets": 3, "changed_assets": 2, "total_changes": 5},
        "generated_at": now,
    }


def _synthetic_rows() -> list[tuple]:
    """The report rows matching _synthetic_event's counts.

    The third asset and the title change are hostile on purpose: a line
    separator, a bidi override and a CRLF must each stay on the one line they
    arrived in.
    """
    return [
        ("new", "test-a.example.com"),
        ("new", "test-b.example.com"),
        ("new", "test-c.example.com\N{LINE SEPARATOR}New: internal-admin.corp"),
        ("field", "status_code", 2),
        ("change", "test-a.example.com", "status_code", "404", "200"),
        ("change", "test-b.example.com", "status_code", "200", "403"),
        ("field", "technologies", 1),
        ("change", "test-a.example.com", "technologies", "[]", '["nginx"]'),
        ("change", "test-a.example.com", "technologies", '["nginx"]', '["nginx", "php"]'),
        ("field", "title", 1),
        (
            "change", "test-b.example.com", "title", "Login",
            "\N{RIGHT-TO-LEFT OVERRIDE}evil\N{CARRIAGE RETURN}\N{LINE FEED}New: forged.corp",
        ),
    ]


async def send_test(channel: str) -> tuple[bool, str]:
    """Send a synthetic event to one channel using the STORED credentials.

    Takes no secret and returns none: the caller names a channel, and the
    message is a short status string with no URL and no token in it.
    """
    if channel not in CHANNELS:
        return False, "Unknown channel"

    event = _synthetic_event()
    rows = _synthetic_rows()
    try:
        # A test send is a one-off, so it owns a short-lived client of its own
        # rather than borrowing the notification path's shared one. It sets no
        # client-level timeout: _post_once puts the configured one on the
        # request, which is what makes the two paths behave identically.
        async with httpx.AsyncClient() as client, _report(
            event, want_lists=channel == "webhook", want_file=channel != "webhook", rows=rows
        ) as report:
            outcome = await _send_channel(client, channel, event, report)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        return False, f"Test send to {channel} failed ({type(exc).__name__})"

    if outcome is None:
        return False, f"The {channel} channel is not configured"
    ok, detail = outcome
    message = f"Test send to {channel} {'succeeded' if ok else 'failed'} ({detail})"
    return ok, message[:_MESSAGE_CHARS]
