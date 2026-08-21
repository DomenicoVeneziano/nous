# backend/services/asset_service.py
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.asset import Asset
from models.tag import SOURCE_MANUAL
from schemas.asset import AssetCreate, AssetUpdate, normalize_crawled_urls
from services import tag_service
import ipaddress
import uuid

# Largest range the API will expand. 1024 is an IPv4 /22, and the same host
# count ceiling applies to IPv6 — a /118 and narrower.
MAX_CIDR_HOSTS = 1024

# Largest expansion a single request may produce across every range it names.
# MAX_CIDR_HOSTS bounds one range; without this a scope listing hundreds of /22s
# would still build a list of hundreds of thousands of addresses in one request.
MAX_CIDR_HOSTS_TOTAL = 4096

# Canonical empty per-source endpoint object stored in assets.crawled_urls.
# Byte-identical to EMPTY_CRAWLED_URLS in engine/queue_manager.py; the engine
# runs as a separate service and cannot import backend code, so the literal is
# duplicated rather than shared. Keep the two in step.
EMPTY_CRAWLED_URLS = '{"crawling": [], "archived": []}'

# SQLite caps bound parameters per statement; chunk long name/id lists well
# under it, matching tag_service._ID_CHUNK.
_NAME_CHUNK = 500


class CidrError(ValueError):
    """A CIDR the API refuses to expand — routers map this to a 422."""


def get_asset_by_name(db: Session, project_id: str, asset: str) -> Asset | None:
    return (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.asset == asset)
        .first()
    )


def detect_asset_type(value: str) -> str:
    """Classify an asset string when the caller did not state its type.

    Mirrors the engine's `_is_ip` (see engine/dns_precheck.py) by using the
    stdlib `ipaddress`, so both IPv4 and IPv6 literals classify as "ip", while
    bracketed forms, CIDR and host:port fall through to "subdomain".
    """
    try:
        ipaddress.ip_address(value.strip())
        return "ip"
    except ValueError:
        return "subdomain"


