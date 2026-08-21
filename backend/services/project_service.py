# backend/services/project_service.py
from sqlalchemy.orm import Session
from models.project import Project
from models.asset import Asset
from models.scan import ScanJob
from models.finding import Finding
from models.tag import SOURCE_SEED, Tag, asset_tags
from schemas.project import ProjectCreate, ProjectUpdate
from services import asset_service
from config import settings
from pathlib import Path
import json
import shutil
import uuid


def _is_wildcard_domain(domain: str) -> bool:
    """Check if a domain is a wildcard scope (e.g. *.example.com)."""
    return domain.startswith("*.")


def _split_domains_and_assets(entries: list[str]) -> tuple[list[str], list[str], list[str]]:
    """
    Split input lines into wildcard domains (kept as root_domains), CIDR ranges
    (expanded into one asset per address) and specific hostnames/IPs (created as
    assets one for one).

    A CIDR gets its own bucket because neither of the other two fits it: recon
    consumes root_domains as resolvable scope, and storing the range as a single
    asset would leave every address in it unscanned.
    """
    wildcards = []
    cidrs = []
    assets = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if _is_wildcard_domain(entry):
            wildcards.append(entry)
        elif asset_service.parse_cidr(entry) is not None:
            cidrs.append(entry)
        else:
            assets.append(entry)
    return wildcards, cidrs, assets


def _expand_scope_cidrs(cidrs: list[str], hostnames: list[str]) -> list[str]:
    """The merged asset names a scope implies: every address of every CIDR,
    followed by the hostnames given verbatim.

    Raises asset_service.CidrError on an oversized range, and on a scope whose
    ranges together exceed asset_service.MAX_CIDR_HOSTS_TOTAL. The aggregate cap
    is enforced incrementally, against the running total and before the next
    range is expanded, so the list being built never exceeds it even briefly:
    a per-range cap alone bounds nothing when a scope names hundreds of ranges.
    Callers run this before writing anything, so that rejection costs nothing to
    undo.
    """
    names: list[str] = []
    for cidr in cidrs:
        net = asset_service.parse_cidr(cidr)
        # num_addresses is an int, so the budget check runs before a single
        # address is materialized. A range that busts the per-range cap on its
        # own is left to expand_cidr, which reports it in its own terms.
        if net is not None and net.num_addresses <= asset_service.MAX_CIDR_HOSTS:
            total = len(names) + net.num_addresses
            if total > asset_service.MAX_CIDR_HOSTS_TOTAL:
                raise asset_service.CidrError(
                    f"Expanding {net} would take this scope to {total} "
                    f"addresses ({len(names)} so far), over the "
                    f"{asset_service.MAX_CIDR_HOSTS_TOTAL} a single request may "
                    f"expand across all its CIDR ranges. Add the remaining "
                    f"ranges in a follow-up edit."
                )
        names.extend(asset_service.expand_cidr(cidr))
    return names + hostnames


def _create_assets_from_hostnames(db: Session, project_id: str, names: list[str]):
    """Create assets for each scope entry, skipping duplicates.

    The single entry point for scope-derived assets: hostnames, bare IPs and the
    addresses a CIDR expanded into all arrive here as one merged list, and each
    is classified by asset_service.detect_asset_type rather than assumed to be a
    subdomain.

    These come from the project's scope field rather than a scan, so they carry
    the Seed source tag. Entries the scope names that are already assets — found
    by an earlier scan, or carried over from a previous scope edit — are not
    re-inserted but are still tagged: the scope naming them is what Seed records,
    the same reasoning that has the engine's attach_source_tag stamp its source
    on rows it did not create. INSERT OR IGNORE on the join table, and the mirror
    rewrite skipping rows whose tags_text already matches, keep re-seeding an
    asset that carries Seed free of both writes and reindexing.
    """
    asset_service.create_assets_bulk(db, project_id, names, SOURCE_SEED)


def create_project(db: Session, data: ProjectCreate) -> Project:
    # Split input: wildcard domains stay as root_domains, others become assets
    wildcards, cidrs, asset_hostnames = _split_domains_and_assets(data.root_domains)
    # Expand before the project row exists. The row, its data directory and
    # meta.json are all committed before assets are created, so a CidrError
    # raised further down would leave a half-created project behind; doing the
    # validation here makes an oversized range a clean 422 with nothing written.
    seed_names = _expand_scope_cidrs(cidrs, asset_hostnames)

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
    if seed_names:
        _create_assets_from_hostnames(db, project.id, seed_names)
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
        wildcards, cidrs, asset_hostnames = _split_domains_and_assets(update_data["root_domains"])
        # Expand before `project` is touched, for the same reason as
        # create_project: a rejected range must not leave a partly updated scope.
        seed_names = _expand_scope_cidrs(cidrs, asset_hostnames)
        update_data["root_domains"] = wildcards
        if seed_names:
            _create_assets_from_hostnames(db, project_id, seed_names)

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
