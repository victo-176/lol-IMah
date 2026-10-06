#!/usr/bin/env python3
"""
EVS SMS OTP Forwarder — Standalone Bot
======================================
Polls your EVS SMS panel for OTPs and forwards them to:
  1. Your Telegram OTP group(s)
  2. The main bot (forwarded to your chat)

Usage:
  python evs_forwarder.py

Config is read from the main bot's database (bot.db) — 
just make sure "EVS SMS" is added in Admin > SMS Panels.
"""

import os
import re
import sys
import json
import time
import hashlib
import logging
import sqlite3
import requests
from datetime import datetime, timedelta

# Premium group-forward format, shared with bot.py's OTP groups.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from premium_emoji import (  # noqa: E402
    group_otp_body, group_otp_buttons, iso_from_flag, premiumize,
)
from panels._premium_flag import flag_html  # noqa: E402,E401

# ═══════════════════════════ CONFIG ═══════════════════════════
PANEL_NAME = "EVS SMS"
DEFAULT_LOGIN_TYPE = "client"
DB_PATH = os.environ.get("DB_PATH", "data/ivasms_bot.db")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))  # seconds

# ═══════════════════════════ DATABASE ═══════════════════════════

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_setting(key, default=None):
    try:
        with _db() as conn:
            r = conn.execute("SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default
    except Exception:
        return default


def get_bot_token():
    t = os.environ.get("BOT_TOKEN")
    return t if t else get_setting("bot_token")


def get_otp_groups():
    raw = get_setting("otp_groups", "[]")
    try:
        return [int(g) for g in json.loads(raw)]
    except Exception:
        return []


def get_bot_link():
    return get_setting("bot_link", "")


def get_forward_user_id():
    """User ID to forward OTPs to in the main bot (optional)."""
    return os.environ.get("FORWARD_USER_ID") or get_setting("forward_user_id")


def get_panel_credentials(panel_name):
    try:
        with _db() as conn:
            r = conn.execute(
                "SELECT url, username, password, login_type FROM sms_panels WHERE name=? AND enabled=1",
                (panel_name,),
            ).fetchone()
            if r:
                return dict(r)
    except Exception:
        pass
    return None


# ═══════════════════════════ VALIDATE ═══════════════════════════
BOT_TOKEN = get_bot_token()
OTP_GROUPS = get_otp_groups()
BOT_LINK = get_bot_link()
FORWARD_USER = get_forward_user_id()
PANEL = get_panel_credentials(PANEL_NAME)

errors = []
if not BOT_TOKEN:
    errors.append("BOT_TOKEN missing — set via bot admin or env var")
if not OTP_GROUPS:
    errors.append("No OTP groups — add via bot admin > OTP Groups")
if not PANEL:
    errors.append(f"Panel '{PANEL_NAME}' not found in database — add via bot admin > SMS Panels")
else:
    if not PANEL.get("url"):
        errors.append("Panel URL is empty")
    if not PANEL.get("username"):
        errors.append("Panel username is empty")
    if not PANEL.get("password"):
        errors.append("Panel password is empty")

if errors:
    print("=" * 55)
    print(f"  {PANEL_NAME} OTP Forwarder — CONFIGURATION ERRORS")
    print("=" * 55)
    for i, e in enumerate(errors, 1):
        print(f"  {i}. {e}")
    print()
    print("  FIX: Bot > /start > Admin > SMS Panels")
    print("  Set FORWARD_USER_ID env var to your Telegram user ID to")
    print("  also receive OTPs directly in your main bot chat.")
    print("=" * 55)
    sys.exit(1)

# ═══════════════════════════ EXTRACTED CONFIG ═══════════════════════════
PANEL_URL = PANEL["url"].rstrip("/")
LOGIN_TYPE = PANEL.get("login_type") or DEFAULT_LOGIN_TYPE
USERNAME = PANEL["username"]
PASSWORD = PANEL["password"]

API_PATHS = [
    f"{LOGIN_TYPE}/res/data_smscdr.php",
    "agent/res/data_smscdr.php",
    "client/res/data_smscdr.php",
]
LOGIN_URL = f"{PANEL_URL}/login"
SIGNIN_URL = f"{PANEL_URL}/signin"

# ═══════════════════════════ SETUP ═══════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EVS] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*",
})

