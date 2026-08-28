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

# Vantage-point tag, not a discovery source: it marks assets whose STORED scan
# result came from a proxied pass. It is the one tag the engine removes
# automatically — a later direct pass that succeeds detaches it.
SYSTEM_TAG_PROXIED = "Proxied"

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


def job_is_cancelled(session: Session, job_id: str) -> bool:
    """True once the job is no longer running — the pass-boundary checkpoint.

    The worker only polls for cancellation every POLL_INTERVAL seconds, so
    without a check here an expensive later pass could start after a cancel was
    already requested. The commit ends any open read snapshot first: a
    long-lived session would otherwise keep reading the status it saw when its
    transaction began.
    """
    session.commit()
    return get_job_status(session, job_id) != "running"


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


def is_in_scope(host: str, root_domains: list[str]) -> bool:
    """True if host equals or is a subdomain of any project root domain.
    Root domains may carry a leading '*.' wildcard (e.g. '*.sisal.com'), which
    is normalised to the apex before matching."""
    host = (host or "").lower().strip(".")
    for d in root_domains:
        d = (d or "").lower().strip()
        if d.startswith("*."):
            d = d[2:]
        d = d.strip(".")
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


# Asset columns whose per-write delta is logged into asset_changes. Everything
# else an engine write touches (date_scanned, screenshot_path, response_file_path,
# crawled_urls) is bookkeeping about the scan rather than about the surface.
# The scalars compare exactly; the set-valued pair compares as sets. Order is the
# SELECT order — the snapshot is zipped against it positionally.
_TRACKED_SCALARS = ("status_code", "title", "redirects_to", "content_length")
_TRACKED_SETS = ("technologies", "dns_records")
_TRACKED_COLUMNS = _TRACKED_SCALARS + _TRACKED_SETS

# A body-size swing under this fraction of the previous size is dynamic noise —
# rotating CSRF tokens, timestamps, ad slots — not an edit to the page.
_CONTENT_LENGTH_MIN_RATIO = 0.10

# Latches only once the asset_changes probe has SEEN the table. A missing table
# is never cached: the race that matters is the table APPEARING, not vanishing.
# On the first deploy of change tracking onto an existing database, wait_for_db
# clears on the migration sentinel the previous build already wrote, so the
# engine can start a job before the backend reaches CREATE TABLE asset_changes.
# Latching that no would kill change tracking for the life of the process.
_ASSET_CHANGES_READY = False


def _asset_changes_ready(session: Session) -> bool:
    """Whether the change log exists. Probed per write until it does, then cached.

    migrations_complete() keys on the tagging sentinel, which every already-
    upgraded database carries, so it proves nothing about a table added after it.
    An INSERT into a missing table raises OperationalError and poisons the
    session, which would roll back an asset UPDATE that had nothing wrong with
    it — so ask sqlite_master and, when the answer is no, write exactly as the
    engine did before the log existed.

    A no costs one sqlite_master lookup per write until the backend creates the
    table, at which point the answer latches and the cost goes away. Same
    self-healing the retention sweep already has, which just retries next tick.
    """
    global _ASSET_CHANGES_READY
    if not _ASSET_CHANGES_READY:
        row = session.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'asset_changes'"
        )).fetchone()
        _ASSET_CHANGES_READY = row is not None
    return _ASSET_CHANGES_READY


def _tech_set(raw) -> set:
    """Technologies as a set. Compared as a set and not as text on purpose: the
    fingerprinter's output order is not stable, and a reordered list is not a
    change to the surface."""
    parsed = _parse_json(raw, default=[])
    if not isinstance(parsed, list):
        return set()
    return {t for t in parsed if isinstance(t, str)}


