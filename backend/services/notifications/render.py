# backend/services/notifications/render.py
"""One shared body text, four per-channel payloads, the full report, and the
escaping each needs.

Everything interpolated below — asset hostnames, page titles, field values,
project titles, engine error messages — is attacker-influenced text: it comes
from a scanned host, not from an operator. Each channel therefore gets the
escaping its own renderer requires, applied at the point of interpolation. The
escaping rules in this module are security controls, not formatting taste.
"""
import json
import re
import unicodedata
from datetime import datetime, timezone

# Slack renders one section block up to 3000 characters and drops the whole
# message if a block overflows; 2900 leaves room for the block scaffolding.
SLACK_BODY_CHARS = 2900
# Discord's embed description limit is 4096; Telegram's sendMessage text limit
# is 4096 UTF-16 code units. 4000 is comfortably inside both.
DISCORD_BODY_CHARS = 4000
TELEGRAM_BODY_CHARS = 4000
# The Slack "text" fallback is the notification preview, not the message.
FALLBACK_CHARS = 300

# The full report file. 8 MiB fits Discord's 10 MB webhook attachment limit
# with room for the multipart envelope, and sits far below Telegram's 50 MB. The
# reserve keeps room for the trailer that says how much was left out.
REPORT_MAX_BYTES = 8 * 1024 * 1024
REPORT_TRAILER_RESERVE = 256
# Lists carried in the generic webhook body. The dict and httpx's serialised
# copy are both in memory while it sends, and a body past a receiver's proxy
# limit comes back 413, which is not retried.
WEBHOOK_LISTS_BYTES = 2 * 1024 * 1024
# Slack incoming webhooks cannot attach a file, so Slack gets the summary plus
# follow-ups. A line is clipped before slack_escape, whose worst case is 5x
# (& -> &amp;), so any single line still fits a block.
SLACK_MAX_MESSAGES = 10
SLACK_LINE_CHARS = 500
TELEGRAM_CAPTION_CHARS = 1024

# The attachment name lands in a multipart Content-Disposition header, so only
# a job id of the UUID shape may reach it.
_REPORT_ID_RE = re.compile(r"\A[0-9a-f-]{1,64}\Z")

# Longest single old/new value shown in a body line. The values already arrive
# truncated to 80 characters by the SQL in summary.py; this only guards the
# rendered line.
VALUE_CHARS = 80
ERROR_CHARS = 300

DISCORD_COLOR_SUCCESS = 0x2ECC71
DISCORD_COLOR_FAILURE = 0xE74C3C

_SUCCESS_STATUSES = ("done",)


# Categories dropped from every interpolated value. Cc covers the ASCII control
# characters including newline and carriage return; Cf covers the bidi overrides
# and the invisible joiners; Cs and Co are surrogates and private use, which no
# client renders predictably. Zl and Zp are LINE SEPARATOR (U+2028) and PARAGRAPH
# SEPARATOR (U+2029): Slack, Discord and Telegram all break a line on them, so
# leaving them in would let scan data end a line exactly like a newline does.
_DROPPED_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")


def _sanitize(value) -> str:
    """Drop every control, formatting and line-separating character from a value.

    Applied by all three escapers before their channel-specific rules. Scan data
    supplies the value, and the renderer — not the data — decides where a line
    ends: a hostname or page title carrying any character a client treats as a
    line break would otherwise forge an extra summary row, such as a fake
    "New: internal-admin.corp". A bidi override (U+202E and friends, category Cf)
    goes for a different reason — it reverses the text after it, hiding what the
    message really says. A plain space is kept; it is the only whitespace a value
    is allowed to carry.
    """
    out = "" if value is None else str(value)
    return "".join(ch for ch in out if ch == " " or unicodedata.category(ch) not in _DROPPED_CATEGORIES)


def slack_escape(value) -> str:
    """Escape a value for Slack mrkdwn.

    Slack's documented rule is exactly these three, ampersand first so the
    replacements it introduces are not re-escaped. Without this a hostname or
    page title containing <http://evil|click me> renders as a live link, and
    <!channel> renders as a broadcast.
    """
    out = _sanitize(value)
    return out.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Characters that carry meaning to Discord's markdown parser and must not reach
