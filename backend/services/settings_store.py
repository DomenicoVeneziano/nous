# backend/services/settings_store.py
"""
Persistence and helpers for app-level settings that must survive restarts.

Currently this backs the proxy and notification configuration. Values live in
the `app_settings` key/value table and are mirrored onto the in-memory
`config.settings` object so the rest of the app keeps reading from a single
source of truth.
"""
from urllib.parse import quote, urlsplit
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
    "PROXY_RETRIES": bool,
}

NOTIFY_FIELDS: dict[str, type] = {
    "NOTIFY_ENABLED": bool,
    "NOTIFY_ON_SUCCESS": bool,
    "NOTIFY_ON_FAILURE": bool,
    "NOTIFY_SLACK_ENABLED": bool,
    "NOTIFY_SLACK_WEBHOOK_URL": str,
    "NOTIFY_DISCORD_ENABLED": bool,
    "NOTIFY_DISCORD_WEBHOOK_URL": str,
    "NOTIFY_WEBHOOK_ENABLED": bool,
    "NOTIFY_WEBHOOK_URL": str,
    "NOTIFY_WEBHOOK_TOKEN": str,
    "NOTIFY_TELEGRAM_ENABLED": bool,
    "NOTIFY_TELEGRAM_BOT_TOKEN": str,
    "NOTIFY_TELEGRAM_CHAT_ID": str,
    "NOTIFY_SAMPLE_SIZE": int,
    "NOTIFY_TIMEOUT_SECONDS": int,
    "NOTIFY_RETRIES": int,
}

# Notification keys whose value is never returned to a client and never logged.
# The read view exposes only a "<field>_set" boolean for each of these.
NOTIFY_SECRET_FIELDS = (
    "NOTIFY_SLACK_WEBHOOK_URL",
    "NOTIFY_DISCORD_WEBHOOK_URL",
    "NOTIFY_WEBHOOK_URL",
    "NOTIFY_WEBHOOK_TOKEN",
    "NOTIFY_TELEGRAM_BOT_TOKEN",
)

# The same five fields under their API names (the setting key lowercased with
# the NOTIFY_ prefix dropped), for callers that speak the API vocabulary.
# Anything NOT in here -- telegram_chat_id in particular -- is a plain field:
# a supplied empty string overwrites the stored value instead of preserving it.
NOTIFY_SECRET_API_FIELDS = tuple(
    key.removeprefix("NOTIFY_").lower() for key in NOTIFY_SECRET_FIELDS
)

# Inclusive (min, max) bounds re-applied on every save AND every load, so a row
# edited directly in the DB can never widen a queue, timeout or retry budget.
NOTIFY_BOUNDS: dict[str, tuple[int, int]] = {
    "NOTIFY_SAMPLE_SIZE": (0, 20),
    "NOTIFY_TIMEOUT_SECONDS": (1, 30),
    "NOTIFY_RETRIES": (0, 5),
}

ALLOWED_SCHEMES = ("http", "https", "socks5")

# Upper bound on a webhook URL, matched to what the delivery targets accept.
MAX_WEBHOOK_URL_LENGTH = 2048

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


def _load_fields(db: Session, fields: dict[str, type]) -> None:
    """Copy the persisted rows for `fields` onto config.settings, coercing each type.

    Keys with no row keep the default declared on config.Settings. The query is
    bounded by the key list, so it never scans the whole table.
    """
    rows = db.query(AppSetting).filter(AppSetting.key.in_(fields.keys())).all()
    for row in rows:
        typ = fields.get(row.key)
        if typ is not None:
            setattr(cfg, row.key, _coerce(typ, row.value))


def _save_fields(db: Session, fields: dict[str, type], prefix: str, values: dict) -> None:
    """Persist the `fields` present in `values` and mirror them onto config.settings.

    `values` keys are the setting key with `prefix` stripped and lowercased
    (e.g. "PROXY_HOST" -> "host"); absent or None entries are left untouched.
    """
    for key, typ in fields.items():
        api_name = key.removeprefix(prefix).lower()
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


def load_proxy_settings(db: Session) -> None:
    """Load persisted proxy values from the DB onto config.settings (called at startup)."""
    _load_fields(db, PROXY_FIELDS)


def save_proxy_settings(db: Session, values: dict) -> None:
    """Persist provided proxy values to the DB and mirror them onto config.settings.

    `values` keys are the lowercase API field names (e.g. "host"); only the
    proxy fields present in `values` are updated.
    """
    _save_fields(db, PROXY_FIELDS, "PROXY_", values)


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
        "retries": cfg.PROXY_RETRIES,
    }


def _clamp_notification_bounds() -> None:
    """Force the bounded notification integers on config.settings back into range."""
    for key, (low, high) in NOTIFY_BOUNDS.items():
        current = getattr(cfg, key, low)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = low
        setattr(cfg, key, max(low, min(high, current)))


def load_notification_settings(db: Session) -> None:
    """Load persisted notification values from the DB onto config.settings (called at startup)."""
    _load_fields(db, NOTIFY_FIELDS)
    _clamp_notification_bounds()