def _dns_key_set(raw) -> set:
    """DNS records flattened to a comparable set of "TYPE value" strings.

    Recon stores records flat, but rows written by older scans wrap them per
    resolver as [{resolver, records: [...]}]. Both shapes have to collapse to the
    same set, or the first rescan of a pre-flat row reads as a total replacement
    of every record it holds. Counterpart of
    backend/routers/assets.py::_flatten_dns_records — change one only by changing
    the other.
    """
    records = _parse_dns(raw)
    if not isinstance(records, list):
        return set()
    keys = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        inner = rec.get("records") if isinstance(rec.get("records"), list) else [rec]
        for r in inner:
            if isinstance(r, dict):
                keys.add(f"{r.get('type')} {r.get('value')}")
    return keys


def _scalar_text(value) -> str | None:
    """Scalar change values are stored as text; an unset side stays SQL NULL."""
    return None if value is None else str(value)


def _diff_asset_fields(before: dict, fields: dict) -> list:
    """The change rows one write leaves behind, as (field, old_value, new_value).

    `fields` must be the caller's own write, read BEFORE update_asset_record
    injects its hostname/pid bind params: those two are not columns, and code
    iterating the dict after the injection sees them as phantom ones.
    """
    status_written = "status_code" in fields
    old_status = before.get("status_code")
    new_status = fields["status_code"] if status_written else old_status
    # 0 is the tech job's dead sentinel, so a write that crosses it in either
    # direction IS the liveness event: the host went dead, or came back alive.
    crosses_dead = status_written and (old_status == 0) != (new_status == 0)
    # A body size only means something when the host was live on both sides and
    # stayed that way. Across a liveness flip the size change is that flip.
    length_comparable = (not status_written or old_status == new_status) and new_status != 0

    changes = []
    for field in _TRACKED_SCALARS:
        if field not in fields:
            continue
        old, new = before.get(field), fields[field]
        if old == new:
            continue
        if field == "title" and crosses_dead:
            # On a liveness flip the title is only the DNS/TCP failure reason
            # (or the page title displacing one), which restates the status_code
            # row instead of adding anything to the timeline.
            continue
        if field == "content_length" and not (
            length_comparable
            # NULL on either side is not a shrink: the redirect path writes the
            # length as None, and an asset scanned for the first time has none.
            and old is not None and new is not None
            and abs(new - old) >= _CONTENT_LENGTH_MIN_RATIO * max(old, 1)
        ):
            continue
        changes.append((field, _scalar_text(old), _scalar_text(new)))

    for field in _TRACKED_SETS:
        if field not in fields:
            continue
        to_set = _dns_key_set if field == "dns_records" else _tech_set
        old_set, new_set = to_set(before.get(field)), to_set(fields[field])
        removed, added = sorted(old_set - new_set), sorted(new_set - old_set)
        if not removed and not added:
            continue
        # A delta, not a before/after: old on the left holds what went away and
        # new on the right what arrived, keeping the column roles the scalars use.
        changes.append((field, json.dumps(removed), json.dumps(added)))

    return changes


