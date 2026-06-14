# backend/services/project_service.py
from sqlalchemy.orm import Session
from models.project import Project
from models.asset import Asset
from models.scan import ScanJob
from models.finding import Finding
from schemas.project import ProjectCreate, ProjectUpdate
from config import settings
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
    """Create assets for each hostname, skipping duplicates."""
    existing = {
        a.asset
        for a in db.query(Asset.asset).filter(Asset.project_id == project_id).all()
    }
    for hostname in hostnames:
        hostname = hostname.strip()
        if not hostname or hostname in existing:
            continue
        db.add(Asset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            asset=hostname,
            asset_type="subdomain",
            manually_inserted=True,
        ))
        existing.add(hostname)


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
    db.query(Asset).filter(Asset.project_id == project_id).delete()
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