# it as syntax. Order matters: the backslash goes first, so the backslashes this
# table introduces are never themselves re-escaped, and so a backslash arriving
# in scan data cannot escape the escape of the character after it.
#
# "[" and "]" are here because of masked links. Discord renders
# [label](url) in an embed description as a live clickable link showing only the
# label, so a crawled page title of "[Session expired - re-authenticate](https://evil.tld)"
# would post a phishing link into the operator's channel over the Nous bot's own
# name. Breaking the label bracket is enough to stop the construct from parsing.
#
# "*", "_", "~" and "|" are the emphasis, underline, strikethrough and spoiler
# runs. Scan data must not be able to restyle a message, hide half a summary row
# behind a spoiler bar, or leave an unclosed run that swallows the lines after it.
#
# A backslash escape is used rather than deleting the character because Discord
# consumes the backslash and renders the character itself: an underscore in a
# hostname or a technology name still reads correctly to a human.
_DISCORD_ESCAPES = ("\\", "*", "_", "~", "|", "[", "]")


def discord_escape(value) -> str:
    """Escape a value for a Discord embed description.

    Backticks are stripped rather than escaped: a lone backtick from asset data
    would otherwise open a code span that swallows the rest of the body, and
    three of them would open a fenced block. Mentions are neutralised at the
    payload level by allowed_mentions, not here.
    """
    out = _sanitize(value).replace("`", "")
    for ch in _DISCORD_ESCAPES:
        out = out.replace(ch, "\\" + ch)
    return out


def plain_escape(value) -> str:
    """Pass a value through for a plain-text target (Telegram, Slack fallback).

    Nothing is escaped because nothing is parsed: the Telegram payload omits
    parse_mode on purpose. Only the shared control-character strip applies.
    """
    return _sanitize(value)


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(0, limit - 1)] + "…"


def _duration(seconds) -> str:
    if seconds is None:
        return "unknown"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {rest}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def headline(event: dict, esc=plain_escape) -> str:
    """The single-line summary used as a title or a notification fallback."""
    job = event.get("job") or {}
    summary = event.get("summary") or {}
    status = str(job.get("status") or "unknown")
    verb = "completed" if status in _SUCCESS_STATUSES else status.replace("_", " ")
    scan_type = esc(job.get("scan_type") or "scan")
    title = esc(job.get("project_title") or "unknown project")
    line = f"{scan_type} scan {verb} for {title}"
    if status in _SUCCESS_STATUSES:
        line += (
            f" — {int(summary.get('new_assets') or 0)} new,"
            f" {int(summary.get('total_changes') or 0)} changes"
        )
    return _clip(line, FALLBACK_CHARS)


def report_header_lines(event: dict, esc=plain_escape) -> list[str]:
    """Headline, status, timing, error and counts: the top of the message body
    and of the report file alike."""
    job = event.get("job") or {}
    summary = event.get("summary") or {}
    status = str(job.get("status") or "unknown")

    lines = [headline(event, esc)]
    lines.append(
        f"Status: {esc(status)} | Duration: {_duration(job.get('duration_s'))}"
    )
    finished = job.get("finished_at")
    if finished:
        lines.append(f"Finished: {esc(finished)}")

    error = job.get("error_msg")
    if error:
        lines.append(f"Error: {_clip(esc(error), ERROR_CHARS)}")

    lines.append(
        f"New assets: {int(summary.get('new_assets') or 0)} | "
        f"Changed assets: {int(summary.get('changed_assets') or 0)} | "
        f"Total changes: {int(summary.get('total_changes') or 0)}"
    )
    return lines