def update_asset_record(
    session: Session,
    hostname: str,
    project_id: str,
    *,
    scan_id: str | None = None,
    **fields,
):
    """Update asset fields by hostname and project_id, logging what changed.

    The UPDATE and the change rows share one transaction and one commit at the
    end, so the log can never assert a transition the asset row did not take:
    split across commits, a crash between them would leave exactly that. Nothing
    in the diff is wrapped in try/except for the same reason — a failure has to
    take the UPDATE down with it rather than half-apply.

    The snapshot SELECT is NOT inside that transaction: get_engine() leaves
    pysqlite's stock isolation in place, which opens the transaction lazily on
    the first DML, so the read runs in autocommit ahead of it. The window is
    between the snapshot and the UPDATE, and a backend asset edit landing inside
    it makes one recorded old_value stale — one wrong row, nothing corrupted.
    Not worth a BEGIN IMMEDIATE that would serialize every asset write.

    Deliberately not a trigger on `assets`, even though the FTS mirror is one:
    both sync_tags_text implementations issue a bare `UPDATE assets SET
    tags_text = ...`, and a trigger would bill every tag edit as a surface change.
    Same split as the is_new badge, which is derived rather than trigger-fed.

    `scan_id` is keyword-only so it can never collide with a column name in
    **fields; `assets` has no such column, and no caller writes one.
    """
    if not fields:
        return

    asset_id = None
    before = None
    # A write that touches no tracked column can only produce an empty diff, so
    # it skips the lookup entirely rather than paying for a foregone conclusion.
    if _asset_changes_ready(session) and not fields.keys().isdisjoint(_TRACKED_COLUMNS):
        # One unique-index lookup on uq_assets_project_asset per asset already
        # being written — the whole cost of the feature. id rides along because
        # the change rows need asset_id, and fetching it separately would double
        # that cost for nothing.
        row = session.execute(text(
            f"SELECT id, date_scanned, {', '.join(_TRACKED_COLUMNS)} FROM assets "
            "WHERE asset = :h AND project_id = :pid"
        ), {"h": hostname, "pid": project_id}).fetchone()
        # date_scanned is a first-observation marker here, not a tracked field:
        # NULL means this asset has never been through a tech analysis, so every
        # tracked column still holds its insert default (NULL, or '[]' for the
        # sets) and the diff would describe nothing but the asset's own
        # discovery. Appearance is already answered by first_seen /
        # first_seen_scan_id, so the first scan of a new asset logs nothing.
        if row and row[1] is not None:
            asset_id = row[0]
            before = dict(zip(_TRACKED_COLUMNS, row[2:]))

    # Computed before the injection below, while `fields` still holds columns only.
    changes = _diff_asset_fields(before, fields) if before is not None else []

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["hostname"] = hostname
    fields["pid"] = project_id
    # Run unconditionally even when the diff came back empty: date_scanned and
    # the FTS reindex the UPDATE fires are the point of a rescan. Only the change
    # rows are conditional, so an unchanged rescan logs nothing.
    session.execute(
        text(f"UPDATE assets SET {set_clause} WHERE asset = :hostname AND project_id = :pid"),
        fields,
    )

    if changes:
        # One statement, at most len(_TRACKED_COLUMNS) rows — far under SQLite's
        # bound-parameter cap, so this needs no _ID_CHUNK batching.
        now = utc_now_str()
        values_sql = ", ".join(
            f"(:id{i}, :pid, :aid, :sid, :f{i}, :o{i}, :n{i}, :ts)" for i in range(len(changes))
        )
        params = {"pid": project_id, "aid": asset_id, "sid": scan_id, "ts": now}
        for i, (field, old_value, new_value) in enumerate(changes):
            params[f"id{i}"] = str(uuid.uuid4())
            params[f"f{i}"] = field
            params[f"o{i}"] = old_value
            params[f"n{i}"] = new_value
        session.execute(text(
            "INSERT INTO asset_changes "
            "(id, project_id, asset_id, scan_id, field, old_value, new_value, changed_at) "
            f"VALUES {values_sql}"
        ), params)

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


def _resolve_asset_ids(session: Session, project_id: str, names: list[str]) -> list[str]:
    """Asset ids for the given normalized hostnames, resolved in _ID_CHUNK batches."""
    asset_ids: list[str] = []
    for start in range(0, len(names), _ID_CHUNK):
        chunk = names[start:start + _ID_CHUNK]
        placeholders, params = _in_params(chunk)
        params["pid"] = project_id
        rows = session.execute(text(
            f"SELECT id FROM assets WHERE project_id = :pid AND asset IN ({placeholders})"
        ), params).fetchall()
        asset_ids.extend(r[0] for r in rows)
    return asset_ids


