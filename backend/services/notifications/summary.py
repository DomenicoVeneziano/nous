# backend/services/notifications/summary.py
"""Bounded change summary for a finished scan job, and the canonical event dict.

Every notification reads a fixed, small number of rows regardless of how many
assets a project holds: five aggregate/sample queries whose combined result set
is capped at 48 rows — 1 (totals) + MAX_FIELD_ROWS (top fields) + 1 (new asset
count) + two samples of at most 20 each, the widest NOTIFY_SAMPLE_SIZE the
bounds allow. Nothing here loads a table, and nothing here scales with asset
volume.

The queries are SQLAlchemy Core text() with bound parameters only — no value,
including the sample size, is ever interpolated into the SQL string.
"""
from datetime import datetime, timezone

from sqlalchemy import text

from config import settings as cfg
from database import SessionLocal
from services.settings_store import NOTIFY_BOUNDS

# The statuses that mean "this job produced a result worth summarising".
SUCCESS_STATUSES = ("done",)
FAILURE_STATUSES = ("failed", "timed_out", "cancelled")

# How many per-field counts a summary keeps; see the module docstring for the
# row ceiling this contributes to.
MAX_FIELD_ROWS = 6

# Longest single value carried in a change sample. Bound into the sample query
# as :vchars and applied by SQLite, never here — see _SQL_CHANGE_SAMPLE.
VALUE_CHARS = 80

# Longest error message echoed into an event.
MAX_ERROR_CHARS = 500

_SQL_TOTALS = text(
    "SELECT COUNT(*) AS total_changes, COUNT(DISTINCT asset_id) AS changed_assets "
    "FROM asset_changes WHERE project_id = :pid AND scan_id = :sid"
)

_SQL_BY_FIELD = text(
    "SELECT field, COUNT(*) AS n FROM asset_changes "
    "WHERE project_id = :pid AND scan_id = :sid GROUP BY field ORDER BY n DESC"
)

_SQL_NEW_ASSETS = text(
    "SELECT COUNT(*) FROM assets WHERE project_id = :pid AND first_seen_scan_id = :sid"
)

# Two deliberate properties of the sample queries, neither of which is a bug:
#
# 1. No ORDER BY. ix_asset_changes_project_scan covers (project_id, scan_id) but
#    not changed_at, so ordering by time would force SQLite to materialise and
#    sort every change row belonging to the scan before it could apply the LIMIT
#    — precisely the unbounded load the guardrails forbid. Unordered, SQLite
#    walks the index and stops after :n hits. What is wanted here is "a few
#    examples", not "the latest few"; the truncation flag says the rest exist.
#
# 2. substr(..., 1, :vchars) runs in SQL rather than in Python, with VALUE_CHARS
#    bound in so the constant and the truncation cannot drift. The technologies
#    and dns_records deltas are JSON arrays that can run to kilobytes per row;
#    truncating after the fetch would still pull the whole payload into the
#    backend's memory before discarding it.
_SQL_CHANGE_SAMPLE = text(
    "SELECT a.asset, c.field, substr(c.old_value, 1, :vchars), substr(c.new_value, 1, :vchars) "
    "FROM asset_changes c JOIN assets a ON a.id = c.asset_id "
    "WHERE c.project_id = :pid AND c.scan_id = :sid LIMIT :n"
)

_SQL_NEW_ASSET_SAMPLE = text(
    "SELECT asset FROM assets WHERE project_id = :pid AND first_seen_scan_id = :sid LIMIT :n"
)

_SQL_PROJECT_TITLE = text("SELECT title FROM projects WHERE id = :pid")


def clamped_sample_size() -> int:
    """NOTIFY_SAMPLE_SIZE forced back inside its declared bounds (0-20).

    Re-clamped at read time, not just at save time, so a row edited straight in
    the database can never widen how many rows a notification reads.
    """
    low, high = NOTIFY_BOUNDS["NOTIFY_SAMPLE_SIZE"]
    try:
        value = int(getattr(cfg, "NOTIFY_SAMPLE_SIZE", low))
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
    """Read the bounded change summary for one scan job.

    Opens its own short-lived session and closes it in a finally, so a caller
    running outside a request (the notifier, the scheduler) never holds a
    connection across an await.
    """
    n = clamped_sample_size()
    db = SessionLocal()
    try:
        params = {"pid": project_id, "sid": scan_id}

        row = db.execute(_SQL_TOTALS, params).first()
        total_changes = int(row[0] or 0) if row else 0
        changed_assets = int(row[1] or 0) if row else 0

        # ORDER BY n DESC above means the bounded fetch keeps the busiest
        # fields; the tail is noise in a summary and is dropped rather than
        # streamed into memory.
        field_rows = db.execute(_SQL_BY_FIELD, params).fetchmany(MAX_FIELD_ROWS)
        changes_by_field = {str(r[0]): int(r[1] or 0) for r in field_rows}

        new_assets = int(db.execute(_SQL_NEW_ASSETS, params).scalar() or 0)

        change_sample: list[dict] = []
        new_asset_sample: list[str] = []
        if n > 0:
            # :n is a bound integer parameter, never string-formatted into SQL.
            sample_params = {"pid": project_id, "sid": scan_id, "n": n}
            change_params = dict(sample_params, vchars=VALUE_CHARS)
            for r in db.execute(_SQL_CHANGE_SAMPLE, change_params).fetchmany(n):
                change_sample.append({
                    "asset": _text(r[0]) or "",
                    "field": _text(r[1]) or "",
                    "old": _text(r[2]),
                    "new": _text(r[3]),
                })
            for r in db.execute(_SQL_NEW_ASSET_SAMPLE, sample_params).fetchmany(n):
                new_asset_sample.append(_text(r[0]) or "")

        return {
            "new_assets": new_assets,
            "changed_assets": changed_assets,
            "total_changes": total_changes,
            "changes_by_field": changes_by_field,
            "new_asset_sample": new_asset_sample,
            "change_sample": change_sample,
            # Either sample can be the truncated one: a recon run that finds
            # 200 new assets and changes no field still lists only n of them.
            "sample_truncated": total_changes > n or new_assets > n,
        }
    finally:
        db.close()


def project_title(project_id: str) -> str:
    """Look up one project title by primary key, or "" when it is gone."""
    db = SessionLocal()
    try:
        return _text(db.execute(_SQL_PROJECT_TITLE, {"pid": project_id}).scalar()) or ""
    finally:
        db.close()


def empty_summary() -> dict:
    """The summary shape with every count at zero (used by the test send)."""
    return {
        "new_assets": 0,
        "changed_assets": 0,
        "total_changes": 0,
        "changes_by_field": {},
        "new_asset_sample": [],
        "change_sample": [],
        "sample_truncated": False,
    }


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