def build_body(event: dict, esc=plain_escape, limit: int = TELEGRAM_BODY_CHARS,
               report_follows: bool = False) -> str:
    """The shared message body, with `esc` applied to every interpolated value.

    Only counts and the fixed labels are unescaped; every string that originated
    in scan data passes through `esc` at the point it is inserted.
    """
    summary = event.get("summary") or {}
    lines = report_header_lines(event, esc)

    by_field = summary.get("changes_by_field") or {}
    if by_field:
        parts = [f"{esc(field)} {int(count)}" for field, count in by_field.items()]
        lines.append("By field: " + ", ".join(parts))

    new_sample = summary.get("new_asset_sample") or []
    if new_sample:
        lines.append("New: " + ", ".join(esc(a) for a in new_sample))

    change_sample = summary.get("change_sample") or []
    if change_sample:
        lines.append("Sample changes:")
        for item in change_sample:
            asset = esc((item or {}).get("asset"))
            field = esc((item or {}).get("field"))
            old = _clip(esc((item or {}).get("old") or "-"), VALUE_CHARS)
            new = _clip(esc((item or {}).get("new") or "-"), VALUE_CHARS)
            lines.append(f"  {asset} {field}: {old} -> {new}")

    if summary.get("sample_truncated"):
        lines.append("(sample truncated — full report follows)" if report_follows else "(sample truncated)")

    return _clip("\n".join(lines), limit)


def build_slack_payload(event: dict, report_follows: bool = False) -> dict:
    body = build_body(event, slack_escape, SLACK_BODY_CHARS, report_follows)
    return {
        "text": headline(event, slack_escape),
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ],
    }


def build_discord_payload(event: dict, report_follows: bool = False) -> dict:
    job = event.get("job") or {}
    status = str(job.get("status") or "")
    stamp = job.get("finished_at") or event.get("generated_at") or datetime.now(timezone.utc).isoformat()
    return {
        "username": "Nous",
        "embeds": [
            {
                "title": _clip(headline(event, discord_escape), 256),
                "description": build_body(event, discord_escape, DISCORD_BODY_CHARS, report_follows),
                "color": DISCORD_COLOR_SUCCESS if status in _SUCCESS_STATUSES else DISCORD_COLOR_FAILURE,
                "timestamp": stamp,
            }
        ],
        # Load-bearing, not decoration: an asset hostname or a scraped page
        # title is attacker-influenced text, and a crafted one containing
        # @everyone would otherwise ping an entire server from a scan result.
        "allowed_mentions": {"parse": []},
    }


def build_telegram_payload(event: dict, chat_id: str, report_follows: bool = False) -> dict:
    # parse_mode is deliberately omitted. With Markdown or HTML, an asset title
    # carrying an unbalanced * or < either makes the API reject the message with
    # a 400 ("can't parse entities") or lets scan data restyle the message.
    # Plain text has neither failure mode.
    return {
        "chat_id": chat_id,
        "text": build_body(event, plain_escape, TELEGRAM_BODY_CHARS, report_follows),
        "disable_web_page_preview": True,
    }


# The full report. Discord and Telegram receive it as a file, Slack as capped
# follow-up messages, the generic webhook as lists in its JSON body. Every item
# line passes through plain_escape, so one item is always exactly one line
# starting with two spaces: slack_followups counts items by that.


def report_filename(job_id) -> str:
    raw = job_id if isinstance(job_id, str) else ""
    return f"nous-scan-report-{raw if _REPORT_ID_RE.match(raw) else 'report'}.txt"


def _report_line(row) -> str:
    if row[0] == "new":
        return f"  {plain_escape(row[1])}\n"
    _, asset, field, old, new = row
    return (
        f"  {plain_escape(asset)} {plain_escape(field)}: "
        f"{plain_escape(old or '-')} -> {plain_escape(new or '-')}\n"
    )


def _list_item(row):
    if row[0] == "new":
        return row[1]
    _, asset, field, old, new = row
    return {"asset": asset, "field": field, "old": old, "new": new}


