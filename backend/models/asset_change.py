# backend/models/asset_change.py
from sqlalchemy import Column, String, DateTime, Index
from database import Base
import uuid
from datetime import datetime, timezone


# One row per changed field per write: a scan that rewrites three fields on an
# asset leaves three rows behind, not one. For the set-valued fields
# (technologies, dns_records) the pair is a delta rather than a before/after —
# old_value is a JSON array of the REMOVED entries and new_value a JSON array of
# the ADDED ones, so a rewrite that only appends records nothing under
# old_value. Every other field is scalar: both columns hold the plain text value,
# or SQL NULL where the field was unset on that side.
class AssetChange(Base):
    __tablename__ = "asset_changes"
    __table_args__ = (
        Index("ix_asset_changes_asset_time", "asset_id", "changed_at"),
        Index("ix_asset_changes_project_scan", "project_id", "scan_id"),
    )

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False)
    asset_id   = Column(String, nullable=False)
    scan_id    = Column(String, nullable=True)
    field      = Column(String, nullable=False)
    old_value  = Column(String, nullable=True)
    new_value  = Column(String, nullable=True)
    # Naive UTC, like the rest of the schema. The engine writes this column as
    # raw SQL in the naive '%Y-%m-%d %H:%M:%S.%f' form; an offset-aware value
    # collates ahead of every naive row and would quietly reorder the history.
    changed_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
