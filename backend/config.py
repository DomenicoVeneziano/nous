# backend/config.py
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    SECRET_KEY: str = "PLACEHOLDER_DO_NOT_USE_IN_PRODUCTION"
    ADMIN_USERNAME: str = "PLACEHOLDER_ADMIN"
    ADMIN_PASSWORD: str = "PLACEHOLDER_PASSWORD"
    JWT_EXPIRY_HOURS: int = 24
    # Shared secret the engine presents to authenticate as a WebSocket producer.
    # Leave empty to derive it deterministically from SECRET_KEY (both backend and
    # engine read SECRET_KEY from the same .env, so the derived value matches).
    ENGINE_WS_SECRET: str = ""
    DATABASE_URL: str = "sqlite:///data/db/nous.db"
    DATA_DIR: Path = Path("./data")
    SCRIPTS_DIR: Path = Path("./scripts")
    WORDLIST_PATH: Path = Path("./data/wordlists/dns_wordlist.txt")
    RESOLVERS_PATH: Path = Path("./data/resolvers/resolvers.txt")
    # Comma-separated list of allowed CORS origins, e.g.
    # ALLOWED_ORIGINS=http://localhost:5173,https://nous.example.com
    # Leave empty to restrict to same-origin only.
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost"
    RECON_TIMEOUT: int = 3600
    TECH_TIMEOUT: int = 0
    CRAWL_TIMEOUT: int = 1200
    CRAWL_MAX_PAGES: int = 50
    DNS_BRUTEFORCE_ENABLED: bool = False
    TECH_RATE_LIMIT_DELAY: float = 0
    DNS_RATE_LIMIT_DELAY: float = 0
    CRAWL_RATE_LIMIT_DELAY: float = 0
    # Capture a screenshot of each asset after page load during tech analysis
    TECH_SCREENSHOTS_ENABLED: bool = False

    # --- Proxy configuration ---
    # Persisted in the app_settings table and loaded at startup; these defaults
    # apply when no value has been saved yet.
    PROXY_ENABLED: bool = False
    PROXY_SCHEME: str = "http"          # http | https | socks5
    PROXY_HOST: str = ""
    PROXY_PORT: int = 8080
    PROXY_USERNAME: str = ""
    PROXY_PASSWORD: str = ""
    PROXY_RECON: bool = False           # route recon traffic through the proxy
    PROXY_TECH: bool = False            # route tech-analysis traffic through the proxy
    PROXY_CRAWL: bool = False           # route crawler traffic through the proxy

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
