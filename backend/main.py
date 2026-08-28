# backend/main.py
import asyncio
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db, SessionLocal
from models.user import User
from config import settings
from notifier import notifier_loop
from scheduler import scheduler_loop
from ws.scan_stream import websocket_endpoint

# Same setup the engine worker uses, so both services' logs read alike. Without
# it the backend's own loggers sit at the root default of WARNING with no
# handler, and everything the scheduler reports — cycles queued, skipped, or
# completed — is dropped before it reaches the container logs.
#
# uvicorn configures logging in Config.__init__, which runs before it imports
# this module, so the root logger is still handler-free here and basicConfig is
# not a no-op. uvicorn keeps its own lines out of this handler: "uvicorn" and
# "uvicorn.access" carry their handlers with propagate=False, and "uvicorn.error"
# propagates no further than "uvicorn", so nothing it emits is logged twice.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

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
from routers.tags import router as tags_router
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
app.include_router(tags_router)
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


# The recurring-scan scheduler and the notification dispatcher both run inside
# the API process. That is only correct because uvicorn serves this app
# single-process (backend/Dockerfile's CMD has no --workers): with several
# workers each would run its own loops, and every cycle would be queued once per
# worker and every notification sent once per worker.
_shutdown_event = asyncio.Event()
_scheduler_task: asyncio.Task | None = None
_notifier_task: asyncio.Task | None = None

log = logging.getLogger("backend.main")


def _scheduler_task_done(task: asyncio.Task):
    """Report a scheduler loop that ended on its own.

    Nothing else would: the API keeps serving and /health keeps returning ok
    while schedules quietly stop firing. Logged rather than restarted — a loop
    that died did so for a reason a restart would hit again, and the operator
    needs to see it in the container logs.
    """
    if _shutdown_event.is_set() or task.cancelled():
        return  # Ordinary shutdown.
    exc = task.exception()
    if exc is not None:
        log.error("Scheduler loop crashed; recurring scans have stopped", exc_info=exc)
    else:
        log.error("Scheduler loop exited early; recurring scans have stopped")


def _notifier_task_done(task: asyncio.Task):
    """Report a notifier loop that ended on its own.

    Same reasoning as the scheduler's callback: the API keeps serving while
    finished scans quietly stop producing notifications, so the exit is logged
    rather than restarted and the operator sees it in the container logs.
    """
    if _shutdown_event.is_set() or task.cancelled():
        return  # Ordinary shutdown.
    exc = task.exception()
    if exc is not None:
        log.error("Notifier loop crashed; notifications have stopped", exc_info=exc)
    else:
        log.error("Notifier loop exited early; notifications have stopped")


@app.on_event("startup")
async def startup():
    # Fail fast if setup.sh hasn't been run
    if "PLACEHOLDER" in settings.SECRET_KEY:
        raise RuntimeError(
            "\n\n"
            "  SECRET_KEY contains a placeholder value.\n"
            "  Run 'bash install/setup.sh' to generate secure credentials.\n"
        )

    init_db()

    # Seed admin user if not exists; load persisted proxy and notification
    # settings into config
    from services.settings_store import load_notification_settings, load_proxy_settings
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
        if not existing:
            admin = User(username=settings.ADMIN_USERNAME, role="admin")
            admin.set_password(settings.ADMIN_PASSWORD)
            db.add(admin)
            db.commit()
        load_proxy_settings(db)
        load_notification_settings(db)
    finally:
        db.close()

    global _scheduler_task, _notifier_task
    _scheduler_task = asyncio.create_task(scheduler_loop(_shutdown_event))
    _scheduler_task.add_done_callback(_scheduler_task_done)
    _notifier_task = asyncio.create_task(notifier_loop(_shutdown_event))
    _notifier_task.add_done_callback(_notifier_task_done)


async def _stop(task: asyncio.Task | None):
    """Wind one background loop down, cancelling it if it overruns."""
    if task is None:
        return
    try:
        # A tick runs on a worker thread or an in-flight HTTP send, so give the
        # one in progress a chance to finish before the process goes away.
        await asyncio.wait_for(task, timeout=10)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    except Exception:  # noqa: BLE001
        # A loop that died on its own already reported itself through its
        # done-callback; re-raising here would strand the other task pending.
        pass


@app.on_event("shutdown")
async def shutdown():
    _shutdown_event.set()
    # Both loops are wound down unconditionally, and concurrently: an absent or
    # already-finished one must not skip the other, and waiting on them in turn
    # would double the worst-case shutdown to twice the 10s grace.
    await asyncio.gather(_stop(_scheduler_task), _stop(_notifier_task))


@app.get("/health")
def health():
    return {"status": "ok"}
