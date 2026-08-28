# backend/routers/settings.py
import re
import socket
from typing import Any, Literal
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
    get_notification_settings, save_notification_settings, validate_webhook_url,
    NOTIFY_SECRET_API_FIELDS,
)
from services.notifications import send_test
# The Telegram bot token is placed in a URL path by the sender, which owns the
# canonical shape check. It is imported rather than restated so the router can
# never accept a token the sender would refuse.
from services.notifications.sender import TELEGRAM_TOKEN_RE
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
    dns_wordlist_expansion_enabled: bool | None = None
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
    retries: bool | None = None

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


# A chat id is either a numeric id (possibly negative, for groups) or an @name.
_TELEGRAM_CHAT_ID_RE = re.compile(r"^(-?[0-9]{1,32}|@[A-Za-z0-9_]{5,32})$")


class NotificationConfigUpdate(BaseModel):
    """Update payload for the notification config.

    The credential-bearing fields are typed `Any` on purpose. A Pydantic
    validation error carries the offending value in its `input` key, and that
    error list becomes the 422 response body, so a field validator rejecting a
    malformed webhook URL or bot token would echo the submitted secret straight
    back into the response and into any log that records it. Their shape is
    checked instead by `_validated_notification_strings`, which raises an
    HTTPException naming the field and the fault without the value.
    """
    enabled: bool | None = None
    on_success: bool | None = None
    on_failure: bool | None = None
    slack_enabled: bool | None = None
    slack_webhook_url: Any = None
    discord_enabled: bool | None = None
    discord_webhook_url: Any = None
    webhook_enabled: bool | None = None
    webhook_url: Any = None
    webhook_token: Any = None
    telegram_enabled: bool | None = None
    telegram_bot_token: Any = None
    telegram_chat_id: Any = None
    sample_size: int | None = None
    timeout_seconds: int | None = None
    retries: int | None = None
    clear_secrets: list[str] | None = None

    @field_validator("sample_size")
    @classmethod
    def validate_sample_size(cls, v):
        if v is not None and not (0 <= v <= 20):
            raise ValueError("sample_size must be between 0 and 20")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, v):
        if v is not None and not (1 <= v <= 30):
            raise ValueError("timeout_seconds must be between 1 and 30")
        return v

    @field_validator("retries")
    @classmethod
    def validate_retries(cls, v):
        if v is not None and not (0 <= v <= 5):
            raise ValueError("retries must be between 0 and 5")
        return v


class NotificationTestRequest(BaseModel):
    """Names a channel and nothing else: a secret here would land in an access log."""
    channel: Literal["slack", "discord", "webhook", "telegram"]


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
        "dns_wordlist_expansion_enabled": settings.DNS_WORDLIST_EXPANSION_ENABLED,
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
    if data.dns_wordlist_expansion_enabled is not None:
        cfg.DNS_WORDLIST_EXPANSION_ENABLED = data.dns_wordlist_expansion_enabled
        updated["dns_wordlist_expansion_enabled"] = data.dns_wordlist_expansion_enabled
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


# --- Notification config ---

# Channel -> (enable flag, credentials it cannot be enabled without). Each
# credential is named by its API field. Whether a SECRET one is already stored
# is read from its "<field>_set" boolean, never from the secret itself;
# telegram_chat_id is not a secret and is read back directly.
_NOTIFY_CHANNEL_REQUIREMENTS = {
    "slack_enabled": ("Slack", ("slack_webhook_url",)),
    "discord_enabled": ("Discord", ("discord_webhook_url",)),
    "webhook_enabled": ("Webhook", ("webhook_url",)),
    "telegram_enabled": ("Telegram", ("telegram_bot_token", "telegram_chat_id")),
}


def _check_webhook_url(value: str) -> None:
    validate_webhook_url(value)


def _check_bot_token(value: str) -> None:
    if not TELEGRAM_TOKEN_RE.match(value):
        raise ValueError("must look like 123456:AA... (digits, a colon, then the secret)")


