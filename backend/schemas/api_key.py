# backend/schemas/api_key.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    key_type: Literal["edit", "view"]


class ApiKeyRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_type: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    full_key: str  # shown exactly once at creation, never stored in DB
