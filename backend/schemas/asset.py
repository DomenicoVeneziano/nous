# backend/schemas/asset.py
from pydantic import BaseModel
from datetime import datetime
from typing import Literal


class AssetCreate(BaseModel):
    asset: str
    asset_type: Literal["subdomain", "ip"] = "subdomain"
    manually_inserted: bool = True
    technologies: list[str] | None = None
    status_code: int | None = None
    title: str | None = None
    content_length: int | None = None
    dns_records: list[dict] | None = None
    crawled_urls: list[str] | None = None


class AssetUpdate(BaseModel):
    asset: str | None = None
    asset_type: Literal["subdomain", "ip"] | None = None
    technologies: list[str] | None = None
    status_code: int | None = None
    title: str | None = None
    content_length: int | None = None
    dns_records: list[dict] | None = None
    crawled_urls: list[str] | None = None


class AssetOut(BaseModel):
    id: str
    project_id: str
    asset: str
    asset_type: str
    dns_records: list[dict]
    technologies: list[str]
    status_code: int | None
    title: str | None
    content_length: int | None
    redirects_to: str | None
    response_file_path: str | None
    screenshot_path: str | None
    crawled_urls: list[str]
    date_scanned: datetime | None
    manually_inserted: bool

    model_config = {"from_attributes": True}
