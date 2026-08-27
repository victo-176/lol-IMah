"""Telegram bot: complete command hierarchy, multi-subscriber dispatch, wallet integration."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from . import redis_store
from .admin import router as admin_router
from .claim_manager import ClaimManager
from .config import settings
from .otp_parser import extract_otp, ParsedOTP
from .rate_limiter import TelegramRateLimiter
from .wallet import wallet_service
from .emoji import (
    BREAKING, CHECKMARK, CONTACT, COPY, DOLLAR, EXCLAMATION, FIRE,
    INFO, NEW_BADGE, PHONE, PLUS, REFRESH, SPEAKER, STAR, STATS,
    TELEGRAM, WHATSAPP, WITHDRAW, EARTH, PIN, LINK, CHAT,
)
try:
    from .emoji import COUNTRY_FLAGS
except ImportError:
    COUNTRY_FLAGS: dict[str, str] = {}  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ── Router & bot setup ──────────────────────────────────────────

router = Router()
router.include_router(admin_router)

_bot: Bot | None = None
_claim_manager = ClaimManager()
_rate_limiter: TelegramRateLimiter | None = None


def setup_bot() -> tuple[Bot, Dispatcher]:
    """Initialize the bot, dispatcher, and all handlers."""
    global _bot, _rate_limiter

    _bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    _rate_limiter = TelegramRateLimiter(
        send_fn=_bot.send_message,
        global_limit=settings.telegram_rate_limit_global,
        user_limit=settings.telegram_rate_limit_user,
    )
    _bot._rate_limiter = _rate_limiter  # type: ignore[attr-defined]

    return _bot, dp


def get_claim_manager() -> ClaimManager:
    return _claim_manager


def get_rate_limiter() -> TelegramRateLimiter | None:
    return _rate_limiter


# ═══════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Initialize user session and display main menu."""
    user = message.from_user
    if not user:
        return

    # Register user in DB and Redis
    db_user = await wallet_service.get_or_create_user(
        user.id, user.username, user.first_name
    )
    await redis_store.register_user_session(user.id, {
        "username": user.username,
        "first_name": user.first_name,
        "first_seen": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "balance": db_user.balance,
    })

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Browse Numbers", callback_data="menu:browse")],
        [InlineKeyboardButton(text="📋 My Active Claims", callback_data="menu:active")],
        [InlineKeyboardButton(text="💰 Balance & Top-up", callback_data="menu:balance")],
        [InlineKeyboardButton(text="💸 Withdraw", callback_data="menu:withdraw")],
        [InlineKeyboardButton(text="📖 Help", callback_data="menu:help")],
    ])

    await message.answer(
        f"{EARTH} <b>IVASMS Real-Time Forwarder</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Monitor IVASMS numbers and receive OTPs in\n"
        "real-time — to this group <b>and</b> directly to you.\n\n"
        f"{DOLLAR} Balance: <b>${db_user.balance:.2f}</b>\n"
        f"{STATS} OTPs received: <b>{db_user.otp_count}</b>\n\n"
        f"{CHAT} <b>Commands:</b>\n"
        f"  {TELEGRAM} /numbers — Browse & claim numbers\n"
        f"  {COPY} /active — View active claims\n"
        f"{REFRESH} /extend — Extend a claim\n"
        f"  /release — Release a number\n"
        f"  {DOLLAR} /balance — Check balance\n"
        f"  {WITHDRAW} /withdraw — Request payout\n"
        f"  /history — Transaction history\n"
        f"  {INFO} /help — Full command list",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await state.clear()


@router.message(Command("numbers", "get_number"))
async def cmd_numbers(message: Message) -> None:
    """Open interactive number browser."""
    await _show_number_browser(message)


@router.message(Command("active", "my_numbers"))
async def cmd_active(message: Message) -> None:
    """Show user's currently claimed numbers."""
    if not message.from_user:
        return

    claims = await _claim_manager.get_user_claims(message.from_user.id)
    if not claims:
        return    await message.answer(
        f"{COPY} <b>Active Claims</b>\n\n"
        "No active claims. Use /numbers to browse.",
        parse_mode="HTML",
    )

    lines = ["📋 <b>Your Active Claims</b>\n"]
    buttons: list[list[InlineKeyboardButton]] = []
    for c in claims:
        phone = c["phone"]
        mins = c["remaining_minutes"]
        secs = c["remaining_seconds"]
        subs = c.get("subscribers", 1)
        total = _claim_manager.ttl_seconds
        elapsed_pct = 1 - (secs / total) if total > 0 else 0
        bar_len = 10
        filled = int(bar_len * elapsed_pct)
        bar = "█" * filled + "░" * (bar_len - filled)

        lines.append(
            f"📱 <code>+{phone}</code>\n"
            f"   ⏳ {mins}m {secs % 60}s remaining\n"
            f"   {bar} {int(elapsed_pct * 100)}%\n"
            f"   👥 {subs} subscriber(s)\n"
        )
        buttons.append([
            InlineKeyboardButton(text=f"Extend +{phone}", callback_data=f"extend:{phone}"),
            InlineKeyboardButton(text=f"Release +{phone}", callback_data=f"release:{phone}"),
        ])

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.message(Command("extend"))
async def cmd_extend(message: Message, command: CommandObject) -> None:
    """Extend an active claim by 5 minutes."""
    if not message.from_user:
        return
    phone = (command.args or "").strip().lstrip("+")
    if not phone:
        return await message.answer("Usage: /extend <number>\nExample: /extend 23403930")

    extended = await _claim_manager.extend(phone, message.from_user.id, extra_seconds=300)
    if extended:
        await message.answer(f"✅ Extended <code>+{phone}</code> by 5 minutes.", parse_mode="HTML")
    else:
        await message.answer(f"ℹ️ No active claim on <code>+{phone}</code>.", parse_mode="HTML")


@router.message(Command("release"))
async def cmd_release(message: Message, command: CommandObject) -> None:
    """Release a claimed number."""
    if not message.from_user:
        return
    phone = (command.args or "").strip().lstrip("+")
    if not phone:
        return await message.answer("Usage: /release <number>")

    released = await _claim_manager.release(phone, message.from_user.id)
    if released:
        await message.answer(f"✅ Released <code>+{phone}</code>.", parse_mode="HTML")
        await redis_store.incr_counter("claims_released")
    else:
        await message.answer(f"ℹ️ No active claim on <code>+{phone}</code>.", parse_mode="HTML")


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    """Display user's account balance."""
    if not message.from_user:
        return
    user = await wallet_service.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )

    await message.answer(
        f"{DOLLAR} <b>Account Balance</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"   Balance: <b>${user.balance:.2f}</b>\n"
        f"   Total earned: ${user.total_earned:.2f}\n"
        f"   Total spent: ${user.total_spent:.2f}\n"
        f"   OTPs received: {user.otp_count}\n\n"
        f"  {NEW_BADGE} Top-up: /deposit\n"
        f"  {WITHDRAW} Withdraw: /withdraw",
        parse_mode="HTML",
    )


