# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db, SessionLocal
from models.user import User
from config import settings
from ws.scan_stream import websocket_endpoint

app = FastAPI(title="Nous", version="1.0.0")

_allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from routers.auth_router import router as auth_router
from routers.projects import router as projects_router
from routers.assets import router as assets_router
from routers.scans import router as scans_router
from routers.search import router as search_router
from routers.files import router as files_router
from routers.settings import router as settings_router
from routers.stats import router as stats_router
from routers.api_keys import router as api_keys_router
from routers.findings import router as findings_router
from routers.vuln_patterns import router as vuln_patterns_router

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(assets_router)
app.include_router(scans_router)
app.include_router(search_router)
app.include_router(files_router)
app.include_router(settings_router)
app.include_router(stats_router)
app.include_router(api_keys_router)
app.include_router(findings_router)
app.include_router(vuln_patterns_router)

# WebSocket route
app.websocket("/ws/scan")(websocket_endpoint)


@app.on_event("startup")
def startup():
    # Fail fast if setup.sh hasn't been run
    if "PLACEHOLDER" in settings.SECRET_KEY:
        raise RuntimeError(
            "\n\n"
            "  SECRET_KEY contains a placeholder value.\n"
            "  Run 'bash install/setup.sh' to generate secure credentials.\n"
        )

    init_db()

    # Seed admin user if not exists; load persisted proxy settings into config
    from services.settings_store import load_proxy_settings
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
        if not existing:
            admin = User(username=settings.ADMIN_USERNAME, role="admin")
            admin.set_password(settings.ADMIN_PASSWORD)
            db.add(admin)
            db.commit()
        load_proxy_settings(db)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}
