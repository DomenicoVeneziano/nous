# backend/routers/api_keys.py
import secrets
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth.middleware import require_viewer
from models.api_key import ApiKey
from schemas.api_key import ApiKeyCreate, ApiKeyRename, ApiKeyOut, ApiKeyCreated

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

_KEY_PREFIX = "nous_"
_KEY_RANDOM_BYTES = 32   # 64 hex chars; total key length = 5 + 64 = 69 chars
_DISPLAY_CHARS = 13      # "nous_" (5) + first 8 hex chars


def _generate_key() -> tuple[str, str, str]:
    """Return (full_key, key_prefix, key_hash)."""
    raw    = secrets.token_hex(_KEY_RANDOM_BYTES)
    full   = _KEY_PREFIX + raw
    prefix = full[:_DISPLAY_CHARS]
    digest = hashlib.sha256(full.encode()).hexdigest()
    return full, prefix, digest


@router.post("/", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    data: ApiKeyCreate,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_viewer),
):
    if data.key_type == "edit" and claims["role"] != "admin":
        raise HTTPException(403, "Only admin users can create edit keys")

    full_key, prefix, digest = _generate_key()

    key = ApiKey(
        user_id    = claims["sub"],
        name       = data.name,
        key_type   = data.key_type,
        key_prefix = prefix,
        key_hash   = digest,
        is_active  = True,
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    out = ApiKeyOut.model_validate(key)
    return ApiKeyCreated(**out.model_dump(), full_key=full_key)


@router.get("/", response_model=list[ApiKeyOut])
def list_api_keys(
    db: Session = Depends(get_db),
    claims: dict = Depends(require_viewer),
):
    return (
        db.query(ApiKey)
        .filter(ApiKey.user_id == claims["sub"], ApiKey.is_active == True)
        .order_by(ApiKey.created_at.desc())
        .all()
    )


@router.patch("/{key_id}", response_model=ApiKeyOut)
def rename_api_key(
    key_id: str,
    data: ApiKeyRename,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_viewer),
):
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.user_id == claims["sub"],
        ApiKey.is_active == True,
    ).first()
    if not key:
        raise HTTPException(404, "API key not found")
    key.name = data.name
    db.commit()
    db.refresh(key)
    return key


@router.delete("/{key_id}", status_code=204)
def delete_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_viewer),
):
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.user_id == claims["sub"],
    ).first()
    if not key:
        raise HTTPException(404, "API key not found")
    db.delete(key)
    db.commit()
