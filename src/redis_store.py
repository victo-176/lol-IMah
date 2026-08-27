"""Redis-backed state store: caching, DLQ, subscriber registry, anti-fraud.

All public functions silently return safe defaults when Redis is unreachable
so the bot can run in degraded mode without crashing.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from .config import settings

logger = logging.getLogger(__name__)

_pool: aioredis.Redis | None = None
_connected = False  # Tracks whether Redis was ever reachable


def _is_available() -> bool:
    """Quick check: do we have a pool that might be connected?"""
    return _pool is not None and _connected


async def get_redis() -> aioredis.Redis:
    """Get or create the shared Redis connection pool."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
            retry_on_timeout=True,
        )
    return _pool


async def mark_connected() -> None:
    """Mark Redis as reachable (called from main after successful ping)."""
    global _connected
    _connected = True


async def mark_disconnected() -> None:
    """Mark Redis as unreachable."""
    global _connected
    _connected = False


async def close_redis() -> None:
    """Shut down the Redis connection pool."""
    global _pool, _connected
    _connected = False
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception:
            pass
        _pool = None


# ── Generic helpers (safe wrappers) ─────────────────────────────


async def set_key(key: str, value: str, ttl_seconds: int | None = None) -> None:
    try:
        r = await get_redis()
        if ttl_seconds:
            await r.set(key, value, ex=ttl_seconds)
        else:
            await r.set(key, value)
    except (RedisConnectionError, RedisError):
        pass


async def get_key(key: str) -> str | None:
    try:
        r = await get_redis()
        return await r.get(key)
    except (RedisConnectionError, RedisError):
        return None


async def delete_key(key: str) -> None:
    try:
        r = await get_redis()
        await r.delete(key)
    except (RedisConnectionError, RedisError):
        pass


async def key_exists(key: str) -> bool:
    try:
        r = await get_redis()
        return bool(await r.exists(key))
    except (RedisConnectionError, RedisError):
        return False


async def incr(key: str) -> int:
    try:
        r = await get_redis()
        return int(await r.incr(key))
    except (RedisConnectionError, RedisError):
        return 0


async def get_json(key: str) -> dict | None:
    try:
        r = await get_redis()
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
        return None
    except (RedisConnectionError, RedisError, json.JSONDecodeError, TypeError):
        return None


async def set_json(key: str, data: dict, ttl_seconds: int | None = None) -> None:
    try:
        r = await get_redis()
        payload = json.dumps(data)
        if ttl_seconds:
            await r.set(key, payload, ex=ttl_seconds)
        else:
            await r.set(key, payload)
    except (RedisConnectionError, RedisError):
        pass


# ── Deduplication ───────────────────────────────────────────────


async def is_duplicate(message_id: str) -> bool:
    """Return True if this message_id was already seen (TTL 10 min).
    Returns False (allow) when Redis is down so messages are never dropped."""
    try:
        r = await get_redis()
        key = f"ivasms:dedup:{message_id}"
        added = await r.set(key, "1", ex=600, nx=True)
        return added is None  # None means key already existed
    except (RedisConnectionError, RedisError):
        return False


# ── User Session Registry ───────────────────────────────────────


async def register_user_session(chat_id: int, data: dict, ttl_seconds: int = 86400 * 30) -> None:
    """Store user session info in Redis."""
    await set_json(f"ivasms:user:session:{chat_id}", data, ttl_seconds)


async def get_user_session(chat_id: int) -> dict | None:
    return await get_json(f"ivasms:user:session:{chat_id}")


async def update_user_session(chat_id: int, updates: dict) -> None:
    existing = await get_user_session(chat_id) or {}
    existing.update(updates)
    await set_json(f"ivasms:user:session:{chat_id}", existing, 86400 * 30)


# ── Multi-Subscriber Registry ──────────────────────────────────


async def subscribe_user(phone: str, chat_id: int, ttl_seconds: int) -> None:
    try:
        r = await get_redis()
        key = f"ivasms:number:subscribers:{phone}"
        pipe = r.pipeline()
        pipe.sadd(key, str(chat_id))
        pipe.expire(key, ttl_seconds)
        await pipe.execute()
    except (RedisConnectionError, RedisError):
        pass


async def unsubscribe_user(phone: str, chat_id: int) -> None:
    try:
        r = await get_redis()
        await r.srem(f"ivasms:number:subscribers:{phone}", str(chat_id))
    except (RedisConnectionError, RedisError):
        pass


