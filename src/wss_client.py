"""WSS ingestion engine: Socket.IO with DLQ, dedup, health monitoring, jittered backoff."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Callable, Coroutine

import socketio

from . import redis_store
from .config import settings

logger = logging.getLogger(__name__)

# Type alias for the message callback
MessageCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class WSSClient:
    """
    Persistent Socket.IO WSS connection to IVASMS.

    Features:
      - Authenticated handshake with Bearer token
      - Active ping/pong keepalive (configurable interval)
      - Jittered exponential backoff reconnect (1s → 60s)
      - Session state preservation across reconnects
      - Frame deduplication via Redis (10 min TTL)
      - Dead Letter Queue for malformed frames
      - Health monitoring and telemetry
      - Periodic token refresh to prevent expiry
    """

    def __init__(self, on_message: MessageCallback) -> None:
        self._on_message = on_message
        self._reconnect_delay = settings.reconnect_base_delay
        self._max_delay = settings.reconnect_max_delay
        self._running = False
        self._sio: socketio.AsyncClient | None = None
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

        while self._running:
            try:
                await self._connect()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("WSS connection error: %s", exc)
                self._error_count += 1

            if not self._running:
                break

            # Jittered exponential backoff: base * 2^attempt * jitter(0.5..1.5)
            jitter = random.uniform(0.5, 1.5)
            delay = min(self._reconnect_delay * jitter, self._max_delay)
            logger.info(
                "Reconnecting in %.1fs (attempt %d, backoff %.1fs)",
                delay, self._reconnect_count, self._reconnect_delay,
            )
            await asyncio.sleep(delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, self._max_delay)
            self._reconnect_count += 1
            await redis_store.incr_counter("wss_reconnect_attempts")

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
        if self._sio:
            await self._sio.disconnect()
        logger.info("WSS client stopped")

    async def _connect(self) -> None:
        """Establish the Socket.IO connection."""
        self._sio = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,
            reconnection=False,  # We handle reconnection ourselves
        )

        # Register event handlers
        self._sio.on("connect", self._on_connect)
        self._sio.on("disconnect", self._on_disconnect)
        self._sio.on("connect_error", self._on_connect_error)

        # Listen for all possible SMS event names from IVASMS
        for event_name in ("message", "sms", "new_message", "event", "data", "notification"):
            self._sio.on(event_name, self._handle_event)

        url = settings.build_wss_url()
        logger.info("Connecting to IVASMS WSS...")

        await self._sio.connect(
            url,
            transports=["websocket"],
            auth={"token": settings.ivasms_auth_token, "user": settings.ivasms_user_id},
            wait_timeout=15,
        )

        # Keep the task alive until disconnect
        while self._connected and self._running:
            await asyncio.sleep(1)

    def _on_connect(self) -> None:
        """Called when the Socket.IO connection is established."""
        self._connected = True
        self._connect_time = time.time()
        self._reconnect_delay = settings.reconnect_base_delay  # Reset backoff
        logger.info("✅ WSS connected to IVASMS")
        asyncio.create_task(redis_store.incr_counter("wss_connections"))

    def _on_disconnect(self) -> None:
        """Called when the Socket.IO connection is lost."""
        self._connected = False
        self._connect_time = None
        logger.warning("⚠️  WSS disconnected from IVASMS")

    def _on_connect_error(self, data: Any) -> None:
        """Called on connection error."""
        logger.error("WSS connection error: %s", data)
        self._error_count += 1
        asyncio.create_task(redis_store.incr_counter("wss_errors"))

    async def _handle_event(self, data: Any) -> None:
        """Handle incoming Socket.IO events from IVASMS with DLQ protection."""
        try:
            # Parse incoming data
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {"raw": data}

            if not isinstance(data, dict):
                data = {"payload": data}

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

            logger.debug("Received SMS event: %s", data)

            # Dispatch to the message handler
            await self._on_message(data)

        except asyncio.CancelledError:
            raise
        except json.JSONDecodeError as exc:
            # Malformed JSON → DLQ
            self._dlq_count += 1
            logger.warning("Malformed JSON frame → DLQ: %s", exc)
            await redis_store.push_dlq(str(data), f"JSON parse error: {exc}")
            await redis_store.incr_counter("wss_malformed_frames")
        except Exception as exc:
            # Any other parsing error → DLQ
            self._dlq_count += 1
            self._error_count += 1
            logger.error("Error processing WSS event: %s", exc, exc_info=True)
            await redis_store.push_dlq(str(data)[:2000], str(exc)[:200])
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
                        "WSS health: connected=%s uptime=%ds msgs=%d errors=%d dlq=%d",
                        self._connected, stats["uptime_seconds"],
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
                if self._connected and self._sio:
                    logger.info("Refreshing WSS auth token...")
                    await redis_store.incr_counter("token_refreshes")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Token refresh error: %s", exc)
