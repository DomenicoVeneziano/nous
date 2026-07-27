# engine/queue_manager.py
import json
import os
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "db" / "nous.db"

# Canonical empty per-source endpoint object stored in assets.crawled_urls.
EMPTY_CRAWLED_URLS = '{"crawling": [], "archived": []}'

# Discovery-source tag names for the paths the engine discovers through. A
# partial mirror of backend/models/tag.py — the engine runs as a separate service
# and cannot import backend code — deliberately leaving out Manual and Seed,
# which only the backend ever applies. Keep the shared names in step.
SOURCE_PASSIVE = "Passive"
SOURCE_BRUTEFORCE = "Bruteforce"
SOURCE_PERMUTATIONS = "Permutations"
SOURCE_CRAWLING = "Crawling"
SOURCE_REDIRECT = "Redirect"

# SQLite caps bound parameters per statement; chunk long id lists well under it.
_ID_CHUNK = 500

# Sentinel row the backend writes into app_settings in the same transaction as
# its schema migrations (mirrors _FTS_SENTINEL in backend/database.py).
MIGRATION_SENTINEL = "FTS_ROWID_REBUILD"

# SQLAlchemy stores DateTime columns on SQLite as naive "%Y-%m-%d %H:%M:%S.%f".
# The engine writes those same columns through raw SQL, so it has to emit that
# exact shape: an isoformat() offset value ("...T...+00:00") does not parse back
# through the ORM, and mixing the two breaks ORDER BY — ' ' (0x20) sorts before
# 'T', so offset rows collate as if they were older than every naive one.
_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def utc_now_str() -> str:
    """Current UTC time in the textual format SQLAlchemy uses for DateTime."""
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


# Valid status transitions
VALID_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"done", "failed", "timed_out", "cancelled"},
}


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def _in_params(items: list, prefix: str = "p") -> tuple[str, dict]:
    """Build a parameterized SQL IN-clause placeholder string and params dict."""
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(items)))
    params = {f"{prefix}{i}": item for i, item in enumerate(items)}
    return placeholders, params


def _parse_json(raw, default=None):
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if parsed is not None else default
        except Exception:
            return default
    return raw if raw is not None else default


def _parse_dns(raw) -> list:
    return _parse_json(raw, default=[])


def migrations_complete(session: Session) -> bool:
    """True once the backend has committed its schema migrations.

    The sentinel is written in the same transaction that adds the tagging
    columns, so its presence is the only cheap proof the engine can write to
    them. Raises OperationalError while app_settings itself is still missing.
    """
    row = session.execute(text(
        "SELECT 1 FROM app_settings WHERE key = :k"
    ), {"k": MIGRATION_SENTINEL}).fetchone()
    return row is not None


def fetch_next_job(session: Session) -> dict | None:
    """Get the next queued job ordered by queue_pos."""
    row = session.execute(text(
        "SELECT id, project_id, scan_type, asset_ids, scope_domains, config "
        "FROM scan_jobs WHERE status = 'queued' "
        "ORDER BY queue_pos ASC LIMIT 1"
    )).fetchone()

    if not row:
        return None

    scope = _parse_json(row[4])
    config = _parse_json(row[5])

    return {
        "id": row[0],
        "project_id": row[1],
        "scan_type": row[2],
        "asset_ids": row[3],
        "scope_domains": scope,
        "config": config,
    }


def transition_status(session: Session, job_id: str, from_status: str, to_status: str, **kwargs):
    """Transition a job's status with validation."""
    if to_status not in VALID_TRANSITIONS.get(from_status, set()):
        raise ValueError(f"Invalid transition: {from_status} -> {to_status}")

    updates = {"status": to_status}
    if to_status == "running":
        updates["started_at"] = utc_now_str()
    if to_status in ("done", "failed", "timed_out", "cancelled"):
        updates["finished_at"] = utc_now_str()

    updates.update(kwargs)

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["job_id"] = job_id
    updates["expected_status"] = from_status

    result = session.execute(
        text(f"UPDATE scan_jobs SET {set_clause} WHERE id = :job_id AND status = :expected_status"),
        updates,
    )
    session.commit()
    return result.rowcount > 0


def get_asset_hostnames(session: Session, asset_ids: list[str]) -> list[str]:
    """Retrieve hostnames for given asset IDs."""
    if not asset_ids:
        return []
    placeholders, params = _in_params(asset_ids)
    rows = session.execute(
        text(f"SELECT asset FROM assets WHERE id IN ({placeholders})"), params
    ).fetchall()
    return [r[0] for r in rows]


