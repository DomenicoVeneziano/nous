# backend/schemas/asset_change.py
from pydantic import BaseModel
from datetime import datetime


class AssetChangeOut(BaseModel):
    id: str
    asset_id: str
    project_id: str
    scan_id: str | None
    field: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime

    model_config = {"from_attributes": True}


# next_cursor is the opaque key of the last item on this page, or null once the
# history is exhausted — the caller pages by echoing it back, never by offset.
class AssetChangePage(BaseModel):
    items: list[AssetChangeOut]
    next_cursor: str | None
