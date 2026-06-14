# backend/models/app_setting.py
from sqlalchemy import Column, String
from database import Base


class AppSetting(Base):
    """Generic key/value store for persisted application settings (e.g. proxy config)."""
    __tablename__ = "app_settings"

    key   = Column(String, primary_key=True)
    value = Column(String, nullable=True)  # stored as a string; coerced on load
