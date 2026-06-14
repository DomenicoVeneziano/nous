import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path

log = logging.getLogger("engine.retention")

LOG_RETENTION_DAYS = 7
RETENTION_CHECK_INTERVAL_SECONDS = 6 * 3600
LOGS_ROOT = Path("data/projects")


def _cleanup_old_logs_sync():
    cutoff = time.time() - timedelta(days=LOG_RETENTION_DAYS).total_seconds()
    deleted = 0
    for log_file in LOGS_ROOT.glob("*/logs/*.log"):
        try:
            if log_file.stat().st_mtime < cutoff:
                log_file.unlink()
                deleted += 1
        except Exception as e:
            log.warning(f"Could not remove {log_file}: {e}")
    if deleted:
        log.info(f"Deleted {deleted} log file(s) older than {LOG_RETENTION_DAYS} days")


async def cleanup_old_logs():
    await asyncio.to_thread(_cleanup_old_logs_sync)


async def retention_loop(shutdown_event: asyncio.Event):
    await cleanup_old_logs()
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=RETENTION_CHECK_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            await cleanup_old_logs()
