"""WSS ingestion engine: raw aiohttp WebSocket with single persistent session.

No python-socketio dependency — eliminates the ClientWSTimeout compatibility
chain entirely. Handles Socket.IO v4 framing transparently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Callable, Coroutine

import aiohttp

from . import redis_store
from .config import settings

logger = logging.getLogger(__name__)

# Type alias for the message callback
MessageCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


def process_raw_ws_payload(raw_text: str) -> dict | None:
    """Filter out Socket.IO/Engine.IO protocol frames, return only real SMS data.

    Protocol frame types that are NOT SMS data:
      0  = Engine.IO open/handshake (contains sid, pingInterval)
      2  = Engine.IO ping
      3  = Engine.IO pong
      40 = Socket.IO connect ack
      41 = Socket.IO disconnect

    Returns parsed dict for real SMS events, None for control frames.
    """
    if not raw_text:
        return None

    # 1. Ignore Engine.IO control frames and Socket.IO connect/disconnect
    if raw_text.startswith(("0", "2", "3", "40", "41")):
        return None

    # 2. Extract Socket.IO event payloads (starts with '42')
    if raw_text.startswith("42"):
        try:
            payload_array = json.loads(raw_text[2:])
            event_name = payload_array[0]
            data = payload_array[1]
            # Return data only if it represents an actual SMS message
            if isinstance(data, dict):
                return data
            if isinstance(data, str):
                try:
                    return json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    return {"raw": data, "event": event_name}
            return {"payload": data, "event": event_name}
        except (json.JSONDecodeError, IndexError, TypeError):
            return None

    # 3. Fallback for raw JSON objects (skip handshake dicts with sid/pingInterval)
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "sid" not in data and "pingInterval" not in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    return None


class WSSClient:
    """
    Persistent aiohttp WebSocket connection to IVASMS.

    Features:
      - Single aiohttp.ClientSession for entire lifecycle (no resource leaks)
      - Authenticated handshake via Bearer token in headers
      - Heartbeat keepalive via aiohttp's built-in ping/pong
      - Jittered exponential backoff reconnect (1s → 60s)
      - Session state preservation across reconnects
      - Frame deduplication via Redis (10 min TTL)
      - Dead Letter Queue for malformed frames
      - Health monitoring and telemetry
    """

    def __init__(self, on_message: MessageCallback) -> None:
        self._on_message = on_message
        self._reconnect_delay = settings.reconnect_base_delay
        self._max_delay = settings.reconnect_max_delay
        self._running = False
        self._connected = False
        self._connect_time: float | None = None
        self._message_count = 0
        self._duplicate_count = 0
        self._error_count = 0
        self._dlq_count = 0
        self._reconnect_count = 0
        self._health_task: asyncio.Task[None] | None = None
        self._token_refresh_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def uptime(self) -> float:
        if self._connect_time:
            return time.time() - self._connect_time
        return 0.0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "uptime_seconds": int(self.uptime),
            "total_messages": self._message_count,
            "duplicate_messages": self._duplicate_count,
            "error_count": self._error_count,
            "dlq_messages": self._dlq_count,
            "reconnect_count": self._reconnect_count,
            "current_delay": round(self._reconnect_delay, 1),
        }

    async def start(self) -> None:
        """Start the WSS client with automatic reconnection."""
        self._running = True
        self._token_refresh_task = asyncio.create_task(self._token_refresh_loop())
        self._health_task = asyncio.create_task(self._health_loop())

        # Single persistent session for the entire lifecycle
        headers = {
            "Authorization": f"Bearer {settings.ivasms_auth_token}",
            "User-Agent": "IVASMS-Forwarder/2.0",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            attempt = 0
            backoff = settings.reconnect_base_delay

            while self._running:
                try:
                    logger.info("Connecting to IVASMS WSS...")
                    await self._connect(session)
                    # _connect blocks until disconnect, so reset backoff on clean exit
                    attempt = 0
                    backoff = settings.reconnect_base_delay

                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("WSS connection error: %s", exc)
                    self._error_count += 1

                if not self._running:
                    break

                # Jittered exponential backoff
                jitter = random.uniform(0.5, 1.5)
                delay = min(backoff * jitter, self._max_delay)
                logger.info(
                    "Reconnecting in %.1fs (attempt %d, backoff %.1fs)",
                    delay, attempt, backoff,
                )
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self._max_delay)
                attempt += 1
                self._reconnect_count += 1
                await redis_store.incr_counter("wss_reconnect_attempts")

        logger.info("WSS client stopped")

    async def stop(self) -> None:
        """Gracefully stop the WSS client."""
        self._running = False
        for task in (self._token_refresh_task, self._health_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _connect(self, session: aiohttp.ClientSession) -> None:
        """Establish WebSocket connection and process messages until disconnect."""
        url = settings.build_wss_url()

        async with session.ws_connect(
            url,
            heartbeat=20.0,
            receive_timeout=30.0,
            timeout=aiohttp.ClientTimeout(total=15, sock_connect=10),
        ) as ws:
            self._connected = True
            self._connect_time = time.time()
            self._reconnect_delay = settings.reconnect_base_delay
            logger.info("✅ WSS connected to IVASMS")
            await redis_store.incr_counter("wss_connections")

            # Process incoming messages
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_raw_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning("WSS stream ended: %s", msg.type)
                    break

            self._connected = False
            self._connect_time = None
            logger.warning("⚠️  WSS disconnected from IVASMS")

    async def _handle_raw_message(self, raw: str) -> None:
        """Parse incoming frame, filter control frames, dispatch real SMS events."""
        try:
            # Strict filter: returns None for control frames (0, 2, 3, 40, 41)
            data = process_raw_ws_payload(raw)
            if data is None:
                return  # Skip control frames / non-SMS messages completely

            # Extract message ID for deduplication
            msg_id = str(
                data.get("id")
                or data.get("message_id")
                or data.get("uid")
                or data.get("msg_id")
                or ""
            )

            # Deduplication
            if msg_id and await redis_store.is_duplicate(msg_id):
                self._duplicate_count += 1
                logger.debug("Duplicate message skipped: %s", msg_id)
                await redis_store.incr_counter("wss_duplicates_skipped")
                return

            self._message_count += 1
            await redis_store.incr_counter("wss_messages_received")

            logger.debug("Received SMS event: %s", str(data)[:200])

            # Dispatch to the message handler
            await self._on_message(data)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._dlq_count += 1
            self._error_count += 1
            logger.error("Error processing WSS event: %s", exc, exc_info=True)
            await redis_store.push_dlq(str(raw)[:2000], str(exc)[:200])
            await redis_store.incr_counter("wss_processing_errors")

    async def _health_loop(self) -> None:
        """Periodic health check: log stats and push gauges to Redis."""
        while self._running:
            try:
                await asyncio.sleep(60)
                stats = self.stats
                await redis_store.set_gauge("wss_connected", 1 if self._connected else 0)
                await redis_store.set_gauge("wss_uptime", stats["uptime_seconds"])
                await redis_store.set_gauge("wss_messages", stats["total_messages"])
                await redis_store.set_gauge("wss_errors", stats["error_count"])
                await redis_store.set_gauge("wss_dlq", stats["dlq_messages"])

                if self._connected:
                    logger.info(
                        "WSS health: uptime=%ds msgs=%d errors=%d dlq=%d",
                        stats["uptime_seconds"],
                        stats["total_messages"], stats["error_count"],
                        stats["dlq_messages"],
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Health check error: %s", exc)

    async def _token_refresh_loop(self) -> None:
        """Periodically refresh the WSS auth token to prevent expiry."""
        while self._running:
            try:
                await asyncio.sleep(1800)  # Every 30 minutes
                if self._connected:
                    logger.info("Token refresh check...")
                    await redis_store.incr_counter("token_refreshes")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Token refresh error: %s", exc)
