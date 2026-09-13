# backend/services/notifications/selfcheck.py
"""Assert-based checks for the summary and the full report. No database and no
settings needed: render imports only the standard library.

    cd backend && python -m services.notifications.selfcheck
"""
import io
import json
import re

from . import render

EVENT = {
    "event": "scan_job_finished",
    "job": {"id": "0b7e2c1a-4d3f-4e8a-9c21-5f6a7b8c9d0e", "status": "done", "scan_type": "recon",
            "project_title": "Selfcheck", "finished_at": "2026-09-13T10:05:09.123456+02:00",
            "duration_s": 12.3, "error_msg": None},
    "summary": {"new_assets": 3, "changed_assets": 2, "total_changes": 5},
    "generated_at": "2026-09-14T00:00:00+00:00",
}

HOSTILE = (
    "evil.example.com\N{LINE SEPARATOR}New: internal-admin.corp"
    "\N{CARRIAGE RETURN}\N{LINE FEED}x\N{RIGHT-TO-LEFT OVERRIDE}y"
)

_HEADING = re.compile(r"\A\d+ (.+ changes|new assets):\Z")


def _report(rows, total, event=EVENT, **kwargs):
    fh = io.BytesIO()
    meta = render.write_report(fh, event, rows, total, **kwargs)
    return fh, meta


def _lines(fh, meta) -> list[str]:
    """Every line after the header, the size-limit trailer included."""
    return fh.getvalue()[meta["body_offset"]:].decode("utf-8").split("\n")


def _items(fh, meta) -> list[str]:
    return [
        line for index, line in enumerate(_lines(fh, meta))
        if index < meta["body_lines"] and line.strip() and index not in meta["labels"]
    ]


def check_summary_text():
    # A successful job carrying a stale error still shows no Error line.
    stale = dict(EVENT, job=dict(EVENT["job"], error_msg="stale"))
    success = "recon scan completed for Selfcheck\nStatus: done\nDuration: 12.3s\n\nNew assets: 3\nChanged assets: 2"
    assert render.build_body(stale) == success, render.build_body(stale)
    assert render.build_telegram_payload(stale, "1")["text"] == success
    assert render.build_slack_payload(stale)["blocks"][0]["text"]["text"] == success
    embed = render.build_discord_payload(stale)["embeds"][0]
    assert embed["title"] == "recon scan completed for Selfcheck"
    assert embed["description"] == success.split("\n", 1)[1], embed["description"]

    failed = dict(EVENT, job=dict(EVENT["job"], status="failed", duration_s=75, error_msg="boom"),
                  summary={"new_assets": 0, "changed_assets": 0, "total_changes": 0})
    expected = "recon scan failed for Selfcheck\nStatus: failed\nDuration: 1m 15s\nError: boom\n\nNew assets: 0\nChanged assets: 0"
    assert render.build_body(failed) == expected, render.build_body(failed)


def check_one_item_one_line():
    rows = [("new", HOSTILE), ("field", "title", 1), ("change", HOSTILE, "title", HOSTILE, None)]
    fh, meta = _report(rows, 2)
    items = _items(fh, meta)
    assert len(items) == 2, items
    text = fh.getvalue().decode("utf-8")
    for ch in ("\N{LINE SEPARATOR}", "\N{RIGHT-TO-LEFT OVERRIDE}", "\N{CARRIAGE RETURN}"):
        assert ch not in text
    assert items[1].endswith("-> -"), items[1]
    assert meta["written"] == 2 and meta["omitted"] == 0 and meta["size"] == len(fh.getvalue())


