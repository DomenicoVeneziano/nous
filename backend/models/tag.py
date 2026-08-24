# backend/models/tag.py
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Table, UniqueConstraint,
)
from database import Base
import uuid
from datetime import datetime, timezone

# Source tags written by the engine, one per discovery path. They are created
# with is_system=True, which makes them read-only over the API: provenance is an
# observation, not a label the operator curates. Source tags accumulate and are
# never removed automatically.
SOURCE_PASSIVE = "Passive"
SOURCE_BRUTEFORCE = "Bruteforce"
SOURCE_PERMUTATIONS = "Permutations"
SOURCE_CRAWLING = "Crawling"
SOURCE_REDIRECT = "Redirect"
SOURCE_MANUAL = "Manual"
SOURCE_SEED = "Seed"

# Vantage-point tag, not a discovery source: it records that the STORED scan
# result for an asset came from a proxied pass. Unlike the SOURCE_* tags it is
# removed automatically when a later direct pass succeeds for that asset.
SYSTEM_TAG_PROXIED = "Proxied"

# Every name the API refuses to let an operator create, rename, delete, or
# hand-attach. Membership buys exactly that; discovery-source attribution is
# driven by the individual SOURCE_* constants, not by this tuple.
SYSTEM_TAG_NAMES = (
    SOURCE_PASSIVE, SOURCE_BRUTEFORCE, SOURCE_PERMUTATIONS, SOURCE_CRAWLING,
    SOURCE_REDIRECT, SOURCE_MANUAL, SOURCE_SEED,
    SYSTEM_TAG_PROXIED,
)

# "New!" is never stored. It is derived per request by comparing an asset's
# first_seen_scan_id to the project's most recent recon job, so a cancelled or
# failed rescan cannot wipe the previous run's markers. Reserved here so an
# operator cannot create a user tag that impersonates it.
DERIVED_NEW_TAG = "New!"


# Plain Core table rather than a mapped class: Asset.tags uses it as a
# `secondary`, and a second mapper over the same rows would make SQLAlchemy warn
# about overlapping relationships on every write.
asset_tags = Table(
    "asset_tags",
    Base.metadata,
    Column("asset_id", String, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_tags_project_name"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)  # #rrggbb, or NULL to use the default chip colour
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
