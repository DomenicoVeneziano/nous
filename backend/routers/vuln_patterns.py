# backend/routers/vuln_patterns.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.vuln_pattern import VulnPatternCreate, VulnPatternUpdate, VulnPatternOut, VulnPatternTestResult
import services.vuln_pattern_service as vuln_pattern_service
from services.search_service import search_assets

router = APIRouter(prefix="/vuln-patterns", tags=["vuln-patterns"])


@router.get("/", response_model=list[VulnPatternOut])
def list_patterns(
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    return vuln_pattern_service.list_patterns(db)


@router.post("/", response_model=VulnPatternOut, status_code=201)
def create_pattern(
    data: VulnPatternCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    existing = vuln_pattern_service.get_pattern_by_name(db, data.name)
    if existing:
        raise HTTPException(409, f"Pattern with name '{data.name}' already exists")
    checks = [c.model_dump() for c in data.checks]
    return vuln_pattern_service.create_pattern(db, data.name, data.description, checks)


@router.put("/{pattern_id}", response_model=VulnPatternOut)
def update_pattern(
    pattern_id: str,
    data: VulnPatternUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    pattern = vuln_pattern_service.get_pattern(db, pattern_id)
    if not pattern:
        raise HTTPException(404, "Pattern not found")
    checks = [c.model_dump() for c in data.checks] if data.checks is not None else None
    return vuln_pattern_service.update_pattern(db, pattern, data.description, checks)


@router.delete("/{pattern_id}", status_code=204)
def delete_pattern(
    pattern_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    pattern = vuln_pattern_service.get_pattern(db, pattern_id)
    if not pattern:
        raise HTTPException(404, "Pattern not found")
    if pattern.is_default:
        raise HTTPException(403, "Default patterns cannot be deleted")
    vuln_pattern_service.delete_pattern(db, pattern)


@router.post("/{pattern_id}/test", response_model=VulnPatternTestResult)
def test_pattern(
    pattern_id: str,
    project_id: str = Query(..., description="Project ID to test against"),
    db: Session = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    pattern = vuln_pattern_service.get_pattern(db, pattern_id)
    if not pattern:
        raise HTTPException(404, "Pattern not found")
    # Run search using vuln: syntax
    matched = search_assets(db, f"vuln:{pattern.name}", project_id=project_id, limit=10000)
    return VulnPatternTestResult(
        pattern_id=pattern.id,
        pattern_name=pattern.name,
        match_count=len(matched),
        matched_asset_ids=[a.id for a in matched],
    )
