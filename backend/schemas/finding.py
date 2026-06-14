# backend/schemas/finding.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

Severity = Literal["informative", "low", "medium", "high", "critical"]


class FindingCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    severity: Severity
    body: str = ""


class FindingUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    severity: Severity | None = None
    body: str | None = None


class FindingOut(BaseModel):
    id: str
    asset_id: str
    project_id: str
    title: str
    severity: str
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
