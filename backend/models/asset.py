# backend/models/asset.py
from sqlalchemy import Column, String, Integer, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
from models.tag import asset_tags  # noqa: F401 — registers the secondary table
import uuid


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("project_id", "asset", name="uq_assets_project_asset"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False, index=True)
    asset = Column(String, nullable=False)  # hostname or IP
    asset_type = Column(String, nullable=False, default="subdomain")  # subdomain | ip
    dns_records = Column(JSON, nullable=False, default=list)
    technologies = Column(JSON, nullable=False, default=list)
    status_code = Column(Integer, nullable=True)
    title = Column(String, nullable=True)
    content_length = Column(Integer, nullable=True)
    redirects_to = Column(String, nullable=True)  # destination host for a cross-host redirect
    response_file_path = Column(String, nullable=True)
    screenshot_path = Column(String, nullable=True)
    crawled_urls = Column(JSON, nullable=False, default=lambda: {"crawling": [], "archived": []})
    date_scanned = Column(DateTime, nullable=True)  # last tech analysis
    first_seen = Column(DateTime, nullable=True)
    # Job that first surfaced this asset. The "New!" badge is derived from it
    # rather than stored, so a cancelled rescan cannot wipe the previous run's
    # markers. NULL for manually added assets and for rows predating tagging.
    first_seen_scan_id = Column(String, nullable=True)
    last_crawl_at = Column(DateTime, nullable=True)
    # Denormalized space-joined tag names. The FTS triggers below fire on
    # `assets` only, so a write to the asset_tags join table would never reindex
    # the row; mirroring the names here means every tag change is an UPDATE on
    # assets, which reindexes for free. Maintained by tag_service.sync_tags_text
    # (backend) and queue_manager.sync_tags_text (engine) — never by hand.
    #
    # server_default mirrors the ALTER TABLE in database.py, which adds this
    # column as `NOT NULL DEFAULT ''`. Without it a fresh CREATE TABLE would emit
    # a bare NOT NULL, so a raw-SQL INSERT that omits the column would succeed on
    # an upgraded database and fail only on a brand-new one.
    tags_text = Column(String, nullable=False, default="", server_default="")

    # Canonical tag order: system (discovery-source) tags first, then name
    # compared case-insensitively. tag_service._NAME_RE limits names to ASCII, so
    # NOCASE here, `name.lower()` in tag_service.ordered_tags, and the frontend's
    # localeCompare agree on every name the API will accept.
    tags = relationship(
        "Tag",
        secondary=asset_tags,
        lazy="selectin",
        order_by="(Tag.is_system.desc(), Tag.name.collate('NOCASE'))",
    )

    # Populated per request by tag_service.decorate_assets; declared here so
    # serialization of an undecorated Asset still resolves the attribute.
    is_new = False


# NOTE: FTS index synchronisation is handled by SQLite triggers created in
# database.py (assets_ai / assets_au / assets_ad), NOT by SQLAlchemy ORM events.
# Triggers fire regardless of which process or access path writes the row, so the
# engine's raw `text()` writes stay indexed too. Do not reintroduce ORM event
# listeners here — they would double-insert alongside the triggers.