def get_job_status(session: Session, job_id: str) -> str | None:
    """Return the current status of a job, or None if not found."""
    row = session.execute(
        text("SELECT status FROM scan_jobs WHERE id = :id"), {"id": job_id}
    ).fetchone()
    return row[0] if row else None


def get_project_asset_hostnames(session: Session, project_id: str) -> list[str]:
    """Retrieve all asset hostnames for a project."""
    rows = session.execute(text(
        "SELECT asset FROM assets WHERE project_id = :pid"
    ), {"pid": project_id}).fetchall()
    return [r[0] for r in rows]


def get_asset_details(session: Session, asset_ids: list[str]) -> list[dict]:
    """Retrieve id, hostname, asset_type, and dns_records for given asset IDs."""
    if not asset_ids:
        return []
    placeholders, params = _in_params(asset_ids)
    rows = session.execute(
        text(f"SELECT id, asset, asset_type, dns_records FROM assets WHERE id IN ({placeholders})"), params
    ).fetchall()
    return [
        {"id": r[0], "hostname": r[1], "asset_type": r[2], "dns_records": _parse_dns(r[3])}
        for r in rows
    ]


def get_all_project_asset_details(session: Session, project_id: str) -> list[dict]:
    """Retrieve id, hostname, asset_type, and dns_records for ALL assets in a project."""
    rows = session.execute(text(
        "SELECT id, asset, asset_type, dns_records FROM assets WHERE project_id = :pid"
    ), {"pid": project_id}).fetchall()
    return [
        {"id": r[0], "hostname": r[1], "asset_type": r[2], "dns_records": _parse_dns(r[3])}
        for r in rows
    ]


