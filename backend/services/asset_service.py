# backend/services/asset_service.py
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.asset import Asset
from models.tag import SOURCE_MANUAL
from schemas.asset import AssetCreate, AssetUpdate, normalize_crawled_urls
from services import tag_service
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
        first_seen=datetime.now(timezone.utc),
    )
    # Apply optional fields if provided
    for field in ("technologies", "status_code", "title", "content_length", "dns_records", "crawled_urls"):
        value = getattr(data, field, None)
        if value is not None:
            if field == "crawled_urls":
                value = normalize_crawled_urls(value.model_dump())
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
    # An asset created through the API is manual by definition — that fact used
    # to live in the manually_inserted boolean and is now a source tag.
    tag_service.apply_system_tag(db, project_id, asset.id, SOURCE_MANUAL)
    db.refresh(asset)
    return asset


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
            value = normalize_crawled_urls(value)
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