last_sms_hashes = set()
total_otps_sent = 0
first_run = True

# ═══════════════════════════ COUNTRY FLAGS ═══════════════════════════
COUNTRY_FLAGS = {
    "EGYPT": "🇪🇬", "GHANA": "🇬🇭", "NIGERIA": "🇳🇬", "KENYA": "🇰🇪",
    "SOUTH AFRICA": "🇿🇦", "MOROCCO": "🇲🇦", "UAE": "🇦🇪", "INDIA": "🇮🇳",
    "PAKISTAN": "🇵🇰", "TURKEY": "🇹🇷", "USA": "🇺🇸", "UK": "🇬🇧",
    "CANADA": "🇨🇦", "AUSTRALIA": "🇦🇺", "GERMANY": "🇩🇪", "FRANCE": "🇫🇷",
    "SPAIN": "🇪🇸", "ITALY": "🇮🇹", "BRAZIL": "🇧🇷", "MEXICO": "🇲🇽",
    "LAOS": "🇱🇦", "CAMBODIA": "🇰🇭", "MYANMAR": "🇲🇲", "THAILAND": "🇹🇭",
    "VIETNAM": "🇻🇳", "PHILIPPINES": "🇵🇭", "INDONESIA": "🇮🇩",
    "MALAYSIA": "🇲🇾", "SINGAPORE": "🇸🇬", "JAPAN": "🇯🇵",
    "SOUTH KOREA": "🇰🇷", "RUSSIA": "🇷🇺", "CHINA": "🇨🇳",
    "SAUDI ARABIA": "🇸🇦", "ISRAEL": "🇮🇱", "JORDAN": "🇯🇴",
    "LEBANON": "🇱🇧", "IRAQ": "🇮🇶", "IRAN": "🇮🇷",
    "PALESTINE": "🇵🇸", "SUDAN": "🇸🇩", "ETHIOPIA": "🇪🇹",
    "TANZANIA": "🇹🇿", "UGANDA": "🇺🇬", "RWANDA": "🇷🇼",
    "SENEGAL": "🇸🇳", "COTE D'IVOIRE": "🇨🇮", "CAMEROON": "🇨🇲",
    "DEMOCRATIC REPUBLIC OF THE CONGO": "🇨🇩", "REPUBLIC OF THE CONGO": "🇨🇬",
    "MOZAMBIQUE": "🇲🇿", "ZAMBIA": "🇿🇲", "ZIMBABWE": "🇿🇼",
    "MALAWI": "🇲🇼", "NAMIBIA": "🇳🇦", "BOTSWANA": "🇧🇼",
    "ANGOLA": "🇦🇴", "LIBYA": "🇱🇾", "TUNISIA": "🇹🇳",
    "ALGERIA": "🇩🇿", "BAHRAIN": "🇧🇭", "KUWAIT": "🇰🇼",
    "QATAR": "🇶🇦", "OMAN": "🇴🇲", "YEMEN": "🇾🇪",
    "CYPRUS": "🇨🇾", "GEORGIA": "🇬🇪", "ARMENIA": "🇦🇲",
    "AZERBAIJAN": "🇦🇿", "KAZAKHSTAN": "🇰🇿", "UZBEKISTAN": "🇺🇿",
    "UKRAINE": "🇺🇦", "POLAND": "🇵🇱", "ROMANIA": "🇷🇴",
    "CZECHIA": "🇨🇿", "HUNGARY": "🇭🇺", "GREECE": "🇬🇷",
    "PORTUGAL": "🇵🇹", "IRELAND": "🇮🇪", "NETHERLANDS": "🇳🇱",
    "BELGIUM": "🇧🇪", "SWEDEN": "🇸🇪", "NORWAY": "🇳🇴",
    "DENMARK": "🇩🇰", "FINLAND": "🇫🇮", "SWITZERLAND": "🇨🇭",
    "AUSTRIA": "🇦🇹", "BULGARIA": "🇧🇬", "SERBIA": "🇷🇸",
    "CROATIA": "🇭🇷", "SLOVENIA": "🇸🇮", "SLOVAKIA": "🇸🇰",
    "ALBANIA": "🇦🇱", "NORTH MACEDONIA": "🇲🇰", "MOLDOVA": "🇲🇩",
    "BELARUS": "🇧🇾", "BANGLADESH": "🇧🇩", "SRI LANKA": "🇱🇰",
    "NEPAL": "🇳🇵", "BHUTAN": "🇧🇹", "MALDIVES": "🇲🇻",
    "AFGHANISTAN": "🇦🇫", "KYRGYZSTAN": "🇰🇬", "TAJIKISTAN": "🇹🇯",
    "TURKMENISTAN": "🇹🇲", "MONGOLIA": "🇲🇳",
    "DOMINICAN REPUBLIC": "🇩🇴", "CUBA": "🇨🇺", "JAMAICA": "🇯🇲",
    "TRINIDAD AND TOBAGO": "🇹🇹", "HAITI": "🇭🇹",
    "COLOMBIA": "🇨🇴", "CHILE": "🇨🇱", "PERU": "🇵🇪",
    "ARGENTINA": "🇦🇷", "ECUADOR": "🇪🇨", "BOLIVIA": "🇧🇴",
    "PARAGUAY": "🇵🇾", "URUGUAY": "🇺🇾", "VENEZUELA": "🇻🇪",
    "PANAMA": "🇵🇦", "COSTA RICA": "🇨🇷", "HONDURAS": "🇭🇳",
    "GUATEMALA": "🇬🇹", "EL SALVADOR": "🇸🇻", "NICARAGUA": "🇳🇮",
    "BELIZE": "🇧🇿",
    "NEW ZEALAND": "🇳🇿", "FIJI": "🇫🇯",
}

