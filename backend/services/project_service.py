# backend/services/project_service.py
from sqlalchemy.orm import Session
from models.project import Project
from models.asset import Asset
from models.scan import ScanJob
from models.finding import Finding
from models.tag import SOURCE_SEED, Tag, asset_tags
from schemas.project import ProjectCreate, ProjectUpdate
from services import tag_service
from config import settings
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import uuid


def _is_wildcard_domain(domain: str) -> bool:
    """Check if a domain is a wildcard scope (e.g. *.example.com)."""
    return domain.startswith("*.")


def _split_domains_and_assets(entries: list[str]) -> tuple[list[str], list[str]]:
    """
    Split input lines into wildcard domains (kept as root_domains)
    and specific hostnames/IPs (to be created as assets).
    """
    wildcards = []
    assets = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if _is_wildcard_domain(entry):
            wildcards.append(entry)
        else:
            assets.append(entry)
    return wildcards, assets


def _create_assets_from_hostnames(db: Session, project_id: str, hostnames: list[str]):
    """Create assets for each hostname, skipping duplicates.

    These come from the project's scope field rather than a scan, so they carry
    the Seed source tag.
    """
    existing = {
        a.asset: a.id
        for a in db.query(Asset.asset, Asset.id).filter(Asset.project_id == project_id).all()
    }
    now = datetime.now(timezone.utc)
    created_ids: list[str] = []
    # Hostnames the scope names that are already assets — found by an earlier
    # scan, or carried over from a previous scope edit. Skipping the insert does
    # not mean skipping the tag: the scope naming them is what Seed records, the
    # same reasoning that has the engine's attach_source_tag stamp its source on
    # rows it did not create. Ids, so a repeated hostname tags one asset once.
    seeded_ids: set[str] = set()
    for hostname in hostnames:
        hostname = hostname.strip()
        if not hostname:
            continue
        asset_id = existing.get(hostname)
        if asset_id:
            seeded_ids.add(asset_id)
            continue
        asset_id = str(uuid.uuid4())
        db.add(Asset(
            id=asset_id,
            project_id=project_id,
            asset=hostname,
            asset_type="subdomain",
            first_seen=now,
        ))
        existing[hostname] = asset_id
        created_ids.append(asset_id)
    if not created_ids and not seeded_ids:
        return
    db.commit()
    tag = tag_service.ensure_system_tag(db, project_id, SOURCE_SEED)
    # INSERT OR IGNORE on the join table, and the mirror rewrite skips rows whose
    # tags_text already matches, so re-seeding an asset that carries Seed costs
    # nothing and reindexes nothing.
    tag_service.assign_tag_bulk(db, created_ids + sorted(seeded_ids), tag.id)


def create_project(db: Session, data: ProjectCreate) -> Project:
    # Split input: wildcard domains stay as root_domains, others become assets
    wildcards, asset_hostnames = _split_domains_and_assets(data.root_domains)

    project = Project(
        id=str(uuid.uuid4()),
        title=data.title,
        description=data.description,
        root_domains=wildcards,
        subdomains=data.subdomains,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Create assets from non-wildcard entries
    if asset_hostnames:
        _create_assets_from_hostnames(db, project.id, asset_hostnames)
        db.commit()
        refresh_counts(db, project.id)

    # Create project data directory and meta.json
    project_dir = settings.DATA_DIR / "projects" / project.id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "responses").mkdir(exist_ok=True)
    (project_dir / "crawl").mkdir(exist_ok=True)
    (project_dir / "logs").mkdir(exist_ok=True)

    meta = {
        "id": project.id,
        "title": project.title,
        "root_domains": project.root_domains,
    }
    (project_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    return project


def get_project(db: Session, project_id: str) -> Project | None:
    return db.query(Project).filter(Project.id == project_id).first()


def list_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.title).all()


def update_project(db: Session, project_id: str, data: ProjectUpdate) -> Project | None:
    project = get_project(db, project_id)
    if not project:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # If root_domains is being updated, filter out non-wildcard entries and create assets
    if "root_domains" in update_data and update_data["root_domains"] is not None:
        wildcards, asset_hostnames = _split_domains_and_assets(update_data["root_domains"])
        update_data["root_domains"] = wildcards
        if asset_hostnames:
            _create_assets_from_hostnames(db, project_id, asset_hostnames)

    for field, value in update_data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)

    if "root_domains" in update_data:
        refresh_counts(db, project_id)

    return project


def delete_project(db: Session, project_id: str) -> bool:
    project = get_project(db, project_id)
    if not project:
        return False
    db.query(Finding).filter(Finding.project_id == project_id).delete()
    db.query(ScanJob).filter(ScanJob.project_id == project_id).delete()
    # Drop tag links before the assets they belong to: these are bulk deletes,
    # which bypass ORM cascades, and tags.project_id carries no foreign key of
    # its own, so nothing would reclaim these rows otherwise.
    asset_ids = [a.id for a in db.query(Asset.id).filter(Asset.project_id == project_id)]
    if asset_ids:
        db.execute(asset_tags.delete().where(asset_tags.c.asset_id.in_(asset_ids)))
    db.query(Asset).filter(Asset.project_id == project_id).delete()
    db.query(Tag).filter(Tag.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    project_dir = settings.DATA_DIR / "projects" / project_id
    shutil.rmtree(project_dir, ignore_errors=True)
    return True


def refresh_counts(db: Session, project_id: str):
    project = get_project(db, project_id)
    if not project:
        return
    project.asset_count = db.query(Asset).filter(Asset.project_id == project_id).count()
    project.tech_count = (
        db.query(Asset)
        .filter(Asset.project_id == project_id)
        .filter(Asset.technologies != "[]")
        .filter(Asset.technologies.isnot(None))
        .count()
    )
    db.commit()
