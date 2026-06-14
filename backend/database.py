# backend/database.py
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


def init_db():
    from models.user import User
    from models.project import Project
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

    # Create FTS5 table if it does not yet exist
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS asset_fts USING fts5(
                asset_id UNINDEXED,
                hostname,
                dns_records,
                technologies,
                status_code,
                title,
                content_length,
                urls
            )
        """))
        conn.commit()

    # Keep the FTS index in sync at the DATABASE level via triggers, so it stays
    # correct no matter which process or code path writes a row. The backend
    # writes via the SQLAlchemy ORM and the engine writes via raw `text()` SQL;
    # ORM event listeners only covered the former, silently leaving every
    # engine-discovered asset out of the index. Triggers cover both.
    #
    # The JSON columns (dns_records, technologies, crawled_urls) are indexed as
    # their raw JSON text. FTS5's default unicode61 tokenizer treats brackets,
    # quotes and commas as separators, so '["nginx","apache"]' tokenizes to the
    # same terms as the previous comma-joined format — searches are unaffected.
    _FTS_COLUMNS = (
        "asset_id, hostname, dns_records, technologies, "
        "status_code, title, content_length, urls"
    )
    _FTS_NEW_VALUES = (
        "new.id, new.asset, "
        "COALESCE(new.dns_records, ''), COALESCE(new.technologies, ''), "
        "COALESCE(new.status_code, ''), COALESCE(new.title, ''), "
        "COALESCE(new.content_length, ''), COALESCE(new.crawled_urls, '')"
    )
    with engine.connect() as conn:
        # Drop legacy/prior triggers first so re-running init_db is idempotent.
        for trig in ("assets_ai", "assets_au", "assets_ad"):
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trig}"))
        conn.execute(text(
            f"CREATE TRIGGER assets_ai AFTER INSERT ON assets BEGIN "
            f"INSERT INTO asset_fts({_FTS_COLUMNS}) VALUES ({_FTS_NEW_VALUES}); END"
        ))
        conn.execute(text(
            f"CREATE TRIGGER assets_au AFTER UPDATE ON assets BEGIN "
            f"DELETE FROM asset_fts WHERE asset_id = old.id; "
            f"INSERT INTO asset_fts({_FTS_COLUMNS}) VALUES ({_FTS_NEW_VALUES}); END"
        ))
        conn.execute(text(
            "CREATE TRIGGER assets_ad AFTER DELETE ON assets BEGIN "
            "DELETE FROM asset_fts WHERE asset_id = old.id; END"
        ))
        conn.commit()

        # Backfill: (re)build the index from existing rows whenever it is empty,
        # using the exact same projection the triggers use so old and new rows
        # are byte-for-byte consistent.
        existing_count = conn.execute(text("SELECT COUNT(*) FROM asset_fts")).scalar()
        if existing_count == 0:
            conn.execute(text(
                f"INSERT INTO asset_fts({_FTS_COLUMNS}) "
                f"SELECT id, asset, COALESCE(dns_records, ''), COALESCE(technologies, ''), "
                f"COALESCE(status_code, ''), COALESCE(title, ''), "
                f"COALESCE(content_length, ''), COALESCE(crawled_urls, '') FROM assets"
            ))
            conn.commit()

    db = SessionLocal()
    try:
        from services.vuln_pattern_service import seed_defaults
        seed_defaults(db)
    finally:
        db.close()
