#!/usr/bin/env python3
"""
TEMP NUMBERS API OTP FORWARDER — standalone sub-bot
===================================================
Polls the Temp Numbers stats API:

    http://147.135.212.197/crapi/st/viewstats
        ?token=SVVWR0VBUzRWV4tmiIFrXGVQckV8Vo90gIN3iWZxlH1VlVVzaFZxQw==
        &records=10

which returns a JSON array of rows:

    [service, number, message_text, timestamp]
    [["WhatsApp", "2347020296087",
      "Your WhatsApp code 734-622Dont share this code with others",
      "2026-10-07 08:45:49"], ...]

Every NEW row (deduplicated, existing rows skipped on startup) is forwarded
to the configured Telegram OTP group(s) in the shared reference format via
premium_emoji.build_otp_group_message():

    {premium flag} #{ISO} {app icon} +2347●○●○6087
    [ green full-width: {app icon} ⧉ Service | <real OTP>  (copy_text) ]
    [ blue NUMBER ] [ blue CHANNEL ]

The same message can also be delivered straight to the owner's chat when
FORWARD_USER_ID is configured.

Usage:
    python temp_numbers_api_forwarder.py        # standalone
    import temp_numbers_api_forwarder as f; f.run()   # as a thread (bot.py)

Configuration — env var first, then the bot database (bot_settings), so
nothing has to be hardcoded:

    TEMP_API_URL         API endpoint (default: the viewstats URL above)
    TEMP_API_TOKEN       API token
    TEMP_API_RECORDS     how many records to pull per poll (default: 10)
    TEMP_API_FORWARDER   set to 0/off to disable the forwarder thread
    POLL_INTERVAL        poll seconds (default 7)
    DB_PATH              bot database path (default /app/data/bot.db)
    BOT_TOKEN            Telegram bot token (else bot_settings bot_token)
    FORWARD_USER_ID      Telegram user id that also receives the OTPs

Importing this module never touches the network and never exits: config
validation happens in main()/run(), so bot.py can safely import it.
"""

import json
import logging
import os
import re
import sqlite3
import sys
import time

import requests

# Premium emoji ids + the shared group format. Kept import-safe (no telebot).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from premium_emoji import (  # noqa: E402
    DEFAULT_BOT_LINK,
    DEFAULT_CHANNEL_LINK,
    build_otp_group_message,
    kb_without_copy,
    premiumize,
)

# =========================== CONFIG ===========================
PANEL_NAME = "TEMP NUMBERS API"

DEFAULT_API_URL = "http://147.135.212.197/crapi/st/viewstats"
DEFAULT_API_TOKEN = (
    "SVVWR0VBUzRWV4tmiIFrXGVQckV8Vo90gIN3iWZxlH1VlVVzaFZxQw=="
)

API_URL = os.environ.get("TEMP_API_URL", DEFAULT_API_URL).strip()
API_TOKEN = os.environ.get("TEMP_API_TOKEN", DEFAULT_API_TOKEN).strip()
try:
    RECORDS = max(1, min(200, int(os.environ.get("TEMP_API_RECORDS", "10"))))
except ValueError:
    RECORDS = 10
try:
    POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "7"))
except ValueError:
    POLL_INTERVAL = 7.0
REQUEST_TIMEOUT = 30

# Telegram Bot API root. Overridable so delivery can be tested locally.
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")

PERSISTENT_DIR = os.environ.get("PERSISTENT_DIR", "/app/data/")
DB_PATH = os.environ.get("DB_PATH", os.path.join(PERSISTENT_DIR, "bot.db"))

# =========================== DATABASE ===========================


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_setting(key, default=None):
    try:
        with _db() as conn:
            r = conn.execute(
                "SELECT value FROM bot_settings WHERE key=?", (key,)
            ).fetchone()
            return r["value"] if r else default
    except Exception:
        return default


def get_bot_token():
    return os.environ.get("BOT_TOKEN") or get_setting("bot_token")


def get_bot_link():
    return get_setting("bot_link") or DEFAULT_BOT_LINK


def get_channel_link():
    return get_setting("channel_link") or DEFAULT_CHANNEL_LINK


def get_forward_user_id():
    """Telegram user id that should receive OTPs directly (optional)."""
    return os.environ.get("FORWARD_USER_ID") or get_setting("forward_user_id")


def get_otp_groups():
    raw = get_setting("otp_groups", "[]") or "[]"
    try:
        groups = [int(g) for g in json.loads(raw)]
    except Exception:
        groups = []
    if not groups:
        default_grp = get_setting("default_otp_group")
        if default_grp:
            try:
                groups = [int(default_grp)]
            except (TypeError, ValueError):
                groups = []
    return groups


