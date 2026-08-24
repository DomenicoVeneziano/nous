# backend/schemas/scan.py
from pydantic import BaseModel, field_serializer
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

    # The scan job config holds proxy URLs of the form
    # scheme://user:password@host:port. /scans/queue and /scans/history are
    # viewer-readable, so the raw config would hand the proxy credentials to
    # every viewer-role user. Replace the URLs with a non-secret marker that
    # still tells a client a proxy was in use.
    @field_serializer("config")
    def _mask_proxy_urls(self, config: dict | None) -> dict | None:
        if not config:
            return config
        if not any(k in config for k in ("proxy_url", "retry_proxy_url")):
            return config
        # Shallow copy: the input may be the live ORM attribute and must not be
        # mutated, or the masked value would be written back to the row.
        masked = dict(config)
        for key in ("proxy_url", "retry_proxy_url"):
            if key in masked:
                masked[key] = "configured"
        return masked

    model_config = {"from_attributes": True}
