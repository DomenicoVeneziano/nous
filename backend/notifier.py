# backend/notifier.py
"""The background loop that turns finished scan jobs into outbound messages.

Every tick does two things, in two different places on purpose: a worker thread
claims a bounded batch of newly-finished jobs and builds each one's event, then
the event loop delivers them. The split is what keeps the API responsive — every
statement this feature runs is blocking SQLite work, and every send is an HTTP
call to a third party that may be slow, unreachable, or hostile.

Nothing here is on the scan path. The engine writes a job's terminal state and
moves on; this loop notices afterwards, so a wedged webhook can never delay a
scan, and a notification that cannot be delivered costs a log line and nothing
else.
"""
import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from sqlalchemy import text

from database import SessionLocal
from models.scan import ScanJob
from services.notifications import build_event, dispatch

log = logging.getLogger("backend.notifier")

NOTIFIER_TICK_SECONDS = 30

# How many finished jobs one tick will claim. The query is index-backed and
# ordered by finish time, so anything past the limit is simply the next tick's
# work — and the bound is what stops a burst of completions (or a backlog left
# by a long outage) from building an unbounded list of events in memory.
NOTIFY_BATCH_LIMIT = 20

# The claim predicate, spelled exactly as it is spelled in the predicate of
# ix_scan_jobs_unnotified (see database.py), and spelled as SQL rather than as
# ScanJob.status.in_(...) on purpose. SQLite only uses a partial index when it
# can prove the query's WHERE clause implies the index's own, and it cannot
# prove that of bound parameters: rendered as `status IN (?,?,?,?)` — which is
# what in_() produces — the plan falls back to SCAN scan_jobs plus a temp
# B-tree for the ORDER BY, i.e. every job ever run, on every tick. With the
# statuses inline the plan is SCAN scan_jobs USING INDEX ix_scan_jobs_unnotified
# over an index that is empty in steady state. The values are module constants,
# never operator or scan input.
_UNNOTIFIED = text(
    "scan_jobs.notified_at IS NULL AND "
    "scan_jobs.status IN ('done','failed','timed_out','cancelled')"
)

# One client for the life of the loop, created on the first tick that actually
# has something to send. A client per send would build and discard a connection
# pool every time, leaving sockets in TIME_WAIT on a busy schedule; creating it
# eagerly at startup would hold a pool open on the many deployments that never
# enable a channel at all.
_client: httpx.AsyncClient | None = None


def _snapshot(job: ScanJob) -> SimpleNamespace:
    """Copy the fields the event needs off the ORM row.

    build_event accepts anything carrying a job's attributes, and taking a plain
    copy first means the summary is built from values read before the claim was
    committed, so what is sent describes the job as it was claimed. Reading them
    off the live row afterwards would work too, but the per-job commit expires
    the instance, so every attribute would be re-selected — and for a row an
    operator deleted in between, that re-select raises outright, inside the send
    loop rather than in the claim that is already guarded.
    """
    return SimpleNamespace(
        id=job.id,
        project_id=job.project_id,
        scan_type=job.scan_type,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_s=job.duration_s,
        error_msg=job.error_msg,
    )


def _claim_one(db, job: ScanJob) -> dict | None:
    """Claim one job and build its event, containing any failure to that row.

    Committing per job is what makes the isolation real, for the same reason the
    scheduler commits per project: a failure during flush marks the transaction
    rollback-only, so every later query and the batch's own commit would then
    raise PendingRollbackError, and the rollback that clears it would discard
    every other job's claim. With each job committed as it is claimed, a
    rollback can only ever throw away the work of the row that failed.

    CLAIM BEFORE SEND. The notified_at commit happens here, before the event
    ever reaches an HTTP call. That is deliberate at-most-once delivery: a crash
    between the commit and the send loses exactly one message, where claiming
    afterwards would replay the whole in-flight batch on every restart and would
    leave a permanently failing endpoint — a revoked webhook, a host that no
    longer resolves — retried on every tick for as long as the backend runs. A
    row is claimed whether the send later succeeds or exhausts its retries; a
    failure is logged and never re-queued.
    """
    try:
        snapshot = _snapshot(job)
        job.notified_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        log.exception(f"Scan job {job.id} could not be claimed for notification")
        return None

    try:
        # Blocking summary queries, so they belong on this thread rather than on
        # the event loop with the sends. The event is built for every claimed
        # job and dispatch applies the NOTIFY_* gating itself; deciding here
        # would mean keeping a second copy of that rule in step with the first.
        return build_event(snapshot)
    except Exception:
        log.exception(
            f"Scan job {job.id} was claimed but its event could not be built; "
            f"it is not re-queued"
        )
        return None