async def get_subscribers(phone: str) -> list[int]:
    try:
        r = await get_redis()
        members = await r.smembers(f"ivasms:number:subscribers:{phone}")
        return [int(m) for m in members if m.isdigit()]
    except (RedisConnectionError, RedisError):
        return []


async def get_subscriber_count(phone: str) -> int:
    try:
        r = await get_redis()
        return int(await r.scard(f"ivasms:number:subscribers:{phone}"))
    except (RedisConnectionError, RedisError):
        return 0


async def is_subscribed(phone: str, chat_id: int) -> bool:
    try:
        r = await get_redis()
        return bool(await r.sismember(f"ivasms:number:subscribers:{phone}", str(chat_id)))
    except (RedisConnectionError, RedisError):
        return False


async def get_all_active_subscriptions() -> dict[str, list[int]]:
    try:
        r = await get_redis()
        keys: list[str] = []
        async for key in r.scan_iter("ivasms:number:subscribers:*"):
            keys.append(key)  # type: ignore[arg-type]
        result: dict[str, list[int]] = {}
        for key in keys:
            phone = key.split(":")[-1]  # type: ignore
            members = await r.smembers(key)
            result[phone] = [int(m) for m in members if m.isdigit()]
        return result
    except (RedisConnectionError, RedisError):
        return {}


# ── Legacy Claim Mapping (backward compat) ─────────────────────


async def claim_number(phone: str, chat_id: int, ttl_seconds: int) -> None:
    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.set(f"ivasms:claim:{phone}", str(chat_id), ex=ttl_seconds)
        pipe.sadd(f"ivasms:user_claims:{chat_id}", phone)
        pipe.expire(f"ivasms:user_claims:{chat_id}", ttl_seconds)
        await pipe.execute()
    except (RedisConnectionError, RedisError):
        pass


async def release_number(phone: str, chat_id: int | None = None) -> None:
    try:
        r = await get_redis()
        if chat_id is None:
            raw = await r.get(f"ivasms:claim:{phone}")
            chat_id = int(raw) if raw else None
        pipe = r.pipeline()
        pipe.delete(f"ivasms:claim:{phone}")
        if chat_id is not None:
            pipe.srem(f"ivasms:user_claims:{chat_id}", phone)
        await pipe.execute()
    except (RedisConnectionError, RedisError):
        pass


async def get_claimed_chat_id(phone: str) -> int | None:
    try:
        r = await get_redis()
        raw = await r.get(f"ivasms:claim:{phone}")
        return int(raw) if raw else None
    except (RedisConnectionError, RedisError):
        return None


async def get_user_claims(chat_id: int) -> list[str]:
    try:
        r = await get_redis()
        return [p for p in await r.smembers(f"ivasms:user_claims:{chat_id}") if p]
    except (RedisConnectionError, RedisError):
        return []


async def get_claim_ttl(phone: str) -> int:
    try:
        r = await get_redis()
        ttl = await r.ttl(f"ivasms:claim:{phone}")
        return max(ttl, 0)
    except (RedisConnectionError, RedisError):
        return 0


# ── Dead Letter Queue ──────────────────────────────────────────


async def push_dlq(payload: str, error_reason: str) -> None:
    try:
        r = await get_redis()
        entry = json.dumps({
            "payload": payload[:2000],
            "error": error_reason,
            "timestamp": time.time(),
        })
        await r.lpush("ivasms:dlq", entry)
        await r.ltrim("ivasms:dlq", 0, 999)
        await r.incr("ivasms:counter:dlq_messages")
    except (RedisConnectionError, RedisError):
        pass


async def pop_dlq(count: int = 10) -> list[dict]:
    try:
        r = await get_redis()
        results = []
        for _ in range(count):
            raw = await r.rpop("ivasms:dlq")
            if raw is None:
                break
            try:
                results.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return results
    except (RedisConnectionError, RedisError):
        return []


async def dlq_size() -> int:
    try:
        r = await get_redis()
        return int(await r.llen("ivasms:dlq"))
    except (RedisConnectionError, RedisError):
        return 0


# ── Rate limiter buckets ────────────────────────────────────────


async def check_rate_limit(key: str, max_count: int, window_seconds: int) -> bool:
    """Sliding-window rate limiter. Returns True (allow) when Redis is down."""
    try:
        r = await get_redis()
        now = time.time()
        window_start = now - window_seconds
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        count = results[2]
        return count <= max_count
    except (RedisConnectionError, RedisError):
        return True


