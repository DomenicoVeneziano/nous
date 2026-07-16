# backend/schemas/asset.py
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Literal


def normalize_crawled_urls(value) -> dict:
    """Coerce any stored/legacy shape into the canonical per-source object.

    Accepts:
      * None                      -> empty object
      * list[str] (legacy)        -> {"crawling": [...], "archived": []}
      * dict with any subset      -> both keys present, deduped, order-preserved
    """
    crawling: list[str] = []
    archived: list[str] = []
    if isinstance(value, list):
        crawling = value
    elif isinstance(value, dict):
        crawling = value.get("crawling") or []
        archived = value.get("archived") or []

    def _dedup(items) -> list[str]:
        seen = set()
        out = []
        for item in items:
            s = str(item)
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    return {"crawling": _dedup(crawling), "archived": _dedup(archived)}


class CrawledUrls(BaseModel):
    crawling: list[str] = []
    archived: list[str] = []

    @field_validator("*", mode="before")
    @classmethod
    def _drop_none(cls, v):
        return v or []


class AssetCreate(BaseModel):
    asset: str
    asset_type: Literal["subdomain", "ip"] = "subdomain"
    manually_inserted: bool = True
    technologies: list[str] | None = None
    status_code: int | None = None
    title: str | None = None
    content_length: int | None = None
    dns_records: list[dict] | None = None
    crawled_urls: CrawledUrls | None = None

    @field_validator("crawled_urls", mode="before")
    @classmethod
    def _normalize(cls, v):
        return None if v is None else normalize_crawled_urls(v)


class AssetUpdate(BaseModel):
    asset: str | None = None
    asset_type: Literal["subdomain", "ip"] | None = None
    technologies: list[str] | None = None
    status_code: int | None = None
    title: str | None = None
    content_length: int | None = None
    dns_records: list[dict] | None = None
    crawled_urls: CrawledUrls | None = None

    @field_validator("crawled_urls", mode="before")
    @classmethod
    def _normalize(cls, v):
        return None if v is None else normalize_crawled_urls(v)


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
    crawled_urls: CrawledUrls
    date_scanned: datetime | None
    manually_inserted: bool

    model_config = {"from_attributes": True}

    @field_validator("crawled_urls", mode="before")
    @classmethod
    def _normalize(cls, v):
        return normalize_crawled_urls(v)
