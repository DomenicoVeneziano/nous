# backend/routers/scans.py
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.scan import ScanCreate, ScanPositionUpdate, ScanOut
from models.scan import ScanJob
from services.project_service import get_project
from services import scan_service
from services.asset_service import _asset_ids_by_name
from ws.scan_stream import clear_buffer_and_broadcast
from datetime import datetime, timezone

router = APIRouter(prefix="/scans", tags=["scans"])

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9._\-]+$")
_MAX_INVALID_LISTED = 20
# Each non-root host is a sequential archive run of up to an hour on the
# single-threaded engine, so one recon run may not queue an unbounded batch.
MAX_ARCHIVE_HOSTS = 500


@router.post("/", response_model=ScanOut, status_code=201)
def enqueue_scan(data: ScanCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    project = get_project(db, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    scope_domains = data.scope_domains
    if scope_domains:
        scope_domains = list(dict.fromkeys(scope_domains))
        roots = set(project.root_domains or [])
        non_root = [d for d in scope_domains if d not in roots]
        if len(non_root) > MAX_ARCHIVE_HOSTS:
            raise HTTPException(422, f"At most {MAX_ARCHIVE_HOSTS} non-root hosts per recon run; {len(non_root)} given")
        # Non-root entries must be existing subdomain assets of this project;
        # the lookup is chunked, so the assets table is never loaded whole.
        candidates = [d for d in non_root if _DOMAIN_RE.match(d)]
        known = _asset_ids_by_name(db, project.id, candidates, asset_type="subdomain")
        invalid = [d for d in non_root if d not in known]
        if invalid:
            listed = invalid[:_MAX_INVALID_LISTED]
            extra = len(invalid) - len(listed)
            suffix = f" (+{extra} more)" if extra else ""
            raise HTTPException(422, f"Domains not in project scope: {listed}{suffix}")

    # Queueing lives in scan_service so this endpoint and the recurring
    # scheduler cannot drift apart on settings snapshots or queue ordering.
    return scan_service.create_scan_job(
        db,
        project_id=data.project_id,
        scan_type=data.scan_type,
        asset_ids=data.asset_ids,
        scope_domains=scope_domains,
    )


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
