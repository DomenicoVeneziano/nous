# backend/models/api_key.py
from sqlalchemy import Column, String, DateTime, Boolean
from database import Base
import uuid
from datetime import datetime, timezone


class ApiKey(Base):
    __tablename__ = "api_keys"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id      = Column(String, nullable=False, index=True)
    name         = Column(String, nullable=False)
    key_type     = Column(String, nullable=False)               # "edit" | "view"
    key_prefix   = Column(String, nullable=False)               # first 15 chars for UI display
    key_hash     = Column(String, nullable=False, unique=True)  # SHA-256 hex of full key
    created_at   = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)
    is_active    = Column(Boolean, nullable=False, default=True)
