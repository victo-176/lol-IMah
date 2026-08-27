"""WSS ingestion engine: raw aiohttp + Socket.IO v4 protocol.

No python-socketio dependency — handles the Socket.IO v4 packet format
directly via aiohttp WebSocket. Eliminates the ClientWSTimeout compatibility
chain entirely.
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

# Socket.IO v4 packet types
SIO_PACKET_OPEN = 0      # server → client: connect
SIO_PACKET_CLOSE = 1     # either: disconnect
SIO_PACKET_PING = 2      # client → server: ping
SIO_PACKET_PONG = 3      # server → client: pong
SIO_PACKET_MESSAGE = 4   # either: message/event


class WSSClient:
    """
    Persistent Socket.IO WSS connection to IVASMS using raw aiohttp.

    Handles the Socket.IO v4 packet format directly:
      - HTTP polling handshake to get session SID
      - WebSocket upgrade with SID
      - Ping/pong keepalive
      - Event message parsing (type 4)
      - Jittered exponential backoff reconnect
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
        self._session: aiohttp.ClientSession | None = None

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
        self._session = aiohttp.ClientSession(
            headers={
                "User-Agent": "IVASMS-Forwarder-v2",
            }
        )

        try:
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

                # Jittered exponential backoff
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
        finally:
            if self._session and not self._session.closed:
                await self._session.close()

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
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("WSS client stopped")

    async def _get_sid(self) -> str:
        """Step 1: HTTP long-poll handshake to get the Socket.IO session ID."""
        base = settings.wss_base_url
        polling_url = base.replace("wss://", "https://").replace("ws://", "http://")
        # Ensure we have the path right
        if "/socket.io/" not in polling_url:
            polling_url = polling_url.rstrip("/") + "/socket.io/"

        params: dict[str, str] = {"EIO": "4", "transport": "polling"}
        if settings.ivasms_auth_token:
            params["token"] = settings.ivasms_auth_token
        if settings.ivasms_user_id:
            params["user"] = settings.ivasms_user_id

        async with self._session.get(polling_url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                raise ConnectionError(f"Socket.IO handshake failed: HTTP {resp.status}")
            text = await resp.text()
            # Socket.IO polling response format: "0{...sid...}" or "96{...}"
            # Strip any prefix bytes (engine.io length prefix)
            for i, ch in enumerate(text):
                if ch == '{':
                    text = text[i:]
                    break
            data = json.loads(text)
            sid = data.get("sid")
            if not sid:
                raise ConnectionError(f"No SID in handshake response: {data}")
            return sid

    async def _connect(self) -> None:
        """Establish the Socket.IO WebSocket connection."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "IVASMS-Forwarder-v2"}
            )

        # Step 1: Get session ID via HTTP polling
        sid = await self._get_sid()
        logger.info("Got Socket.IO SID: %s", sid[:16] + "...")

        # Step 2: WebSocket upgrade
        ws_url = settings.build_wss_url()
        if "sid=" not in ws_url:
            sep = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{sep}sid={sid}"

        logger.info("Connecting to IVASMS WSS...")

        async with self._session.ws_connect(
            ws_url,
            heartbeat=20.0,
            receive_timeout=30.0,
            timeout=aiohttp.ClientTimeout(total=15, sock_connect=10),
        ) as ws:
            # Send Socket.IO connect packet with auth
            connect_payload = json.dumps({
                "token": settings.ivasms_auth_token,
                "user": settings.ivasms_user_id,
            })
            await ws.send_str(f"{SIO_PACKET_MESSAGE}42{connect_payload}")

            self._connected = True
            self._connect_time = time.time()
            self._reconnect_delay = settings.reconnect_base_delay
            logger.info("✅ WSS connected to IVASMS (SID: %s)", sid[:16])
            await redis_store.incr_counter("wss_connections")

            # Listen for messages
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
        """Parse Socket.IO v4 packets and dispatch events."""
        if not raw:
            return

        # Socket.IO v4 packet format: "<type><data>"
        # type 0 = connect, 1 = disconnect, 2 = ping, 3 = pong, 4 = message
        packet_type = int(raw[0])
        payload = raw[1:]

        if packet_type == SIO_PACKET_PONG:
            # Server pong — connection alive
            return

        if packet_type == SIO_PACKET_PING:
            # Server ping — respond with pong
            # (aiohttp heartbeat handles this, but be safe)
            return

        if packet_type == SIO_PACKET_CLOSE:
            logger.warning("Server sent disconnect packet")
            return

        if packet_type == SIO_PACKET_MESSAGE:
            # Message packet: "42" prefix means event, "43" means ack
            if payload.startswith("2"):
                # Event: "42["event_name", data]
                event_data = payload[1:]
                try:
                    events = json.loads(event_data)
                    if isinstance(events, list) and len(events) >= 2:
                        event_name = events[0]
                        data = events[1]
                        await self._handle_event(event_name, data)
                    else:
                        # Single value, treat as raw data
                        await self._handle_event("message", events)
                except json.JSONDecodeError:
                    await self._handle_event("message", {"raw": event_data})
            elif payload.startswith("0"):
                # Connect acknowledgment
                logger.info("Socket.IO connected (server ack)")
            return

        # Unknown packet type — log but don't crash
        logger.debug("Unknown Socket.IO packet type %d: %s", packet_type, raw[:100])

    async def _handle_event(self, event_name: str, data: Any) -> None:
        """Handle incoming Socket.IO events with DLQ protection."""
        try:
            # Normalize data
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {"raw": data}

            if not isinstance(data, dict):
                data = {"payload": data, "event": event_name}

            # Add event name if not present
            if "event" not in data:
                data["event"] = event_name

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

            logger.debug("Received event '%s': %s", event_name, str(data)[:200])

            # Dispatch to the message handler
            await self._on_message(data)

        except asyncio.CancelledError:
            raise
        except json.JSONDecodeError as exc:
            self._dlq_count += 1
            logger.warning("Malformed JSON frame → DLQ: %s", exc)
            await redis_store.push_dlq(str(data), f"JSON parse error: {exc}")
            await redis_store.incr_counter("wss_malformed_frames")
        except Exception as exc:
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
                if self._connected:
                    logger.info("Refreshing WSS auth token...")
                    await redis_store.incr_counter("token_refreshes")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Token refresh error: %s", exc)