COUNTRIES_LIST = "|".join(re.escape(c) for c in COUNTRY_FLAGS.keys())
COUNTRY_PATTERN = re.compile(r"(" + COUNTRIES_LIST + ")", re.IGNORECASE)


# ═══════════════════════════ TELEGRAM ═══════════════════════════

def send_to_groups(text, reply_markup=None):
    """Send message to all configured OTP groups."""
    sent = 0
    for gid in OTP_GROUPS:
        try:
            payload = {"chat_id": gid, "text": premiumize(text), "parse_mode": "HTML"}
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data=payload, timeout=10,
            )
            if r.status_code == 200:
                sent += 1
                logger.info(f"  ✅ Group {gid}: sent")
            else:
                logger.warning(f"  ⚠️  Group {gid}: HTTP {r.status_code} — {r.text[:100]}")
        except Exception as exc:
            logger.error(f"  ❌ Group {gid}: {exc}")
    return sent > 0


def forward_to_main_bot(text, otp_code):
    """Forward OTP to the main bot user via the bot's send_message API."""
    if not FORWARD_USER:
        return False
    try:
        kb = {"inline_keyboard": [[
            {"text": f"📋 {otp_code}", "callback_data": f"copy_{otp_code}"},
        ]]}
        payload = {
        "chat_id": int(FORWARD_USER),
        "text": premiumize(text),
            "parse_mode": "HTML",
            "reply_markup": json.dumps(kb),
        }
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=payload, timeout=10,
        )
        if r.status_code == 200:
            logger.info(f"  ✅ Main bot: forwarded to user {FORWARD_USER}")
            return True
        else:
            logger.warning(f"  ⚠️  Main bot: HTTP {r.status_code} — {r.text[:100]}")
    except Exception as exc:
        logger.error(f"  ❌ Main bot forward error: {exc}")
    return False