def attach_tag(session: Session, project_id: str, hostnames: list[str], name: str) -> None:
    """Attach one system tag to every named asset, creating the tag if needed."""
    names = [h.strip().lower() for h in hostnames if h and h.strip()]
    if not names:
        return
    tag_id = ensure_tag(session, project_id, name)
    asset_ids = _resolve_asset_ids(session, project_id, names)
    for start in range(0, len(asset_ids), _ID_CHUNK):
        chunk = asset_ids[start:start + _ID_CHUNK]
        values_sql = ", ".join(f"(:a{i}, :t)" for i in range(len(chunk)))
        params = {f"a{i}": asset_id for i, asset_id in enumerate(chunk)}
        params["t"] = tag_id
        session.execute(text(
            f"INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES {values_sql}"
        ), params)
    sync_tags_text(session, asset_ids)
    session.commit()


def detach_tag(session: Session, project_id: str, hostnames: list[str], name: str) -> None:
    """Remove one tag from every named asset. No-op if the project never used it.

    Deliberately does NOT go through ensure_tag: resolving the tag with a
    read-only SELECT is what stops a detach-only call from materializing a tag
    row in every project that has never once taken this path. A missing tag row
    means nothing to detach, so the whole call costs a single SELECT.

    The tag row itself is left in place even once no asset carries it — it is
    cheap, and dropping it would race concurrent attaches.
    """
    names = [h.strip().lower() for h in hostnames if h and h.strip()]
    if not names:
        return
    row = session.execute(text(
        "SELECT id FROM tags WHERE project_id = :pid AND name = :n"
    ), {"pid": project_id, "n": name}).fetchone()
    if not row:
        return
    tag_id = row[0]
    asset_ids = _resolve_asset_ids(session, project_id, names)
    if not asset_ids:
        return
    for start in range(0, len(asset_ids), _ID_CHUNK):
        chunk = asset_ids[start:start + _ID_CHUNK]
        placeholders, params = _in_params(chunk)
        params["t"] = tag_id
        session.execute(text(
            f"DELETE FROM asset_tags WHERE tag_id = :t AND asset_id IN ({placeholders})"
        ), params)
    sync_tags_text(session, asset_ids)
    session.commit()


def attach_source_tag(session: Session, project_id: str, hostnames: list[str], source: str) -> None:
    """Tag every named asset with a discovery source.

    Applied to hostnames that already existed as well as newly inserted ones:
    an asset independently re-found by bruteforce genuinely has two sources, and
    that accumulation is the signal. Source tags are never removed automatically.
    """
    attach_tag(session, project_id, hostnames, source)


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


def enqueue_scan(
    session: Session,
    project_id: str,
    scan_type: str,
    asset_ids: list[str],
    config: dict | None,
) -> str:
    """Queue a follow-up scan over the given assets. Used by the tech job to
    follow in-scope cross-host redirects and by the crawl job for the hosts it
    discovers. Mirrors the backend enqueue: appends to the end of the queue.

    Returns the new job id, or "" when `asset_ids` is empty — an empty set has
    nothing to scan, so no row is written rather than queueing a no-op job.

    The queue position is MAX(queue_pos) + 1 across ALL queued jobs regardless
    of scan_type: one queue, one ordering. Never scope this count by scan_type.
    """
    if scan_type not in ("recon", "tech", "crawl"):
        raise ValueError(f"invalid scan_type: {scan_type}")
    if not asset_ids:
        return ""

    row = session.execute(text(
        "SELECT MAX(queue_pos) FROM scan_jobs WHERE status = 'queued'"
    )).fetchone()
    next_pos = (row[0] + 1) if row and row[0] is not None else 1
    job_id = str(uuid.uuid4())
    session.execute(text(
        "INSERT INTO scan_jobs (id, project_id, scan_type, status, queue_pos, asset_ids, created_at, config) "
        "VALUES (:id, :pid, :stype, 'queued', :pos, :aids, :created, :cfg)"
    ), {
        "id": job_id,
        "pid": project_id,
        "stype": scan_type,
        "pos": next_pos,
        "aids": json.dumps(asset_ids),
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
