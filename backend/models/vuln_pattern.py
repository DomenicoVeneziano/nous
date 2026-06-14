# backend/models/vuln_pattern.py
from sqlalchemy import Column, String, Boolean, DateTime, JSON
from database import Base
import uuid
from datetime import datetime, timezone


class VulnPattern(Base):
    __tablename__ = "vuln_patterns"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False)
    checks      = Column(JSON, nullable=False)  # [{field, regex}]
    is_default  = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