def check_sections():
    rows = [
        ("new", "a.example.com"), ("new", "b.example.com"), ("new", "c.example.com"),
        ("field", "status_code", 4),
        ("field", "title", 1),
        ("change", "a.example.com", "title", "x", "y"),
        ("change", "a.example.com", "title", "y", "z"),
        ("change", "a.example.com", "title", "z", "x"),
        ("field", "dns_records", 2),
        ("change", "a.example.com", "dns_records", None, "1.2.3.4"),
        ("change", "b.example.com", "dns_records", "5.6.7.8", None),
    ]
    # The heading carries the scan's count, not the number of rows passed in.
    fh, meta = _report(rows, 8, dict(EVENT, summary=dict(EVENT["summary"], new_assets=5)))
    assert fh.getvalue().decode("utf-8") == (
        "recon scan for Selfcheck\n"
        "Issue date: 2026-09-13 08:05 UTC\n"
        "\n"
        "Total changes: 5\n"
        "\n"
        "5 new assets:\n"
        "a.example.com\n"
        "b.example.com\n"
        "c.example.com\n"
        "\n"
        "1 title changes:\n"
        "a.example.com: x -> y\n"
        "a.example.com: y -> z\n"
        "a.example.com: z -> x\n"
        "\n"
        "2 dns records changes:\n"
        "a.example.com: - -> 1.2.3.4\n"
        "b.example.com: 5.6.7.8 -> -\n"
    ), fh.getvalue().decode("utf-8")
    assert len(_items(fh, meta)) == meta["written"] == 8
    assert meta["labels"] == {1, 3, 8, 13}, meta["labels"]

    fh, meta = _report(rows[4:8], 3, dict(EVENT, summary=dict(EVENT["summary"], new_assets=0)))
    text = "\n".join(_lines(fh, meta))
    assert text.startswith("\nTotal changes: 5\n\n1 title changes:\n"), text
    assert "new assets:" not in text and len(_items(fh, meta)) == 3

    naive = dict(EVENT, job=dict(EVENT["job"], finished_at="2026-09-13T08:05:59"))
    missing = dict(EVENT, job=dict(EVENT["job"], finished_at=None))
    assert b"Issue date: 2026-09-13 08:05 UTC\n" in _report([], 0, naive)[0].getvalue()
    assert b"Issue date: 2026-09-14 00:00 UTC\n" in _report([], 0, missing)[0].getvalue()
    garbled = dict(EVENT, job=dict(EVENT["job"], finished_at="not a date"))
    assert b"Issue date: 2026-09-14 00:00 UTC\n" in _report([], 0, garbled)[0].getvalue()
    edge = dict(EVENT, job=dict(EVENT["job"], finished_at="0001-01-01T00:00:00+05:00"))
    assert b"Issue date: 2026-09-14 00:00 UTC\n" in _report([], 0, edge)[0].getvalue()


def check_mixed_truncation():
    # Cuts land all around the second section's heading and first items: a
    # heading must never be written without its first item, and every label
    # must point at a label line.
    rows = (
        [("new", f"n{i}.example.com") for i in range(3)]
        + [("field", "status_code", 2)] + [("change", f"s{i}.example.com", "status_code", "404", "200") for i in range(4)]
        + [("field", "title", 1)] + [("change", "t.example.com", "title", "x" * 200, "y") for _ in range(50)]
    )
    total = 57
    full = _report(rows, total, max_bytes=10**6)[0].getvalue()
    heading_at = full.index(b"1 title changes:")
    for extra in range(-40, 1200, 7):
        fh, meta = _report(iter(rows), total, max_bytes=heading_at + render.REPORT_TRAILER_RESERVE + extra)
        lines = _lines(fh, meta)
        assert meta["omitted"] > 0 and meta["written"] + meta["omitted"] == total, (extra, meta)
        assert len(_items(fh, meta)) == meta["written"]
        for index in meta["labels"]:
            assert lines[index].startswith("Total changes:") or _HEADING.match(lines[index]), (extra, lines[index])
            if index != 1:
                assert index + 1 < meta["body_lines"] and lines[index + 1].strip(), (extra, index)
        assert not any(_HEADING.match(line) for index, line in enumerate(lines) if index not in meta["labels"])


def check_byte_ceiling():
    # Multibyte hostnames: the ceiling is in bytes and must never split a character.
    total = 50_000
    rows = (("new", f"bücher-例え-{i}.example.com") for i in range(total))
    fh, meta = _report(rows, total, max_bytes=4096)
    data = fh.getvalue()
    assert meta["size"] == len(data) <= 4096, meta
    assert data.decode("utf-8").rstrip().endswith("more items omitted (report size limit)")
    assert meta["written"] + meta["omitted"] == total, meta
    assert len(_items(fh, meta)) == meta["written"]


def check_webhook_lists():
    total = 30_000
    rows = [("field", "title", total)] + [("change", "a" * 90 + str(i), "title", "x", "y") for i in range(total)]
    fh, meta = _report(iter(rows), total, want_lists=True)
    lists = meta["lists"]
    assert meta["written"] == total, meta["written"]
    assert lists["lists_omitted"] > 0 and not lists["new_assets_all"]
    assert all(set(item) == {"asset", "field", "old", "new"} for item in lists["changes_all"])
    assert len(json.dumps(lists["changes_all"])) <= render.WEBHOOK_LISTS_BYTES
    assert len(lists["changes_all"]) + lists["lists_omitted"] == total


