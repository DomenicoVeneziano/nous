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
import logging
import re

import httpx

from config import settings as cfg
from services.settings_store import NOTIFY_BOUNDS, validate_webhook_url

from . import render
from .summary import empty_summary, is_failure, is_success

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


def _clamped(key: str) -> int:
    """A bounded NOTIFY_* integer, re-clamped at use time as well as at save time."""
    low, high = NOTIFY_BOUNDS[key]
    try:
        value = int(getattr(cfg, key, low))
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _timeout_seconds() -> float:
    return float(_clamped("NOTIFY_TIMEOUT_SECONDS"))


def _retries() -> int:
    return _clamped("NOTIFY_RETRIES")


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
        return url, headers, render.build_generic_payload(event)

    if channel == "telegram":
        token = _stored("NOTIFY_TELEGRAM_BOT_TOKEN")
        chat_id = _stored("NOTIFY_TELEGRAM_CHAT_ID")
        if not TELEGRAM_TOKEN_RE.match(token) or not _TELEGRAM_CHAT_ID_RE.match(chat_id):
            return None
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return url, headers, render.build_telegram_payload(event, chat_id)

    return None


async def _post_once(
    client: httpx.AsyncClient, url: str, headers: dict, body: dict, timeout: float
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
    return await client.post(
        url, json=body, headers=headers, follow_redirects=False, timeout=timeout
    )


async def _deliver(client: httpx.AsyncClient, channel: str, url: str, headers: dict, body: dict) -> tuple[bool, str]:
    """Send one payload with a per-attempt timeout and a bounded retry.

    Returns (ok, detail) where detail carries a status code or an exception
    class name — never a URL, a token, or an exception message that might quote
    one back.
    """
    attempts = _retries() + 1
    timeout = _timeout_seconds()
    detail = "not attempted"

    for attempt in range(attempts):
        retryable = False
        try:
            # httpx enforces the configured timeout per phase; wait_for bounds
            # the whole attempt so a target that trickles bytes forever, or a
            # client whose timeout was somehow disabled, still cannot pin the
            # task. The grace keeps httpx's more precise error the usual one.
            response = await asyncio.wait_for(
                _post_once(client, url, headers, body, timeout),
                timeout=timeout + _TIMEOUT_GRACE_SECONDS,
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

    for channel in CHANNELS:
        if not _channel_enabled(channel):
            continue
        # One channel's failure must never skip the next, so every channel —
        # including payload construction — is wrapped.
        try:
            target = _build_target(channel, event)
            if target is None:
                log.warning("notification channel %s enabled but not configured", channel)
                results[channel] = False
                continue
            url, headers, body = target
            ok, detail = await _deliver(client, channel, url, headers, body)
            results[channel] = ok
            if ok:
                log.info("notification to %s delivered (%s)", channel, detail)
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
    summary = empty_summary()
    summary.update({
        "new_assets": 2,
        "changed_assets": 1,
        "total_changes": 3,
        "changes_by_field": {"technologies": 2, "status_code": 1},
        "new_asset_sample": ["test-a.example.com", "test-b.example.com"],
        "change_sample": [
            {"asset": "test-a.example.com", "field": "status_code", "old": "404", "new": "200"},
        ],
    })
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
        "summary": summary,
        "generated_at": now,
    }


async def send_test(channel: str) -> tuple[bool, str]:
    """Send a synthetic event to one channel using the STORED credentials.

    Takes no secret and returns none: the caller names a channel, and the
    message is a short status string with no URL and no token in it.
    """
    if channel not in CHANNELS:
        return False, "Unknown channel"

    try:
        target = _build_target(channel, _synthetic_event())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not build the {channel} request ({type(exc).__name__})"

    if target is None:
        return False, f"The {channel} channel is not configured"

    url, headers, body = target
    timeout = _timeout_seconds()
    try:
        # A test send is a one-off, so it owns a short-lived client of its own
        # rather than borrowing the notification path's shared one. It sets no
        # client-level timeout: _post_once puts the configured one on the
        # request, which is what makes the two paths behave identically.
        async with httpx.AsyncClient() as client:
            ok, detail = await _deliver(client, channel, url, headers, body)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        return False, f"Test send to {channel} failed ({type(exc).__name__})"

    message = f"Test send to {channel} {'succeeded' if ok else 'failed'} ({detail})"
    return ok, message[:_MESSAGE_CHARS]
