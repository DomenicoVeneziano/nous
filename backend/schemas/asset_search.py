# backend/schemas/asset_search.py
from pydantic import BaseModel
from schemas.asset import AssetOut


class Highlight(BaseModel):
    field: str       # user-queried field (e.g. "tech", "vuln", "body")
    source: str      # concrete field the span lives in (same as field, except for "vuln")
    snippet: str     # short text around the match (or full value for small fields)
    start: int       # start offset of the match inside `snippet`
    end: int         # end offset of the match inside `snippet` (exclusive)
    index: int | None = None  # list index for list-valued fields (technologies, crawled_urls, dns_records)


class AssetSearchOut(AssetOut):
    highlights: list[Highlight] = []
