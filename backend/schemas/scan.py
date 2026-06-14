# backend/schemas/scan.py
from pydantic import BaseModel
from datetime import datetime
from typing import Literal


class ScanCreate(BaseModel):
    project_id: str
    scan_type: Literal["recon", "tech", "crawl"]
    asset_ids: list[str] | None = None
    scope_domains: list[str] | None = None  # recon only; null/omit = all root domains


class ScanPositionUpdate(BaseModel):
    queue_pos: int


class ScanOut(BaseModel):
    id: str
    project_id: str
    scan_type: str
    status: str
    queue_pos: int | None
    asset_ids: list[str] | None
    scope_domains: list[str] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_s: float | None
    log_path: str | None
    error_msg: str | None
    config: dict | None = None

    model_config = {"from_attributes": True}