@router.message(Command("deposit"))
async def cmd_deposit(message: Message) -> None:
    """Show deposit options with crypto and local payment methods."""
    await message.answer(
        "💳 <b>Deposit Options</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Contact admin: /admin_help\n"
        "2️⃣ Crypto: Send USDT/LTC to admin\n"
        "3️⃣ Local: Bank transfer to admin\n\n"
        "Admin will credit your balance manually.\n"
        "Use /balance to check after deposit.",
        parse_mode="HTML",
    )


@router.message(Command("withdraw"))
async def cmd_withdraw(message: Message, command: CommandObject) -> None:
    """Request a withdrawal."""
    if not message.from_user:
        return

    args = (command.args or "").strip().split()
    if len(args) < 1:
        return await message.answer(
            "Usage: /withdraw <amount> [method]\n"
            "Methods: usdt, ltc, local\n\n"
            f"Minimum: ${settings.min_withdrawal_amount:.2f}"
        )

    try:
        amount = float(args[0])
    except ValueError:
        return await message.answer("Invalid amount. Usage: /withdraw 10.00 usdt")

    method = args[1] if len(args) > 1 else "usdt"

    success, msg = await wallet_service.request_withdrawal(
        message.from_user.id, amount, method
    )
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    """Show transaction history."""
    if not message.from_user:
        return

    txs = await wallet_service.get_transaction_history(message.from_user.id, limit=10)
    if not txs:
        return await message.answer("📊 No transactions yet.")

    lines = ["📊 <b>Transaction History</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"]
    for tx in txs:
        sign = "+" if tx["amount"] >= 0 else ""
        emoji = {"credit": "💰", "debit": "📤", "deposit": "💳", "withdrawal": "💸", "refund": "🔄"}.get(tx["type"], "📝")
        lines.append(
            f"{emoji} <code>{sign}${tx['amount']:.2f}</code> — {tx['type']}\n"
            f"   {tx['description']} | Balance: ${tx['balance_after']:.2f}\n"
            f"   🕒 {tx['date']}\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show command reference."""
    await message.answer(
        "📖 <b>IVASMS Bot — Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>User Commands:</b>\n"
        "/start — Main menu\n"
        "/numbers — Browse available numbers\n"
        "/active — View your active claims\n"
        "/extend &lt;number&gt; — Extend a claim (+5 min)\n"
        "/release &lt;number&gt; — Release a number\n"
        "/balance — Check account balance\n"
        "/withdraw &lt;amount&gt; — Request payout\n"
        "/history — Transaction history\n"
        "/help — This message\n\n"
        "<b>Admin Commands:</b>\n"
        "/stats — Live telemetry\n"
        "/broadcast &lt;msg&gt; — Notify all users\n"
        "/kick &lt;number&gt; — Force-release a number\n"
        "/block &lt;service&gt; — Block a service\n"
        "/unblock &lt;service&gt; — Unblock a service\n"
        "/filter &lt;country&gt; — Block country code\n"
        "/admin_help — Admin command list",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════
# CALLBACK QUERY HANDLERS
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data == "menu:browse")
async def cb_browse(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await _show_number_browser(callback.message)


@router.callback_query(F.data == "menu:active")
async def cb_active(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and isinstance(callback.message, Message) and callback.from_user:
        claims = await _claim_manager.get_user_claims(callback.from_user.id)
        if not claims:
            await callback.message.edit_text("📋 No active claims.\nUse /numbers to browse.")
        else:
            lines = [f"📋 <b>Active Claims</b> ({len(claims)})\n"]
            for c in claims:
                lines.append(
                    f"📱 <code>+{c['phone']}</code> — "
                    f"⏳ {c['remaining_minutes']}m remaining"
                )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Release +{c['phone']}", callback_data=f"release:{c['phone']}")]
                for c in claims
            ])
            await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "menu:balance")
