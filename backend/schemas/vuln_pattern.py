# backend/schemas/vuln_pattern.py
from pydantic import BaseModel, Field
from datetime import datetime


class VulnPatternCheck(BaseModel):
    field: str
    regex: str


class VulnPatternCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-z0-9_]+$')
    description: str = Field(..., min_length=1, max_length=256)
    checks: list[VulnPatternCheck] = Field(..., min_length=1)


class VulnPatternUpdate(BaseModel):
    description: str | None = Field(None, min_length=1, max_length=256)
    checks: list[VulnPatternCheck] | None = Field(None, min_length=1)


class VulnPatternOut(BaseModel):
    id: str
    name: str
    description: str
    checks: list[VulnPatternCheck]
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VulnPatternTestResult(BaseModel):
    pattern_id: str
    pattern_name: str
    match_count: int
    matched_asset_ids: list[str]
