# backend/models/finding.py
from sqlalchemy import Column, String, DateTime
from database import Base
import uuid
from datetime import datetime, timezone


class Finding(Base):
    __tablename__ = "findings"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_id   = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=False, index=True)
    title      = Column(String, nullable=False)
    severity   = Column(String, nullable=False)  # informative|low|medium|high|critical
    body       = Column(String, nullable=False, default="")  # markdown text
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
