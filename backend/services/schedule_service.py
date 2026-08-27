# backend/services/schedule_service.py
"""Time math and the write-time rules for a project's recurring scan schedule.

Deliberately stdlib-only and free of any database access: the scheduler loop and
the project write path both have to agree on when the next cycle is due, and the
cheapest way to guarantee that is for the arithmetic to live in exactly one
place that neither of them can special-case.
"""
import calendar
from datetime import datetime, timedelta, timezone

# The four columns a client may write. Everything else on the schedule
# (next_scan_at, the in-flight cycle, the last run) is derived state that only
# this module and the scheduler set.
SCHEDULE_FIELDS = (
    "schedule_enabled",
    "schedule_interval_value",
    "schedule_interval_unit",
    "schedule_phases",
)


def utc_now() -> datetime:
    """Now, as the naive UTC the rest of the schema stores.

    Every datetime written to a schedule column goes through here. An
    offset-aware value reaching SQLite would collate ahead of the naive rows and
    quietly reorder every due-time comparison — the same trap the timestamp
    normalization in database.py exists to undo.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_months(when: datetime, months: int) -> datetime:
    """Advance by whole calendar months, clamping the day to the target month.

    Month arithmetic has no fixed length, so timedelta cannot express it: Jan 31
    plus one month is Feb 28 (or 29), not Mar 3. Time of day is preserved so a
    monthly schedule keeps landing at the hour it was set for.
    """
    total = when.month - 1 + months
    year = when.year + total // 12
    month = total % 12 + 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def add_interval(when: datetime, value: int, unit: str) -> datetime:
    if unit == "hours":
        return when + timedelta(hours=value)
    if unit == "days":
        return when + timedelta(days=value)
    if unit == "weeks":
        return when + timedelta(weeks=value)
    if unit == "months":
        return add_months(when, value)
    raise ValueError(f"Unknown schedule interval unit: {unit}")


def compute_next_scan_at(project, from_time: datetime) -> datetime | None:
    """The due time one full interval after `from_time`, or None if the schedule
    is off."""
    if not project.schedule_enabled:
        return None
    return add_interval(
        from_time, project.schedule_interval_value, project.schedule_interval_unit
    )


def apply_schedule_change(project, incoming: dict, now: datetime) -> None:
    """Apply a schedule edit to `project` and recompute its due time.

    The single place the write-time rules live; the caller owns the commit.
    `incoming` holds only the SCHEDULE_FIELDS keys the client actually sent, so
    an absent key means "leave as stored" rather than "set to None".
    """
    was_enabled = bool(project.schedule_enabled)
    prev_value = project.schedule_interval_value
    prev_unit = project.schedule_interval_unit

    for field in SCHEDULE_FIELDS:
        if field in incoming:
            setattr(project, field, incoming[field])
    # The column is NOT NULL, and on a freshly constructed Project the Python
    # default has not been applied yet.
    project.schedule_enabled = bool(project.schedule_enabled)

    if not project.schedule_enabled:
        # Turning off only stops future cycles. Jobs already queued keep their
        # place — the operator asked for no more scans, not for the running one
        # to be thrown away — and schedule_last_run_at survives as history.
        project.next_scan_at = None
        project.schedule_cycle_job_ids = None
        project.schedule_cycle_started_at = None
        return

    if not was_enabled:
        # Enabling never fires immediately: the first scan lands one full
        # interval out, so switching a schedule on is not a way to trigger a scan.
        project.next_scan_at = compute_next_scan_at(project, now)
        project.schedule_cycle_job_ids = None
        project.schedule_cycle_started_at = None
        return

    interval_changed = (
        project.schedule_interval_value != prev_value
        or project.schedule_interval_unit != prev_unit
    )
    if not interval_changed:
        # A phases-only edit changes what the next cycle runs, not when it runs.
        return

    if project.schedule_cycle_job_ids:
        # A cycle is in flight and its jobs may still be queued behind others.
        # Leaving the project not-due keeps the scheduler from stacking a second
        # cycle on top; it recomputes from the new interval when this one closes.
        project.next_scan_at = None
        return

    # Re-anchor on the last completed run so shortening an interval brings the
    # next scan forward rather than restarting the clock. If that anchor is
    # already in the past, fall forward to a full interval from now — the point
    # is a new cadence, not an instant scan.
    base = project.schedule_last_run_at or now
    next_at = add_interval(
        base, project.schedule_interval_value, project.schedule_interval_unit
    )
    if next_at <= now:
        next_at = add_interval(
            now, project.schedule_interval_value, project.schedule_interval_unit
        )
    project.next_scan_at = next_at
