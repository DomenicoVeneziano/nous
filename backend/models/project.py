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
