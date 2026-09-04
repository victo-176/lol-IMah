#!/usr/bin/env python3
"""
Goat SMS OTP Bot
Reads ALL credentials from main bot database. NO hardcoded passwords.
Admin adds panel via bot admin, then runs this script.

Usage: python panels/goat_sms.py
"""

import time
import re
import hashlib
import logging
import json
import sqlite3
import os
import sys
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# =========================== CONFIG ===========================
PANEL_NAME = "Goat SMS"
DEFAULT_LOGIN_TYPE = "client"

DB_PATH = os.environ.get("DB_PATH", "data/ivasms_bot.db")
POLL_INTERVAL = 15

# =========================== DATABASE HELPERS ===========================
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


def get_panel_credentials(panel_name):
    """Fetch panel URL / username / password / login_type from sms_panels table."""
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


# =========================== VALIDATE ===========================
BOT_TOKEN = get_bot_token()
OTP_GROUPS = get_otp_groups()
BOT_LINK = get_bot_link()
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
    print("=" * 50)
    print(f"  {PANEL_NAME} — CONFIGURATION ERRORS")
    print("=" * 50)
    for i, e in enumerate(errors, 1):
        print(f"  {i}. {e}")
    print()
    print("  FIX: Bot > /start > Admin > SMS Panels")
    print("=" * 50)
    sys.exit(1)

# =========================== EXTRACTED CONFIG ===========================
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

# =========================== SETUP ===========================
logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{PANEL_NAME}] %(message)s")
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

