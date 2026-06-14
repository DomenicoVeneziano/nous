# backend/services/finding_search_service.py
from sqlalchemy.orm import Session
from models.finding import Finding
from models.asset import Asset


def search_findings(
    db: Session,
    query: str | None = None,
    severity: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Finding]:
    """Search findings by text and/or severity, optionally scoped to a project."""
    q = db.query(Finding, Asset).join(Asset, Finding.asset_id == Asset.id)

    if project_id:
        q = q.filter(Finding.project_id == project_id)

    if severity:
        q = q.filter(Finding.severity == severity)

    if query and query.strip():
        term = f"%{query.strip()}%"
        q = q.filter(
            Finding.title.ilike(term) | Finding.body.ilike(term)
        )

    q = q.order_by(Finding.created_at.desc())
    rows = q.offset(offset).limit(limit).all()

    results = []
    for finding, asset in rows:
        finding.asset_hostname = asset.asset  # type: ignore[attr-defined]
        results.append(finding)
    return results
