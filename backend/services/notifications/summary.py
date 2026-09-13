# backend/services/notifications/summary.py
"""Change counts for a finished scan job, the canonical event dict, and the
rows of the full report.

The summary reads two aggregate rows whatever the size of the project: the
change totals and the new-asset count. Nothing here loads a table.

The full report (iter_report_rows) is the one read not fixed in rows: it pages
through a scan's rows by rowid, and render.write_report bounds it in bytes.

The queries are SQLAlchemy Core text() with bound parameters only — no value is
ever interpolated into the SQL string.
"""
from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import text

from config import settings as cfg
from database import SessionLocal
from services.settings_store import NOTIFY_BOUNDS

# The statuses that mean "this job produced a result worth summarising".
SUCCESS_STATUSES = ("done",)
FAILURE_STATUSES = ("failed", "timed_out", "cancelled")

# Longest error message echoed into an event.
MAX_ERROR_CHARS = 500

# The full report. Pages walk ix_asset_changes_project_scan and
# ix_assets_first_seen_scan, which carry the rowid as their implicit last
# column, so "rowid > :after ORDER BY rowid" is a range seek with no sort.
# Values are cut in SQL one character past the ceiling, so the ellipsis added
# in _report_value marks only a real cut.
REPORT_PAGE_ROWS = 500
REPORT_VALUE_CHARS = 1000
REPORT_ASSET_CHARS = 300
REPORT_FIELD_CHARS = 64
# ponytail: sections beyond this many fields are dropped without a word; count
# and report the omitted fields if a scan type ever tracks more than a handful.
REPORT_MAX_FIELDS = 32

_SQL_TOTALS = text(
    "SELECT COUNT(*) AS total_changes, COUNT(DISTINCT asset_id) AS changed_assets "
    "FROM asset_changes WHERE project_id = :pid AND scan_id = :sid"
)

_SQL_NEW_ASSETS = text(
    "SELECT COUNT(*) FROM assets WHERE project_id = :pid AND first_seen_scan_id = :sid"
)

_SQL_PROJECT_TITLE = text("SELECT title FROM projects WHERE id = :pid")

_SQL_REPORT_NEW = text(
    "SELECT rowid, substr(asset, 1, :achars) FROM assets "
    "WHERE project_id = :pid AND first_seen_scan_id = :sid AND rowid > :after "
    "ORDER BY rowid LIMIT :page"
)

# One section per field, busiest first by the number of assets it touched.
_SQL_REPORT_FIELDS = text(
    "SELECT field, COUNT(DISTINCT asset_id) AS assets FROM asset_changes "
    "WHERE project_id = :pid AND scan_id = :sid "
    "GROUP BY field ORDER BY assets DESC, field LIMIT :nfields"
)

# ponytail: each field's pass walks every change row of the scan on
# ix_asset_changes_project_scan and filters by field, so a report costs
# fields x scan rows; replace that index with (project_id, scan_id, field) if
# scans grow large enough for it to show.
#
# LEFT JOIN: a change whose asset was deleted since is still a change, and
# _SQL_TOTALS, which the report's item count comes from, counts it. "IS" rather
# than "=" so a NULL field still matches its own rows.
_SQL_REPORT_FIELD_CHANGES = text(
    "SELECT c.rowid, substr(a.asset, 1, :achars), "
    "substr(c.old_value, 1, :vchars), substr(c.new_value, 1, :vchars) "
    "FROM asset_changes c LEFT JOIN assets a ON a.id = c.asset_id "
    "WHERE c.project_id = :pid AND c.scan_id = :sid AND c.field IS :field AND c.rowid > :after "
    "ORDER BY c.rowid LIMIT :page"
)