def parse_cidr(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """The network `value` denotes, or None when it is not a CIDR at all.

    The literal "/" test is load-bearing: `ipaddress.ip_network("1.2.3.4")`
    succeeds as a /32, so without it every bare IP would take the expansion
    path. `strict=False` accepts a host address with a prefix ("10.0.0.5/24")
    and normalizes it to its network.
    """
    value = (value or "").strip()
    if "/" not in value:
        return None
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        return None


def expand_cidr(value: str) -> list[str]:
    """Every address in `value`, or raise CidrError.

    The size guard reads num_addresses — an integer — and runs before anything
    is materialized: an IPv6 /64 is 2**64 addresses, a Python bigint here and an
    out-of-memory kill the moment it becomes a list.

    `hosts()` excludes the network and broadcast addresses of a /30 and wider,
    but the stdlib already special-cases the degenerate prefixes, returning both
    addresses of a /31 or /127 and the single address of a /32 or /128. The
    fallback covers an IPv6 range whose only address is the network address
    (anycast), which `hosts()` yields as empty.
    """
    net = parse_cidr(value)
    if net is None:
        raise CidrError(f"'{value}' is not a valid CIDR range")
    if net.num_addresses > MAX_CIDR_HOSTS:
        raise CidrError(
            f"CIDR {net} spans {net.num_addresses} addresses, over the "
            f"{MAX_CIDR_HOSTS} limit. The cap counts every address in the "
            f"range, so an IPv4 /22 (1024 addresses, 1022 usable hosts) is the "
            f"widest range accepted."
        )
    return [str(h) for h in net.hosts()] or [str(net.network_address)]


def _asset_ids_by_name(db: Session, project_id: str, names: list[str]) -> dict[str, str]:
    """{asset name: id} for the names of `names` that already exist.

    One statement per chunk of names, never one per name — the lookup runs on
    ranges of up to MAX_CIDR_HOSTS addresses.
    """
    found: dict[str, str] = {}
    for start in range(0, len(names), _NAME_CHUNK):
        chunk = names[start:start + _NAME_CHUNK]
        placeholders = ", ".join(f":n{i}" for i in range(len(chunk)))
        params = {f"n{i}": name for i, name in enumerate(chunk)}
        params["pid"] = project_id
        rows = db.execute(text(
            f"SELECT asset, id FROM assets"
            f" WHERE project_id = :pid AND asset IN ({placeholders})"
        ), params).fetchall()
        for row in rows:
            found[row[0]] = row[1]
    return found


# Mirrors the column list and the '[]' / empty-crawled-urls / '' tags_text
# literals of engine/queue_manager.py::insert_asset_if_absent, the existing
# precedent for a raw insert against these JSON columns. first_seen_scan_id is
# left out rather than bound to NULL: an asset seeded from the scope or typed in
# by hand has no originating scan, which is exactly what the NULL column means.
#
# INSERT OR IGNORE is what absorbs a uq_assets_project_asset race — a concurrent
# writer landing the same address between the lookup and this insert — without
# raising an IntegrityError that would poison the session for the whole batch.
_INSERT_ASSET_SQL = (
    "INSERT OR IGNORE INTO assets"
    " (id, project_id, asset, asset_type, dns_records, technologies,"
    " crawled_urls, first_seen, tags_text)"
    " VALUES (:id, :pid, :asset, :atype, '[]', '[]', :cu, :now, '')"
)

# SQLAlchemy stores DateTime columns on SQLite as naive
# "%Y-%m-%d %H:%M:%S.%f". A raw insert has to emit that exact shape or the value
# will not read back through the ORM; see engine/queue_manager._TS_FORMAT.
_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def create_assets_bulk(
    db: Session, project_id: str, names: list[str], source_tag: str
) -> list[str]:
    """Create every named asset that does not exist yet, tag them all, return ids.

    Ids, not ORM objects: the scope-seeding path creates thousands of assets it
    never reads back, and materializing them would also pull every row's tags
    through the selectin load on Asset.tags. A caller that needs the objects —
    only the asset router, which serializes them — passes these ids to
    load_assets_by_ids.

    Ids come back in the order `names` gave them, deduplicated, so the router's
    response preserves the order of the expansion it asked for.

    Three statements' worth of work regardless of how many names arrive: a
    chunked existence lookup, one executemany insert, and a chunked lookup to
    resolve ids for the full set. No per-name SELECT and no per-name commit —
    this runs on CIDR expansions of up to MAX_CIDR_HOSTS_TOTAL addresses.

    Names that already exist are not re-inserted but are still returned and
    still tagged: naming an asset is what the source tag records, the same
    reasoning that has the engine's attach_source_tag stamp its source on rows
    it did not create.

    Each name is classified by detect_asset_type, so an IP is stored as "ip"
    whether it came from a CIDR, from a project's scope, or on its own.
    """
    unique: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = (raw or "").strip()
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    if not unique:
        return []

    existing = _asset_ids_by_name(db, project_id, unique)
    to_insert = [name for name in unique if name not in existing]
    if to_insert:
        now = datetime.now(timezone.utc).strftime(_TS_FORMAT)
        db.execute(text(_INSERT_ASSET_SQL), [
            {
                "id": str(uuid.uuid4()),
                "pid": project_id,
                "asset": name,
                "atype": detect_asset_type(name),
                "cu": EMPTY_CRAWLED_URLS,
                "now": now,
            }
            for name in to_insert
        ])
        db.commit()

    # Re-read rather than trusting the ids just generated: an OR IGNORE that hit
    # a race inserted nothing, and the row that won carries a different id.
    ids_by_name = _asset_ids_by_name(db, project_id, unique)
    asset_ids = [ids_by_name[name] for name in unique if name in ids_by_name]
    if not asset_ids:
        return []
    tag = tag_service.ensure_system_tag(db, project_id, source_tag)
    tag_service.assign_tag_bulk(db, asset_ids, tag.id)
    return asset_ids


def load_assets_by_ids(db: Session, asset_ids: list[str]) -> list[Asset]:
    """The Asset rows for `asset_ids`, in that order, loaded in chunks.

    Chunked for the same reason as _asset_ids_by_name: SQLite caps bound
    parameters per statement. Ids that no longer resolve to a row are dropped.
    """
    if not asset_ids:
        return []
    loaded: dict[str, Asset] = {}
    for start in range(0, len(asset_ids), _NAME_CHUNK):
        chunk = asset_ids[start:start + _NAME_CHUNK]
        for asset in db.query(Asset).filter(Asset.id.in_(chunk)).all():
            loaded[asset.id] = asset
    return [loaded[aid] for aid in asset_ids if aid in loaded]


def create_asset(db: Session, project_id: str, data: AssetCreate) -> Asset:
    name = data.asset.strip()
    asset = Asset(
        id=str(uuid.uuid4()),
        project_id=project_id,
        asset=name,
        asset_type=data.asset_type or detect_asset_type(name),
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