# Resolved once per process; tests may patch these directly.
BOT_TOKEN = get_bot_token()
OTP_GROUPS = get_otp_groups()
FORWARD_USER = get_forward_user_id()

# =========================== SETUP ===========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TEMP-API] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# =========================== PARSING ===========================

# Same extractor the main bot uses, so the API rows and the scraped panel
# rows agree on what an OTP looks like ("code 734-622", "code: 241626", ...).
_OTP_PATTERNS = [
    r'(?:code|رمز|كود|verification|تحقق|otp|pin)[:\s]+[\u200e]?(\d{3,8}(?:[- ]\d{3,4})?)',
    r'(\d{3})[- ](\d{3,4})',
    r'\b(\d{4,8})\b',
    r'[\u200e](\d{3,8})',
]


def extract_otp(text):
    """The verification code inside an SMS body ('' when there is none)."""
    text = str(text or "")
    for pat in _OTP_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if len(m.groups()) > 1:
                return "".join(g or "" for g in m.groups()).replace(" ", "")
            return (m.group(1) or "").replace(" ", "").replace("-", "")
    return ""


def _clean_service(service):
    """Tidy the API's service/cli column for the message body."""
    s = re.sub(r"<[^>]+>", "", str(service or ""))
    s = re.sub(r"[\r\n\t]+", " ", s).strip()
    return s[:60]


def parse_records(data):
    """API payload -> list of sms dicts ({service, number, otp, full_text, timestamp}).

    Accepts both the documented list rows `[service, number, text, time]`
    and dict rows (`{service/cli, number/phone, message/text/content, time}`),
    so a payload change on the API side degrades instead of crashing.
    """
    rows = []
    if not isinstance(data, list):
        return rows
    for rec in data:
        if isinstance(rec, dict):
            service = (rec.get("service") or rec.get("cli")
                       or rec.get("sender") or "Unknown")
            number = (rec.get("number") or rec.get("phone")
                       or rec.get("num") or "N/A")
            text = (rec.get("message") or rec.get("text")
                    or rec.get("content") or "")
            ts = (rec.get("time") or rec.get("timestamp") or rec.get("date")
                  or rec.get("dt") or "")
        elif isinstance(rec, (list, tuple)) and len(rec) >= 3:
            service = rec[0]
            number = rec[1]
            text = rec[2]
            ts = rec[3] if len(rec) > 3 else ""
        else:
            continue
        text = str(text)
        rows.append({
            "service": _clean_service(service) or "Unknown",
            "number": str(number or "N/A"),
            "otp": extract_otp(text),
            "full_text": text[:500],
            "timestamp": str(ts or ""),
        })
    return rows


