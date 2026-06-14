# backend/services/asset_service.py
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.asset import Asset
from schemas.asset import AssetCreate, AssetUpdate
import uuid


def get_asset_by_name(db: Session, project_id: str, asset: str) -> Asset | None:
    return (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.asset == asset)
        .first()
    )


def create_asset(db: Session, project_id: str, data: AssetCreate) -> Asset:
    asset = Asset(
        id=str(uuid.uuid4()),
        project_id=project_id,
        asset=data.asset.strip(),
        asset_type=data.asset_type,
        manually_inserted=data.manually_inserted,
    )
    # Apply optional fields if provided
    for field in ("technologies", "status_code", "title", "content_length", "dns_records", "crawled_urls"):
        value = getattr(data, field, None)
        if value is not None:
            setattr(asset, field, value)
    db.add(asset)
    # The (project_id, asset) unique constraint can still trip on a race even
    # after a pre-check, so roll back and re-raise so the router maps it to 409
    # rather than leaking a 500 with a poisoned session.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(asset)
    return asset


def bulk_create_assets(db: Session, project_id: str, hostnames: list[str]) -> int:
    """Create assets in bulk, skipping duplicates. Returns count of newly created."""
    existing = {
        a.asset
        for a in db.query(Asset.asset).filter(Asset.project_id == project_id).all()
    }
    new_count = 0
    for hostname in hostnames:
        hostname = hostname.strip()
        if not hostname or hostname in existing:
            continue
        db.add(Asset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            asset=hostname,
            asset_type="subdomain",
            manually_inserted=False,
        ))
        existing.add(hostname)
        new_count += 1
    db.commit()
    return new_count


def get_asset(db: Session, asset_id: str) -> Asset | None:
    return db.query(Asset).filter(Asset.id == asset_id).first()


def list_assets(db: Session, project_id: str, limit: int = 500, offset: int = 0) -> list[Asset]:
    return (
        db.query(Asset)
        .filter(Asset.project_id == project_id)
        .order_by(Asset.asset)
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_assets(db: Session, project_id: str) -> int:
    return db.query(Asset).filter(Asset.project_id == project_id).count()


def update_asset(db: Session, asset_id: str, data: AssetUpdate) -> Asset | None:
    asset = get_asset(db, asset_id)
    if not asset:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "crawled_urls" and value is not None:
            value = sorted(set(value), key=str.lower)
        setattr(asset, field, value)
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, asset_id: str) -> bool:
    asset = get_asset(db, asset_id)
    if not asset:
        return False
    db.delete(asset)
    db.commit()
    return True
