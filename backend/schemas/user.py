# backend/schemas/user.py
from pydantic import BaseModel
from typing import Literal


class UserCreate(BaseModel):
    username: str
    password: str
    role: Literal["admin", "viewer"] = "viewer"


class UserUpdate(BaseModel):
    username: str | None = None
    role: Literal["admin", "viewer"] | None = None
    password: str | None = None


class UserOut(BaseModel):
    id: str
    username: str
    role: str

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