def clamped(key: str) -> int:
    """A bounded NOTIFY_* integer forced back inside its declared bounds.

    Re-clamped at use time, not just at save time, so a row edited straight in
    the database can never widen how long a send may hang or how many times it
    retries. sender.py imports this for its timeout and retry bounds rather than
    keeping a second copy; summary.py is the lower module of the two, so the
    import direction cannot cycle.
    """
    low, high = NOTIFY_BOUNDS[key]
    try:
        value = int(getattr(cfg, key, low))
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _iso(value) -> str | None:
    """Render a datetime as ISO 8601, treating a naive value as UTC.

    The schema stores naive UTC; an aware value is passed through as-is so both
    conventions land on the same instant.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _text(value, limit: int | None = None) -> str | None:
    if value is None:
        return None
    out = value if isinstance(value, str) else str(value)
    if limit is not None and len(out) > limit:
        out = out[:limit]
    return out


def is_success(status: str | None) -> bool:
    """True for a job status that counts as a successful run."""
    return (status or "") in SUCCESS_STATUSES


def is_failure(status: str | None) -> bool:
    """True for a job status that counts as a failed run."""
    return (status or "") in FAILURE_STATUSES


def collect_summary(project_id: str, scan_id: str) -> dict:
    """Read the change counts for one scan job.

    Opens its own short-lived session and closes it in a finally, so a caller
    running outside a request (the notifier, the scheduler) never holds a
    connection across an await.
    """
    db = SessionLocal()
    try:
        params = {"pid": project_id, "sid": scan_id}
        row = db.execute(_SQL_TOTALS, params).first()
        return {
            "new_assets": int(db.execute(_SQL_NEW_ASSETS, params).scalar() or 0),
            "changed_assets": int(row[1] or 0) if row else 0,
            "total_changes": int(row[0] or 0) if row else 0,
        }
    finally:
        db.close()


def _report_value(value) -> str | None:
    if value is None:
        return None
    out = str(value)
    return out if len(out) <= REPORT_VALUE_CHARS else out[:REPORT_VALUE_CHARS] + "…"


def _pages(db, sql, params: dict, shape, stop) -> Iterator[tuple]:
    """Yield shaped rows of one keyset query, a page at a time.

    Each page is its own read transaction, ended by the rollback: the database
    runs in WAL mode, and one snapshot held open across a long report would keep
    the WAL from checkpointing. `stop`, a threading.Event, is checked before
    every page so a cancelled send stops reading.
    """
    after = -(2 ** 63)
    while not stop.is_set():
        rows = db.execute(sql, dict(params, after=after)).fetchall()
        db.rollback()
        yield from (shape(r) for r in rows)
        if len(rows) < REPORT_PAGE_ROWS:
            return
        after = rows[-1][0]


def iter_report_rows(db, project_id: str, scan_id: str, stop) -> Iterator[tuple]:
    """Yield every new asset of one scan, then its changes field by field.

    Rows are ("new", asset), then for each field a ("field", field, assets)
    marker followed by that field's ("change", asset, field, old, new) rows.
    """
    base = {"pid": project_id, "sid": scan_id, "page": REPORT_PAGE_ROWS, "achars": REPORT_ASSET_CHARS}
    yield from _pages(db, _SQL_REPORT_NEW, base, lambda r: ("new", r[1] or ""), stop)
    if stop.is_set():
        return

    fields = db.execute(
        _SQL_REPORT_FIELDS, {"pid": project_id, "sid": scan_id, "nfields": REPORT_MAX_FIELDS}
    ).fetchall()
    db.rollback()
    params = dict(base, vchars=REPORT_VALUE_CHARS + 1)
    for field, assets in fields:
        if stop.is_set():
            return
        name = ("" if field is None else str(field))[:REPORT_FIELD_CHARS]
        yield ("field", name, int(assets or 0))
        yield from _pages(
            db,
            _SQL_REPORT_FIELD_CHANGES,
            dict(params, field=field),
            lambda r, name=name: (
                "change",
                "(deleted asset)" if r[1] is None else r[1],
                name,
                _report_value(r[2]),
                _report_value(r[3]),
            ),
            stop,
        )


def project_title(project_id: str) -> str:
    """Look up one project title by primary key, or "" when it is gone."""
    db = SessionLocal()
    try:
        return _text(db.execute(_SQL_PROJECT_TITLE, {"pid": project_id}).scalar()) or ""
    finally:
        db.close()


def empty_summary() -> dict:
    """The summary shape with every count at zero (used by the test send)."""
    return {"new_assets": 0, "changed_assets": 0, "total_changes": 0}


def build_event(job, title: str | None = None) -> dict:
    """Build the canonical event for a finished scan job.

    `job` is a ScanJob row (or anything carrying the same attributes). The
    returned dict IS the generic-webhook body; the other channels render their
    payloads from it.
    """
    project_id = getattr(job, "project_id", None)
    scan_id = getattr(job, "id", None)
    if title is None:
        title = project_title(project_id) if project_id else ""

    duration = getattr(job, "duration_s", None)
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None

    return {
        "event": "scan_job_finished",
        "job": {
            "id": _text(scan_id) or "",
            "scan_type": _text(getattr(job, "scan_type", None)) or "",
            "status": _text(getattr(job, "status", None)) or "",
            "project_id": _text(project_id) or "",
            "project_title": title or "",
            "started_at": _iso(getattr(job, "started_at", None)),
            "finished_at": _iso(getattr(job, "finished_at", None)),
            "duration_s": duration,
            "error_msg": _text(getattr(job, "error_msg", None), MAX_ERROR_CHARS),
        },
        "summary": collect_summary(project_id, scan_id) if project_id and scan_id else empty_summary(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
