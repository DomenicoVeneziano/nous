# backend/routers/search.py
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from database import get_db
from auth.middleware import require_viewer
from models.asset import Asset
from schemas.asset_search import AssetSearchOut
from schemas.finding_search import FindingSearchOut
from services.search_service import search_assets
from services.finding_search_service import search_findings
from services.export_service import export_json, export_csv

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/", response_model=list[AssetSearchOut])
def search(
    query: str = Query(..., min_length=1),
    project_id: str | None = Query(None),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    # No limit by default — every matching asset is returned and paginated
    # client-side, matching the uncapped project asset list.
    return search_assets(db, query, project_id, limit, offset)


@router.get("/findings", response_model=list[FindingSearchOut])
def search_findings_endpoint(
    query: str | None = Query(None),
    severity: str | None = Query(None, pattern="^(informative|low|medium|high|critical)$"),
    project_id: str | None = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    return search_findings(db, query, severity, project_id, limit, offset)


@router.get("/export")
def search_export(
    query: str = Query("", min_length=0),
    format: str = Query("json", pattern="^(json|csv)$"),
    project_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    if query:
        assets = search_assets(db, query, project_id, limit=10000, offset=0)
    else:
        q = db.query(Asset)
        if project_id:
            q = q.filter(Asset.project_id == project_id)
        assets = q.limit(10000).all()
    if format == "csv":
        return PlainTextResponse(
            content=export_csv(assets),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=export.csv"},
        )
    return PlainTextResponse(
        content=export_json(assets),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=export.json"},
    )
