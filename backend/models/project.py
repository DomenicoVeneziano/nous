# backend/models/project.py
from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, JSON
from database import Base
import uuid


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    icon = Column(String, nullable=True)  # emoji or icon identifier
    logo_path = Column(String, nullable=True)
    root_domains = Column(JSON, nullable=False, default=list)
    subdomains = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="to_scan")  # to_scan | scanning | scanned
    last_scan_date = Column(DateTime, nullable=True)
    last_scan_duration_s = Column(Float, nullable=True)
    asset_count = Column(Integer, nullable=False, default=0)
    tech_count = Column(Integer, nullable=False, default=0)
    is_master = Column(Boolean, nullable=False, default=False)

    # Recurring scan schedule. Every datetime here is naive UTC, matching the
    # rest of the schema (see the normalization block in database.py) — writes go
    # through services.schedule_service.utc_now() so nothing offset-aware reaches
    # SQLite.
    schedule_enabled = Column(Boolean, nullable=False, default=False)
    schedule_interval_value = Column(Integer, nullable=True)
    schedule_interval_unit = Column(String, nullable=True)  # hours | days | weeks | months
    # none_as_null on both nullable JSON columns below is load-bearing, not
    # tidiness: the default maps Python None to the JSON text 'null', which the
    # ORM reads back as None but SQL sees as a non-NULL value. The scheduler
    # decides whether a cycle is in flight with a plain IS NOT NULL test, so a
    # 'null' string there reads as a cycle that never ends.
    schedule_phases = Column(JSON(none_as_null=True), nullable=True)  # subset of recon | tech | crawl, canonical order
    # NULL means "not due": either the schedule is off, or a cycle is already in
    # flight and the next due time is only known once that cycle closes. No
    # single-column index here — ix_projects_schedule_due (database.py) leads
    # with schedule_enabled and already serves the due-project poll, and a second
    # index would only be maintained on every project write.
    next_scan_at = Column(DateTime, nullable=True)
    schedule_cycle_job_ids = Column(JSON(none_as_null=True), nullable=True)  # non-NULL => cycle in flight
    schedule_cycle_started_at = Column(DateTime, nullable=True)
    schedule_last_run_at = Column(DateTime, nullable=True)  # last cycle completion

    @property
    def schedule_cycle_active(self) -> bool:
        return bool(self.schedule_cycle_job_ids)
