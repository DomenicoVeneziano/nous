# backend/services/vuln_pattern_service.py
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models.vuln_pattern import VulnPattern

_DEFAULT_PATTERNS = [
    {
        "name": "api_keys",
        "description": "Exposed API keys, tokens, and secrets in response bodies",
        "checks": [
            {"field": "body", "regex": r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}"},
            {"field": "body", "regex": r"(AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35})"},
        ],
        "is_default": True,
    },
    {
        "name": "debug",
        "description": "Debug pages, stack traces, and verbose error messages",
        "checks": [
            {"field": "body", "regex": r"(?i)(stack\s?trace|traceback|debug\s?mode|SQLSTATE\[|mysqli?_|pg_query|runtime error|Fatal error)"},
            {"field": "title", "regex": r"(?i)(debug|stack trace|exception|phpinfo|error occurred)"},
        ],
        "is_default": True,
    },
    {
        "name": "sensitive_files",
        "description": "Sensitive file paths discovered in crawled URLs",
        "checks": [
            {"field": "url", "regex": r"(?i)(\.(env|git|svn|htaccess|htpasswd|bak|backup|old|sql|log|conf|config|yml|yaml|toml|pem|key|p12|pfx)$|/\.git/|/wp-config|/config\.php|/phpinfo)"},
        ],
        "is_default": True,
    },
    {
        "name": "misconfig",
        "description": "Server misconfigurations including directory listings and default pages",
        "checks": [
            {"field": "body", "regex": r"(?i)(index of /|directory listing|parent directory|phpinfo\(\)|server at .+ port \d+)"},
            {"field": "title", "regex": r"(?i)(index of|directory listing|apache (status|info)|phpinfo)"},
        ],
        "is_default": True,
    },
    {
        "name": "cors",
        "description": "Permissive CORS headers allowing any origin",
        "checks": [
            {"field": "header", "regex": r"(?i)access-control-allow-origin:\s*\*"},
        ],
        "is_default": True,
    },
    {
        "name": "info_disclosure",
        "description": "Information disclosure via response headers and internal IP addresses",
        "checks": [
            {"field": "header", "regex": r"(?i)(x-powered-by:|server:\s*(apache|nginx|iis|tomcat|jetty|lighttpd)|x-aspnet-version:|x-debug-token:)"},
            {"field": "body", "regex": r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"},
        ],
        "is_default": True,
    },
]


def seed_defaults(db: Session) -> None:
    """Insert any default patterns not yet present (safe to re-run)."""
    existing_names = {name for (name,) in db.query(VulnPattern.name).filter(VulnPattern.is_default == True).all()}
    now = datetime.now(timezone.utc)
    added = False
    for p in _DEFAULT_PATTERNS:
        if p["name"] not in existing_names:
            db.add(VulnPattern(
                name=p["name"],
                description=p["description"],
                checks=p["checks"],
                is_default=True,
                created_at=now,
                updated_at=now,
            ))
            added = True
    if added:
        db.commit()


def list_patterns(db: Session) -> list[VulnPattern]:
    return db.query(VulnPattern).order_by(VulnPattern.name).all()


def get_pattern(db: Session, pattern_id: str) -> VulnPattern | None:
    return db.query(VulnPattern).filter(VulnPattern.id == pattern_id).first()


def get_pattern_by_name(db: Session, name: str) -> VulnPattern | None:
    return db.query(VulnPattern).filter(VulnPattern.name == name).first()


def create_pattern(db: Session, name: str, description: str, checks: list[dict]) -> VulnPattern:
    now = datetime.now(timezone.utc)
    pattern = VulnPattern(
        name=name,
        description=description,
        checks=checks,
        is_default=False,
        created_at=now,
        updated_at=now,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


def update_pattern(db: Session, pattern: VulnPattern, description: str | None, checks: list[dict] | None) -> VulnPattern:
    if description is not None:
        pattern.description = description
    if checks is not None:
        pattern.checks = checks
    pattern.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pattern)
    return pattern


def delete_pattern(db: Session, pattern: VulnPattern) -> None:
    db.delete(pattern)
    db.commit()
