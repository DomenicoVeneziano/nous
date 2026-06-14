# backend/services/settings_store.py
"""
Persistence and helpers for app-level settings that must survive restarts.

Currently this backs the proxy configuration. Values live in the `app_settings`
key/value table and are mirrored onto the in-memory `config.settings` object so
the rest of the app keeps reading from a single source of truth.
"""
from urllib.parse import quote
from sqlalchemy.orm import Session

from models.app_setting import AppSetting
from config import settings as cfg

# Setting key -> python type used to coerce the stored string back to a value.
PROXY_FIELDS: dict[str, type] = {
    "PROXY_ENABLED": bool,
    "PROXY_SCHEME": str,
    "PROXY_HOST": str,
    "PROXY_PORT": int,
    "PROXY_USERNAME": str,
    "PROXY_PASSWORD": str,
    "PROXY_RECON": bool,
    "PROXY_TECH": bool,
    "PROXY_CRAWL": bool,
}

ALLOWED_SCHEMES = ("http", "https", "socks5")

# Maps a scan_type to the per-type "use proxy" flag on config.settings.
_SCAN_TYPE_FLAG = {
    "recon": "PROXY_RECON",
    "tech": "PROXY_TECH",
    "crawl": "PROXY_CRAWL",
}


def _coerce(typ: type, raw: str):
    if typ is bool:
        return str(raw).lower() in ("1", "true", "yes", "on")
    if typ is int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    return raw if raw is not None else ""


def load_proxy_settings(db: Session) -> None:
    """Load persisted proxy values from the DB onto config.settings (called at startup)."""
    rows = db.query(AppSetting).filter(AppSetting.key.in_(PROXY_FIELDS.keys())).all()
    for row in rows:
        typ = PROXY_FIELDS.get(row.key)
        if typ is not None:
            setattr(cfg, row.key, _coerce(typ, row.value))


def save_proxy_settings(db: Session, values: dict) -> None:
    """Persist provided proxy values to the DB and mirror them onto config.settings.

    `values` keys are the lowercase API field names (e.g. "host"); only the
    proxy fields present in `values` are updated.
    """
    for key, typ in PROXY_FIELDS.items():
        api_name = key.removeprefix("PROXY_").lower()
        if api_name not in values or values[api_name] is None:
            continue
        coerced = bool(values[api_name]) if typ is bool else _coerce(typ, values[api_name])
        setattr(cfg, key, coerced)
        if typ is bool:
            stored = "true" if coerced else "false"
        else:
            stored = str(coerced)
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=stored))
        else:
            row.value = stored
    db.commit()


def get_proxy_settings() -> dict:
    """Return the current proxy config from config.settings (password excluded)."""
    return {
        "enabled": cfg.PROXY_ENABLED,
        "scheme": cfg.PROXY_SCHEME,
        "host": cfg.PROXY_HOST,
        "port": cfg.PROXY_PORT,
        "username": cfg.PROXY_USERNAME,
        "password_set": bool(cfg.PROXY_PASSWORD),
        "recon": cfg.PROXY_RECON,
        "tech": cfg.PROXY_TECH,
        "crawl": cfg.PROXY_CRAWL,
    }


def build_proxy_url(include_auth: bool = True) -> str | None:
    """Build a proxy URL from config.settings, or None if proxy is unconfigured.

    Returns e.g. "http://user:pass@127.0.0.1:8080". Credentials are URL-encoded.
    """
    host = (cfg.PROXY_HOST or "").strip()
    if not host or not cfg.PROXY_PORT:
        return None
    scheme = (cfg.PROXY_SCHEME or "http").strip().lower()
    if scheme not in ALLOWED_SCHEMES:
        scheme = "http"
    auth = ""
    if include_auth and cfg.PROXY_USERNAME:
        user = quote(cfg.PROXY_USERNAME, safe="")
        pw = quote(cfg.PROXY_PASSWORD or "", safe="")
        auth = f"{user}:{pw}@" if pw else f"{user}@"
    return f"{scheme}://{auth}{host}:{cfg.PROXY_PORT}"


def proxy_url_for_scan_type(scan_type: str) -> str | None:
    """Return the proxy URL to use for a given scan_type, or None if it should bypass."""
    if not cfg.PROXY_ENABLED:
        return None
    flag = _SCAN_TYPE_FLAG.get(scan_type)
    if not flag or not getattr(cfg, flag, False):
        return None
    return build_proxy_url(include_auth=True)