def send_otp(sms):
    """Format and send OTP to both groups AND main bot."""
    country = "Unknown"
    if sms.get("range"):
        parts = sms["range"].split()
        if parts:
            country = parts[0].upper()
    if country == "Unknown":
        m = COUNTRY_PATTERN.search(sms.get("full_text", ""))
        if m:
            country = m.group(1).upper()

    flag = flag_html(COUNTRY_FLAGS, country)
    phone = sms.get("number", "N/A")
    otp = sms["otp"]
    service = sms.get("service", "Unknown")
    ts = sms.get("timestamp", "")

    # Group post: the shared forward format (flag, #ISO, mail + number,
    # #SERVICE) with the premium-icon keyboard (Switch / NUMBER / CHANNEL).
    iso = iso_from_flag(COUNTRY_FLAGS.get(country) or "")
    msg = group_otp_body(flag, iso, phone, service)
    kb = {"inline_keyboard": group_otp_buttons(otp, BOT_LINK)}

    # Send to groups
    sent_groups = send_to_groups(msg, kb)

    # Forward to main bot
    forward_msg = (
        f"📨 <b>EVS OTP RECEIVED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗺️ {country} {flag}\n"
        f"📱 {service}\n"
        f"📞 <code>{phone}</code>\n"
        f"🔑 <b><code>{otp}</code></b>\n"
        f"📅 {ts}"
    )
    sent_main = forward_to_main_bot(forward_msg, otp)

    return sent_groups or sent_main


# ═══════════════════════════ LOGIN ═══════════════════════════

def login():
    """Login to EVS SMS panel. Returns True on success."""
    logger.info(f"Logging in to {PANEL_NAME} ({PANEL_URL})...")
    try:
        resp = session.get(LOGIN_URL, timeout=30)
        # Solve captcha if present
        nums = re.findall(r"(\d+)\s*\+\s*(\d+)", resp.text)
        data = {"username": USERNAME, "password": PASSWORD}
        if nums:
            data["capt"] = str(int(nums[0][0]) + int(nums[0][1]))
            logger.info(f"Captcha: {nums[0][0]} + {nums[0][1]} = {data['capt']}")

        resp = session.post(SIGNIN_URL, data=data, timeout=30, allow_redirects=True)
        final_url = resp.url.lower()
        resp_html = resp.text.lower()

        # Check URL for dashboard indicators
        if "dashboard" in final_url or "smcdrstats" in final_url or "home" in final_url:
            logger.info(f"✅ Login OK (redirected to {resp.url[:60]})")
            return True

        # Check if no longer on login page
        if "signin" not in final_url and "login" not in final_url:
            logger.info(f"✅ Login OK (redirected away from login)")
            return True

        # EVS-style: URL may still say login but content has dashboard
        has_login_form = 'type="password"' in resp_html
        has_dashboard = 'smcdrstats' in resp_html or 'sms reports' in resp_html or 'side-nav' in resp_html
        if not has_login_form and has_dashboard:
            logger.info("✅ Login OK (dashboard content in response)")
            return True

        # Check cookies as last resort
        if len(session.cookies) > 0:
            logger.info("✅ Login OK (got cookies)")
            return True

        logger.warning(f"❌ Login FAILED — final URL: {resp.url[:80]}")
        return False
    except Exception as exc:
        logger.error(f"❌ Login error: {exc}")
        return False


# ═══════════════════════════ FETCH OTPS ═══════════════════════════

