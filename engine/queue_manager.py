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
        updates["started_at"] = datetime.now(timezone.utc).isoformat()
    if to_status in ("done", "failed", "timed_out", "cancelled"):
        updates["finished_at"] = datetime.now(timezone.utc).isoformat()

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


def insert_assets_bulk(session: Session, project_id: str, hostnames: list[str]) -> int:
    """Insert new asset records, skipping duplicates. Returns count created."""
    count = 0
    for hostname in hostnames:
        hostname = hostname.strip().lower()
        if not hostname:
            continue
        result = session.execute(text(
            "INSERT OR IGNORE INTO assets "
            "(id, project_id, asset, asset_type, dns_records, technologies, crawled_urls, manually_inserted) "
            "VALUES (:id, :pid, :asset, 'subdomain', '[]', '[]', '[]', 0)"
        ), {"id": str(uuid.uuid4()), "pid": project_id, "asset": hostname})
        count += result.rowcount
    session.commit()
    return count


def insert_asset_if_absent(session: Session, project_id: str, hostname: str) -> str | None:
    """Insert a single subdomain asset if it does not already exist.
    Returns the new asset id if created, or None if it was already present."""
    hostname = hostname.strip().lower()
    if not hostname:
        return None
    new_id = str(uuid.uuid4())
    result = session.execute(text(
        "INSERT OR IGNORE INTO assets "
        "(id, project_id, asset, asset_type, dns_records, technologies, crawled_urls, manually_inserted) "
        "VALUES (:id, :pid, :asset, 'subdomain', '[]', '[]', '[]', 0)"
    ), {"id": new_id, "pid": project_id, "asset": hostname})
    session.commit()
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
        "created": datetime.now(timezone.utc).isoformat(),
        "cfg": json.dumps(config) if config is not None else None,
    })
    session.commit()
    return job_id


def merge_crawled_urls_bulk(
    session: Session,
    project_id: str,
    host_paths: dict,
) -> int:
    """Merge URL paths into existing assets' crawled_urls. Returns count of assets updated."""
    if not host_paths:
        return 0

    hostnames = list(host_paths.keys())
    placeholders, params = _in_params(hostnames)
    params["pid"] = project_id

    rows = session.execute(text(
        f"SELECT asset, crawled_urls FROM assets WHERE project_id = :pid AND asset IN ({placeholders})"
    ), params).fetchall()

    updates = {}
    for asset, current_json in rows:
        current_urls = json.loads(current_json) if current_json else []
        merged = sorted(set(current_urls) | set(host_paths[asset]), key=str.lower)
        if merged != current_urls:
            updates[asset] = json.dumps(merged)

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