# ── Blocked services/countries/users ────────────────────────────


async def add_blocked_service(service: str) -> None:
    try:
        r = await get_redis()
        await r.sadd("ivasms:blocked_services", service.lower())
    except (RedisConnectionError, RedisError):
        pass


async def remove_blocked_service(service: str) -> None:
    try:
        r = await get_redis()
        await r.srem("ivasms:blocked_services", service.lower())
    except (RedisConnectionError, RedisError):
        pass


async def is_service_blocked(service: str) -> bool:
    try:
        r = await get_redis()
        return bool(await r.sismember("ivasms:blocked_services", service.lower()))
    except (RedisConnectionError, RedisError):
        return False


async def add_blocked_country(code: str) -> None:
    try:
        r = await get_redis()
        await r.sadd("ivasms:blocked_countries", code.upper())
    except (RedisConnectionError, RedisError):
        pass


async def remove_blocked_country(code: str) -> None:
    try:
        r = await get_redis()
        await r.srem("ivasms:blocked_countries", code.upper())
    except (RedisConnectionError, RedisError):
        pass


async def is_country_blocked(code: str) -> bool:
    try:
        r = await get_redis()
        return bool(await r.sismember("ivasms:blocked_countries", code.upper()))
    except (RedisConnectionError, RedisError):
        return False


async def add_blocked_user(chat_id: int) -> None:
    try:
        r = await get_redis()
        await r.sadd("ivasms:blocked_users", str(chat_id))
    except (RedisConnectionError, RedisError):
        pass


async def remove_blocked_user(chat_id: int) -> None:
    try:
        r = await get_redis()
        await r.srem("ivasms:blocked_users", str(chat_id))
    except (RedisConnectionError, RedisError):
        pass


async def is_user_blocked(chat_id: int) -> bool:
    try:
        r = await get_redis()
        return bool(await r.sismember("ivasms:blocked_users", str(chat_id)))
    except (RedisConnectionError, RedisError):
        return False


async def get_blocked_services() -> set[str]:
    try:
        r = await get_redis()
        return await r.smembers("ivasms:blocked_services")
    except (RedisConnectionError, RedisError):
        return set()


async def get_blocked_countries() -> set[str]:
    try:
        r = await get_redis()
        return await r.smembers("ivasms:blocked_countries")
    except (RedisConnectionError, RedisError):
        return set()


# ── Anti-Fraud ──────────────────────────────────────────────────


async def check_fraud_limit(chat_id: int) -> bool:
    """Check if user has exceeded daily claim limit. Returns False (allow) when Redis is down."""
    try:
        r = await get_redis()
        key = f"ivasms:fraud:claims:{chat_id}:{int(time.time()) // 86400}"
        count = int(await r.incr(key))
        await r.expire(key, 86400 * 2)
        return count > settings.max_daily_claims
    except (RedisConnectionError, RedisError):
        return False


async def record_claim_ip(chat_id: int, ip: str) -> int:
    try:
        r = await get_redis()
        key = f"ivasms:fraud:ip:{ip}:{int(time.time()) // 86400}"
        count = int(await r.incr(key))
        await r.expire(key, 86400 * 2)
        user_key = f"ivasms:fraud:ip_users:{ip}:{int(time.time()) // 86400}"
        await r.sadd(user_key, str(chat_id))
        await r.expire(user_key, 86400 * 2)
        user_count = int(await r.scard(user_key))
        return user_count
    except (RedisConnectionError, RedisError):
        return 0


# ── Telemetry counters ──────────────────────────────────────────


async def incr_counter(name: str) -> int:
    try:
        r = await get_redis()
        return int(await r.incr(f"ivasms:counter:{name}"))
    except (RedisConnectionError, RedisError):
        return 0


async def get_counter(name: str) -> int:
    try:
        r = await get_redis()
        raw = await r.get(f"ivasms:counter:{name}")
        return int(raw) if raw else 0
    except (RedisConnectionError, RedisError):
        return 0


async def set_gauge(name: str, value: int) -> None:
    try:
        r = await get_redis()
        await r.set(f"ivasms:gauge:{name}", str(value))
    except (RedisConnectionError, RedisError):
        pass


async def get_gauge(name: str) -> int:
    try:
        r = await get_redis()
        raw = await r.get(f"ivasms:gauge:{name}")
        return int(raw) if raw else 0
    except (RedisConnectionError, RedisError):
        return 0
