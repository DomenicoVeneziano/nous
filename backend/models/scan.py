# backend/models/scan.py
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON
from database import Base
import uuid
from datetime import datetime, timezone


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False, index=True)
    scan_type = Column(String, nullable=False)  # recon | tech | crawl
    status = Column(String, nullable=False, default="queued")  # queued | running | done | failed | cancelled | timed_out
    queue_pos = Column(Integer, nullable=True)
    asset_ids = Column(JSON, nullable=True)
    scope_domains = Column(JSON, nullable=True)  # list[str] | None — recon only
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_s = Column(Float, nullable=True)
    log_path = Column(String, nullable=True)
    error_msg = Column(String, nullable=True)
    config = Column(JSON, nullable=True)