def write_report(fh, event: dict, rows, total_items: int, *, want_lists: bool = False,
                 want_file: bool = True, stop=None, max_bytes: int = REPORT_MAX_BYTES) -> dict:
    """Stream `rows` into the binary file `fh` and describe what was written.

    Rows are ("new", asset) or ("change", asset, field, old, new), new assets
    first. Writing stops once the next line would cross the byte ceiling, and no
    further row is read. With `want_lists`, the raw items also collect into the
    webhook lists within WEBHOOK_LISTS_BYTES; they are left unescaped there
    because JSON encoding is what carries them safely. Without `want_file` the
    lists are the only consumer, so reading stops as soon as they are full.
    """
    header = ("\n".join(report_header_lines(event)) + "\n").encode("utf-8")
    fh.write(header)
    size = body_offset = len(header)
    budget = max_bytes - REPORT_TRAILER_RESERVE
    written = 0
    truncated = False
    section = None
    new_all: list = []
    changes_all: list = []
    list_bytes = 0
    lists_full = not want_lists

    for row in rows:
        if stop is not None and stop.is_set():
            break
        heading = "" if row[0] == section else ("\nNew assets:\n" if row[0] == "new" else "\nChanges:\n")
        chunk = (heading + _report_line(row)).encode("utf-8")
        if size + len(chunk) > budget:
            truncated = True
            break
        fh.write(chunk)
        size += len(chunk)
        written += 1
        section = row[0]
        if not lists_full:
            item = _list_item(row)
            # Two bytes for the ", " that separates list items once serialised.
            cost = len(json.dumps(item)) + 2
            if list_bytes + cost > WEBHOOK_LISTS_BYTES:
                lists_full = True
            else:
                (new_all if row[0] == "new" else changes_all).append(item)
                list_bytes += cost
        if lists_full and not want_file:
            break

    omitted = max(0, total_items - written) if truncated else 0
    if truncated:
        trailer = f"\n… {omitted} more items omitted (report size limit)\n".encode("utf-8")
        fh.write(trailer)
        size += len(trailer)

    lists = None
    if want_lists:
        listed = len(new_all) + len(changes_all)
        lists = {
            "new_assets_all": new_all,
            "changes_all": changes_all,
            "lists_truncated": listed < total_items,
            "lists_omitted": max(0, total_items - listed),
        }
    return {
        "body_offset": body_offset,
        "size": size,
        "written": written,
        "omitted": omitted,
        "lists": lists,
        "list_bytes": list_bytes,
    }


def slack_followups(lines, total_items: int, *, max_messages: int = SLACK_MAX_MESSAGES - 1) -> list[str]:
    """Pack report lines into at most `max_messages` Slack messages.

    Stops reading `lines` once the last message is full, so at most
    max_messages * SLACK_BODY_CHARS characters are ever held. The last message
    keeps room for a line counting the items that did not fit.
    """
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    included = 0
    for raw in lines:
        line = slack_escape(_clip(raw.rstrip("\n"), SLACK_LINE_CHARS))
        if not line.strip():
            continue
        last = len(chunks) == max_messages - 1
        cost = len(line) + (1 if current else 0)
        if size + cost > SLACK_BODY_CHARS - (REPORT_TRAILER_RESERVE if last else 0):
            if last:
                break
            chunks.append("\n".join(current))
            current, size, cost = [], 0, len(line)
        current.append(line)
        size += cost
        if raw.startswith("  "):
            included += 1
    if current:
        chunks.append("\n".join(current))

    omitted = total_items - included
    if omitted <= 0:
        return chunks
    note = slack_omitted_note(omitted)
    # Filling the last message always leaves REPORT_TRAILER_RESERVE free, so the
    # note fits there; only a message ended early by running out of lines can
    # be too full, and then a slot is still free.
    if not chunks or len(chunks) < max_messages and len(chunks[-1]) + 1 + len(note) > SLACK_BODY_CHARS:
        chunks.append(note)
    else:
        chunks[-1] += "\n" + note
    return chunks


def slack_omitted_note(omitted: int) -> str:
    return f"… {omitted} more items not shown (Slack webhooks cannot carry attachments)"


def build_discord_report_payload(event: dict) -> dict:
    return {
        "username": "Nous",
        "content": _clip("Full report: " + headline(event, discord_escape), 2000),
        # Same reason as on the summary embed: the headline carries scan data.
        "allowed_mentions": {"parse": []},
    }


def build_telegram_report_fields(event: dict, chat_id: str) -> dict:
    # No parse_mode, for the same reason as build_telegram_payload.
    return {"chat_id": chat_id, "caption": _clip(headline(event), TELEGRAM_CAPTION_CHARS)}
