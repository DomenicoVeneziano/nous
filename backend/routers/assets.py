# backend/routers/assets.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.asset import AssetCreate, AssetUpdate, AssetOut
from services import asset_service, project_service
from config import settings

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["assets"])


@router.get("/", response_model=list[AssetOut])
def list_assets(
    project_id: str,
    limit: int = Query(500, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    return asset_service.list_assets(db, project_id, limit, offset)


@router.get("/count")
def count_assets(project_id: str, db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    return {"count": asset_service.count_assets(db, project_id)}


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(project_id: str, asset_id: str, db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    asset = asset_service.get_asset(db, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Asset not found")
    return asset


@router.post("/", response_model=AssetOut, status_code=201)
def create_asset(project_id: str, data: AssetCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    proj = project_service.get_project(db, project_id)
    if not proj:
        raise HTTPException(404, "Project not found")
    name = data.asset.strip()
    if not name:
        raise HTTPException(422, "Asset value is required")
    if asset_service.get_asset_by_name(db, project_id, name):
        raise HTTPException(409, f"Asset '{name}' already exists in this project")
    try:
        asset = asset_service.create_asset(db, project_id, data)
    except IntegrityError:
        raise HTTPException(409, f"Asset '{name}' already exists in this project")
    project_service.refresh_counts(db, project_id)
    return asset


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(project_id: str, asset_id: str, data: AssetUpdate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    asset = asset_service.update_asset(db, asset_id, data)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Asset not found")
    return asset


@router.delete("/{asset_id}", status_code=204)
def delete_asset(project_id: str, asset_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    asset = asset_service.get_asset(db, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Asset not found")
    asset_service.delete_asset(db, asset_id)
    project_service.refresh_counts(db, project_id)


@router.delete("/{asset_id}/screenshot", status_code=204)
def delete_asset_screenshot(project_id: str, asset_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Delete an asset's screenshot: remove the file on disk and clear the path."""
    asset = asset_service.get_asset(db, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Asset not found")
    if asset.screenshot_path:
        # screenshot_path is stored relative to data/projects/ (e.g.
        # "<project_id>/screenshots/<host>.png"). Resolve + confine before unlink.
        file_path = (settings.DATA_DIR / "projects" / asset.screenshot_path).resolve()
        safe_base = (settings.DATA_DIR / "projects").resolve()
        if file_path.is_relative_to(safe_base) and file_path.is_file():
            file_path.unlink()
        asset.screenshot_path = None
        db.commit()