def fetch_otps():
    """Fetch OTPs from EVS panel API. Returns list of SMS dicts."""
    sms_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    for date in [today, yesterday]:
        params = {
            "draw": "1", "start": "0", "length": "100",
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "0", "order[0][dir]": "asc",
            "fdate1": f"{date} 00:00:00", "fdate2": f"{date} 23:59:59",
            "frange": "", "fclient": "", "fnum": "", "fcli": "",
            "fgdate": "", "fgmonth": "", "fgrange": "", "fgclient": "",
            "fgnumber": "", "fgcli": "", "fg": "0",
        }
        for path in API_PATHS:
            try:
                resp = session.get(f"{PANEL_URL}/{path}", params=params, timeout=30)
                if resp.status_code != 200:
                    # Session expired?
                    if resp.status_code in (302, 403, 503) or "login" in resp.url.lower():
                        logger.warning(f"Session expired (HTTP {resp.status_code}), re-logging...")
                        session.cookies.clear()
                        if not login():
                            logger.error("Re-login failed")
                            return []
                    continue

                data = resp.json()
                records = data.get("aaData") or data.get("data") or []
                if isinstance(data, list):
                    records = data
                if not records:
                    continue

                for rec in records:
                    if not isinstance(rec, list) or len(rec) < 5:
                        continue
                    # EVS format: [Date, Range, Number, CLI, SMS, ...]
                    full = str(rec[4] if len(rec) > 4 else rec[-1] or "")
                    m = (
                        re.search(r"code\s+(\d{4,6})", full, re.I)
                        or re.search(r"use code\s+(\d{4,6})", full, re.I)
                        or re.search(r"code[:]\s*(\d{4,6})", full, re.I)
                        or re.search(r"<#>\s*(\d{4,6})", full, re.I)
                        or re.search(r"(\d{4,6})", full)
                    )
                    if m:
                        sms_list.append({
                            "otp": m.group(1),
                            "service": str(rec[3] if len(rec) > 3 else "Unknown") or "Unknown",
                            "full_text": full,
                            "timestamp": str(rec[0] if len(rec) > 0 else ""),
                            "range": str(rec[1] if len(rec) > 1 else ""),
                            "number": str(rec[2] if len(rec) > 2 else "N/A"),
                        })
                break  # Got data from this path, no need to try others
            except (requests.RequestException, json.JSONDecodeError) as exc:
                logger.debug(f"API path {path} error: {exc}")
                continue

    if sms_list:
        logger.info(f"Found {len(sms_list)} OTPs")
    return sms_list


# ═══════════════════════════ MAIN LOOP ═══════════════════════════

def main():
    global total_otps_sent, last_sms_hashes, first_run

    print("=" * 55)
    print(f"  🔥 {PANEL_NAME} OTP Forwarder")
    print("=" * 55)
    print(f"  Panel:    {PANEL_URL}")
    print(f"  Type:     {LOGIN_TYPE}")
    print(f"  Groups:   {len(OTP_GROUPS)}")
    print(f"  Main bot: {'User ' + FORWARD_USER if FORWARD_USER else 'Not configured'}")
    print(f"  Poll:     Every {POLL_INTERVAL}s")
    print("=" * 55)
    print()

    if not login():
        logger.error("❌ Login failed! Check credentials in bot admin panel.")
        sys.exit(1)

    # Send startup notification
    startup_msg = f"🟢 <b>{PANEL_NAME} Forwarder Started!</b>\nPolling every {POLL_INTERVAL}s"
    send_to_groups(startup_msg)
    if FORWARD_USER:
        forward_to_main_bot(startup_msg, "start")

    logger.info("📡 Monitoring OTPs...")

    while True:
        try:
            otps = fetch_otps()
            for sms in otps:
                h = hashlib.md5((sms["otp"] + sms["timestamp"]).encode()).hexdigest()
                if h not in last_sms_hashes:
                    if not first_run:
                        if send_otp(sms):
                            last_sms_hashes.add(h)
                            total_otps_sent += 1
                            logger.info(f"✅ Sent OTP {sms['otp']} (Total: {total_otps_sent})")
                    else:
                        last_sms_hashes.add(h)
            if first_run:
                logger.info(f"Init: {len(last_sms_hashes)} existing OTPs loaded (won't re-forward)")
                first_run = False
        except Exception as exc:
            logger.error(f"Loop error: {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
