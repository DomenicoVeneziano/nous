# backend/auth/rate_limit.py
"""In-memory login throttle with temporary lockout.

Keyed by client IP. Counts consecutive failed logins within a rolling window;
once the threshold is crossed the IP is locked out for a cooldown period. A
successful login clears the counter. State is process-local, which is sufficient
for the single-worker, self-hosted deployment this app targets; a multi-worker or
multi-replica setup would need a shared store (e.g. Redis).
"""
import threading
import time

# Tunables
MAX_FAILURES = 5          # failed attempts allowed within WINDOW_SECONDS
WINDOW_SECONDS = 300      # rolling window over which failures accumulate
LOCKOUT_SECONDS = 300     # how long an IP stays locked after crossing the threshold

_lock = threading.Lock()
# ip -> {"failures": int, "first_failure": float, "locked_until": float}
_state: dict[str, dict] = {}


def _now() -> float:
    return time.monotonic()


def check_allowed(ip: str) -> float:
    """Return 0 if the IP may attempt a login, else seconds remaining on lockout."""
    with _lock:
        entry = _state.get(ip)
        if not entry:
            return 0.0
        remaining = entry.get("locked_until", 0.0) - _now()
        return remaining if remaining > 0 else 0.0


def record_failure(ip: str) -> None:
    """Record a failed attempt, arming a lockout once the threshold is crossed."""
    with _lock:
        now = _now()
        entry = _state.get(ip)
        # Start a fresh window if none exists or the previous one has expired.
        if not entry or (now - entry.get("first_failure", now)) > WINDOW_SECONDS:
            entry = {"failures": 0, "first_failure": now, "locked_until": 0.0}
        entry["failures"] += 1
        if entry["failures"] >= MAX_FAILURES:
            entry["locked_until"] = now + LOCKOUT_SECONDS
        _state[ip] = entry


def record_success(ip: str) -> None:
    """Clear any throttle state for an IP after a successful login."""
    with _lock:
        _state.pop(ip, None)


def reset() -> None:
    """Clear all state — intended for tests."""
    with _lock:
        _state.clear()