async def cb_balance(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and isinstance(callback.message, Message) and callback.from_user:
        balance = await wallet_service.get_balance(callback.from_user.id)
        await callback.message.edit_text(
            f"💰 <b>Balance: ${balance:.2f}</b>\n\n"
            "💳 Use /deposit to top up",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:withdraw")
async def cb_withdraw(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "💸 <b>Withdrawal</b>\n\nUse: /withdraw &lt;amount&gt; [method]\n"
            "Methods: usdt, ltc, local\n"
            f"Minimum: ${settings.min_withdrawal_amount:.2f}",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:help")
async def cb_help(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "📖 Use /help for the full command list.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("claim:"))
async def cb_claim_number(callback: CallbackQuery) -> None:
    """Handle number claim confirmation."""
    if not callback.data or not callback.from_user:
        return await callback.answer("Error", show_alert=True)

    phone = callback.data.split(":", 1)[1]
    chat_id = callback.from_user.id

    success = await _claim_manager.claim(phone, chat_id)
    if success:
        await redis_store.incr_counter("active_claims")
        await redis_store.incr_counter("claims_created")
        ttl = _claim_manager.ttl_minutes

        text = (
            f"✅ <b>Number Claimed!</b>\n\n"
            f"📱 <code>+{phone}</code>\n"
            f"⏳ Session expires in <b>{ttl} minutes</b>\n\n"
            f"You'll receive OTPs for this number in your DM.\n"
            f"Use /extend +{phone} to add time."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 View Active Claims", callback_data="menu:active")],
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)  # type: ignore[union-attr]
    else:
        await callback.answer("⚠️ This number is already claimed.", show_alert=True)


@router.callback_query(F.data.startswith("release:"))
async def cb_release_number(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        return await callback.answer("Error", show_alert=True)

    phone = callback.data.split(":", 1)[1]
    released = await _claim_manager.release(phone, callback.from_user.id)
    if released:
        await callback.answer(f"✅ Released +{phone}")
        if callback.message and isinstance(callback.message, Message):
            await callback.message.edit_text(f"✅ Released <code>+{phone}</code>", parse_mode="HTML")
    else:
        await callback.answer("⚠️ Could not release.", show_alert=True)


@router.callback_query(F.data.startswith("extend:"))
async def cb_extend_number(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        return await callback.answer("Error", show_alert=True)

    phone = callback.data.split(":", 1)[1]
    extended = await _claim_manager.extend(phone, callback.from_user.id)
    if extended:
        await callback.answer(f"✅ Extended +{phone} by 5 min")
    else:
        await callback.answer("⚠️ No active claim to extend.", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# NUMBER BROWSER
# ═══════════════════════════════════════════════════════════════

# Sample number catalog — in production, pull from IVASMS API
_SAMPLE_NUMBERS = [
    {"phone": "23403930", "country": "🇺🇸 US", "service": "WhatsApp"},
    {"phone": "23403931", "country": "🇺🇸 US", "service": "Telegram"},
    {"phone": "23403932", "country": "🇬🇧 UK", "service": "Google"},
    {"phone": "23403933", "country": "🇩🇪 DE", "service": "Instagram"},
    {"phone": "23403934", "country": "🇵🇱 PL", "service": "TikTok"},
    {"phone": "23403935", "country": "🇰🇿 KZ", "service": "Discord"},
    {"phone": "23403936", "country": "🇦🇿 AZ", "service": "OpenAI"},
    {"phone": "23403937", "country": "🇺🇦 UA", "service": "Steam"},
    {"phone": "23403938", "country": "🇷🇺 RU", "service": "Netflix"},
    {"phone": "23403939", "country": "🇧🇷 BR", "service": "Amazon"},
]


async def _show_number_browser(message: Message) -> None:
    """Show interactive inline keyboard of available numbers."""
    lines = ["🔍 <b>Available Numbers</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"]
    keyboard_rows: list[list[InlineKeyboardButton]] = []

    for num in _SAMPLE_NUMBERS:
        claim_info = await _claim_manager.get_claim_info(num["phone"])
        status = "🟢 Available"
        if claim_info:
            status = f"🔴 Claimed ({claim_info['remaining_minutes']}m, {claim_info.get('subscribers', 1)} sub(s))"

        lines.append(
            f"📱 <code>+{num['phone']}</code> — {num['country']} | {num['service']}\n"
            f"   {status}\n"
        )
        if not claim_info:
            keyboard_rows.append([
                InlineKeyboardButton(text=f"Claim +{num['phone']}", callback_data=f"claim:{num['phone']}")
            ])

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )


# ═══════════════════════════════════════════════════════════════
# COPY OTP CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("copy_otp:"))
async def cb_copy_otp(callback: CallbackQuery) -> None:
    """Show the OTP code in an alert so the user can tap-to-copy."""
    if not callback.data:
        return
    code = callback.data.split(":", 1)[1]
    await callback.answer(
        text=f"🔑 Your OTP: {code}",
        show_alert=True,
    )


# ═══════════════════════════════════════════════════════════════
# MESSAGE FORMAT & DISPATCH
# ═══════════════════════════════════════════════════════════════


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


WATERMARK = "Anonmatrixx"
BOT_LINK = "https://t.me/Anon_MatrixxV3bot"


def format_group_message(phone: str, parsed: ParsedOTP, raw_body: str, sender: str | None = None) -> str:
    otp_line = f"{EXCLAMATION} OTP: <code>{parsed.code}</code>" if parsed.code else (
        f"{LINK} Magic Link" if parsed.is_magic_link else f"{INFO} No code detected"
    )
    sender_line = f"{CONTACT} Sender: {_escape_html(sender)}" if sender else ""
    return (
        f"{BREAKING} <b>[GLOBAL FEED] Inbound SMS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{PHONE} Target: <code>+{phone}</code>\n"
        f"{WHATSAPP} Service: {parsed.service}\n"
        f"{otp_line}\n"
        f"{sender_line}\n"
        f"{CHAT} Text: <i>{_escape_html(raw_body[:300])}</i>\n"
        f"{PIN} {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"\n<i>— {WATERMARK}</i>"
    )


def build_group_keyboard(otp_code: str | None) -> InlineKeyboardMarkup | None:
    """Build inline keyboard for group OTP messages:
    Row 1: [📋 Copy OTP]  (shows code in alert for copy)
    Row 2: [🔢 Get Number]  (links to t.me/Anon_MatrixxV3bot)
    """
    rows: list[list[InlineKeyboardButton]] = []
    if otp_code:
        rows.append([
            InlineKeyboardButton(
                text="📋 Copy OTP",
                callback_data=f"copy_otp:{otp_code}",
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔢 Get Number",
            url=BOT_LINK,
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_dm_message(phone: str, parsed: ParsedOTP, raw_body: str, remaining_seconds: int) -> str:
    mins = remaining_seconds // 60
    secs = remaining_seconds % 60
    otp_line = (
        f"{COPY} Code: <code>{parsed.code}</code>  <i>(Tap code to copy)</i>"
        if parsed.code
        else (f"{LINK} Magic Link Detected" if parsed.is_magic_link else "")
    )
    return (
        f"{FIRE} <b>[YOUR OTP RECEIVED]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{PHONE} Number: <code>+{phone}</code>\n"
        f"{otp_line}\n"
        f"{CHAT} Full Content: <i>{_escape_html(raw_body[:300])}</i>\n"
        f"{STATS} Claim Status: Active ({mins}m {secs}s remaining)\n"
        f"\n<i>— {WATERMARK}</i>"
    )


# ═══════════════════════════════════════════════════════════════
# MAIN DISPATCH FUNCTION (called by WSS handler)
# ═══════════════════════════════════════════════════════════════


async def dispatch_sms(
    bot: Bot,
    phone: str,
    body: str,
    sender: str | None = None,
    raw_data: dict | None = None,
) -> None:
    """
    Dual-target dispatch pipeline:
      1. Global broadcast to TELEGRAM_GROUP_ID (always)
      2. Multi-subscriber private DM delivery
    """
    parsed = extract_otp(body)

    if parsed.code:
        await redis_store.incr_counter("otps_parsed")

    # Check blocked services
    if parsed.service != "Unknown" and await redis_store.is_service_blocked(parsed.service):
        await redis_store.incr_counter("blocked_service_hits")
        return

    # Check blocked country
    country_prefix = phone[:2] if len(phone) >= 2 else ""
    if country_prefix and await redis_store.is_country_blocked(country_prefix):
        await redis_store.incr_counter("blocked_country_hits")
        return

    # ── Route A: Global Group Broadcast ────────────────────
    group_text = format_group_message(phone, parsed, body, sender)
    group_keyboard = build_group_keyboard(parsed.code)
    try:
        await bot.send_message(
            chat_id=settings.telegram_group_id,
            text=group_text,
            parse_mode="HTML",
            reply_markup=group_keyboard,
        )
        await redis_store.incr_counter("group_messages_sent")
    except Exception as exc:
        logger.error("Failed to send group message: %s", exc)

    # ── Route B: Multi-Subscriber Private DM ──────────────
    subscribers = await redis_store.get_subscribers(phone)
    if not subscribers:
        # Fallback to legacy single claim
        legacy_chat = await redis_store.get_claimed_chat_id(phone)
        if legacy_chat:
            subscribers = [legacy_chat]

    for chat_id in subscribers:
        remaining = await redis_store.get_claim_ttl(phone)
        dm_text = format_dm_message(phone, parsed, body, remaining)
        try:
            await bot.send_message(chat_id=chat_id, text=dm_text, parse_mode="HTML")
            await redis_store.incr_counter("dm_messages_sent")
            if parsed.code:
                await redis_store.incr_counter("otps_delivered")
                # Credit earnings for subscriber
                await wallet_service.credit_earnings(chat_id, phone)
        except Exception as exc:
            logger.error("Failed to send DM to %s: %s", chat_id, exc)

    # Log to database (best-effort)
    try:
        from .database import async_session_factory
        from .models import MessageLog

        async with async_session_factory() as session:
            log = MessageLog(
                phone_number=phone,
                sender=sender,
                body=body,
                otp_code=parsed.code,
                service_detected=parsed.service,
                delivered_to_group=True,
                delivered_to_user=len(subscribers) > 0,
                delivered_to_chat_ids=json.dumps(subscribers) if subscribers else None,
                raw_payload=str(raw_data) if raw_data else None,
            )
            session.add(log)
            await session.commit()
    except Exception as exc:
        logger.debug("Failed to log message to DB: %s", exc)
