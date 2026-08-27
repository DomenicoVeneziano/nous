# backend/scheduler.py
"""The background loop that turns a project's stored schedule into scan jobs.

Every tick does two things: close out cycles whose jobs have all finished (which
is what re-arms the next due time), then queue a cycle for whatever is due now.
Keeping both in one loop means a project is only ever in one of two states —
in flight, or waiting for next_scan_at — and neither the API nor the engine has
to know the scheduler exists.
"""
import asyncio
import logging
from datetime import timedelta

from database import SessionLocal
from models.project import Project
from schemas.project import SCAN_PHASES
from services import scan_service
from services.schedule_service import compute_next_scan_at, utc_now

log = logging.getLogger("backend.scheduler")

SCHEDULER_TICK_SECONDS = 60

# How long a cycle may stay in flight before it is closed regardless. A job the
# engine lost — killed mid-run, or a row an operator cleared out from under it —
# would otherwise pin next_scan_at at NULL and silently stop the schedule
# forever, which is far worse than one cycle finishing late.
MAX_CYCLE_HOURS = 48

# How many due projects one tick will fire. The query is index-backed and
# ordered by due time, so anything past the limit is simply the next tick's work.
DUE_BATCH_LIMIT = 50

# The same bound for the cycles the finalizer walks. Ordering by start time means
# the oldest cycle — the one closest to the watchdog cutoff — is always in the
# batch, so nothing past the limit can be starved.
IN_FLIGHT_BATCH_LIMIT = 50

# The failures that are a property of the stored row rather than of the moment.
# The interval math is the only thing here that inspects operator-supplied values:
# it raises TypeError for an interval the arithmetic cannot use (a NULL value) and
# ValueError for a unit it does not know. Both are deterministic — the next tick
# would recompute exactly the same way — so these, and only these, are grounds for
# taking a schedule off. Everything else is presumed transient and retried.
SCHEDULE_DATA_ERRORS = (TypeError, ValueError)


def _quarantine(project, reason: str) -> None:
    """Take a project off the schedule because its stored schedule is unusable.

    Only ever reached for SCHEDULE_DATA_ERRORS: a row whose interval or unit the
    time math rejects will be rejected identically on every future tick, so
    leaving it enabled means logging the same traceback every 60 seconds and
    never scanning it anyway. Disabling is the same escape the empty-phase branch
    takes, and it is deliberately not the response to a database error — a lock
    or a dropped connection says nothing about the operator's schedule.

    Anything still in flight is released with it, or the finalizer would keep
    picking the row back up.
    """
    log.exception(
        f"Project {project.id} {reason}; its stored schedule is unusable, "
        f"so the schedule is being disabled"
    )
    project.schedule_enabled = False
    project.next_scan_at = None
    project.schedule_cycle_job_ids = None
    project.schedule_cycle_started_at = None


def _process_isolated(db, project, step, now, what: str) -> None:
    """Run one project's step and commit it, containing any failure to that row.

    Committing per project is what makes the isolation real. A statement error
    (the "database is locked" the engine's concurrent writes make realistic)
    leaves the session usable, but a failure during flush marks the transaction
    rollback-only: every later query and the batch's own commit then raise
    PendingRollbackError, and the rollback that clears it discards every other
    project's pending mutations. With each project committed as it completes,
    the rollback can only ever throw away the work of the row that failed.
    """
    try:
        step(db, project, now)
        db.commit()
    except SCHEDULE_DATA_ERRORS:
        # Roll back first so the quarantine is written onto the stored row rather
        # than on top of whatever half-applied state the failure left behind.
        db.rollback()
        _quarantine(project, what)
        try:
            db.commit()
        except Exception:
            log.exception(f"Project {project.id}: could not record the quarantine")
            db.rollback()
    except Exception:
        # Transient as far as this loop can tell — a lock, a dropped connection,
        # anything the next tick may well get past. The schedule is left exactly
        # as stored, so the project is simply picked up again in 60 seconds.
        db.rollback()
        log.exception(
            f"Project {project.id} {what}; leaving its schedule untouched and "
            f"retrying on the next tick"
        )


def _in_flight_query(db):
    """The bounded, index-backed selection of projects with a cycle in flight.

    Backed by ix_projects_cycle_in_flight, a partial index over exactly these
    rows (see database.py), so the poll never touches the projects that are not
    mid-cycle — which is nearly all of them.
    """
    return (
        db.query(Project)
        .filter(Project.schedule_cycle_job_ids.isnot(None))
        .order_by(Project.schedule_cycle_started_at)
        .limit(IN_FLIGHT_BATCH_LIMIT)
    )