def fetch_records():
    """One API call -> parsed rows. Raises on network/JSON problems."""
    resp = requests.get(
        API_URL,
        params={"token": API_TOKEN, "records": RECORDS},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return parse_records(resp.json())


# =========================== TELEGRAM ===========================


def _tg_send(chat_id, text, reply_markup=None):
    """POST one message; returns True on success. Never raises."""
    # Raw API post, so nothing else upgrades these emoji: do it here or the
    # OTP groups get plain unicode while the bot's own messages are premium.
    payload = {"chat_id": chat_id, "text": premiumize(text), "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(
            f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage",
            data=payload, timeout=15,
        )
        if r.status_code == 200:
            return True
        logger.warning("Telegram send to %s failed: HTTP %s — %s",
                       chat_id, r.status_code, (r.text or "")[:120])
    except Exception as exc:
        logger.error("Telegram send to %s error: %s", chat_id, exc)
    return False


def send_to_groups(text, reply_markup=None, otp=""):
    """Send the OTP to every configured OTP group.

    If a group rejects the copy_text button, retry once with the same
    keyboard downgraded to a `copy_<otp>` callback so the OTP still lands.
    """
    sent = 0
    for gid in OTP_GROUPS:
        ok = _tg_send(gid, text, reply_markup)
        if not ok and reply_markup:
            fallback = kb_without_copy(reply_markup, otp)
            if fallback != reply_markup:
                ok = _tg_send(gid, text, fallback)
        if ok:
            sent += 1
            logger.info("Group %s: sent", gid)
    return sent > 0


def forward_to_main_bot(text, otp_code):
    """Send the OTP straight to the owner's chat, with a copy button."""
    if not FORWARD_USER:
        return False
    kb = {"inline_keyboard": [[
        {"text": f"\U0001F4CB {otp_code}", "callback_data": f"copy_{otp_code}"},
        {"text": "\U0001F916 BOT", "url": get_bot_link()},
    ]]}
    try:
        ok = _tg_send(int(FORWARD_USER), text, kb)
        if ok:
            logger.info("Forwarded to main bot user %s", FORWARD_USER)
        return ok
    except (TypeError, ValueError):
        logger.error("FORWARD_USER_ID is not a valid id: %r", FORWARD_USER)
        return False


def send_otp(sms):
    """Format and deliver one OTP to the group(s) and the owner's chat."""
    service = _clean_service(sms.get("service")) or PANEL_NAME
    phone = sms.get("number") or "N/A"
    otp = str(sms.get("otp") or "").strip()
    if not otp:
        logger.debug("No OTP in row (%s) — skipping", sms.get("full_text", "")[:60])
        return False

    # Same reference format the main bot posts: flag + #ISO + app icon +
    # watermark number, green copy button carrying the real OTP, blue
    # NUMBER/CHANNEL links — every button with its premium icon id.
    msg, kb = build_otp_group_message(
        phone, otp, service,
        number_link=get_setting("number_link") or get_bot_link(),
        channel_link=get_setting("channel_link") or get_channel_link(),
    )

    sent_groups = send_to_groups(msg, kb, otp)
    sent_main = forward_to_main_bot(msg, otp)
    return sent_groups or sent_main


# =========================== MAIN LOOP ===========================

_seen = set()


def _sms_key(sms):
    """Stable identity for an SMS row so we never forward it twice."""
    return "|".join([
        str(sms.get("otp") or ""),
        str(sms.get("number") or ""),
        str(sms.get("timestamp") or ""),
        str(sms.get("full_text") or "")[:60],
    ])


def handle_rows(rows, first_run=False):
    """Forward every not-yet-seen row; returns how many were delivered.

    ``first_run`` marks the existing backlog as seen without sending, so
    starting the forwarder never spams the groups with old OTPs. Failed
    deliveries stay unseen and are retried on the next poll.
    """
    sent = 0
    for sms in rows:
        key = _sms_key(sms)
        if key in _seen:
            continue
        if first_run:
            _seen.add(key)
            continue
        if send_otp(sms):
            _seen.add(key)
            sent += 1
            logger.info("Sent OTP %s (total sent this run: %s)",
                        sms.get("otp"), sent)
        else:
            logger.warning("Delivery failed for OTP %s — will retry next poll",
                           sms.get("otp"))
    return sent


def run():
    """Poll forever (thread target used by bot.py). Never raises."""
    if os.environ.get("TEMP_API_FORWARDER", "1").strip().lower() in (
            "0", "false", "off", "no"):
        logger.info("Temp Numbers API forwarder disabled (TEMP_API_FORWARDER)")
        return

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing — set it via bot admin > Settings "
                     "or as an env var; Temp Numbers API forwarder not started")
        return
    if not OTP_GROUPS:
        logger.error("No OTP groups — add one via bot admin > OTP Groups; "
                     "Temp Numbers API forwarder not started")
        return

    logger.info("Temp Numbers API forwarder: polling %s every %ss "
                "(records=%s, groups=%s)",
                API_URL, POLL_INTERVAL, RECORDS, len(OTP_GROUPS))

    first_run = True
    total = 0
    while True:
        try:
            rows = fetch_records()
            total += handle_rows(rows, first_run=first_run)
            if first_run:
                logger.info("Init: %s existing row(s) marked as seen",
                            len(_seen))
                first_run = False
            if len(_seen) > 5000:
                for stale in list(_seen)[:2000]:
                    _seen.discard(stale)
        except Exception as exc:
            logger.error("Loop error: %s", exc)
        finally:
            # Always sleep, even after an error, so a broken poll never
            # turns into a tight retry loop.
            time.sleep(POLL_INTERVAL)


def main():
    print("=" * 55)
    print(f"  \U0001F525 {PANEL_NAME} OTP Forwarder")
    print("=" * 55)
    print(f"  API:      {API_URL}")
    print(f"  Records:  {RECORDS}")
    print(f"  Groups:   {len(OTP_GROUPS)}")
    print(f"  Main bot: {FORWARD_USER or 'Not configured'}")
    print(f"  Poll:     Every {POLL_INTERVAL}s")
    print("=" * 55)
    print()

    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN missing — set via bot admin > Settings or env")
    if not OTP_GROUPS:
        errors.append("No OTP groups — add via bot admin > OTP Groups")
    if not API_TOKEN:
        errors.append("API token missing — set TEMP_API_TOKEN")
    if errors:
        print("-" * 55)
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}")
        print("-" * 55)
        sys.exit(1)

    if OTP_GROUPS:
        _tg_send(
            OTP_GROUPS[0],
            f"\U0001F7E2 <b>{PANEL_NAME} Forwarder Started!</b>\n"
            f"Polling every {POLL_INTERVAL}s",
        )
    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Forwarder stopped.")
