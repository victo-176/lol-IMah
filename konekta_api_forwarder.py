#!/usr/bin/env python3
"""
KONEKTA API OTP FORWARDER — standalone sub-bot
==============================================
Polls the Konekta stats API:

    http://51.77.216.195/crapi/konek/viewstats
        ?token=Qk5RRUlBUzR3T5Z3RINVeXVleYpKj4ZJdWeJSHeLVoFld2dlhouZSQ==
        &records=10

API behaviour (probed live, 2026-10-07):
  * valid token, no traffic  -> HTTP 200 {"status":"error",
                                           "msg":"No Records Found"}
  * wrong token              -> HTTP 200 {"msg":"Invalid Authtype"}
  * missing token            -> HTTP 200 {"msg":"Not Authorized"}
  * with traffic (success)   -> HTTP 200
        {"status":"success","total":4,
         "data":[{"dt":"2026-10-07 19:02:26", "num":"263787140515",
                   "cli":"PayPal", "message":"# PayPal Your security
                   code is 980088 ...", "payout":"0.015"}, ...]}

Every row the API returns is forwarded to the configured Telegram OTP
group(s) in the shared reference format (deduplicated within the process,
so the same row is only ever posted once per run):

    {premium flag} #{ISO} {app icon} +2347●○●○6087
    [ green full-width: {app icon} ⧉ Service | <real OTP>  (copy_text) ]
    [ blue NUMBER ] [ blue CHANNEL ]

Parsing, OTP extraction and the dedupe key are shared with
temp_numbers_api_forwarder (same crapi row shape); delivery and loop state
are this module's own, so the two forwarders never touch each other.

Usage:
    python konekta_api_forwarder.py          # standalone
    import konekta_api_forwarder as k; k.run()   # as a thread (bot.py)

Configuration — env var first, then the bot database (bot_settings):

    KONEKTA_API_URL      API endpoint (default: the viewstats URL above)
    KONEKTA_API_TOKEN    API token
    KONEKTA_RECORDS      how many records to pull per poll (default: 10)
    KONEKTA_FORWARDER    set to 0/off to disable the forwarder thread
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
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from premium_emoji import (  # noqa: E402
    DEFAULT_BOT_LINK,
    DEFAULT_CHANNEL_LINK,
    build_otp_group_message,
    kb_without_copy,
    premiumize,
)
# Pure helpers (no network, no module state): row parsing, OTP extraction,
# the dedupe key and the bot_settings readers are the same for every crapi
# stats source, so they come from the temp numbers forwarder instead of
# being copied again.
from temp_numbers_api_forwarder import (  # noqa: E402
    _clean_service,
    _sms_key,
    extract_otp,
    get_bot_link,
    get_bot_token,
    get_channel_link,
    get_forward_user_id,
    get_otp_groups,
    get_setting,
    parse_records,
)

# =========================== CONFIG ===========================
PANEL_NAME = "KONEKTA"

DEFAULT_API_URL = "http://51.77.216.195/crapi/konek/viewstats"
DEFAULT_API_TOKEN = (
    "Qk5RRUlBUzR3T5Z3RINVeXVleYpKj4ZJdWeJSHeLVoFld2dlhouZSQ=="
)

API_URL = os.environ.get("KONEKTA_API_URL", DEFAULT_API_URL).strip()
API_TOKEN = os.environ.get("KONEKTA_API_TOKEN", DEFAULT_API_TOKEN).strip()
try:
    RECORDS = max(1, min(200, int(os.environ.get("KONEKTA_RECORDS", "10"))))
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

# Resolved once per process; tests may patch these directly.
BOT_TOKEN = get_bot_token()
OTP_GROUPS = get_otp_groups()
FORWARD_USER = get_forward_user_id()

# =========================== SETUP ===========================
# temp_numbers_api_forwarder already configured the root logger when it was
# imported; just grab a named logger so these lines are identifiable.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [KONEKTA] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("konekta_api_forwarder")

# =========================== FETCH ===========================


def fetch_records():
    """One API call -> parsed rows. Raises on network/JSON problems.

    An error payload (no records / auth problem) is logged and yields []
    instead of raising, so a quiet or briefly angry API never kills the
    poll loop.
    """
    resp = requests.get(
        API_URL,
        params={"token": API_TOKEN, "records": RECORDS},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return parse_records(data)

    if isinstance(data, dict):
        # Success payload: {"status":"success","total":N,"data":[{...}]}.
        # Without this branch every record was silently dropped, which is
        # why nothing reached the OTP group.
        payload = data.get("data")
        if payload is None:
            payload = data.get("records")
        if isinstance(payload, list):
            return parse_records(payload)
        msg = str(data.get("msg") or data.get("message") or data)
        if "no records" in msg.lower():
            logger.debug("Konekta: no records right now")
        else:
            # "Invalid Authtype" / "Not Authorized" land here — keep the
            # loop alive but make the problem visible.
            logger.warning("Konekta API: %s", msg)
        return []
    logger.warning("Konekta API: unexpected payload type %s", type(data).__name__)
    return []


# =========================== TELEGRAM ===========================


# Premium <tg-emoji> entities Telegram may reject (e.g. an emoji id the
# bot can't use): stripped for the plain-text retry below.
_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">([^<]*)</tg-emoji>')


def _tg_send(chat_id, text, reply_markup=None):
    """POST one message; returns True on success. Never raises.

    Raw API post, so nothing else upgrades these emoji: do it here or the
    OTP groups get plain unicode while the bot's own messages are premium.
    If Telegram rejects the premium <tg-emoji> entities (HTTP 400), retry
    once with the tags stripped so the OTP still lands as plain glyphs —
    a rejected emoji id must never lose the message entirely.
    """
    sent_text = premiumize(text)
    payload = {"chat_id": chat_id, "text": sent_text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(
            f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage",
            data=payload, timeout=15,
        )
        if r.status_code == 200:
            return True
        desc = (r.text or "")[:160]
        if r.status_code == 400 and "<tg-emoji" in sent_text:
            plain = _TG_EMOJI_RE.sub(r"\1", sent_text)
            if plain != sent_text:
                payload["text"] = plain
                r = requests.post(
                    f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage",
                    data=payload, timeout=15,
                )
                if r.status_code == 200:
                    logger.info("Sent to %s with premium tags stripped "
                                "(rejected emoji id)", chat_id)
                    return True
                desc = (r.text or "")[:160]
        logger.warning("Telegram send to %s failed: HTTP %s — %s",
                       chat_id, r.status_code, desc)
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


def handle_rows(rows):
    """Forward every not-yet-seen row; returns how many were delivered.

    The panel's current records are posted immediately (the OTP group is
    supposed to show them), rows are deduplicated within the process so a
    record is only posted once, and failed deliveries stay unseen so they
    are retried on the next poll.
    """
    sent = 0
    for sms in rows:
        key = _sms_key(sms)
        if key in _seen:
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


def _heartbeat():
    """Post a startup notice so the group shows the forwarder is live.

    Returns True once it has actually been delivered; run() keeps trying
    every poll until it lands, so the group always ends up showing life.
    """
    if not OTP_GROUPS:
        return False
    return _tg_send(
        OTP_GROUPS[0],
        f"\U0001F7E2 <b>{PANEL_NAME} Forwarder Started!</b>\n"
        f"Polling every {POLL_INTERVAL}s",
    )


def resolve_config():
    """Fresh (bot token, group ids) for the current poll.

    Re-read every loop instead of trusting the import-time snapshot:
    bot.py seeds 'otp_groups' as '[]' (the default-group fallback lives
    in get_otp_groups) and settings written after boot must be picked up
    without a restart.
    """
    return get_bot_token(), get_otp_groups()


def run():
    """Poll forever (thread target used by bot.py). Never raises.

    Missing config no longer aborts the forwarder: it logs once and keeps
    retrying every poll, so a settings row written after boot, or a bot
    token that appears later, still starts delivery without a restart.
    """
    global BOT_TOKEN, OTP_GROUPS
    if os.environ.get("KONEKTA_FORWARDER", "1").strip().lower() in (
            "0", "false", "off", "no"):
        logger.info("Konekta API forwarder disabled (KONEKTA_FORWARDER)")
        return

    heartbeat_sent = False
    config_warned = False
    first = True
    while True:
        try:
            BOT_TOKEN, OTP_GROUPS = resolve_config()
            if not BOT_TOKEN or not OTP_GROUPS:
                if not config_warned:
                    logger.error(
                        "Config not ready (bot_token=%s, groups=%s) — "
                        "retrying every %ss instead of exiting",
                        bool(BOT_TOKEN), len(OTP_GROUPS), POLL_INTERVAL)
                    config_warned = True
                continue
            config_warned = False
            if first:
                logger.info("Konekta API forwarder: polling %s every %ss "
                            "(records=%s, groups=%s)",
                            API_URL, POLL_INTERVAL, RECORDS, len(OTP_GROUPS))
                first = False
            if not heartbeat_sent:
                heartbeat_sent = bool(_heartbeat())
            rows = fetch_records()
            handle_rows(rows)
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
        errors.append("API token missing — set KONEKTA_API_TOKEN")
    if errors:
        print("-" * 55)
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}")
        print("-" * 55)
        sys.exit(1)

    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Forwarder stopped.")