def check_lists_only_stop_reading():
    total = 100_000
    pulled = 0

    def rows():
        nonlocal pulled
        for i in range(total):
            pulled += 1
            yield ("new", "a" * 1000 + str(i))

    _, meta = _report(rows(), total, want_lists=True, want_file=False)
    lists = meta["lists"]
    assert lists["lists_omitted"] > 0
    assert pulled == len(lists["new_assets_all"]) + 1 < total, pulled


def _note_count(chunk: str) -> int:
    return int(chunk.rsplit("… ", 1)[1].split(" ", 1)[0])


def _chunk_items(chunks) -> int:
    return sum(
        1 for chunk in chunks for line in chunk.split("\n")
        if not _HEADING.match(line) and not line.startswith("Total changes:") and not line.startswith("… ")
    )


def check_slack_cap():
    total = 5000
    rows = [("field", "title", total)] + [
        ("change", f"host-{i}.example.com <b>", "title", "&" * 600, "y") for i in range(total)
    ]
    fh, meta = _report(iter(rows), total)
    chunks = render.slack_followups(iter(_lines(fh, meta)), total, meta["labels"], meta["body_lines"])
    assert len(chunks) == render.SLACK_MAX_MESSAGES - 1, len(chunks)
    assert all(len(chunk) <= render.SLACK_BODY_CHARS for chunk in chunks)
    assert chunks[0].startswith(f"Total changes: 5\n{total} title changes:\n"), chunks[0][:80]
    assert _note_count(chunks[-1]) == total - _chunk_items(chunks)
    assert "<b>" not in "".join(chunks)

    lines = ["", "Total changes: 0", "", "2 new assets:", "a.example.com", "b.example.com"]
    small = render.slack_followups(iter(lines), 2, frozenset({1, 3}), len(lines))
    assert small == ["Total changes: 0\n2 new assets:\na.example.com\nb.example.com"], small


def check_slack_skips_trailer():
    # The unsliced file lines go in, size-limit trailer and all; the cut at
    # body_lines is what keeps the trailer out of Slack.
    total = 5000
    fh, meta = _report((("new", f"h{i}.example.com") for i in range(total)), total, max_bytes=4096)
    lines = _lines(fh, meta)
    assert any("report size limit" in line for line in lines)
    chunks = render.slack_followups(iter(lines), total, meta["labels"], meta["body_lines"])
    assert not any("report size limit" in chunk for chunk in chunks), chunks[-1][-200:]
    assert _chunk_items(chunks) == meta["written"]
    assert _note_count(chunks[-1]) == total - meta["written"]


def check_slack_short_lines():
    # Many short lines fill the last message up to its reserve; varying how many
    # lines exist and how many items lie beyond them moves the note between
    # "appended to the last message" and "a message of its own".
    assert len(render.slack_omitted_note(10**12)) + 1 < render.REPORT_TRAILER_RESERVE
    for count in (0, 1, 150, 180, 200, 400, 5000, 50_000):
        for extra in (0, 7, 100_000):
            for max_messages in (1, 2, render.SLACK_MAX_MESSAGES - 1):
                lines = ["", "Total changes: 0", "", f"{count} new assets:"] + [f"h{i}.example.com" for i in range(count)]
                total = count + extra
                chunks = render.slack_followups(
                    iter(lines), total, frozenset({1, 3}), len(lines), max_messages=max_messages
                )
                assert len(chunks) <= max_messages, (count, extra, len(chunks))
                assert all(len(chunk) <= render.SLACK_BODY_CHARS for chunk in chunks)
                included = _chunk_items(chunks)
                if included < total:
                    assert _note_count(chunks[-1]) == total - included, (count, extra, max_messages)
                else:
                    assert "more items not shown" not in chunks[-1]


def check_filename():
    assert render.report_filename("../x\r\n") == "nous-scan-report-report.txt"
    assert render.report_filename(None) == "nous-scan-report-report.txt"
    assert render.report_filename(EVENT["job"]["id"]) == f"nous-scan-report-{EVENT['job']['id']}.txt"


if __name__ == "__main__":
    for check in (
        check_summary_text, check_one_item_one_line, check_sections, check_mixed_truncation,
        check_byte_ceiling, check_webhook_lists, check_lists_only_stop_reading, check_slack_cap,
        check_slack_skips_trailer, check_slack_short_lines, check_filename,
    ):
        check()
    print("notifications selfcheck: ok")
