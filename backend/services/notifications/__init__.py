# backend/services/notifications/__init__.py
"""Scan notification delivery: build one canonical event, send it everywhere.

    build_event(job)            -> the canonical event dict (also the generic
                                   webhook body), carrying a bounded summary
    dispatch(client, event)     -> deliver it to every enabled channel
    send_test(channel)          -> (ok, message) for a single configured channel
"""
from .sender import dispatch, send_test
from .summary import build_event

__all__ = ["build_event", "dispatch", "send_test"]
