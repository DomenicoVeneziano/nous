# engine/worker.py
import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

import websockets

from sqlalchemy.exc import OperationalError
from queue_manager import get_session, fetch_next_job, get_job_status
from jobs.recon_job import run_recon_job
from jobs.tech_job import run_tech_job
from jobs.crawler_job import run_crawler_job
from retention import retention_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("engine.worker")

BACKEND_WS_URL = os.environ.get("BACKEND_WS_URL", "ws://backend:8000/ws/scan")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))


def _engine_ws_url() -> str:
    """Append the engine producer credential to the backend WS URL.

    Uses ENGINE_WS_SECRET when provided, else derives it from SECRET_KEY exactly
    as the backend does (both read the same .env), so no extra config is needed.
    """
    secret = os.environ.get("ENGINE_WS_SECRET", "")
    if not secret:
        secret_key = os.environ.get("SECRET_KEY", "")
        secret = hashlib.sha256(f"engine-ws:{secret_key}".encode()).hexdigest()
    parts = urlsplit(BACKEND_WS_URL)
    query = urlencode({"engine_token": secret})
    new_query = f"{parts.query}&{query}" if parts.query else query
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

JOB_HANDLERS = {
    "recon": run_recon_job,
    "tech": run_tech_job,
    "crawl": run_crawler_job,
}


class WSBroadcaster:
    """Manages a single persistent WebSocket connection to the backend."""

    def __init__(self, url: str):
        self.url = url
        self._ws = None
        self._connecting = False

    async def connect(self):
        """Establish connection. Safe to call multiple times — only connects once."""
        if self._ws is not None:
            return
        if self._connecting:
            return
        self._connecting = True
        try:
            self._ws = await websockets.connect(self.url)
            log.info("Connected to backend WebSocket")
        except Exception as e:
            log.warning(f"Could not connect to backend WS: {e}")
            self._ws = None
        finally:
            self._connecting = False

    async def broadcast(self, event_type: str, data: dict):
        if not self._ws:
            await self.connect()
        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": event_type, "data": data}))
            except Exception:
                # Connection broke — close it cleanly
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None

    async def close(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


def wait_for_db(retries: int = 10, delay: int = 3):
    """Block until scan_jobs table is accessible, retrying on OperationalError."""
    for attempt in range(1, retries + 1):
        session = get_session()
        try:
            fetch_next_job(session)
            log.info("Database ready.")
            return
        except OperationalError as e:
            log.warning(f"DB not ready (attempt {attempt}/{retries}): {e.orig} — retrying in {delay}s")
            time.sleep(delay)
        finally:
            session.close()
    log.error("Database never became ready — aborting.")
    sys.exit(1)


async def main_loop():
    log.info("Engine worker starting...")
    wait_for_db()
    broadcaster = WSBroadcaster(_engine_ws_url())
    await broadcaster.connect()

    shutdown_event = asyncio.Event()
    retention_task = asyncio.create_task(retention_loop(shutdown_event))

    def _handle_shutdown(sig, frame):
        log.info(f"Received signal {sig}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    while not shutdown_event.is_set():
        session = get_session()
        try:
            job = fetch_next_job(session)
        finally:
            session.close()

        if not job:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        scan_type = job["scan_type"]
        handler = JOB_HANDLERS.get(scan_type)

        if not handler:
            log.error(f"Unknown scan type: {scan_type}")
            await asyncio.sleep(POLL_INTERVAL)
            continue

        log.info(f"Processing job {job['id']} (type={scan_type}, project={job['project_id']})")

        job_task = asyncio.create_task(handler(job, ws_broadcast=broadcaster.broadcast))
        job_id = job["id"]

        async def cancellation_watcher():
            session = get_session()
            try:
                while not job_task.done():
                    await asyncio.sleep(POLL_INTERVAL)
                    if get_job_status(session, job_id) == "cancelled":
                        job_task.cancel()
                        return
            finally:
                session.close()

        cancelled = False
        watcher_task = asyncio.create_task(cancellation_watcher())
        try:
            await job_task
        except asyncio.CancelledError:
            cancelled = True
            log.info(f"Job {job_id} was cancelled")
        except Exception as e:
            log.error(f"Job {job_id} failed with exception: {e}")
        finally:
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass

        if not cancelled:
            log.info(f"Job {job_id} completed")

    retention_task.cancel()
    try:
        await retention_task
    except asyncio.CancelledError:
        pass

    log.info("Shutdown event received — closing broadcaster.")
    await broadcaster.close()


if __name__ == "__main__":
    asyncio.run(main_loop())
