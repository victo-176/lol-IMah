"""Admin control panel with full management controls."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from . import redis_store
from .config import settings

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(chat_id: int) -> bool:
    return chat_id in settings.telegram_admin_ids


# ── /stats (admin) ─────────────────────────────────────────────


@router.message(Command("stats", "admin_stats"))
async def cmd_stats(message: Message, command: CommandObject) -> None:
    """Display real-time WSS telemetry and global throughput."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    msgs_received = await redis_store.get_counter("wss_messages_received")
    wss_conns = await redis_store.get_counter("wss_connections")
    wss_reconn = await redis_store.get_counter("wss_reconnect_attempts")
    wss_errors = await redis_store.get_counter("wss_errors")
    wss_dupes = await redis_store.get_counter("wss_duplicates_skipped")
    otps_parsed = await redis_store.get_counter("otps_parsed")
    otps_delivered = await redis_store.get_counter("otps_delivered")
    group_msgs = await redis_store.get_counter("group_messages_sent")
    dm_msgs = await redis_store.get_counter("dm_messages_sent")
    claims_created = await redis_store.get_counter("claims_created")
    claims_released = await redis_store.get_counter("claims_released")
    blocked_svc = await redis_store.get_counter("blocked_service_hits")
    blocked_ctry = await redis_store.get_counter("blocked_country_hits")
    dlq_msgs = await redis_store.dlq_size()
    malformed = await redis_store.get_counter("wss_malformed_frames")

    blocked_services = await redis_store.get_blocked_services()
    blocked_countries = await redis_store.get_blocked_countries()

    limiter_stats = getattr(message.bot, "_rate_limiter_stats", {"sent": 0, "dropped": 0})  # type: ignore[union-attr]

    await message.answer(
        "📊 <b>IVASMS Bot — Live Telemetry</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔌 <b>WSS Connection</b>\n"
        f"   Connections: {wss_conns}\n"
        f"   Reconnects: {wss_reconn}\n"
        f"   Errors: {wss_errors}\n\n"
        f"📨 <b>Message Pipeline</b>\n"
        f"   Received: {msgs_received}\n"
        f"   Duplicates: {wss_dupes}\n"
        f"   Malformed: {malformed}\n"
        f"   OTPs parsed: {otps_parsed}\n"
        f"   OTPs delivered: {otps_delivered}\n\n"
        f"📤 <b>Telegram Dispatch</b>\n"
        f"   Group: {group_msgs}\n"
        f"   DMs: {dm_msgs}\n"
        f"   Queue sent: {limiter_stats.get('sent', 0)}\n"
        f"   Queue dropped: {limiter_stats.get('dropped', 0)}\n\n"
        f"📋 <b>Claims</b>\n"
        f"   Created: {claims_created}\n"
        f"   Released: {claims_released}\n\n"
        f"🚫 <b>Filters</b>\n"
        f"   Blocked services: {', '.join(blocked_services) or 'none'}\n"
        f"   Blocked countries: {', '.join(blocked_countries) or 'none'}\n"
        f"   Service hits: {blocked_svc}\n"
        f"   Country hits: {blocked_ctry}\n\n"
        f"📮 <b>Dead Letter Queue</b>: {dlq_msgs} pending",
        parse_mode="HTML",
    )


# ── /broadcast (admin) ─────────────────────────────────────────


