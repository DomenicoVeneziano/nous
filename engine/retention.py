import asyncio
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

log = logging.getLogger("engine.retention")

LOG_RETENTION_DAYS = 7
RETENTION_CHECK_INTERVAL_SECONDS = 6 * 3600
LOGS_ROOT = Path("data/projects")

# Scratch directories left in the shared tmp when a script dies without running
# its own cleanup. runner.py gives every run a private TMPDIR and removes it in
# its finally block, so this is a backstop for the cases that skip it entirely:
# a SIGKILLed engine, or a browser that outlived the run and rewrote its profile
# after the tree was removed. Playwright/camoufox profiles are the expensive
# ones — roughly 70 MB per abandoned tech-analysis run.
TMP_ROOT = Path(os.environ.get("TMPDIR", "/tmp"))
TMP_RETENTION_HOURS = int(os.environ.get("TMP_RETENTION_HOURS", "6"))
STALE_TMP_PREFIXES = (
    "nous_run_",
    "playwright_firefoxdev_profile",
    "playwright-artifacts",
    "nous_active.", "nous_brute.", "nous_perm.", "nous_combined.",
    "nous_wildcard.", "nous_newwords.", "nous_expanded_wl.",
    "nous_filtered_wl.", "nous_archived_urls.",
)


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


def _newest_mtime(path: Path) -> float:
    """Most recent mtime anywhere under path.

    A browser profile keeps being written while its browser lives, but the
    directory's own mtime only moves when entries are added or removed. Walking
    the tree is what keeps this sweep from deleting the scratch space of a job
    that is still running.
    """
    newest = 0.0
    try:
        newest = path.stat().st_mtime
    except OSError:
        return 0.0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                continue
    return newest


def _cleanup_stale_tmp_sync():
    cutoff = time.time() - TMP_RETENTION_HOURS * 3600
    removed = 0
    reclaimed = 0
    try:
        entries = list(TMP_ROOT.iterdir())
    except OSError as e:
        log.warning(f"Could not scan {TMP_ROOT}: {e}")
        return
    for entry in entries:
        if not entry.name.startswith(STALE_TMP_PREFIXES):
            continue
        try:
            if entry.is_dir():
                if _newest_mtime(entry) >= cutoff:
                    continue
                size = sum(
                    os.lstat(os.path.join(r, f)).st_size
                    for r, _, fs in os.walk(entry, onerror=lambda e: None)
                    for f in fs
                    if os.path.exists(os.path.join(r, f))
                )
                shutil.rmtree(entry, ignore_errors=True)
            else:
                stat = entry.stat()
                if stat.st_mtime >= cutoff:
                    continue
                size = stat.st_size
                entry.unlink()
            removed += 1
            reclaimed += size
        except Exception as e:
            log.warning(f"Could not remove {entry}: {e}")
    if removed:
        log.info(
            f"Removed {removed} stale tmp entr{'y' if removed == 1 else 'ies'} "
            f"older than {TMP_RETENTION_HOURS}h ({reclaimed / 1_048_576:.1f} MB reclaimed)"
        )


async def cleanup_old_logs():
    await asyncio.to_thread(_cleanup_old_logs_sync)


async def cleanup_stale_tmp():
    await asyncio.to_thread(_cleanup_stale_tmp_sync)


async def _run_cleanups():
    await cleanup_old_logs()
    await cleanup_stale_tmp()


async def retention_loop(shutdown_event: asyncio.Event):
    await _run_cleanups()
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=RETENTION_CHECK_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            await _run_cleanups()
