# backend/database.py
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings
from pathlib import Path

db_path = settings.DATA_DIR / "db"
db_path.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{db_path / 'nous.db'}",
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Marks a database whose asset_fts index has been rebuilt with rowids that match
# assets.rowid. Lives in the app_settings key/value table.
_FTS_SENTINEL = "FTS_ROWID_REBUILD"

# How SQLAlchemy renders a DateTime for SQLite: naive, no offset. Raw SQL writes
# to those columns have to match it or the two forms sort against each other.
_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

_FTS_CREATE = """
    CREATE VIRTUAL TABLE IF NOT EXISTS asset_fts USING fts5(
        asset_id UNINDEXED,
        hostname,
        dns_records,
        technologies,
        status_code,
        title,
        content_length,
        urls,
        tags
    )
"""

# The index is keyed by assets.rowid. FTS5's xBestIndex only honours MATCH and
# `rowid = ?` constraints, so keying the triggers on the stored asset_id (which
# is UNINDEXED) turned every delete into a full scan of the index: a single-row
# UPDATE on `assets` paid a whole-index scan, and a table-wide UPDATE — the
# tags_text repair below, for one — degraded to O(n^2). On rowid it is a point
# lookup.
#
# Two invariants this depends on:
#   * `assets` must stay a rowid table. Declaring it WITHOUT ROWID removes
#     `old.rowid` and would silently break the delete half of every trigger.
#   * `assets` must never be written with INSERT OR REPLACE. recursive_triggers
#     is off, so the implicit delete would not fire assets_ad, and the
#     replacement row would collide with the stale index entry on its rowid.
#
# The JSON columns (dns_records, technologies, crawled_urls) are indexed as their
# raw JSON text. FTS5's default unicode61 tokenizer treats brackets, quotes and
# commas as separators, so '["nginx","apache"]' tokenizes to the same terms as
# the previous comma-joined format — searches are unaffected.
_FTS_COLUMNS = (
    "rowid, asset_id, hostname, dns_records, technologies, "
    "status_code, title, content_length, urls, tags"
)
_FTS_NEW_VALUES = (
    "new.rowid, new.id, new.asset, "
    "COALESCE(new.dns_records, ''), COALESCE(new.technologies, ''), "
    "COALESCE(new.status_code, ''), COALESCE(new.title, ''), "
    "COALESCE(new.content_length, ''), COALESCE(new.crawled_urls, ''), "
    "COALESCE(new.tags_text, '')"
)
# Bulk (re)build using the exact projection the triggers use, so a backfilled row
# and a trigger-written row are byte-for-byte identical — rowid included, which
# is what lets the triggers find the row again later.
_FTS_BACKFILL = (
    f"INSERT INTO asset_fts({_FTS_COLUMNS}) SELECT "
    "rowid, id, asset, COALESCE(dns_records, ''), COALESCE(technologies, ''), "
    "COALESCE(status_code, ''), COALESCE(title, ''), "
    "COALESCE(content_length, ''), COALESCE(crawled_urls, ''), "
    "COALESCE(tags_text, '') FROM assets"
)

# Keep the FTS index in sync at the DATABASE level via triggers, so it stays
# correct no matter which process or code path writes a row. The backend writes
# via the SQLAlchemy ORM and the engine writes via raw `text()` SQL; ORM event
# listeners only covered the former, silently leaving every engine-discovered
# asset out of the index. Triggers cover both. assets_ai has to supply the rowid
# explicitly — an auto-assigned one would not match `old.rowid` when the row is
# later updated or deleted.
_FTS_TRIGGERS = (
    f"CREATE TRIGGER assets_ai AFTER INSERT ON assets BEGIN "
    f"INSERT INTO asset_fts({_FTS_COLUMNS}) VALUES ({_FTS_NEW_VALUES}); END",
    f"CREATE TRIGGER assets_au AFTER UPDATE ON assets BEGIN "
    f"DELETE FROM asset_fts WHERE rowid = old.rowid; "
    f"INSERT INTO asset_fts({_FTS_COLUMNS}) VALUES ({_FTS_NEW_VALUES}); END",
    "CREATE TRIGGER assets_ad AFTER DELETE ON assets BEGIN "
    "DELETE FROM asset_fts WHERE rowid = old.rowid; END",
)