def save_notification_settings(db: Session, values: dict) -> None:
    """Persist provided notification values to the DB and mirror them onto config.settings.

    `values` keys are the lowercase API field names (e.g. "slack_webhook_url");
    only the notification fields present in `values` are updated.

    Secrets are write-only: an omitted or empty-string secret leaves the stored
    value untouched, so a client can round-trip a masked placeholder without
    ever reading the real value back. The only way to erase one is to name it in
    `values["clear_secrets"]`; names that are not secret fields are ignored.

    Non-secret fields follow the opposite rule: a supplied value always
    replaces what is stored, so sending `telegram_chat_id: ""` erases the chat
    id. Callers that guard on a credential being configured must judge
    non-secret fields by what this leaves behind, not by what is stored now.
    """
    clear = values.get("clear_secrets") or []
    if isinstance(clear, str):
        clear = [clear]
    cleared = {
        name for name in clear
        if isinstance(name, str)
        and f"NOTIFY_{name.upper()}" in NOTIFY_SECRET_FIELDS
    }

    to_save: dict = {}
    for key, typ in NOTIFY_FIELDS.items():
        api_name = key.removeprefix("NOTIFY_").lower()
        if key in NOTIFY_SECRET_FIELDS:
            if api_name in cleared:
                to_save[api_name] = ""
                continue
            provided = values.get(api_name)
            # Absent, None or blank all mean "keep whatever is stored".
            if not isinstance(provided, str) or not provided.strip():
                continue
            to_save[api_name] = provided
            continue
        if api_name not in values or values[api_name] is None:
            continue
        value = values[api_name]
        if key in NOTIFY_BOUNDS:
            low, high = NOTIFY_BOUNDS[key]
            coerced = _coerce(int, value)
            value = max(low, min(high, coerced))
        to_save[api_name] = value

    _save_fields(db, NOTIFY_FIELDS, "NOTIFY_", to_save)
    _clamp_notification_bounds()


def get_notification_settings() -> dict:
    """Return the current notification config from config.settings.

    Secret values are never included: each is reported only as a
    "<field>_set" boolean, following the proxy "password_set" precedent.
    """
    _clamp_notification_bounds()
    return {
        "enabled": cfg.NOTIFY_ENABLED,
        "on_success": cfg.NOTIFY_ON_SUCCESS,
        "on_failure": cfg.NOTIFY_ON_FAILURE,
        "slack_enabled": cfg.NOTIFY_SLACK_ENABLED,
        "slack_webhook_url_set": bool(cfg.NOTIFY_SLACK_WEBHOOK_URL),
        "discord_enabled": cfg.NOTIFY_DISCORD_ENABLED,
        "discord_webhook_url_set": bool(cfg.NOTIFY_DISCORD_WEBHOOK_URL),
        "webhook_enabled": cfg.NOTIFY_WEBHOOK_ENABLED,
        "webhook_url_set": bool(cfg.NOTIFY_WEBHOOK_URL),
        "webhook_token_set": bool(cfg.NOTIFY_WEBHOOK_TOKEN),
        "telegram_enabled": cfg.NOTIFY_TELEGRAM_ENABLED,
        "telegram_bot_token_set": bool(cfg.NOTIFY_TELEGRAM_BOT_TOKEN),
        "telegram_chat_id": cfg.NOTIFY_TELEGRAM_CHAT_ID,
        "sample_size": cfg.NOTIFY_SAMPLE_SIZE,
        "timeout_seconds": cfg.NOTIFY_TIMEOUT_SECONDS,
        "retries": cfg.NOTIFY_RETRIES,
    }


def validate_webhook_url(value: str) -> str:
    """Validate a webhook URL and return it unchanged, or raise ValueError.

    Only http/https with a non-empty host is accepted, the string must carry no
    whitespace or control characters, and its length is bounded. The URL is a
    secret, so the messages describe the fault without echoing the value.

    This is a transport check only: the result is passed to an HTTP client and
    must never be interpolated into a shell command.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("Webhook URL must be a non-empty string")
    if len(value) > MAX_WEBHOOK_URL_LENGTH:
        raise ValueError(f"Webhook URL exceeds {MAX_WEBHOOK_URL_LENGTH} characters")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Webhook URL must not contain whitespace or control characters")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ValueError("Webhook URL is not a valid URL") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Webhook URL must use the http or https scheme")
    if not parts.netloc:
        raise ValueError("Webhook URL must include a host")
    return value


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


def retry_proxy_url_for_scan_type(scan_type: str) -> str | None:
    """Return the proxy URL to use for RETRY passes of a scan_type, or None.

    Retries only apply to "tech" and "crawl"; recon always returns None.

    This is deliberately NOT gated by PROXY_TECH / PROXY_CRAWL: the retries
    toggle is independent of the per-phase "Apply Proxy To" flags. Those flags
    decide whether MAIN traffic is proxied; PROXY_RETRIES decides whether a
    blocked or throttled host is re-attempted through the proxy.

    Truth table (with PROXY_ENABLED on), for tech/crawl:
      phase off + retries off -> direct main,   direct retry
      phase off + retries on  -> direct main,   PROXIED retry
      phase on  + retries off -> PROXIED main,  direct retry
      phase on  + retries on  -> PROXIED main,  PROXIED retry
    """
    if scan_type not in ("tech", "crawl"):
        return None
    if not cfg.PROXY_ENABLED:
        return None
    if not cfg.PROXY_RETRIES:
        return None
    return build_proxy_url(include_auth=True)
