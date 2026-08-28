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
    # Append word tokens parsed from subdomains found in the non-bruteforce
    # recon phase to the DNS bruteforce wordlist. Opt-in: it enlarges the
    # wordlist and therefore the bruteforce phase.
    DNS_WORDLIST_EXPANSION_ENABLED: bool = False
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
    PROXY_RETRIES: bool = False         # retry blocked/throttled hosts through the proxy

    # --- Notification configuration ---
    # Persisted in the app_settings table and loaded at startup; these defaults
    # apply when no value has been saved yet.
    NOTIFY_ENABLED: bool = False
    NOTIFY_ON_SUCCESS: bool = True      # notify when a scan completes
    NOTIFY_ON_FAILURE: bool = True      # notify when a scan fails
    NOTIFY_SLACK_ENABLED: bool = False
    NOTIFY_SLACK_WEBHOOK_URL: str = ""
    NOTIFY_DISCORD_ENABLED: bool = False
    NOTIFY_DISCORD_WEBHOOK_URL: str = ""
    NOTIFY_WEBHOOK_ENABLED: bool = False
    NOTIFY_WEBHOOK_URL: str = ""
    NOTIFY_WEBHOOK_TOKEN: str = ""      # sent as a bearer token on the generic webhook
    NOTIFY_TELEGRAM_ENABLED: bool = False
    NOTIFY_TELEGRAM_BOT_TOKEN: str = ""
    NOTIFY_TELEGRAM_CHAT_ID: str = ""
    NOTIFY_SAMPLE_SIZE: int = 5         # sample findings listed in a message (0-20)
    NOTIFY_TIMEOUT_SECONDS: int = 10    # per-delivery HTTP timeout (1-30)
    NOTIFY_RETRIES: int = 2             # delivery retry attempts (0-5)

    # Anchor the .env lookup to the project root rather than the process's
    # working directory: running `uvicorn main:app` from backend/ would
    # otherwise find no .env and fall back to the placeholder credentials
    # above, silently signing tokens with a key that is public in the repo.
    #
    # Under Docker this resolves to /.env, which does not exist — harmless,
    # because compose passes the same .env in as environment variables via
    # env_file, and those take precedence anyway. It only matters for the
    # bare-metal path.
    #
    # extra="ignore" because .env is shared with docker compose, which reads
    # keys that are not application settings (BACKEND_PORT, FRONTEND_PORT).
    # Without it, loading the .env that install/setup.sh generates fails
    # validation outright.
    model_config = {
        "env_file": Path(__file__).resolve().parent.parent / ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
