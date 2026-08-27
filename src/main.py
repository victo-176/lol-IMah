"""Application entry point: wires WSS client, Telegram bot, and all subsystems."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

from aiohttp import web

from . import redis_store
from .bot import dispatch_sms, get_claim_manager, get_rate_limiter, setup_bot
from .claim_manager import ClaimManager
from .config import settings
from .database import close_db, init_db
from .otp_parser import extract_otp
from .wss_client import WSSClient

# ── Logging ──────────────────────────────────────────────────────

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s"
LOG_DATE = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATE,
        stream=sys.stdout,
    )
    for lib in ("aiogram", "engineio", "socketio", "aiohttp", "redis"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ── WSS → Bot bridge ────────────────────────────────────────────

_bot_ref = None


async def on_wss_message(data: dict[str, Any]) -> None:
    """Bridge: called by WSSClient for every inbound SMS event."""
    global _bot_ref

    if _bot_ref is None:
        logging.getLogger(__name__).error("Bot not initialized")
        return

    # Check if sender is blocked
    chat_id_from_data = data.get("chat_id")
    if chat_id_from_data and await redis_store.is_user_blocked(int(chat_id_from_data)):
        return

    phone = (
        data.get("phone") or data.get("target") or data.get("number")
        or data.get("to") or data.get("msisdn") or "unknown"
    )
    body = (
        data.get("body") or data.get("text") or data.get("message")
        or data.get("content") or str(data)
    )
    sender = data.get("sender") or data.get("from") or data.get("source") or data.get("sender_id")

    phone = str(phone).lstrip("+").strip()
    logger.info("Inbound SMS: phone=%s service=%s", phone, extract_otp(body).service)

    await dispatch_sms(bot=_bot_ref, phone=phone, body=body, sender=sender, raw_data=data)


# ── Graceful shutdown ───────────────────────────────────────────


async def shutdown(wss: WSSClient, dp: Any, bot: Any, cm: ClaimManager) -> None:
    log = logging.getLogger(__name__)
    log.info("Shutting down...")

    await wss.stop()
    await cm.stop_cleanup_loop()

    limiter = get_rate_limiter()
    if limiter:
        flushed = await limiter.flush()
        log.info("Flushed %d queued messages", flushed)
        await limiter.stop()

    await bot.session.close()
    await redis_store.close_redis()
    await close_db()
    log.info("Shutdown complete.")


# ── Health Check Server (for Railway port detection) ────────────


async def _health_handler(request: web.Request) -> web.Response:
    """Health check endpoint for Railway /load balancers."""
    return web.json_response({"status": "ok", "service": "ivasms-bot"})


async def start_health_server() -> tuple[web.AppRunner, web.TCPSite]:
    """Start a minimal HTTP server on $PORT (default 8080) for Railway."""
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/", _health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health check server listening on 0.0.0.0:%d", port)
    return runner, site


# ── Main ─────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


async def _wait_for_redis(max_attempts: int = 30, delay: float = 2.0) -> None:
    """Retry Redis connection with backoff. Non-fatal if it never connects."""
    import redis.asyncio as aioredis

    for attempt in range(1, max_attempts + 1):
        try:
            r = await redis_store.get_redis()
            await r.ping()
            await redis_store.mark_connected()
            logger.info("Redis connected ✓ (attempt %d)", attempt)
            return
        except Exception as exc:
            logger.warning("Redis attempt %d/%d failed: %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                await asyncio.sleep(delay)
    logger.error("Redis unavailable after %d attempts — running in degraded mode (no caching)", max_attempts)


async def main() -> None:
    global _bot_ref

    setup_logging()
    logger.info("=" * 60)
    logger.info("IVASMS WSS Real-Time Forwarder & Telegram Bot v2")
    logger.info("=" * 60)

    # ══ START HEALTH SERVER FIRST ══
    # Railway needs /health to respond immediately or it kills the container.
    health_runner, health_site = await start_health_server()

    # Validate config (non-fatal, log and continue)
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set — bot commands will not work")
    if not settings.ivasms_wss_url:
        logger.error("IVASMS_WSS_URL is not set — WSS stream will not connect")

    # Initialize database
    logger.info("Initializing database...")
    try:
        await init_db()
    except Exception as exc:
        logger.error("Database init failed: %s", exc)

    # Connect Redis with retry loop
    logger.info("Connecting to Redis...")
    await _wait_for_redis()

    # Setup Telegram bot (skip if no token)
    bot = None
    dp = None
    if settings.telegram_bot_token:
        logger.info("Setting up Telegram bot...")
        bot, dp = setup_bot()
        _bot_ref = bot

        # Start rate limiter
        limiter = get_rate_limiter()
        if limiter:
            limiter.start()

        # Start claim cleanup
        claim_manager = get_claim_manager()
        claim_manager.start_cleanup_loop()
    else:
        logger.warning("Skipping bot setup — no TELEGRAM_BOT_TOKEN")

    # Setup WSS client
    wss_client = WSSClient(on_message=on_wss_message)

    # Graceful shutdown on signals
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Received shutdown signal")
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task(loop):
                task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    # Run everything concurrently
    logger.info("Starting all subsystems...")
    tasks: list[asyncio.Task[None]] = []

    async def _run_wss() -> None:
        await wss_client.start()

    tasks.append(asyncio.create_task(_run_wss()))

    if dp and bot:
        async def _start_bot_polling() -> None:
            await dp.start_polling(bot)

        tasks.append(asyncio.create_task(_start_bot_polling()))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await health_runner.cleanup()
        if bot and dp:
            await shutdown(wss_client, dp, bot, get_claim_manager())
        else:
            await redis_store.close_redis()
            await close_db()


def run() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    run()
