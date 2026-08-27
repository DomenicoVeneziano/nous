# backend/services/scan_service.py
"""Enqueue logic shared by the scans router and the recurring scheduler.

Both paths have to snapshot settings and allocate queue positions identically —
a job the scheduler creates is indistinguishable from one an operator created —
so the logic lives here rather than in the router, where only one of the two
callers could reach it.
"""
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.scan import ScanJob
from schemas.project import SCAN_PHASES
from services import schedule_service
from services.settings_store import proxy_url_for_scan_type, retry_proxy_url_for_scan_type
from config import settings

# The statuses a job never leaves.
TERMINAL_STATUSES = ("done", "failed", "cancelled", "timed_out")
ACTIVE_STATUSES = ("queued", "running")


def build_job_config(scan_type: str) -> dict | None:
    """Snapshot all scan-relevant settings into the job config so the engine
    (a separate process) uses the values active at enqueue time."""
    if scan_type == "recon":
        job_config = {
            "dns_bruteforce_enabled": settings.DNS_BRUTEFORCE_ENABLED,
            "dns_wordlist_expansion_enabled": settings.DNS_WORDLIST_EXPANSION_ENABLED,
            "recon_timeout": settings.RECON_TIMEOUT,
            "wordlist_path": str(settings.WORDLIST_PATH),
            "resolvers_path": str(settings.RESOLVERS_PATH),
            "dns_rate_limit_delay": settings.DNS_RATE_LIMIT_DELAY,
        }
    elif scan_type == "tech":
        job_config = {
            "per_domain_timeout": settings.TECH_TIMEOUT,
            "tech_rate_limit_delay": settings.TECH_RATE_LIMIT_DELAY,
            "dns_rate_limit_delay": settings.DNS_RATE_LIMIT_DELAY,
            "resolvers_path": str(settings.RESOLVERS_PATH),
            "screenshots_enabled": settings.TECH_SCREENSHOTS_ENABLED,
        }
    elif scan_type == "crawl":
        job_config = {
            "crawl_timeout": settings.CRAWL_TIMEOUT,
            "crawl_max_pages": settings.CRAWL_MAX_PAGES,
            "crawl_rate_limit_delay": settings.CRAWL_RATE_LIMIT_DELAY,
        }
    else:
        job_config = None

    # Snapshot the proxy URL for this scan type (None if proxy disabled or this
    # type is not selected) so the engine routes — or bypasses — accordingly.
    # The retry URL is snapshotted the same way: it is independent of the
    # per-phase flags and lets the engine run a direct pass first and re-attempt
    # blocked hosts through the proxy within the same job. Both are enqueue-time
    # snapshots, so a later settings change never alters an already queued job.
    proxy_url = proxy_url_for_scan_type(scan_type)
    if proxy_url:
        if job_config is None:
            job_config = {}
        job_config["proxy_url"] = proxy_url

    retry_proxy_url = retry_proxy_url_for_scan_type(scan_type)
    if retry_proxy_url:
        if job_config is None:
            job_config = {}
        job_config["retry_proxy_url"] = retry_proxy_url

    return job_config


def next_queue_pos(db: Session) -> int:
    """The position after the last queued job."""
    max_pos = db.query(ScanJob.queue_pos).filter(
        ScanJob.status == "queued"
    ).order_by(ScanJob.queue_pos.desc()).first()
    return (max_pos[0] + 1) if max_pos and max_pos[0] is not None else 1


def create_scan_job(
    db: Session,
    project_id: str,
    scan_type: str,
    asset_ids: list[str] | None = None,
    scope_domains: list[str] | None = None,
    queue_pos: int | None = None,
    commit: bool = True,
) -> ScanJob:
    """Queue one job. `queue_pos` is passed in only by callers that allocate a
    block of positions themselves; otherwise it is taken from the tail of the
    queue."""
    job = ScanJob(
        id=str(uuid.uuid4()),
        project_id=project_id,
        scan_type=scan_type,
        status="queued",
        queue_pos=next_queue_pos(db) if queue_pos is None else queue_pos,
        asset_ids=asset_ids,
        scope_domains=scope_domains,
        created_at=schedule_service.utc_now(),
        config=build_job_config(scan_type),
    )
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    return job


def enqueue_cycle(db: Session, project_id: str, phases: list[str]) -> list[str]:
    """Queue one full scheduled cycle and return its job ids.

    The base position is allocated once and the phases take consecutive slots
    from it: the engine is single-threaded and drains by ascending queue_pos, so
    consecutive positions are what makes recon finish before tech starts. Every
    job is project-wide — a scheduled cycle has no selection to honour, and both
    tech and crawl already read an empty asset list as "all project assets",
    just as recon reads no scope_domains as "all root domains".
    """
    wanted = set(phases or ())
    ordered = [p for p in SCAN_PHASES if p in wanted]
    if not ordered:
        return []

    base = next_queue_pos(db)
    job_ids = []
    for offset, phase in enumerate(ordered):
        job = create_scan_job(
            db,
            project_id,
            phase,
            queue_pos=base + offset,
            commit=False,
        )
        job_ids.append(job.id)
    # One commit for the cycle: a partially queued cycle would run phases out of
    # order against a scheduler that believes it queued all of them.
    db.commit()
    return job_ids


def has_active_jobs(db: Session, project_id: str) -> bool:
    """Whether the project has anything queued or running. An EXISTS probe, so
    a project with a large scan history costs the same as an idle one."""
    probe = select(ScanJob.id).where(
        ScanJob.project_id == project_id,
        ScanJob.status.in_(ACTIVE_STATUSES),
    ).exists()
    return bool(db.query(probe).scalar())


def all_jobs_finished(db: Session, job_ids: list[str]) -> tuple[bool, datetime | None]:
    """Whether every job of a cycle has reached a terminal state, and when the
    last of them finished.

    A job id that no longer resolves counts as finished: scan history is
    clearable, and a cycle whose rows an operator deleted must not pin the
    schedule open forever.
    """
    ids = list(job_ids or ())
    if not ids:
        return True, None

    rows = db.query(ScanJob.status, ScanJob.finished_at).filter(
        ScanJob.id.in_(ids)
    ).all()
    if not rows:
        return True, None

    latest = None
    for status, finished_at in rows:
        if status not in TERMINAL_STATUSES:
            return False, None
        if finished_at is not None and (latest is None or finished_at > latest):
            latest = finished_at
    return True, latest
