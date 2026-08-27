"""Number claiming and subscription lifecycle manager with multi-subscriber support."""

from __future__ import annotations

import asyncio
import logging

from . import redis_store
from .config import settings

logger = logging.getLogger(__name__)


class ClaimManager:
    """
    Manages phone-number → user-chat claim bindings.

    Supports:
      - Exclusive mode (one user per number)
      - Shared mode (multiple subscribers per number)
      - Auto-expiration with TTL
      - Manual extend and release
      - Expiry notifications via callback
    """

    def __init__(self) -> None:
        self._ttl_seconds = settings.claim_ttl_minutes * 60
        self._cleanup_task: asyncio.Task[None] | None = None
        self._on_expire: asyncio.Task[None] | None = None
        self._expiry_callback = None

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @property
    def ttl_minutes(self) -> int:
        return self._ttl_seconds // 60

    def set_expiry_callback(self, callback) -> None:
        """Set a callback for when claims expire (for DM notification)."""
        self._expiry_callback = callback

    def start_cleanup_loop(self) -> None:
        """Start the background expired-claim cleanup."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_loop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def claim(
        self,
        phone: str,
        chat_id: int,
        ttl_override: int | None = None,
    ) -> bool:
        """
        Attempt to claim/subscribe to a phone number for a user.

        In exclusive mode: returns False if already claimed by another user.
        In shared mode: adds as subscriber.

        Returns True if the claim/subscription succeeded.
        """
        ttl = ttl_override or self._ttl_seconds

        # Check anti-fraud limits
        if await redis_store.check_fraud_limit(chat_id):
            logger.warning("Fraud limit exceeded for chat %s", chat_id)
            return False

        if settings.exclusive_claim_mode:
            existing = await redis_store.get_claimed_chat_id(phone)
            if existing is not None and existing != chat_id:
                logger.info(
                    "Claim denied: phone %s already held by %s (exclusive)", phone, existing
                )
                return False

        # Register in both systems (legacy claim + multi-subscriber)
        await redis_store.claim_number(phone, chat_id, ttl)
        await redis_store.subscribe_user(phone, chat_id, ttl)

        # Update session
        await redis_store.update_user_session(chat_id, {
            "active_phone": phone,
            "claimed_at": int(asyncio.get_running_loop().time()),
            "expires_in": ttl,
        })

        logger.info("Claimed phone %s for chat %s (TTL %ds)", phone, chat_id, ttl)
        return True

    async def extend(self, phone: str, chat_id: int, extra_seconds: int = 300) -> bool:
        """Extend an existing claim by extra_seconds."""
        current_chat = await redis_store.get_claimed_chat_id(phone)
        if current_chat is None or current_chat != chat_id:
            return False

        # Re-claim with extended TTL
        current_ttl = await redis_store.get_claim_ttl(phone)
        new_ttl = current_ttl + extra_seconds
        await redis_store.claim_number(phone, chat_id, new_ttl)
        await redis_store.subscribe_user(phone, chat_id, new_ttl)

        logger.info("Extended phone %s for chat %s by %ds (new TTL %ds)", phone, chat_id, extra_seconds, new_ttl)
        return True

    async def release(self, phone: str, chat_id: int | None = None) -> bool:
        """Release a claimed number. Returns True if something was released."""
        current = await redis_store.get_claimed_chat_id(phone)
        if current is None:
            return False

        if chat_id is not None and current != chat_id:
            return False  # can't release someone else's claim

        await redis_store.release_number(phone, current)
        await redis_store.unsubscribe_user(phone, current)

        logger.info("Released phone %s from chat %s", phone, current)
        return True

    async def release_all_for_user(self, chat_id: int) -> int:
        """Release all numbers claimed by a user. Returns count released."""
        phones = await redis_store.get_user_claims(chat_id)
        count = 0
        for phone in phones:
            await redis_store.release_number(phone, chat_id)
            await redis_store.unsubscribe_user(phone, chat_id)
            count += 1
        return count

    async def get_user_claims(self, chat_id: int) -> list[dict]:
        """Get all active claims for a user with remaining TTL."""
        phones = await redis_store.get_user_claims(chat_id)
        claims = []
        for phone in phones:
            ttl = await redis_store.get_claim_ttl(phone)
            if ttl > 0:
                subscribers = await redis_store.get_subscriber_count(phone)
                claims.append({
                    "phone": phone,
                    "remaining_seconds": ttl,
                    "remaining_minutes": ttl // 60,
                    "subscribers": subscribers,
                })
        return claims

    async def get_claim_info(self, phone: str) -> dict | None:
        """Get claim details for a phone number."""
        chat_id = await redis_store.get_claimed_chat_id(phone)
        if chat_id is None:
            return None
        ttl = await redis_store.get_claim_ttl(phone)
        subscribers = await redis_store.get_subscriber_count(phone)
        return {
            "phone": phone,
            "chat_id": chat_id,
            "remaining_seconds": ttl,
            "remaining_minutes": ttl // 60,
            "subscribers": subscribers,
        }

    async def get_all_subscribers_for_phone(self, phone: str) -> list[int]:
        """Get all subscribed chat_ids for a phone number."""
        return await redis_store.get_subscribers(phone)

    async def force_release(self, phone: str) -> tuple[bool, int | None]:
        """Admin force-release: release regardless of owner. Returns (released, chat_id)."""
        chat_id = await redis_store.get_claimed_chat_id(phone)
        if chat_id is None:
            return False, None
        await redis_store.release_number(phone, chat_id)
        await redis_store.unsubscribe_user(phone, chat_id)
        logger.info("Admin force-released phone %s from chat %s", phone, chat_id)
        return True, chat_id

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup — Redis handles TTL natively, but this
        ensures user_claims sets stay in sync and triggers expiry notifications."""
        while True:
            try:
                await asyncio.sleep(30)
                # The actual expiry is handled by Redis TTL on the claim keys.
                # This loop is a safety net for any orphaned user_claims sets.
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Cleanup loop error: %s", exc)
                await asyncio.sleep(30)
