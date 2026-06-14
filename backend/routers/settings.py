# backend/routers/settings.py
import socket
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from pathlib import Path
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.user import UserCreate, UserUpdate, UserOut
from models.user import User
from config import settings as _cfg
from services.settings_store import (
    ALLOWED_SCHEMES, get_proxy_settings, save_proxy_settings,
)
import uuid

_ALLOWED_PATH_BASES = tuple(
    base.resolve()
    for base in (_cfg.DATA_DIR / "wordlists", _cfg.DATA_DIR / "resolvers")
)


def _validate_file_path(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        resolved = Path(value).resolve()
    except (OSError, ValueError):
        raise ValueError("Invalid path")
    if not any(resolved.is_relative_to(base) for base in _ALLOWED_PATH_BASES):
        raise ValueError(f"Path must be within {[str(b) for b in _ALLOWED_PATH_BASES]}")
    return value


class ScanConfigUpdate(BaseModel):
    recon_timeout: int | None = None
    tech_timeout: int | None = None
    crawl_timeout: int | None = None
    crawl_max_pages: int | None = None
    wordlist_path: str | None = None
    resolvers_path: str | None = None
    dns_bruteforce_enabled: bool | None = None
    tech_screenshots_enabled: bool | None = None
    tech_rate_limit_delay: float | None = None
    dns_rate_limit_delay: float | None = None
    crawl_rate_limit_delay: float | None = None

    @field_validator("wordlist_path", "resolvers_path", mode="before")
    @classmethod
    def validate_paths(cls, v):
        return _validate_file_path(v)


class ProxyConfigUpdate(BaseModel):
    enabled: bool | None = None
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    recon: bool | None = None
    tech: bool | None = None
    crawl: bool | None = None

    @field_validator("scheme")
    @classmethod
    def validate_scheme(cls, v):
        if v is not None and v not in ALLOWED_SCHEMES:
            raise ValueError(f"scheme must be one of {ALLOWED_SCHEMES}")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v):
        if v is not None and not (1 <= v <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v):
        if v is not None and (" " in v or "/" in v):
            raise ValueError("host must be a bare hostname or IP (no scheme or path)")
        return v


class ProxyTestRequest(BaseModel):
    host: str
    port: int


router = APIRouter(prefix="/settings", tags=["settings"])


# --- Scan config ---

@router.get("/scan-config")
def get_scan_config(_: dict = Depends(require_viewer)):
    from config import settings
    return {
        "recon_timeout": settings.RECON_TIMEOUT,
        "tech_timeout": settings.TECH_TIMEOUT,
        "crawl_timeout": settings.CRAWL_TIMEOUT,
        "crawl_max_pages": settings.CRAWL_MAX_PAGES,
        "wordlist_path": str(settings.WORDLIST_PATH),
        "resolvers_path": str(settings.RESOLVERS_PATH),
        "dns_bruteforce_enabled": settings.DNS_BRUTEFORCE_ENABLED,
        "tech_screenshots_enabled": settings.TECH_SCREENSHOTS_ENABLED,
        "tech_rate_limit_delay": settings.TECH_RATE_LIMIT_DELAY,
        "dns_rate_limit_delay": settings.DNS_RATE_LIMIT_DELAY,
        "crawl_rate_limit_delay": settings.CRAWL_RATE_LIMIT_DELAY,
    }


@router.put("/scan-config")
def update_scan_config(data: ScanConfigUpdate, _: dict = Depends(require_admin)):
    from config import settings as cfg
    from pathlib import Path
    updated = {}
    if data.recon_timeout is not None:
        cfg.RECON_TIMEOUT = data.recon_timeout
        updated["recon_timeout"] = data.recon_timeout
    if data.tech_timeout is not None:
        cfg.TECH_TIMEOUT = data.tech_timeout
        updated["tech_timeout"] = data.tech_timeout
    if data.crawl_timeout is not None:
        cfg.CRAWL_TIMEOUT = data.crawl_timeout
        updated["crawl_timeout"] = data.crawl_timeout
    if data.crawl_max_pages is not None:
        cfg.CRAWL_MAX_PAGES = data.crawl_max_pages
        updated["crawl_max_pages"] = data.crawl_max_pages
    if data.wordlist_path is not None:
        cfg.WORDLIST_PATH = Path(data.wordlist_path)
        updated["wordlist_path"] = data.wordlist_path
    if data.resolvers_path is not None:
        cfg.RESOLVERS_PATH = Path(data.resolvers_path)
        updated["resolvers_path"] = data.resolvers_path
    if data.dns_bruteforce_enabled is not None:
        cfg.DNS_BRUTEFORCE_ENABLED = data.dns_bruteforce_enabled
        updated["dns_bruteforce_enabled"] = data.dns_bruteforce_enabled
    if data.tech_screenshots_enabled is not None:
        cfg.TECH_SCREENSHOTS_ENABLED = data.tech_screenshots_enabled
        updated["tech_screenshots_enabled"] = data.tech_screenshots_enabled
    if data.tech_rate_limit_delay is not None:
        cfg.TECH_RATE_LIMIT_DELAY = data.tech_rate_limit_delay
        updated["tech_rate_limit_delay"] = data.tech_rate_limit_delay
    if data.dns_rate_limit_delay is not None:
        cfg.DNS_RATE_LIMIT_DELAY = data.dns_rate_limit_delay
        updated["dns_rate_limit_delay"] = data.dns_rate_limit_delay
    if data.crawl_rate_limit_delay is not None:
        cfg.CRAWL_RATE_LIMIT_DELAY = data.crawl_rate_limit_delay
        updated["crawl_rate_limit_delay"] = data.crawl_rate_limit_delay
    return {"updated": updated}


# --- Proxy config ---

@router.get("/proxy-config")
def get_proxy_config(_: dict = Depends(require_viewer)):
    return get_proxy_settings()


@router.put("/proxy-config")
def update_proxy_config(data: ProxyConfigUpdate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    values = data.model_dump(exclude_none=True)
    # Guard against enabling the proxy without a host configured.
    will_be_enabled = values.get("enabled", _cfg.PROXY_ENABLED)
    effective_host = values.get("host", _cfg.PROXY_HOST)
    if will_be_enabled and not (effective_host or "").strip():
        raise HTTPException(400, "Proxy host is required when the proxy is enabled")
    save_proxy_settings(db, values)
    return get_proxy_settings()


@router.post("/proxy-config/test")
def test_proxy_config(data: ProxyTestRequest, _: dict = Depends(require_admin)):
    """Best-effort TCP reachability check against the proxy endpoint."""
    if not (1 <= data.port <= 65535):
        raise HTTPException(400, "port must be between 1 and 65535")
    host = data.host.strip()
    if not host:
        raise HTTPException(400, "host is required")
    try:
        with socket.create_connection((host, data.port), timeout=5):
            return {"reachable": True, "message": f"Connected to {host}:{data.port}"}
    except OSError as e:
        return {"reachable": False, "message": f"Could not connect: {e}"}


# --- User management ---

@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    return db.query(User).order_by(User.username).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username already exists")
    user = User(id=str(uuid.uuid4()), username=data.username, role=data.role)
    user.set_password(data.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, data: UserUpdate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if data.username is not None:
        existing = db.query(User).filter(User.username == data.username, User.id != user_id).first()
        if existing:
            raise HTTPException(400, "Username already exists")
        user.username = data.username
    if data.role is not None:
        user.role = data.role
    if data.password is not None:
        user.set_password(data.password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