def _migrate_asset_rows(cur):
    """Row-level `assets` repairs. Idempotent; safe to run on every boot."""
    # Migrate crawled_urls from the legacy flat list to the per-source object
    # {"crawling": [...], "archived": []}. Legacy combined endpoints land under
    # "crawling". Only list-shaped values (JSON starting with '[') are touched.
    cur.execute("SELECT id, crawled_urls FROM assets WHERE crawled_urls LIKE '[%'")
    for asset_id, raw in cur.fetchall():
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            items = []
        if not isinstance(items, list):
            continue
        new_val = json.dumps({"crawling": items, "archived": []})
        cur.execute(
            "UPDATE assets SET crawled_urls = ? WHERE id = ?", (new_val, asset_id)
        )

    # Retire the manually_inserted boolean in favour of the Manual source tag,
    # which carries the same fact in the system every other discovery path now
    # reports through. Idempotent: the column is dropped once the rows have been
    # converted, so a second run finds nothing to do.
    cur.execute("PRAGMA table_info(assets)")
    if "manually_inserted" in {r[1] for r in cur.fetchall()}:
        cur.execute("SELECT id, project_id FROM assets WHERE manually_inserted = 1")
        by_project: dict[str, list[str]] = {}
        for asset_id, pid in cur.fetchall():
            by_project.setdefault(pid, []).append(asset_id)
        for pid, asset_ids in by_project.items():
            cur.execute(
                "SELECT id FROM tags WHERE project_id = ? AND name = 'Manual'", (pid,)
            )
            tag_row = cur.fetchone()
            if tag_row:
                tag_id = tag_row[0]
            else:
                tag_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO tags (id, project_id, name, is_system, created_at) "
                    "VALUES (?, ?, 'Manual', 1, ?)",
                    (tag_id, pid, datetime.now(timezone.utc).strftime(_TS_FORMAT)),
                )
            for asset_id in asset_ids:
                cur.execute(
                    "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (?, ?)",
                    (asset_id, tag_id),
                )
        # DROP COLUMN landed in SQLite 3.35.0; older builds parse it as a syntax
        # error, which would abort the enclosing transaction on every restart.
        # The column cannot simply be left in place either: it is NOT NULL with
        # no SQL-level default (the old model carried a Python-side default), and
        # the current model no longer maps it, so every later asset INSERT would
        # fail the NOT NULL constraint. Booting into that state is worse than not
        # booting, so refuse explicitly and say what to upgrade.
        cur.execute("SELECT sqlite_version()")
        sqlite_version = cur.fetchone()[0]
        if tuple(int(p) for p in sqlite_version.split(".")[:2]) < (3, 35):
            raise RuntimeError(
                f"SQLite 3.35.0 or newer is required to complete this schema "
                f"upgrade (found {sqlite_version}). Upgrade SQLite and restart."
            )
        cur.execute("ALTER TABLE assets DROP COLUMN manually_inserted")

    # Rebuild the tags_text mirror whenever a tagged asset is out of sync with
    # the join table (first run after the migration above, or a DB touched by an
    # older build). Cheap to evaluate, rare to fire. The probe uses IS NOT rather
    # than != because != yields NULL — not true — for a NULL mirror, and would
    # under-report drift on such a row. tags_text is NOT NULL on every current
    # path, so this is insurance against a future nullable column, not a live bug.
    cur.execute(
        "SELECT COUNT(*) FROM assets a WHERE a.tags_text IS NOT COALESCE("
        " (SELECT GROUP_CONCAT(t.name, ' ') FROM asset_tags at"
        "  JOIN tags t ON t.id = at.tag_id WHERE at.asset_id = a.id), '')"
    )
    if cur.fetchone()[0]:
        cur.execute(
            "UPDATE assets SET tags_text = COALESCE("
            " (SELECT GROUP_CONCAT(t.name, ' ') FROM asset_tags at"
            "  JOIN tags t ON t.id = at.tag_id WHERE at.asset_id = assets.id), '')"
        )