# =========================== COUNTRY FLAGS ===========================
COUNTRY_FLAGS = {
    "EGYPT": "🇪🇬", "GHANA": "🇬🇭", "NIGERIA": "🇳🇬", "KENYA": "🇰🇪",
    "SOUTH AFRICA": "🇿🇦", "MOROCCO": "🇲🇦", "UAE": "🇦🇪", "INDIA": "🇮🇳",
    "PAKISTAN": "🇵🇰", "TURKEY": "🇹🇷", "USA": "🇺🇸", "UK": "🇬🇧",
    "CANADA": "🇨🇦", "AUSTRALIA": "🇦🇺", "GERMANY": "🇩🇪", "FRANCE": "🇫🇷",
    "SPAIN": "🇪🇸", "ITALY": "🇮🇹", "BRAZIL": "🇧🇷", "MEXICO": "🇲🇽",
    "ARGENTINA": "🇦🇷", "LAOS": "🇱🇦", "LEBANON": "🇱🇧", "JORDAN": "🇯🇴",
    "ISRAEL": "🇮🇱", "SAUDI ARABIA": "🇸🇦", "KUWAIT": "🇰🇼", "QATAR": "🇶🇦",
    "OMAN": "🇴🇲", "BAHRAIN": "🇧🇭", "RUSSIA": "🇷🇺", "CHINA": "🇨🇳",
    "JAPAN": "🇯🇵", "SOUTH KOREA": "🇰🇷", "SINGAPORE": "🇸🇬", "MALAYSIA": "🇲🇾",
    "INDONESIA": "🇮🇩", "PHILIPPINES": "🇵🇭", "VIETNAM": "🇻🇳", "THAILAND": "🇹🇭",
    "CAMBODIA": "🇰🇭", "MYANMAR": "🇲🇲", "BANGLADESH": "🇧🇩", "SRI LANKA": "🇱🇰",
    "NEPAL": "🇳🇵", "NEW ZEALAND": "🇳🇿", "SWITZERLAND": "🇨🇭", "SWEDEN": "🇸🇪",
    "NORWAY": "🇳🇴", "DENMARK": "🇩🇰", "FINLAND": "🇫🇮", "IRELAND": "🇮🇪",
    "PORTUGAL": "🇵🇹", "GREECE": "🇬🇷", "POLAND": "🇵🇱", "UKRAINE": "🇺🇦",
    "ROMANIA": "🇷🇴", "CZECHIA": "🇨🇿", "HUNGARY": "🇭🇺", "SLOVAKIA": "🇸🇰",
    "SLOVENIA": "🇸🇮", "CROATIA": "🇭🇷", "BOSNIA": "🇧🇦", "SERBIA": "🇷🇸",
    "ALBANIA": "🇦🇱", "BULGARIA": "🇧🇬", "AFGHANISTAN": "🇦🇫", "ALGERIA": "🇩🇿",
    "ANGOLA": "🇦🇴", "ARMENIA": "🇦🇲", "AUSTRIA": "🇦🇹", "AZERBAIJAN": "🇦🇿",
    "BELARUS": "🇧🇾", "BELGIUM": "🇧🇪", "BELIZE": "🇧🇿", "BENIN": "🇧🇯",
    "BHUTAN": "🇧🇹", "BOLIVIA": "🇧🇴", "BOTSWANA": "🇧🇼", "BRUNEI": "🇧🇳",
    "BURKINA": "🇧🇫", "BURUNDI": "🇧🇮", "CAMEROON": "🇨🇲", "CHAD": "🇹🇩",
    "CHILE": "🇨🇱", "COLOMBIA": "🇨🇴", "CONGO": "🇨🇬", "COSTA RICA": "🇨🇷",
    "CUBA": "🇨🇺", "CYPRUS": "🇨🇾", "DJIBOUTI": "🇩🇯", "DOMINICAN REPUBLIC": "🇩🇴",
    "ECUADOR": "🇪🇨", "EL SALVADOR": "🇸🇻", "ESTONIA": "🇪🇪", "ETHIOPIA": "🇪🇹",
    "FIJI": "🇫🇯", "GABON": "🇬🇦", "GAMBIA": "🇬🇲", "GEORGIA": "🇬🇪",
    "GUATEMALA": "🇬🇹", "GUINEA": "🇬🇳", "GUYANA": "🇬🇾", "HAITI": "🇭🇹",
    "HONDURAS": "🇭🇳", "ICELAND": "🇮🇸", "JAMAICA": "🇯🇲", "KAZAKHSTAN": "🇰🇰",
    "KYRGYZSTAN": "🇰🇬", "LATVIA": "🇱🇻", "LESOTHO": "🇱🇸", "LIBERIA": "🇱🇷",
    "LIBYA": "🇱🇾", "LITHUANIA": "🇱🇹", "LUXEMBOURG": "🇱🇺", "MADAGASCAR": "🇲🇬",
    "MALAWI": "🇲🇼", "MALDIVES": "🇲🇻", "MALI": "🇲🇱", "MALTA": "🇲🇹",
    "MAURITANIA": "🇲🇷", "MAURITIUS": "🇲🇺", "MOLDOVA": "🇲🇩", "MONACO": "🇲🇨",
    "MONGOLIA": "🇲🇳", "MONTENEGRO": "🇲🇪", "MOZAMBIQUE": "🇲🇿", "NAMIBIA": "🇳🇦",
    "NICARAGUA": "🇳🇮", "NIGER": "🇳🇪", "NORTH MACEDONIA": "🇲🇰", "PALESTINE": "🇵🇸",
    "PANAMA": "🇵🇦", "PARAGUAY": "🇵🇾", "PERU": "🇵🇪", "RWANDA": "🇷🇼",
    "SENEGAL": "🇸🇳", "SIERRA LEONE": "🇸🇱", "SOMALIA": "🇸🇴", "SOUTH SUDAN": "🇸🇸",
    "SYRIA": "🇸🇾", "TAJIKISTAN": "🇹🇯", "TANZANIA": "🇹🇿", "TOGO": "🇹🇬",
    "TUNISIA": "🇹🇳", "TURKMENISTAN": "🇹🇲", "UGANDA": "🇺🇬", "URUGUAY": "🇺🇾",
    "UZBEKISTAN": "🇺🇿", "VENEZUELA": "🇻🇪", "YEMEN": "🇾🇪",
    "ZAMBIA": "🇿🇲", "ZIMBABWE": "🇿🇼"
}

COUNTRIES_LIST = "|".join(re.escape(c) for c in COUNTRY_FLAGS.keys())
COUNTRY_PATTERN = re.compile(r"(" + COUNTRIES_LIST + ")", re.IGNORECASE)


# =========================== TELEGRAM ===========================
def send_to_groups(text, reply_markup=None):
    sent = 0
    for gid in OTP_GROUPS:
        try:
            payload = {"chat_id": gid, "text": text, "parse_mode": "HTML"}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=payload, timeout=10)
            if r.status_code == 200:
                sent += 1
        except Exception as exc:
            logger.error(f"Telegram error to {gid}: {exc}")
    return sent > 0


