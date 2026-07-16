# backend/routers/assets.py
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
from auth.middleware import require_admin, require_viewer
from models.finding import Finding
from schemas.asset import AssetCreate, AssetUpdate, AssetOut, normalize_crawled_urls
from services import asset_service, project_service
from config import settings

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["assets"])


def _read_response_file(rel_path: str) -> str | None:
    """Read an asset's stored response body, confined to data/projects/.

    response_file_path is stored relative to the data dir (e.g.
    "projects/<id>/responses/<host>.txt"), but the files live under
    data/projects/. Strip the leading "projects/" before resolving so the
    lookup isn't doubled, and refuse anything that escapes the safe base.
    """
    stripped = rel_path[len("projects/"):] if rel_path.startswith("projects/") else rel_path
    file_path = (settings.DATA_DIR / "projects" / stripped).resolve()
    safe_base = (settings.DATA_DIR / "projects").resolve()
    if not file_path.is_relative_to(safe_base) or not file_path.is_file():
        return None
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _flatten_dns_records(records) -> list[dict]:
    """Mirror the detail view's DNS flattening: recon scans store records flat,
    but older scans wrapped them per resolver as [{resolver, records: [...]}].
    Expand any such envelopes and drop cross-resolver duplicates so the export
    matches what the UI renders."""
    if not isinstance(records, list):
        return []
    flat: list[dict] = []
    seen: set[tuple] = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        inner = rec.get("records") if isinstance(rec.get("records"), list) else [rec]
        for r in inner:
            if not isinstance(r, dict):
                continue
            key = (r.get("type"), r.get("value"))
            if key in seen:
                continue
            seen.add(key)
            flat.append(r)
    return flat


def _build_asset_export(db: Session, asset) -> dict:
    """Assemble a self-contained, ordered snapshot of everything the asset
    detail view surfaces: metadata, technologies, DNS, endpoints, the response
    body, and findings."""
    findings = (
        db.query(Finding)
        .filter(Finding.asset_id == asset.id)
        .order_by(Finding.created_at.asc())
        .all()
    )
    crawled = normalize_crawled_urls(asset.crawled_urls)
    export = {
        "asset": asset.asset,
        "asset_type": asset.asset_type,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "identifiers": {"id": asset.id, "project_id": asset.project_id},
        "metadata": {
            "status_code": asset.status_code,
            "title": asset.title,
            "content_length": asset.content_length,
            "redirects_to": asset.redirects_to,
            "date_scanned": asset.date_scanned.isoformat() if asset.date_scanned else None,
            "manually_inserted": asset.manually_inserted,
        },
        "technologies": asset.technologies or [],
        "dns_records": _flatten_dns_records(asset.dns_records),
        "endpoints": {
            "crawled": crawled["crawling"],
            "archived": crawled["archived"],
        },
        "screenshot_path": asset.screenshot_path,
        "response": None,
        "findings": [
            {
                "title": f.title,
                "severity": f.severity,
                "body": f.body,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in findings
        ],
    }
    if asset.response_file_path:
        export["response"] = {
            "path": asset.response_file_path,
            "content": _read_response_file(asset.response_file_path),
        }
    return export


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


@router.get("/{asset_id}/export")
def export_asset(project_id: str, asset_id: str, db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    """Download a single asset as a formatted <asset>.json snapshot containing
    every field shown in the asset detail view, including its findings."""
    asset = asset_service.get_asset(db, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Asset not found")
    body = json.dumps(_build_asset_export(db, asset), indent=2, ensure_ascii=False)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", asset.asset) or "asset"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
    )


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