def _check_chat_id(value: str) -> None:
    if not _TELEGRAM_CHAT_ID_RE.match(value):
        raise ValueError("must be a numeric id or an @username")


# Free-text notification fields, with the check each one's value must pass.
# `None` means any non-empty string is acceptable (a bearer token has no shape).
_NOTIFY_STRING_CHECKS = {
    "slack_webhook_url": _check_webhook_url,
    "discord_webhook_url": _check_webhook_url,
    "webhook_url": _check_webhook_url,
    "webhook_token": None,
    "telegram_bot_token": _check_bot_token,
    "telegram_chat_id": _check_chat_id,
}


def _validated_notification_strings(values: dict) -> None:
    """Check the shape of every free-text notification field that was supplied.

    Raises a 422 whose detail is a plain sentence naming the field and the
    fault. The value itself is never included: these carry webhook URLs and bot
    tokens, and a 422 body is echoed into access and error logs. This is why the
    checks live here rather than in a Pydantic field validator, whose error dict
    would carry the submitted value in its `input` key.

    A blank string is left to the save layer, which reads it as "keep the stored
    secret" for a secret field and as "erase this" for a plain one.
    """
    for field, check in _NOTIFY_STRING_CHECKS.items():
        if field not in values:
            continue
        value = values[field]
        if not isinstance(value, str):
            raise HTTPException(422, f"{field} must be a string")
        if not value.strip():
            continue
        if check is None:
            continue
        try:
            check(value)
        except ValueError as e:
            raise HTTPException(422, f"{field}: {e}") from None


def _notify_credential_present(field: str, values: dict, current: dict, cleared: set) -> bool:
    """True if `field` will hold a value once this request is saved.

    The two field families answer this differently, and the answer must match
    what save_notification_settings actually does:

    * a secret is write-only, so a blank or absent one keeps whatever is stored;
      only `clear_secrets` erases it.
    * a plain field (telegram_chat_id) is overwritten by whatever is supplied,
      so a supplied blank erases it and this returns False -- otherwise a
      request could enable a channel on the strength of a stored value it wipes
      in the same save.
    """
    supplied = values.get(field)
    if field not in NOTIFY_SECRET_API_FIELDS:
        if field in values:
            return bool(supplied) and bool(str(supplied).strip())
        return bool((current.get(field) or "").strip())
    if isinstance(supplied, str) and supplied.strip():
        return True
    if field in cleared:
        return False
    if f"{field}_set" in current:
        return bool(current[f"{field}_set"])
    return bool((current.get(field) or "").strip())


@router.get("/notification-config")
def get_notification_config(_: dict = Depends(require_viewer)):
    return get_notification_settings()


@router.put("/notification-config")
def update_notification_config(
    data: NotificationConfigUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    values = data.model_dump(exclude_none=True)
    _validated_notification_strings(values)
    current = get_notification_settings()
    # Mirrors the save layer, which ignores names that are not secret fields.
    cleared = {
        name for name in (values.get("clear_secrets") or [])
        if isinstance(name, str) and name.lower() in NOTIFY_SECRET_API_FIELDS
    }
    # Mirrors the proxy's "host required when enabled": a channel cannot be
    # turned on unless its credential arrives here or is already stored.
    for flag, (label, required) in _NOTIFY_CHANNEL_REQUIREMENTS.items():
        if not values.get(flag, current.get(flag)):
            continue
        missing = [
            field for field in required
            if not _notify_credential_present(field, values, current, cleared)
        ]
        if missing:
            raise HTTPException(
                400,
                f"{label} notifications require {', '.join(missing)} to be configured"
                " — set a value or turn the channel off",
            )
    save_notification_settings(db, values)
    return get_notification_settings()


@router.post("/notification-config/test")
async def test_notification_config(
    data: NotificationTestRequest,
    _: dict = Depends(require_admin),
):
    """Send a synthetic event to one channel using the stored credentials.

    A delivery failure is a result, not an error: it comes back as ok=false so
    the caller can show the reason without a 500.
    """
    ok, message = await send_test(data.channel)
    return {"ok": ok, "message": message}


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
