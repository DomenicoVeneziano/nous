# backend/services/notifications/selfcheck.py
"""Assert-based checks for the full report. No database and no settings needed:
render imports only the standard library.

    cd backend && python -m services.notifications.selfcheck
"""
import io
import json

from . import render

EVENT = {
    "job": {"id": "0b7e2c1a-4d3f-4e8a-9c21-5f6a7b8c9d0e", "status": "done", "scan_type": "recon",
            "project_title": "Selfcheck"},
    "summary": {"new_assets": 0, "total_changes": 0},
}

HOSTILE = (
    "evil.example.com\N{LINE SEPARATOR}New: internal-admin.corp"
    "\N{CARRIAGE RETURN}\N{LINE FEED}x\N{RIGHT-TO-LEFT OVERRIDE}y"
)


def _body_lines(fh, meta) -> list[str]:
    return fh.getvalue()[meta["body_offset"]:].decode("utf-8").splitlines()


def check_one_item_one_line():
    fh = io.BytesIO()
    meta = render.write_report(fh, EVENT, [("new", HOSTILE), ("change", HOSTILE, "title", HOSTILE, None)], 2)
    lines = _body_lines(fh, meta)
    items = [line for line in lines if line.startswith("  ")]
    assert len(items) == 2, items
    assert not any(line.startswith("New:") for line in lines), lines
    text = fh.getvalue().decode("utf-8")
    for ch in ("\N{LINE SEPARATOR}", "\N{RIGHT-TO-LEFT OVERRIDE}", "\N{CARRIAGE RETURN}"):
        assert ch not in text
    assert items[1].endswith("-> -"), items[1]
    assert meta["written"] == 2 and meta["omitted"] == 0 and meta["size"] == len(fh.getvalue())


def check_byte_ceiling():
    # Multibyte hostnames: the ceiling is in bytes and must never split a character.
    total = 50_000
    fh = io.BytesIO()
    rows = (("new", f"bücher-例え-{i}.example.com") for i in range(total))
    meta = render.write_report(fh, EVENT, rows, total, max_bytes=4096)
    data = fh.getvalue()
    assert meta["size"] == len(data) <= 4096, meta
    assert data.decode("utf-8").rstrip().endswith("more items omitted (report size limit)")
    assert meta["written"] + meta["omitted"] == total, meta
    assert sum(line.startswith("  ") for line in _body_lines(fh, meta)) == meta["written"]


def check_webhook_lists():
    total = 30_000
    rows = (("change", "a" * 90 + str(i), "title", "x", "y") for i in range(total))
    meta = render.write_report(io.BytesIO(), EVENT, rows, total, want_lists=True)
    lists = meta["lists"]
    assert meta["list_bytes"] <= render.WEBHOOK_LISTS_BYTES
    assert meta["written"] == total, meta["written"]
    assert lists["lists_truncated"]
    assert len(json.dumps(lists["changes_all"])) <= render.WEBHOOK_LISTS_BYTES
    assert len(lists["changes_all"]) + lists["lists_omitted"] == total


def check_slack_cap():
    total = 5000
    lines = ["", "New assets:"] + [f"  host-{i}.example.com <b>" + "&" * 600 for i in range(total)]
    chunks = render.slack_followups(iter(lines), total)
    assert len(chunks) == render.SLACK_MAX_MESSAGES - 1, len(chunks)
    assert all(len(chunk) <= render.SLACK_BODY_CHARS for chunk in chunks)
    included = sum(line.startswith("  ") for chunk in chunks for line in chunk.split("\n"))
    assert chunks[-1].endswith(f"… {total - included} more items not shown (Slack webhooks cannot carry attachments)")
    assert "<b>" not in "".join(chunks)

    small = render.slack_followups(iter(["", "New assets:", "  a.example.com", "  b.example.com"]), 2)
    assert small == ["New assets:\n  a.example.com\n  b.example.com"], small


def _note_count(chunk: str) -> int:
    return int(chunk.rsplit("… ", 1)[1].split(" ", 1)[0])


def check_slack_short_lines():
    # Many short lines fill the last message up to its reserve; varying how many
    # lines exist and how many items lie beyond them moves the note between
    # "appended to the last message" and "a message of its own".
    assert len(render.slack_omitted_note(10**12)) + 1 < render.REPORT_TRAILER_RESERVE
    for count in (0, 1, 150, 180, 200, 400, 5000, 50_000):
        for extra in (0, 7, 100_000):
            for max_messages in (1, 2, render.SLACK_MAX_MESSAGES - 1):
                lines = [f"  h{i}.example.com" for i in range(count)]
                total = count + extra
                chunks = render.slack_followups(iter(lines), total, max_messages=max_messages)
                assert len(chunks) <= max_messages, (count, extra, len(chunks))
                assert all(len(chunk) <= render.SLACK_BODY_CHARS for chunk in chunks)
                included = sum(line.startswith("  ") for chunk in chunks for line in chunk.split("\n"))
                if included < total:
                    assert _note_count(chunks[-1]) == total - included, (count, extra, max_messages)
                else:
                    assert not chunks or "more items not shown" not in chunks[-1]


def check_lists_only_stop_reading():
    total = 100_000
    pulled = 0

    def rows():
        nonlocal pulled
        for i in range(total):
            pulled += 1
            yield ("new", "a" * 1000 + str(i))

    meta = render.write_report(io.BytesIO(), EVENT, rows(), total, want_lists=True, want_file=False)
    lists = meta["lists"]
    assert lists["lists_truncated"]
    assert pulled == len(lists["new_assets_all"]) + 1 < total, pulled


def check_filename():
    assert render.report_filename("../x\r\n") == "nous-scan-report-report.txt"
    assert render.report_filename(None) == "nous-scan-report-report.txt"
    assert render.report_filename(EVENT["job"]["id"]) == f"nous-scan-report-{EVENT['job']['id']}.txt"


if __name__ == "__main__":
    for check in (
        check_one_item_one_line, check_byte_ceiling, check_webhook_lists, check_slack_cap,
        check_slack_short_lines, check_lists_only_stop_reading, check_filename,
    ):
        check()
    print("notifications selfcheck: ok")