def _finalize_one(db, project, now):
    """Close one cycle if its jobs have all reached a terminal state."""
    finished, last_finished_at = scan_service.all_jobs_finished(
        db, project.schedule_cycle_job_ids or []
    )

    if not finished:
        started_at = project.schedule_cycle_started_at
        # A cycle with no start time is already the stuck state the watchdog
        # exists for — nothing can ever compare against a NULL — so it expires
        # immediately rather than pinning next_scan_at at NULL forever.
        expired = started_at is None or now - started_at > timedelta(hours=MAX_CYCLE_HOURS)
        if not expired:
            return
        log.warning(
            f"Project {project.id} cycle exceeded {MAX_CYCLE_HOURS}h "
            f"(started {started_at}); forcing it closed"
        )
        finished = True
        # The jobs never reported a finish time, so the schedule re-anchors
        # on now rather than on a completion that did not happen.
        last_finished_at = None

    completed_at = last_finished_at or now
    project.schedule_last_run_at = completed_at
    project.schedule_cycle_job_ids = None
    project.schedule_cycle_started_at = None
    project.next_scan_at = (
        compute_next_scan_at(project, completed_at)
        if project.schedule_enabled
        else None
    )

    # A cycle that ran longer than its own interval would come out already
    # due and fire again immediately, forever. Re-anchoring on now spaces the
    # next run a full interval from the moment the last one actually ended.
    if project.next_scan_at is not None and project.next_scan_at <= now:
        project.next_scan_at = compute_next_scan_at(project, now)

    log.info(
        f"Project {project.id} scheduled cycle completed at {completed_at}; "
        f"next scan at {project.next_scan_at}"
    )


def _finalize_cycles(db, now):
    """Close cycles whose jobs have all reached a terminal state."""
    for project in _in_flight_query(db).all():
        # Per project, and committed per project, so neither an unusable row nor
        # a database error can cost the rest of the batch its close-out.
        _process_isolated(db, project, _finalize_one, now, "could not close its scheduled cycle")


def _fire_one(db, project, now):
    """Queue one project's cycle, or roll its due time forward."""
    wanted = set(project.schedule_phases or ())
    phases = [p for p in SCAN_PHASES if p in wanted]

    if not phases:
        # The API rejects an empty phase list, so this only happens to a row
        # edited outside it. Disabling is the only way to stop the project
        # from coming up due on every tick with nothing to run.
        log.warning(
            f"Project {project.id} is due but has no runnable phases; "
            f"disabling its schedule"
        )
        project.schedule_enabled = False
        project.next_scan_at = None
        return

    if scan_service.has_active_jobs(db, project.id):
        # Anything queued or running — scheduled, manual, or an engine
        # follow-up — means the previous work is not done. Skipping the whole
        # cycle and rolling forward keeps scheduled scans from piling onto a
        # queue that is already behind.
        project.next_scan_at = compute_next_scan_at(project, now)
        log.info(
            f"Project {project.id} is due but has active jobs; skipping "
            f"until {project.next_scan_at}"
        )
        return

    # enqueue_cycle commits the jobs itself, so for a moment the jobs exist
    # while this project row is not yet marked in flight. That is the safe
    # direction: the next tick finds the project still due, sees its own
    # fresh jobs through has_active_jobs, and takes the collision path —
    # rolling the due time forward instead of queueing a second cycle. The
    # reverse (a project marked in flight with no jobs) cannot happen,
    # because the marker is only written after the jobs are committed, and
    # even then all_jobs_finished treats ids that no longer resolve as
    # finished and closes the cycle out.
    job_ids = scan_service.enqueue_cycle(db, project.id, phases)
    project.schedule_cycle_job_ids = job_ids
    project.schedule_cycle_started_at = now
    # NULL while in flight; _finalize_cycles re-arms it when the cycle ends.
    project.next_scan_at = None
    log.info(
        f"Project {project.id} scheduled cycle queued: "
        f"phases={','.join(phases)} jobs={','.join(job_ids)}"
    )


def _fire_due(db, now):
    """Queue a cycle for every project whose due time has passed."""
    due = (
        db.query(Project)
        .filter(
            Project.schedule_enabled.is_(True),
            Project.next_scan_at.isnot(None),
            Project.next_scan_at <= now,
        )
        .order_by(Project.next_scan_at)
        .limit(DUE_BATCH_LIMIT)
        .all()
    )

    for project in due:
        # Per project, for the same reason as the finalizer: a row whose stored
        # interval the time math cannot use, or one unlucky lock, must not cost
        # the rest of the batch its cycle.
        _process_isolated(db, project, _fire_one, now, "could not be fired")


def _tick_sync():
    """One scheduler pass. Blocking, so it runs on a worker thread.

    The outer backstop only: per-project failures are already isolated inside
    _finalize_cycles and _fire_due, so what reaches here is a session or commit
    failure affecting the whole tick. It is caught because a tick that raises
    must not take the loop — and with it every project's schedule — down until
    the next backend restart.
    """
    db = None
    try:
        db = SessionLocal()
        now = utc_now()
        _finalize_cycles(db, now)
        _fire_due(db, now)
    except Exception:
        log.exception("Scheduler tick failed")
    finally:
        # Constructed inside the guard, so a session that could not be opened
        # neither leaks nor escapes: without this the loop task would die on the
        # first failure and stop scheduling silently.
        if db is not None:
            db.close()


async def _run_tick():
    """Dispatch one tick onto a worker thread.

    _tick_sync swallows its own errors; this guards the hand-off itself, which is
    the last place an exception could escape scheduler_loop and end the task.
    """
    try:
        await asyncio.to_thread(_tick_sync)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Scheduler tick could not be dispatched")


async def scheduler_loop(shutdown_event: asyncio.Event):
    # Run once on startup so a restart immediately picks up cycles that finished
    # and due times that passed while the backend was down.
    await _run_tick()
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=SCHEDULER_TICK_SECONDS)
        except asyncio.TimeoutError:
            await _run_tick()
