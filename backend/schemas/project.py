# backend/schemas/project.py
from pydantic import BaseModel, Field
from datetime import datetime


# A scope entry can be a CIDR, and each expands into one asset per address, so
# an unbounded entry list is an unbounded amount of work. The count is capped
# here — a 422 before anything is parsed — and the addresses they expand to are
# capped separately by asset_service.MAX_CIDR_HOSTS_TOTAL.
MAX_SCOPE_ENTRIES = 1000


class ProjectCreate(BaseModel):
    title: str
    description: str | None = None
    root_domains: list[str] = Field(max_length=MAX_SCOPE_ENTRIES)
    subdomains: list[str] = []


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    root_domains: list[str] | None = Field(default=None, max_length=MAX_SCOPE_ENTRIES)
    subdomains: list[str] | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    id: str
    title: str
    description: str | None
    icon: str | None
    logo_path: str | None
    root_domains: list[str]
    subdomains: list[str]
    status: str
    last_scan_date: datetime | None
    last_scan_duration_s: float | None
    asset_count: int
    tech_count: int
    is_master: bool

    model_config = {"from_attributes": True}


class BulkProjectAction(BaseModel):
    project_ids: list[str]