@router.message(Command("broadcast", "admin_broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject) -> None:
    """Send a global notification to the group."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    text = command.args
    if not text:
        return await message.answer("Usage: /broadcast <message>")

    try:
        await message.bot.send_message(
            chat_id=settings.telegram_group_id,
            text=f"📢 <b>System Announcement</b>\n\n{text}",
            parse_mode="HTML",
        )
        await message.answer(f"✅ Broadcast sent.")
    except Exception as exc:
        await message.answer(f"❌ Broadcast failed: {exc}")


# ── /kick (admin) ──────────────────────────────────────────────


@router.message(Command("kick", "admin_release", "kick_claim"))
async def cmd_kick(message: Message, command: CommandObject) -> None:
    """Force-release a claimed number."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    phone = (command.args or "").strip().lstrip("+")
    if not phone:
        return await message.answer("Usage: /kick <phone_number>")

    from .claim_manager import ClaimManager
    cm = ClaimManager()
    released, chat_id = await cm.force_release(phone)
    if released:
        await message.answer(f"✅ Force-released +{phone} (was held by {chat_id})")
        # Notify the displaced user
        try:
            await message.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Your claim on <code>+{phone}</code> was forcibly released by an admin.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await message.answer(f"ℹ️ +{phone} is not currently claimed.")


# ── /block (admin) ─────────────────────────────────────────────


@router.message(Command("block", "admin_block_service"))
async def cmd_block(message: Message, command: CommandObject) -> None:
    """Block a service from being parsed/delivered."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    service = (command.args or "").strip()
    if not service:
        return await message.answer("Usage: /block <service_name>")

    await redis_store.add_blocked_service(service)
    await message.answer(f"🚫 Service '{service}' blocked.")


# ── /unblock (admin) ───────────────────────────────────────────


@router.message(Command("unblock", "admin_unblock_service"))
async def cmd_unblock(message: Message, command: CommandObject) -> None:
    """Unblock a previously blocked service."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    service = (command.args or "").strip()
    if not service:
        return await message.answer("Usage: /unblock <service_name>")

    await redis_store.remove_blocked_service(service)
    await message.answer(f"✅ Service '{service}' unblocked.")


# ── /filter (admin) ────────────────────────────────────────────


@router.message(Command("filter", "admin_filter_country"))
async def cmd_filter(message: Message, command: CommandObject) -> None:
    """Block SMS from a specific country code."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    code = (command.args or "").strip().upper()
    if not code:
        return await message.answer("Usage: /filter <XX>")

    await redis_store.add_blocked_country(code)
    await message.answer(f"🚫 Country '{code}' filtered.")


# ── /unfilter (admin) ──────────────────────────────────────────


@router.message(Command("unfilter", "admin_unfilter_country"))
async def cmd_unfilter(message: Message, command: CommandObject) -> None:
    """Remove a country filter."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    code = (command.args or "").strip().upper()
    if not code:
        return await message.answer("Usage: /unfilter <XX>")

    await redis_store.remove_blocked_country(code)
    await message.answer(f"✅ Country '{code}' unfiltered.")


# ── /ban (admin) ───────────────────────────────────────────────


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject) -> None:
    """Ban a user by chat_id."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    target = (command.args or "").strip()
    if not target or not target.isdigit():
        return await message.answer("Usage: /ban <chat_id>")

    chat_id = int(target)
    await redis_store.add_blocked_user(chat_id)
    await message.answer(f"🚫 User {chat_id} banned.")


# ── /unban (admin) ─────────────────────────────────────────────


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject) -> None:
    """Unban a user."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    target = (command.args or "").strip()
    if not target or not target.isdigit():
        return await message.answer("Usage: /unban <chat_id>")

    chat_id = int(target)
    await redis_store.remove_blocked_user(chat_id)
    await message.answer(f"✅ User {chat_id} unbanned.")


# ── /dlq (admin) ───────────────────────────────────────────────


@router.message(Command("dlq"))
async def cmd_dlq(message: Message, command: CommandObject) -> None:
    """Inspect Dead Letter Queue."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    size = await redis_store.dlq_size()
    entries = await redis_store.pop_dlq(5)

    if not entries:
        return await message.answer(f"📮 DLQ is empty (size: {size})")

    lines = [f"📮 <b>Dead Letter Queue</b> ({size} total, showing {len(entries)}):\n"]
    for i, entry in enumerate(entries, 1):
        lines.append(
            f"<b>{i}.</b> Error: <code>{entry.get('error', '?')[:100]}</code>\n"
            f"   Payload: <code>{entry.get('payload', '?')[:100]}</code>\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /withdrawals (admin) ───────────────────────────────────────


@router.message(Command("withdrawals"))
async def cmd_withdrawals(message: Message, command: CommandObject) -> None:
    """View pending withdrawal requests."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    from .wallet import wallet_service
    requests = await wallet_service.get_withdrawal_requests("pending")

    if not requests:
        return await message.answer("💸 No pending withdrawal requests.")

    lines = ["💸 <b>Pending Withdrawals</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"]
    for req in requests:
        lines.append(
            f"#{req['id']} — ${req['amount']:.2f} via {req['method']}\n"
            f"   User: {req['chat_id']} | {req['date']}\n"
            f"   Approve: /approve_{req['id']}\n"
            f"   Reject: /reject_{req['id']}\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("approve"))
async def cmd_approve(message: Message, command: CommandObject) -> None:
    """Approve a withdrawal request."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    rid = (command.args or "").strip().lstrip("_").replace("approve_", "")
    if not rid or not rid.isdigit():
        return await message.answer("Usage: /approve_<request_id>")

    from .wallet import wallet_service
    ok = await wallet_service.approve_withdrawal(int(rid), message.chat.id)
    if ok:
        await message.answer(f"✅ Withdrawal #{rid} approved.")
    else:
        await message.answer(f"ℹ️ Withdrawal #{rid} not found or already processed.")


@router.message(Command("reject"))
async def cmd_reject(message: Message, command: CommandObject) -> None:
    """Reject a withdrawal request and refund."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    rid = (command.args or "").strip().lstrip("_").replace("reject_", "")
    if not rid or not rid.isdigit():
        return await message.answer("Usage: /reject_<request_id>")

    from .wallet import wallet_service
    ok = await wallet_service.reject_withdrawal(int(rid), message.chat.id)
    if ok:
        await message.answer(f"✅ Withdrawal #{rid} rejected and refunded.")
    else:
        await message.answer(f"ℹ️ Withdrawal #{rid} not found or already processed.")


# ── /admin_help ─────────────────────────────────────────────────


@router.message(Command("admin_help"))
async def cmd_admin_help(message: Message, command: CommandObject) -> None:
    """Show admin command reference."""
    if not _is_admin(message.chat.id):
        return await message.answer("⛔ Admin access required.")

    await message.answer(
        "🔧 <b>Admin Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "/stats — Live telemetry & metrics\n"
        "/broadcast &lt;msg&gt; — Notify all users\n"
        "/kick &lt;number&gt; — Force-release a number\n"
        "/block &lt;service&gt; — Block a service\n"
        "/unblock &lt;service&gt; — Unblock a service\n"
        "/filter &lt;country&gt; — Block country code\n"
        "/unfilter &lt;country&gt; — Unblock country\n"
        "/ban &lt;chat_id&gt; — Ban a user\n"
        "/unban &lt;chat_id&gt; — Unban a user\n"
        "/dlq — Inspect Dead Letter Queue\n"
        "/withdrawals — View pending withdrawals\n"
        "/approve_&lt;id&gt; — Approve withdrawal\n"
        "/reject_&lt;id&gt; — Reject withdrawal\n"
        "/admin_help — This message",
        parse_mode="HTML",
    )
