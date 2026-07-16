# backend/models/asset.py
from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, UniqueConstraint
from database import Base
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
    date_scanned = Column(DateTime, nullable=True)
    manually_inserted = Column(Boolean, nullable=False, default=False)

# NOTE: FTS index synchronisation is handled by SQLite triggers created in
# database.py (assets_ai / assets_au / assets_ad), NOT by SQLAlchemy ORM events.
# Triggers fire regardless of which process or access path writes the row, so the
# engine's raw `text()` writes stay indexed too. Do not reintroduce ORM event
# listeners here — they would double-insert alongside the triggers.
