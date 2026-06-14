# backend/schemas/project.py
from pydantic import BaseModel
from datetime import datetime


class ProjectCreate(BaseModel):
    title: str
    description: str | None = None
    root_domains: list[str]
    subdomains: list[str] = []


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    root_domains: list[str] | None = None
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
