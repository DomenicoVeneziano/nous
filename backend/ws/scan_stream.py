# backend/ws/scan_stream.py
import asyncio
import hashlib
import hmac
import json
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect, Query
from jose import JWTError
from auth.jwt import verify_jwt
from config import settings

# Separate sets for producers (engine) and consumers (frontend)
_producers: set[WebSocket] = set()
_consumers: set[WebSocket] = set()

# Ring buffer: replayed to new consumers so they catch up on lines sent before they connected
_message_buffer: deque[str] = deque(maxlen=1000)


def expected_engine_token() -> str:
    """The token the engine must present to connect as a producer.

    Uses ENGINE_WS_SECRET when set, else derives a stable value from SECRET_KEY
    so a fresh deployment needs no extra configuration. The engine computes the
    same value from the shared .env.
    """
    if settings.ENGINE_WS_SECRET:
        return settings.ENGINE_WS_SECRET
    return hashlib.sha256(f"engine-ws:{settings.SECRET_KEY}".encode()).hexdigest()


async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    engine_token: str | None = Query(default=None),
):
    # Two authenticated roles, no anonymous access:
    #   * producer (engine)  — presents engine_token matching the shared secret;
    #     may push scan events but never receives the replay buffer.
    #   * consumer (frontend) — presents a valid JWT; receives broadcasts and the
    #     replay buffer but its inbound messages are ignored (never relayed).
    # A connection that presents neither valid credential is rejected, closing the
    # previous hole where any tokenless client became a trusted producer.
    role: str | None = None
    if engine_token is not None:
        if hmac.compare_digest(engine_token, expected_engine_token()):
            role = "producer"
        else:
            await websocket.close(code=4401)
            return
    elif token is not None:
        try:
            verify_jwt(token)
            role = "consumer"
        except JWTError:
            await websocket.close(code=4401)
            return
    else:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    if role == "producer":
        _producers.add(websocket)
    else:
        _consumers.add(websocket)
        # Replay buffered messages so the new consumer catches up
        for msg in list(_message_buffer):
            try:
                await websocket.send_text(msg)
            except Exception:
                _consumers.discard(websocket)
                return

    try:
        while True:
            raw = await websocket.receive_text()

            # Only authenticated producers may inject events into the stream.
            # Consumer-sent frames are read (to detect disconnects) but ignored.
            if role != "producer":
                continue

            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "type" in parsed:
                    # Clear the buffer when a new job starts so stale output isn't replayed
                    if parsed.get("type") == "job_started":
                        _message_buffer.clear()

                    message = json.dumps(parsed)
                    # asset_update events are transient push-hints — replaying them
                    # on reconnect causes a burst of /assets requests (one per buffered
                    # event) because the frontend refetches the full asset list on each.
                    if parsed.get("type") != "asset_update":
                        _message_buffer.append(message)

                    dead = set()
                    for client in _consumers:
                        try:
                            await client.send_text(message)
                        except Exception:
                            dead.add(client)
                    _consumers.difference_update(dead)
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        _consumers.discard(websocket)
        _producers.discard(websocket)
    except Exception:
        _consumers.discard(websocket)
        _producers.discard(websocket)


async def clear_buffer_and_broadcast():
    _message_buffer.clear()
    await broadcast("output_cleared", {})


async def broadcast(event_type: str, data: dict):
    """Broadcast an event to all consumer WebSocket clients."""
    message = json.dumps({"type": event_type, "data": data})
    dead = set()
    for client in _consumers:
        try:
            await client.send_text(message)
        except Exception:
            dead.add(client)
    _consumers.difference_update(dead)


def broadcast_sync(event_type: str, data: dict):
    """Synchronous wrapper for broadcast, usable from non-async context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast(event_type, data))
        else:
            loop.run_until_complete(broadcast(event_type, data))
    except RuntimeError:
        pass
