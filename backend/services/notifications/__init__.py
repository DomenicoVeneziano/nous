# backend/services/notifications/__init__.py
"""Scan notification delivery: build one canonical event, send it everywhere.

    build_event(job)            -> the canonical event dict (also the generic
                                   webhook body), carrying a bounded summary
    dispatch(client, event)     -> deliver it to every enabled channel, with
                                   the full report as a file (Discord,
                                   Telegram), capped follow-up messages
                                   (Slack) or lists in the body (webhook)
    send_test(channel)          -> (ok, message) for a single configured channel
"""
