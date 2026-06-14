# backend/routers/findings.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth.middleware import require_admin, require_viewer
from models.asset import Asset
from models.finding import Finding
from schemas.finding import FindingCreate, FindingUpdate, FindingOut

router = APIRouter(
    prefix="/projects/{project_id}/assets/{asset_id}/findings",
    tags=["findings"],
)


def _get_asset(db: Session, project_id: str, asset_id: str) -> Asset:
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.project_id == project_id,
    ).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset


@router.get("/", response_model=list[FindingOut])
def list_findings(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    _get_asset(db, project_id, asset_id)
    return (
        db.query(Finding)
        .filter(Finding.asset_id == asset_id)
        .order_by(Finding.created_at.asc())
        .all()
    )


@router.post("/", response_model=FindingOut, status_code=201)
def create_finding(
    project_id: str,
    asset_id: str,
    data: FindingCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    _get_asset(db, project_id, asset_id)
    now = datetime.now(timezone.utc)
    finding = Finding(
        asset_id   = asset_id,
        project_id = project_id,
        title      = data.title,
        severity   = data.severity,
        body       = data.body,
        created_at = now,
        updated_at = now,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


@router.put("/{finding_id}", response_model=FindingOut)
def update_finding(
    project_id: str,
    asset_id: str,
    finding_id: str,
    data: FindingUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    _get_asset(db, project_id, asset_id)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.asset_id == asset_id,
    ).first()
    if not finding:
        raise HTTPException(404, "Finding not found")
    if data.title is not None:
        finding.title = data.title
    if data.severity is not None:
        finding.severity = data.severity
    if data.body is not None:
        finding.body = data.body
    finding.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(finding)
    return finding


@router.delete("/{finding_id}", status_code=204)
def delete_finding(
    project_id: str,
    asset_id: str,
    finding_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    _get_asset(db, project_id, asset_id)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.asset_id == asset_id,
    ).first()
    if not finding:
        raise HTTPException(404, "Finding not found")
    db.delete(finding)
    db.commit()
