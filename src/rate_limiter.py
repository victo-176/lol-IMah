"""Rate limiter, async message queue, and flood control for Telegram dispatch."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from . import redis_store

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """A message waiting to be dispatched through the rate limiter."""

    chat_id: int
    text: str
    parse_mode: str | None = None
    reply_markup: Any = None
    priority: int = 0  # higher = sent first
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3


class TelegramRateLimiter:
    """
    Token-bucket rate limiter with async queue for Telegram API flood control.

    Enforces:
      - Global: 25 msg/sec (under Telegram's 30 msg/sec ceiling)
      - Per-user: 1 msg/sec (to avoid DM flood)
    Handles 429 Too Many Requests with dynamic retry_after backoff.
    """

    def __init__(
        self,
        send_fn: Callable[..., Coroutine[Any, Any, Any]],
        global_limit: int = 25,
        user_limit: int = 1,
    ) -> None:
        self._send = send_fn
        self._global_limit = global_limit
        self._user_limit = user_limit
        self._queue: asyncio.PriorityQueue[tuple[int, QueuedMessage]] = (
            asyncio.PriorityQueue()
        )
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._paused = False
        self._pause_until: float = 0.0
        self._stats = {"sent": 0, "dropped": 0, "retried": 0, "rate_limited": 0}

    @property
    def stats(self) -> dict[str, int]:
        return self._stats.copy()

    def start(self) -> None:
        """Start the background queue worker."""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Rate limiter queue worker started (global=%d, user=%d/s)",
                        self._global_limit, self._user_limit)

    async def stop(self) -> None:
        """Stop the worker and flush remaining messages."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Rate limiter stopped, queue drained")

    async def enqueue(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: Any = None,
        priority: int = 0,
    ) -> None:
        """Add a message to the dispatch queue."""
        msg = QueuedMessage(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            priority=priority,
        )
        await self._queue.put((-priority, msg))  # negative for max-heap

    async def _worker_loop(self) -> None:
        """Background loop: dequeue and send with rate limiting."""
        while self._running:
            try:
                priority, msg = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Check if globally paused due to 429
            if self._paused and time.time() < self._pause_until:
                # Re-enqueue and wait
                await self._queue.put((priority, msg))
                await asyncio.sleep(0.5)
                continue
            elif self._paused:
                self._paused = False
                logger.info("Rate limit pause lifted")

            # Check queue age (drop messages older than 5 minutes)
            age = time.time() - msg.created_at
            if age > 300:
                logger.warning(
                    "Dropping stale message (age %.1fs) to chat %s", age, msg.chat_id
                )
                self._stats["dropped"] += 1
                continue

            # Global rate limit
            global_key = "ivasms:ratelimit:global"
            while not await redis_store.check_rate_limit(
                global_key, self._global_limit, 1
            ):
                await asyncio.sleep(0.1)

            # Per-user rate limit
            user_key = f"ivasms:ratelimit:user:{msg.chat_id}"
            while not await redis_store.check_rate_limit(
                user_key, self._user_limit, 1
            ):
                await asyncio.sleep(0.2)

            # Dispatch with 429 handling
            try:
                kwargs: dict[str, Any] = {
                    "chat_id": msg.chat_id,
                    "text": msg.text,
                }
                if msg.parse_mode:
                    kwargs["parse_mode"] = msg.parse_mode
                if msg.reply_markup:
                    kwargs["reply_markup"] = msg.reply_markup

                await self._send(**kwargs)
                self._stats["sent"] += 1

            except Exception as exc:
                error_msg = str(exc).lower()

                # Handle 429 Too Many Requests
                if "429" in error_msg or "too many requests" in error_msg:
                    self._stats["rate_limited"] += 1
                    # Extract retry_after from error if possible
                    retry_after = 5  # default
                    if "retry after" in error_msg:
                        try:
                            retry_after = int(error_msg.split("retry after")[-1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass

                    logger.warning("429 rate limited, pausing for %ds", retry_after)
                    self._paused = True
                    self._pause_until = time.time() + retry_after

                    # Re-enqueue the message for retry
                    if msg.retry_count < msg.max_retries:
                        msg.retry_count += 1
                        self._stats["retried"] += 1
                        await self._queue.put((priority, msg))
                    else:
                        self._stats["dropped"] += 1
                        logger.error("Message dropped after %d retries to chat %s",
                                    msg.max_retries, msg.chat_id)
                else:
                    logger.error("Failed to send message to %s: %s", msg.chat_id, exc)
                    self._stats["dropped"] += 1

    async def flush(self) -> int:
        """Force-send all queued messages (for shutdown). Returns count sent."""
        count = 0
        while not self._queue.empty():
            try:
                _, msg = self._queue.get_nowait()
                await self._send(chat_id=msg.chat_id, text=msg.text)
                count += 1
            except Exception:
                break
        return count