def send_otp(sms):
    country = "Unknown"
    if sms.get("range"):
        parts = sms["range"].split()
        if parts:
            country = parts[0].upper()
    if country == "Unknown":
        m = COUNTRY_PATTERN.search(sms["full_text"])
        if m:
            country = m.group(1).upper()

    flag = COUNTRY_FLAGS.get(country, "\U0001f30d")
    phone = sms.get("number", "N/A")
    otp = sms["otp"]
    service = sms.get("service", "Unknown")
    ts = sms.get("timestamp", "")
    clean = re.sub(r"\s+", " ", sms["full_text"]).strip()[:300]

    msg = (
        f"\U0001f525 {country} {service.upper()} OTP!\n"
        f"\U0001f4c5 {ts}\n"
        f"\U0001f5fa\ufe0f {country} {flag}\n"
        f"\U0001f4f1 {service}\n"
        f"\U0001f4de {phone}\n"
        f"\U0001f511 {otp}\n\n"
        f"\U0001f4e9 {clean}"
    )
    kb = {"inline_keyboard": [[{"text": "\U0001f916 Bot", "url": BOT_LINK}]]}
    return send_to_groups(msg, json.dumps(kb))


# =========================== LOGIN ===========================
def login():
    logger.info(f"Logging in to {PANEL_NAME}...")
    try:
        resp = session.get(LOGIN_URL, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        nums = re.findall(r"(\d+)\s*\+\s*(\d+)", soup.get_text())
        data = {"username": USERNAME, "password": PASSWORD}
        if nums:
            data["capt"] = str(int(nums[0][0]) + int(nums[0][1]))
            logger.info(f"Captcha: {nums[0][0]} + {nums[0][1]} = {data['capt']}")
        resp = session.post(SIGNIN_URL, data=data, timeout=30, allow_redirects=True)
        final_url = resp.url.lower()
        resp_html = resp.text.lower()
        # Check URL for dashboard
        if "dashboard" in final_url or "smcdrstats" in final_url or "home" in final_url:
            logger.info("Login successful!")
            return True
        # Check if not on login page
        if "signin" not in final_url and "login" not in final_url:
            logger.info("Login successful!")
            return True
        # EVS-style: URL may still say login but response has dashboard content
        has_login_form = 'type="password"' in resp_html
        has_dashboard = 'smcdrstats' in resp_html or 'sms reports' in resp_html or 'side-nav' in resp_html
        if not has_login_form and has_dashboard:
            logger.info("Login successful (dashboard content in response)!")
            return True
        logger.warning(f"Login failed ({resp.url[:80]})")
        return False
    except Exception as exc:
        logger.error(f"Login error: {exc}")
        return False


# =========================== FETCH OTPS ===========================
def fetch_otps():
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
                    continue
                data = resp.json()
                records = data.get("aaData") or data.get("data") or []
                if not records:
                    continue
                for rec in records:
                    if not isinstance(rec, list) or len(rec) < 6:
                        continue
                    full = str(rec[5] or "")
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
                            "service": str(rec[3] or "Unknown"),
                            "full_text": full,
                            "timestamp": str(rec[0] or ""),
                            "range": str(rec[1] or ""),
                            "number": str(rec[2] or "N/A"),
                        })
                break
            except (requests.RequestException, json.JSONDecodeError):
                continue
    if sms_list:
        logger.info(f"Found {len(sms_list)} OTPs")
    return sms_list


# =========================== MAIN ===========================
def main():
    global total_otps_sent, last_sms_hashes, first_run

    print("=" * 50)
    print(f"  {PANEL_NAME} OTP Bot")
    print("=" * 50)
    print(f"  Panel: {PANEL_URL}")
    print(f"  Type:  {LOGIN_TYPE}")
    print(f"  Groups: {len(OTP_GROUPS)}")
    print("=" * 50)

    if not login():
        logger.error("Login failed! Check credentials in bot admin panel.")
        return

    send_to_groups(f"\U0001f7e2 {PANEL_NAME} Started!")
    logger.info("Monitoring OTPs...")

    while True:
        try:
            for sms in fetch_otps():
                h = hashlib.md5((sms["otp"] + sms["timestamp"]).encode()).hexdigest()
                if h not in last_sms_hashes:
                    if not first_run:
                        if send_otp(sms):
                            last_sms_hashes.add(h)
                            total_otps_sent += 1
                            logger.info(f"\u2705 Sent {sms['otp']} (Total: {total_otps_sent})")
                    else:
                        last_sms_hashes.add(h)
            if first_run:
                logger.info(f"Init: {len(last_sms_hashes)} existing OTPs loaded")
                first_run = False
        except Exception as exc:
            logger.error(f"Loop error: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