def get_project_domains(session: Session, project_id: str) -> list[str]:
    """Get root_domains for a project."""
    row = session.execute(text(
        "SELECT root_domains FROM projects WHERE id = :pid"
    ), {"pid": project_id}).fetchone()
    if not row or not row[0]:
        return []
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def update_asset_record(session: Session, hostname: str, project_id: str, **fields):
    """Update asset fields by hostname and project_id."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["hostname"] = hostname
    fields["pid"] = project_id
    session.execute(
        text(f"UPDATE assets SET {set_clause} WHERE asset = :hostname AND project_id = :pid"),
        fields,
    )
    session.commit()


def ensure_tag(session: Session, project_id: str, name: str) -> str:
    """Get-or-create a system tag for a project. Returns its id."""
    row = session.execute(text(
        "SELECT id FROM tags WHERE project_id = :pid AND name = :name"
    ), {"pid": project_id, "name": name}).fetchone()
    if row:
        return row[0]
    tag_id = str(uuid.uuid4())
    session.execute(text(
        "INSERT OR IGNORE INTO tags (id, project_id, name, is_system, created_at) "
        "VALUES (:id, :pid, :name, 1, :now)"
    ), {"id": tag_id, "pid": project_id, "name": name, "now": utc_now_str()})
    session.commit()
    # A concurrent writer may have won the race; re-read rather than assume.
    row = session.execute(text(
        "SELECT id FROM tags WHERE project_id = :pid AND name = :name"
    ), {"pid": project_id, "name": name}).fetchone()
    return row[0]


# The tags_text mirror rendered from the join table. Byte-identical to the
# expression in backend/services/tag_service.py: both processes write this column
# and identical SQL is what stops them ping-ponging two renderings of the same
# tag set at each other. Change one only by changing the other.
_TAGS_TEXT_EXPR = (
    "COALESCE(("
    " SELECT GROUP_CONCAT(t.name, ' ') FROM asset_tags at"
    " JOIN tags t ON t.id = at.tag_id WHERE at.asset_id = assets.id"
    "), '')"
)
_SYNC_TAGS_TEXT_SQL = f"UPDATE assets SET tags_text = {_TAGS_TEXT_EXPR}"

# Restrict the rewrite to rows whose mirror does not already hold what the SET
# would write. Every UPDATE on `assets` fires assets_au, which deletes and
# reinserts the entire FTS row, so an id-scoped rewrite with no value comparison
# pays full reindex cost for assets whose tags did not change — and attach_source_tag
# is handed the whole result set on every recon pass, most of it already tagged.
#
# `IS NOT`, never `!=`: SQLite evaluates `NULL != x` to NULL, so `!=` would drop a
# NULL mirror from the update set and leave that row's drift unrepaired. tags_text
# is NOT NULL on every path today, so this guards a future nullable column rather
# than a reachable bug — but `!=` has no upside to trade for that.
#
# The subquery is spelled out on both sides on purpose — SET and WHERE have to
# evaluate the identical expression. GROUP_CONCAT's order is plan-determined
# (neither alphabetical nor insertion order), which is harmless precisely because
# both sides are the same subquery inside one statement, so a skip can only mean
# stored == computed. Do not add ORDER BY to one side alone.
#
# One incidental effect is lost: the unconditional form also rewrote the other
# eight FTS columns, so it repaired rows that had gone stale for reasons having
# nothing to do with tags. Repairing those is the rebuild path's job, not this one's.
_DRIFTED_ONLY = f"tags_text IS NOT {_TAGS_TEXT_EXPR}"


def sync_tags_text(session: Session, asset_ids: list[str]) -> None:
    """Refresh the denormalized tags_text mirror on `assets`.

    The FTS triggers fire on `assets` only, so writing to the asset_tags join
    table alone would leave the search index stale. Every tag change has to end
    in an UPDATE here. Mirrors backend/services/tag_service.sync_tags_text.
    """
    for start in range(0, len(asset_ids), _ID_CHUNK):
        chunk = asset_ids[start:start + _ID_CHUNK]
        placeholders, params = _in_params(chunk)
        session.execute(text(
            f"{_SYNC_TAGS_TEXT_SQL} WHERE id IN ({placeholders}) AND {_DRIFTED_ONLY}"
        ), params)


def attach_source_tag(session: Session, project_id: str, hostnames: list[str], source: str) -> None:
    """Tag every named asset with a discovery source.

    Applied to hostnames that already existed as well as newly inserted ones:
    an asset independently re-found by bruteforce genuinely has two sources, and
    that accumulation is the signal. Source tags are never removed automatically.
    """
    names = [h.strip().lower() for h in hostnames if h and h.strip()]
    if not names:
        return
    tag_id = ensure_tag(session, project_id, source)
    asset_ids: list[str] = []
    for start in range(0, len(names), _ID_CHUNK):
        chunk = names[start:start + _ID_CHUNK]
        placeholders, params = _in_params(chunk)
        params["pid"] = project_id
        rows = session.execute(text(
            f"SELECT id FROM assets WHERE project_id = :pid AND asset IN ({placeholders})"
        ), params).fetchall()
        asset_ids.extend(r[0] for r in rows)
    for asset_id in asset_ids:
        session.execute(text(
            "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (:a, :t)"
        ), {"a": asset_id, "t": tag_id})
    sync_tags_text(session, asset_ids)
    session.commit()


def set_last_crawl_at(session: Session, project_id: str, hostnames: list[str]) -> None:
    """Stamp the crawl timestamp on the given assets."""
    names = [h.strip().lower() for h in hostnames if h and h.strip()]
    if not names:
        return
    now = utc_now_str()
    for start in range(0, len(names), _ID_CHUNK):
        chunk = names[start:start + _ID_CHUNK]
        placeholders, params = _in_params(chunk)
        params["pid"] = project_id
        params["now"] = now
        session.execute(text(
            f"UPDATE assets SET last_crawl_at = :now "
            f"WHERE project_id = :pid AND asset IN ({placeholders})"
        ), params)
    session.commit()


def insert_assets_bulk(
    session: Session,
    project_id: str,
    hostnames: list[str],
    source: str | None = None,
    scan_job_id: str | None = None,
) -> int:
    """Insert new asset records, skipping duplicates. Returns count created.

    first_seen / first_seen_scan_id are set on insert only, never on a
    re-discovery: they record when the asset entered the project, and the
    scan id is what the derived "New!" badge is compared against.
    """
    count = 0
    now = utc_now_str()
    for hostname in hostnames:
        hostname = hostname.strip().lower()
        if not hostname:
            continue
        result = session.execute(text(
            "INSERT OR IGNORE INTO assets "
            "(id, project_id, asset, asset_type, dns_records, technologies, crawled_urls, "
            "first_seen, first_seen_scan_id, tags_text) "
            "VALUES (:id, :pid, :asset, 'subdomain', '[]', '[]', :cu, :now, :job, '')"
        ), {"id": str(uuid.uuid4()), "pid": project_id, "asset": hostname,
            "cu": EMPTY_CRAWLED_URLS, "now": now, "job": scan_job_id})
        count += result.rowcount
    session.commit()
    if source:
        attach_source_tag(session, project_id, hostnames, source)
    return count


def insert_asset_if_absent(
    session: Session,
    project_id: str,
    hostname: str,
    source: str | None = None,
    scan_job_id: str | None = None,
) -> str | None:
    """Insert a single subdomain asset if it does not already exist.
    Returns the new asset id if created, or None if it was already present."""
    hostname = hostname.strip().lower()
    if not hostname:
        return None
    new_id = str(uuid.uuid4())
    result = session.execute(text(
        "INSERT OR IGNORE INTO assets "
        "(id, project_id, asset, asset_type, dns_records, technologies, crawled_urls, "
        "first_seen, first_seen_scan_id, tags_text) "
        "VALUES (:id, :pid, :asset, 'subdomain', '[]', '[]', :cu, :now, :job, '')"
    ), {"id": new_id, "pid": project_id, "asset": hostname, "cu": EMPTY_CRAWLED_URLS,
        "now": utc_now_str(), "job": scan_job_id})
    session.commit()
    if source:
        attach_source_tag(session, project_id, [hostname], source)
    return new_id if result.rowcount else None


def enqueue_tech_scan(session: Session, project_id: str, asset_id: str, config: dict | None) -> str:
    """Queue a tech scan for a single asset (used to follow in-scope cross-host
    redirects). Mirrors the backend enqueue: appends to the end of the queue."""
    row = session.execute(text(
        "SELECT MAX(queue_pos) FROM scan_jobs WHERE status = 'queued'"
    )).fetchone()
    next_pos = (row[0] + 1) if row and row[0] is not None else 1
    job_id = str(uuid.uuid4())
    session.execute(text(
        "INSERT INTO scan_jobs (id, project_id, scan_type, status, queue_pos, asset_ids, created_at, config) "
        "VALUES (:id, :pid, 'tech', 'queued', :pos, :aids, :created, :cfg)"
    ), {
        "id": job_id,
        "pid": project_id,
        "pos": next_pos,
        "aids": json.dumps([asset_id]),
        "created": utc_now_str(),
        "cfg": json.dumps(config) if config is not None else None,
    })
    session.commit()
    return job_id


def _normalize_crawled_urls(value) -> dict:
    """Coerce any stored/legacy shape into {"crawling": [...], "archived": [...]}."""
    crawling, archived = [], []
    if isinstance(value, list):          # legacy flat list -> crawling bucket
        crawling = value
    elif isinstance(value, dict):
        crawling = value.get("crawling") or []
        archived = value.get("archived") or []
    return {"crawling": list(crawling), "archived": list(archived)}


def merge_crawled_urls_bulk(
    session: Session,
    project_id: str,
    host_paths: dict,
    source: str = "crawling",
) -> int:
    """Merge URL paths into existing assets' crawled_urls under the given source
    section ("crawling" or "archived"). Returns count of assets updated. Paths in
    the target section are deduped and sorted; the other section is left untouched.
    """
    if not host_paths:
        return 0
    if source not in ("crawling", "archived"):
        raise ValueError(f"invalid crawled_urls source: {source}")

    hostnames = list(host_paths.keys())
    placeholders, params = _in_params(hostnames)
    params["pid"] = project_id

    rows = session.execute(text(
        f"SELECT asset, crawled_urls FROM assets WHERE project_id = :pid AND asset IN ({placeholders})"
    ), params).fetchall()

    updates = {}
    for asset, current_json in rows:
        current = _normalize_crawled_urls(json.loads(current_json) if current_json else None)
        merged_section = sorted(set(current[source]) | set(host_paths[asset]), key=str.lower)
        if merged_section != current[source]:
            current[source] = merged_section
            updates[asset] = json.dumps(current)

    for asset, merged_json in updates.items():
        session.execute(text(
            "UPDATE assets SET crawled_urls = :urls WHERE asset = :h AND project_id = :pid"
        ), {"urls": merged_json, "h": asset, "pid": project_id})

    if updates:
        session.commit()
    return len(updates)


def refresh_project_counts(session: Session, project_id: str):
    """Update denormalized counts and status on project record."""
    row = session.execute(text(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN technologies != '[]' AND technologies IS NOT NULL THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN date_scanned IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM assets WHERE project_id = :pid"
    ), {"pid": project_id}).fetchone()
    asset_count, tech_count, has_scanned = row[0], row[1] or 0, row[2] or 0
    if has_scanned:
        session.execute(text(
            "UPDATE projects SET asset_count = :ac, tech_count = :tc, status = 'scanned' WHERE id = :pid"
        ), {"ac": asset_count, "tc": tech_count, "pid": project_id})
    else:
        session.execute(text(
            "UPDATE projects SET asset_count = :ac, tech_count = :tc WHERE id = :pid"
        ), {"ac": asset_count, "tc": tech_count, "pid": project_id})
    session.commit()