def _claim_sync() -> list[dict]:
    """One claim pass: the bounded batch, stamped and turned into events.

    Blocking, so it runs on a worker thread. The outer backstop only — per-row
    failures are already isolated in _claim_one, so what reaches here is a
    session or query failure affecting the whole tick. It is caught because a
    tick that raises must not take the loop down until the next restart.
    """
    events: list[dict] = []
    db = None
    try:
        db = SessionLocal()
        jobs = (
            db.query(ScanJob)
            .filter(_UNNOTIFIED)
            .order_by(ScanJob.finished_at)
            .limit(NOTIFY_BATCH_LIMIT)
            .all()
        )
        for job in jobs:
            event = _claim_one(db, job)
            if event is not None:
                events.append(event)
    except Exception:
        log.exception("Notifier claim pass failed")
    finally:
        # Constructed inside the guard, so a session that could not be opened
        # neither leaks nor escapes: without this the loop task would die on the
        # first failure and stop notifying silently.
        if db is not None:
            db.close()
    return events


def _get_client() -> httpx.AsyncClient:
    """The shared client, created on first use.

    The pool is deliberately small. This loop sends at most a handful of
    messages per tick to a fixed set of chat endpoints, so a wide pool would
    only hold idle sockets open against a service the operator is not otherwise
    talking to.

    No client-level timeout is set here on purpose: sender._post_once puts the
    operator's configured NOTIFY_TIMEOUT_SECONDS on each request, which
    overrides whatever this client carries. A default set here could only ever
    go stale against a setting the operator changes at runtime, and would give
    this path a different bound from the test send's.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
    return _client


async def _close_client() -> None:
    """Close the shared client, whatever ended the loop."""
    global _client
    client, _client = _client, None
    if client is None:
        return
    try:
        await client.aclose()
    except asyncio.CancelledError:
        # Reached only when the loop is already being cancelled and the close
        # itself is interrupted; the sockets go with the process. Swallowing it
        # here does not hide the cancellation — the CancelledError that ended
        # the loop body is re-raised once this finally completes.
        log.warning("Notifier client close was interrupted by shutdown")
    except Exception:
        log.exception("Notifier client could not be closed")


async def _send(event: dict) -> None:
    """Deliver one already-claimed event, absorbing anything it raises."""
    job_id = ((event or {}).get("job") or {}).get("id") or "unknown"
    try:
        results = await dispatch(_get_client(), event)
    except asyncio.CancelledError:
        raise
    except Exception:
        # The job stays claimed: see _claim_one. Only the outcome is logged, and
        # dispatch already reports channels by name and status code, never by
        # URL or token, so nothing here can put a credential in the log.
        log.exception(f"Notification for scan job {job_id} could not be sent")
        return

    failed = [channel for channel, ok in results.items() if not ok]
    if failed:
        log.warning(
            f"Notification for scan job {job_id} failed on: {','.join(sorted(failed))}"
        )


async def _run_tick() -> None:
    """Claim on a worker thread, then send on the event loop.

    _claim_sync swallows its own errors; this guards the hand-off itself and
    each send, which are the last places an exception could escape
    notifier_loop and end the task.
    """
    try:
        events = await asyncio.to_thread(_claim_sync)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Notifier tick could not be dispatched")
        return

    for event in events:
        await _send(event)


async def notifier_loop(shutdown_event: asyncio.Event):
    try:
        # Run once on startup so a restart immediately picks up the jobs that
        # finished while the backend was down.
        await _run_tick()
        while not shutdown_event.is_set():
            try:
                # Waiting on the event rather than sleeping is what makes the
                # tick interval invisible to shutdown: the wait returns as soon
                # as the event is set instead of sitting out the remaining 30s.
                await asyncio.wait_for(shutdown_event.wait(), timeout=NOTIFIER_TICK_SECONDS)
            except asyncio.TimeoutError:
                await _run_tick()
    finally:
        # Runs on the normal exit, on an unexpected raise, and on cancellation —
        # the only place the client is closed, so the pool cannot outlive the
        # loop that owns it.
        await _close_client()
