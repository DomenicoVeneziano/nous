# backend/routers/scans.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.scan import ScanCreate, ScanPositionUpdate, ScanOut
from models.scan import ScanJob
from services.project_service import get_project
from ws.scan_stream import clear_buffer_and_broadcast
from services.settings_store import proxy_url_for_scan_type
from config import settings
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("/", response_model=ScanOut, status_code=201)
def enqueue_scan(data: ScanCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    project = get_project(db, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if data.scope_domains:
        valid = set(project.root_domains or [])
        invalid = [d for d in data.scope_domains if d not in valid]
        if invalid:
            raise HTTPException(422, f"Domains not in project scope: {invalid}")

    # Get next queue position
    max_pos = db.query(ScanJob.queue_pos).filter(
        ScanJob.status == "queued"
    ).order_by(ScanJob.queue_pos.desc()).first()
    next_pos = (max_pos[0] + 1) if max_pos and max_pos[0] is not None else 1

    # Snapshot all scan-relevant settings into the job config so the engine
    # (a separate process) uses the values active at enqueue time.
    if data.scan_type == "recon":
        job_config = {
            "dns_bruteforce_enabled": settings.DNS_BRUTEFORCE_ENABLED,
            "recon_timeout": settings.RECON_TIMEOUT,
            "wordlist_path": str(settings.WORDLIST_PATH),
            "resolvers_path": str(settings.RESOLVERS_PATH),
            "dns_rate_limit_delay": settings.DNS_RATE_LIMIT_DELAY,
        }
    elif data.scan_type == "tech":
        job_config = {
            "per_domain_timeout": settings.TECH_TIMEOUT,
            "tech_rate_limit_delay": settings.TECH_RATE_LIMIT_DELAY,
            "dns_rate_limit_delay": settings.DNS_RATE_LIMIT_DELAY,
            "resolvers_path": str(settings.RESOLVERS_PATH),
            "screenshots_enabled": settings.TECH_SCREENSHOTS_ENABLED,
        }
    elif data.scan_type == "crawl":
        job_config = {
            "crawl_timeout": settings.CRAWL_TIMEOUT,
            "crawl_max_pages": settings.CRAWL_MAX_PAGES,
            "crawl_rate_limit_delay": settings.CRAWL_RATE_LIMIT_DELAY,
        }
    else:
        job_config = None

    # Snapshot the proxy URL for this scan type (None if proxy disabled or this
    # type is not selected) so the engine routes — or bypasses — accordingly.
    proxy_url = proxy_url_for_scan_type(data.scan_type)
    if proxy_url:
        if job_config is None:
            job_config = {}
        job_config["proxy_url"] = proxy_url

    job = ScanJob(
        id=str(uuid.uuid4()),
        project_id=data.project_id,
        scan_type=data.scan_type,
        status="queued",
        queue_pos=next_pos,
        asset_ids=data.asset_ids,
        scope_domains=data.scope_domains,
        created_at=datetime.now(timezone.utc),
        config=job_config,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/queue", response_model=list[ScanOut])
def get_queue(db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    return (
        db.query(ScanJob)
        .filter(ScanJob.status.in_(["queued", "running"]))
        .order_by(ScanJob.queue_pos)
        .all()
    )


@router.get("/history", response_model=list[ScanOut])
def get_history(db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    return (
        db.query(ScanJob)
        .filter(ScanJob.status.in_(["done", "failed", "cancelled", "timed_out"]))
        .order_by(ScanJob.finished_at.desc())
        .limit(100)
        .all()
    )


@router.delete("/output", status_code=204)
async def clear_output(_: dict = Depends(require_admin)):
    await clear_buffer_and_broadcast()


@router.delete("/history", status_code=204)
def clear_history(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    db.query(ScanJob).filter(
        ScanJob.status.in_(["done", "failed", "cancelled", "timed_out"])
    ).delete(synchronize_session="fetch")
    db.commit()


@router.patch("/{job_id}/position", response_model=ScanOut)
def reorder_job(job_id: str, data: ScanPositionUpdate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "queued":
        raise HTTPException(400, "Can only reorder queued jobs")
    job.queue_pos = data.queue_pos
    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=204)
def cancel_or_delete_job(job_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("queued", "running"):
        # Cancel active jobs
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    else:
        # Delete completed/failed/cancelled jobs from history
        db.delete(job)
        db.commit()
