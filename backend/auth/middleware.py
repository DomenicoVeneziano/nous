# backend/auth/middleware.py
import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from auth.jwt import verify_jwt
from database import get_db

# auto_error=False so FastAPI doesn't reject requests that use X-API-Key instead of Bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Minimum seconds between last_used_at writes for a given key. Without this every
# authenticated request issues a write + commit, amplifying SQLite lock contention
# and turning read traffic into write traffic.
_LAST_USED_THROTTLE_SECONDS = 60


def _should_touch_last_used(last_used_at) -> bool:
    """True if last_used_at is unset or older than the throttle window."""
    if last_used_at is None:
        return True
    # Stored values are naive UTC (SQLite DateTime); compare in UTC.
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_used_at).total_seconds() >= _LAST_USED_THROTTLE_SECONDS


def _lookup_api_key(raw_key: str, db: Session) -> dict:
    """
    Validate a raw API key string against the database.
    Returns a {sub, role} claims dict or raises HTTP 401.
    Role is derived from the key's key_type DB field — never from request input.
    """
    from models.api_key import ApiKey  # local import avoids circular at module load

    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    row = db.query(ApiKey).filter(
        ApiKey.key_hash == digest,
        ApiKey.is_active == True,
    ).first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # best-effort audit timestamp — throttled so we don't write on every request,
    # and never allowed to fail the auth path
    if _should_touch_last_used(row.last_used_at):
        try:
            row.last_used_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()

    # Map key_type → role, preserving the {sub, role} claims shape invariant
    role = "admin" if row.key_type == "edit" else "viewer"
    return {"sub": row.user_id, "role": role}


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> dict:
    """
    Accepts three credential forms (checked in this order):
      1. Authorization: Bearer nous_<hex>   → API key (Bearer header)
      2. Authorization: Bearer <jwt>        → JWT
      3. X-API-Key: nous_<hex>             → API key (dedicated header)

    Returns a {sub, role} claims dict. Role is always sourced from a
    verified credential — JWT payload or DB row — never from request fields.
    """
    if token is not None:
        if token.startswith("nous_"):
            return _lookup_api_key(token, db)
        # Standard JWT path — verify_jwt() is the sole JWT verifier (invariant #1)
        try:
            return verify_jwt(token)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    api_key_header = request.headers.get("X-API-Key")
    if api_key_header and api_key_header.startswith("nous_"):
        return _lookup_api_key(api_key_header, db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(claims: dict = Depends(get_current_user)) -> dict:
    if claims["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return claims


def require_viewer(claims: dict = Depends(get_current_user)) -> dict:
    return claims