def init_db():
    from models.user import User
    from models.project import Project
    from models.tag import Tag, asset_tags
    from models.asset import Asset
    from models.scan import ScanJob
    from models.api_key import ApiKey
    from models.finding import Finding
    from models.vuln_pattern import VulnPattern
    from models.app_setting import AppSetting

    Base.metadata.create_all(bind=engine)

    # Add icon column if missing (migration for existing DBs)
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE projects ADD COLUMN icon TEXT"))
            conn.commit()
        except Exception:
            pass  # Column already exists

    # Add scope_domains column to scan_jobs if missing
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE scan_jobs ADD COLUMN scope_domains JSON"))
            conn.commit()
        except Exception:
            pass  # Column already exists

    # Add screenshot_path column to assets if missing
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE assets ADD COLUMN screenshot_path TEXT"))
            conn.commit()
        except Exception:
            pass  # Column already exists

    # Add redirects_to column to assets if missing
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE assets ADD COLUMN redirects_to TEXT"))
            conn.commit()
        except Exception:
            pass  # Column already exists

    # Add unique constraint on (project_id, asset) if missing
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX uq_assets_project_asset ON assets (project_id, asset)"
            ))
            conn.commit()
        except Exception:
            pass  # Index already exists

    # Tagging columns. first_seen_scan_id backs the derived "New!" badge;
    # tags_text is the denormalized mirror the FTS triggers index (see
    # models/asset.py). Left NULL on pre-existing rows — the discovery date of an
    # asset found before tagging existed is genuinely unknown, and date_scanned
    # records a tech analysis, not a discovery.
    for ddl in (
        "ALTER TABLE assets ADD COLUMN first_seen DATETIME",
        "ALTER TABLE assets ADD COLUMN first_seen_scan_id TEXT",
        "ALTER TABLE assets ADD COLUMN last_crawl_at DATETIME",
        "ALTER TABLE assets ADD COLUMN tags_text TEXT NOT NULL DEFAULT ''",
    ):
        with engine.connect() as conn:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # Column already exists

    # Recurring-schedule columns. next_scan_at is NULL for every pre-existing
    # row, which is exactly "not due" — an upgrade must not make anything
    # scannable that the operator never asked to schedule. The three indexes are
    # what keep the scheduler's poll off a table scan: one covers the due-project
    # lookup, one the in-flight cycles the finalizer walks (partial, so it holds
    # only the handful of rows actually mid-cycle), and one the per-project
    # active-job probe in scan_service.
    for ddl in (
        "ALTER TABLE projects ADD COLUMN schedule_enabled BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN schedule_interval_value INTEGER",
        "ALTER TABLE projects ADD COLUMN schedule_interval_unit TEXT",
        "ALTER TABLE projects ADD COLUMN schedule_phases JSON",
        "ALTER TABLE projects ADD COLUMN next_scan_at DATETIME",
        "ALTER TABLE projects ADD COLUMN schedule_cycle_job_ids JSON",
        "ALTER TABLE projects ADD COLUMN schedule_cycle_started_at DATETIME",
        "ALTER TABLE projects ADD COLUMN schedule_last_run_at DATETIME",
        "CREATE INDEX IF NOT EXISTS ix_projects_schedule_due ON projects (schedule_enabled, next_scan_at)",
        "CREATE INDEX IF NOT EXISTS ix_projects_cycle_in_flight ON projects (schedule_cycle_started_at) "
        "WHERE schedule_cycle_job_ids IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_scan_jobs_project_status ON scan_jobs (project_id, status)",
    ):
        with engine.connect() as conn:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # Column or index already exists

    # Repair rows written before the JSON columns were declared none_as_null.
    # SQLAlchemy's JSON type stores a Python None as the JSON text 'null' by
    # default, which the ORM reads back as None but SQL counts as a value: a
    # project whose schedule_cycle_job_ids held 'null' looked to the scheduler
    # like a cycle permanently in flight, so its due time was recomputed on
    # every tick and no scheduled scan could ever come due. Idempotent, and a
    # no-op on any database written by the current model.
    for ddl in (
        "UPDATE projects SET schedule_cycle_job_ids = NULL WHERE schedule_cycle_job_ids = 'null'",
        "UPDATE projects SET schedule_phases = NULL WHERE schedule_phases = 'null'",
    ):
        with engine.connect() as conn:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # Column not present yet on a database mid-upgrade

    # Normalize timestamps the engine wrote as offset-aware ISO strings
    # ("2026-07-27T09:15:00.123456+00:00") to the naive, space-separated form
    # SQLAlchemy's SQLite DateTime reads and writes. Both processes write these
    # columns, and the two spellings do not interleave: ' ' (0x20) sorts before
    # 'T', so an offset row collates as older than every naive one and ORDER BY
    # returns the wrong sequence. The LIKE guard is the whole idempotency story —
    # it matches only the offset shape, so NULLs and already-canonical values are
    # never touched and a re-run finds nothing to do. Rewriting `assets` re-fires
    # assets_au per row, which is a rowid point lookup and reindexes nothing that
    # changed — none of these columns is in the FTS projection.
    for table, column in (
        ("assets", "first_seen"),
        ("assets", "last_crawl_at"),
        ("assets", "date_scanned"),
        ("scan_jobs", "created_at"),
        ("scan_jobs", "started_at"),
        ("scan_jobs", "finished_at"),
        ("projects", "last_scan_date"),
        ("projects", "next_scan_at"),
        ("projects", "schedule_cycle_started_at"),
        ("projects", "schedule_last_run_at"),
        ("tags", "created_at"),
    ):
        with engine.connect() as conn:
            try:
                conn.execute(text(
                    f"UPDATE {table} SET {column} = "
                    f"replace(substr({column}, 1, length({column}) - 6), 'T', ' ') "
                    f"WHERE {column} LIKE '____-__-__T%+00:00'"
                ))
                conn.commit()
            except Exception:
                pass  # Column missing on an older schema — nothing to normalize

    # One-shot upgrade to the rowid-keyed index, gated on a sentinel rather than
    # on "is the index empty?": the tags_text repair rebuilds the index through
    # the triggers, so an emptiness test is already false by the time it would be
    # consulted. Rowid-keyed triggers must never be installed over an index built
    # by the old asset_id-keyed ones — those rowids were auto-assigned at each
    # row's last UPDATE and no longer correspond to any asset, so a delete would
    # evict a different asset's entry and every subsequent insert would collide —
    # hence the index is dropped and rebuilt in the same breath.
    #
    # The row migrations run with no triggers installed, which is what makes them
    # linear rather than quadratic; the index is rebuilt from `assets` afterwards,
    # so nothing is lost by them going unindexed in the meantime. That window is
    # also why the whole upgrade is a single transaction opened with BEGIN
    # IMMEDIATE: a concurrent engine write is held off rather than silently
    # skipping the index, and an interrupted run rolls back whole — it makes no
    # partial forward progress and simply restarts on the next boot.
    #
    # Driven through the raw DBAPI connection because pysqlite runs DDL outside
    # the transaction it manages implicitly; only an explicit BEGIN keeps the
    # DROP/CREATE of the index and of the triggers inside it.
    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        prev_isolation = dbapi.isolation_level
        dbapi.isolation_level = None  # hand BEGIN/COMMIT control to us
        cur = dbapi.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT 1 FROM app_settings WHERE key = ?", (_FTS_SENTINEL,))
            rebuilt = cur.fetchone() is not None

            for trig in ("assets_ai", "assets_au", "assets_ad"):
                cur.execute(f"DROP TRIGGER IF EXISTS {trig}")

            if not rebuilt:
                _migrate_asset_rows(cur)
                # Unconditional drop: a pre-tagging index also lacks the `tags`
                # column, and either way the contents are rebuilt from `assets`.
                cur.execute("DROP TABLE IF EXISTS asset_fts")
                cur.execute(_FTS_CREATE)
                cur.execute(_FTS_BACKFILL)
                for ddl in _FTS_TRIGGERS:
                    cur.execute(ddl)
                cur.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, '1')",
                    (_FTS_SENTINEL,),
                )
            else:
                # Already rowid-aligned. Recreate the index only if it went
                # missing, and refill it only if that left it empty.
                cur.execute(_FTS_CREATE)
                cur.execute("SELECT 1 FROM asset_fts LIMIT 1")
                if cur.fetchone() is None:
                    cur.execute(_FTS_BACKFILL)
                for ddl in _FTS_TRIGGERS:
                    cur.execute(ddl)
                # Triggers are back in place first, so these stay indexed.
                _migrate_asset_rows(cur)

            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.close()
            dbapi.isolation_level = prev_isolation
    finally:
        raw.close()

    db = SessionLocal()
    try:
        from services.vuln_pattern_service import seed_defaults
        seed_defaults(db)
    finally:
        db.close()
