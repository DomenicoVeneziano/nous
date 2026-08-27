# backend/routers/scans.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.scan import ScanCreate, ScanPositionUpdate, ScanOut
from models.scan import ScanJob
from services.project_service import get_project
from services import scan_service
from ws.scan_stream import clear_buffer_and_broadcast
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

    # Queueing lives in scan_service so this endpoint and the recurring
    # scheduler cannot drift apart on settings snapshots or queue ordering.
    return scan_service.create_scan_job(
        db,
        project_id=data.project_id,
        scan_type=data.scan_type,
        asset_ids=data.asset_ids,
        scope_domains=data.scope_domains,
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
