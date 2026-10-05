#!/usr/bin/env python3
"""
TEMP NUMBERS CLIENT PANEL OTP FORWARDER — Standalone Sub-Bot
============================================================
Autonomous scraper for the Temp Numbers client panel:

    http://tempnumbers.net/client/SMSCDRStats

It logs into the panel as a normal client user, scrapes the SMS report
page every 7 seconds, and forwards every new OTP to:

  1. The configured Telegram OTP group(s)
  2. The bot owner's chat (main bot DM) when FORWARD_USER_ID is set

It runs as its own process with its own ``requests.Session`` so the main
bot's login/sesskey state in ``bot.py`` is never touched.

Usage:
    python temp_numbers_panel.py

Configuration — every value comes from an env var first, then from the
bot database, so nothing has to be hardcoded:

    TEMP_PANEL_URL         panel base url (default: the saved Number Panel)
    TEMP_PANEL_USERNAME    panel login
    TEMP_PANEL_PASSWORD    panel password
    DB_PATH                bot database path
    POLL_INTERVAL          poll seconds (default 7)
    BOT_TOKEN              Telegram bot token
    FORWARD_USER_ID        Telegram user id that receives OTPs directly

Panel credentials are otherwise read from the ``sms_panels`` row whose name
is "Number Panel"/"TEMP NUMBERS" or whose URL points at tempnumbers.net
(admin > SMS Panels).

Notes on the live panel (verified against tempnumbers.net):
  * The login form posts to ``/signin`` with ``username``/``password``/
    ``capt``. The captcha question lives in the label bound to the ``capt``
    input ("What is 1 + 5 = ?"); scanning the whole page for the first
    "a + b" picks up unrelated numbers and answers wrong.
  * Login is rate limited to one attempt per minute ("Error 27: Session
    invalid try after 1 minute"), so retries are throttled by LOGIN_COOLDOWN.
  * The report page is ``/client/SMSCDRStats``. ``/Client/SMSCDRReports``
    returns 404 on this panel and is only kept as a fallback.
"""

import html as html_mod
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

import requests

# Premium emoji ids for the group OTPs. Kept import-safe (no telebot, no DB),
# and the maps are pinned identical to bot.py's by tests/test_otp_group_premium.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from premium_emoji import premiumize  # noqa: E402

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback to regex parsing
    BS4_AVAILABLE = False

# =========================== CONFIG ===========================
PANEL_NAME = "TEMP NUMBERS"
# Names the admin may have used for this panel in the bot's SMS Panels menu.
PANEL_NAMES = {"temp numbers", "tempnumbers", "temp numbers panel", "number panel"}
PANEL_HOST_HINT = "tempnumbers.net"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "7"))  # 7 seconds
REQUEST_TIMEOUT = 30

PERSISTENT_DIR = os.environ.get("PERSISTENT_DIR", "/app/data/")
DB_PATH = os.environ.get("DB_PATH", os.path.join(PERSISTENT_DIR, "bot.db"))

# Telegram Bot API root. Overridable so delivery can be tested locally.
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")

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
    return get_setting("bot_link", "") or "https://t.me/Anon_MatrixxV3bot"


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


def get_panel_credentials():
    """Find the tempnumbers.net row in sms_panels (any enabled name).

    Env overrides (TEMP_PANEL_URL / _USERNAME / _PASSWORD) win, so the
    forwarder can also be pointed at a mirror or run before the admin has
    saved the panel row.
    """
    env_url = os.environ.get("TEMP_PANEL_URL")
    if env_url:
        return {
            "name": os.environ.get("TEMP_PANEL_NAME", PANEL_NAME),
            "url": env_url,
            "username": os.environ.get("TEMP_PANEL_USERNAME", ""),
            "password": os.environ.get("TEMP_PANEL_PASSWORD", ""),
            "login_type": "client",
        }

    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT name, url, username, password, login_type "
                "FROM sms_panels WHERE enabled=1"
            ).fetchall()
    except Exception:
        return None

    by_name = None
    by_host = None
    for row in rows:
        name = (row["name"] or "").strip().lower()
        url = (row["url"] or "").strip()
        if name in PANEL_NAMES:
            by_name = dict(row)
            break
        if by_host is None and PANEL_HOST_HINT in url.lower():
            by_host = dict(row)
    return by_name or by_host


# =========================== VALIDATE ===========================
BOT_TOKEN = get_bot_token()
OTP_GROUPS = get_otp_groups()
BOT_LINK = get_bot_link()
FORWARD_USER = get_forward_user_id()
PANEL = get_panel_credentials()

errors = []
if not BOT_TOKEN:
    errors.append(
        "BOT_TOKEN missing — set it via bot admin > Settings or as an env var"
    )
if not OTP_GROUPS:
    errors.append(
        "No OTP groups — add one via bot admin > OTP Groups"
    )
if not PANEL:
    errors.append(
        f"Panel '{PANEL_HOST_HINT}' not found in the database — add it via "
        "bot admin > SMS Panels (name \"Number Panel\", "
        "url http://tempnumbers.net, type Client)"
    )
else:
    if not (PANEL.get("url") or "").strip():
        errors.append("Panel URL is empty")
    if not (PANEL.get("username") or "").strip():
        errors.append("Panel username is empty")
    if not (PANEL.get("password") or "").strip():
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

# =========================== EXTRACTED CONFIG ===========================
PANEL_URL = PANEL["url"].rstrip("/")
USERNAME = PANEL["username"]
PASSWORD = PANEL["password"]
LOGIN_URL = f"{PANEL_URL}/login"
SIGNIN_URL = f"{PANEL_URL}/signin"

# The SMS report page. tempnumbers.net serves it at /client/SMSCDRStats
# (the nav links confirm this); /Client/SMSCDRReports is kept as a fallback
# for deployments that do expose it.
REPORT_PAGES = [
    f"{PANEL_URL}/client/SMSCDRStats",
    f"{PANEL_URL}/Client/SMSCDRReports",
    f"{PANEL_URL}/client/SMSCDRReports",
]

# The panel refuses more than one login attempt per minute
# ("Error 27: Session invalid try after 1 minute").
LOGIN_COOLDOWN = 65
_last_login_attempt = 0.0

# =========================== SETUP ===========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TEMP] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Dedicated session: never shares cookies with the main bot's panel threads.
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

# =========================== COUNTRY FLAGS ===========================
COUNTRY_FLAGS = {
    "EGYPT": "\U0001F1EA\U0001F1EC", "GHANA": "\U0001F1EC\U0001F1ED",
    "NIGERIA": "\U0001F1F3\U0001F1EC", "KENYA": "\U0001F1F0\U0001F1EA",
    "SOUTH AFRICA": "\U0001F1FF\U0001F1E6", "MOROCCO": "\U0001F1F2\U0001F1E6",
    "UAE": "\U0001F1E6\U0001F1EA", "INDIA": "\U0001F1EE\U0001F1F3",
    "PAKISTAN": "\U0001F1F5\U0001F1F0", "TURKEY": "\U0001F1F9\U0001F1F7",
    "USA": "\U0001F1FA\U0001F1F8", "UK": "\U0001F1EC\U0001F1E7",
    "CANADA": "\U0001F1E8\U0001F1E6", "AUSTRALIA": "\U0001F1E6\U0001F1FA",
    "GERMANY": "\U0001F1E9\U0001F1EA", "FRANCE": "\U0001F1EB\U0001F1F7",
    "SPAIN": "\U0001F1EA\U0001F1F8", "ITALY": "\U0001F1EE\U0001F1F9",
    "BRAZIL": "\U0001F1E7\U0001F1F7", "MEXICO": "\U0001F1F2\U0001F1FD",
    "LAOS": "\U0001F1F1\U0001F1F6", "CAMBODIA": "\U0001F1F0\U0001F1ED",
    "MYANMAR": "\U0001F1F2\U0001F1FE", "THAILAND": "\U0001F1F9\U0001F1ED",
    "VIETNAM": "\U0001F1FB\U0001F1F3", "PHILIPPINES": "\U0001F1F5\U0001F1ED",
    "INDONESIA": "\U0001F1EE\U0001F1E9", "MALAYSIA": "\U0001F1F2\U0001F1FE",
    "SINGAPORE": "\U0001F1F8\U0001F1EC", "JAPAN": "\U0001F1EF\U0001F1F5",
    "SOUTH KOREA": "\U0001F1F0\U0001F1F7", "RUSSIA": "\U0001F1F7\U0001F1FA",
    "CHINA": "\U0001F1E8\U0001F1F3", "SAUDI ARABIA": "\U0001F1F8\U0001F1E6",
    "ISRAEL": "\U0001F1EE\U0001F1F1", "JORDAN": "\U0001F1EF\U0001F1F4",
    "LEBANON": "\U0001F1F1\U0001F1F7", "IRAQ": "\U0001F1EE\U0001F1F3",
    "IRAN": "\U0001F1EE\U0001F1F7", "PALESTINE": "\U0001F1F5\U0001F1F4",
    "SUDAN": "\U0001F1F8\U0001F1E9", "ETHIOPIA": "\U0001F1EA\U0001F1F9",
    "TANZANIA": "\U0001F1F9\U0001F1FF", "UGANDA": "\U0001F1FA\U0001F1EC",
    "RWANDA": "\U0001F1F7\U0001F1F8", "SENEGAL": "\U0001F1F8\U0001F1F3",
    "COTE D'IVOIRE": "\U0001F1E8\U0001F1EE", "CAMEROON": "\U0001F1E8\U0001F1F2",
    "MOZAMBIQUE": "\U0001F1F2\U0001F1FF", "ZAMBIA": "\U0001F1FF\U0001F1FC",
    "ZIMBABWE": "\U0001F1FF\U0001F1FC", "MALAWI": "\U0001F1F2\U0001F1FC",
    "NAMIBIA": "\U0001F1F3\U0001F1F6", "BOTSWANA": "\U0001F1E7\U0001F1EA",
    "ANGOLA": "\U0001F1E6\U0001F1F4", "LIBYA": "\U0001F1EE\U0001F1F9",
    "TUNISIA": "\U0001F1F9\U0001F1F3", "ALGERIA": "\U0001F1E9\U0001F1FF",
    "BAHRAIN": "\U0001F1E7\U0001F1ED", "KUWAIT": "\U0001F1F0\U0001F1FC",
    "QATAR": "\U0001F1F6\U0001F1E6", "OMAN": "\U0001F1F2\U0001F1EA",
    "YEMEN": "\U0001F1FE\U0001F1EA", "CYPRUS": "\U0001F1E8\U0001F1FA",
    "GEORGIA": "\U0001F1EC\U0001F1EA", "ARMENIA": "\U0001F1F2\U0001F1F2",
    "AZERBAIJAN": "\U0001F1E6\U0001F1FF", "KAZAKHSTAN": "\U0001F1F0\U0001F1FF",
    "UZBEKISTAN": "\U0001F1FA\U0001F1FF", "UKRAINE": "\U0001F1FA\U0001F1E6",
    "POLAND": "\U0001F1F5\U0001F1F1", "ROMANIA": "\U0001F1F7\U0001F1F4",
    "CZECHIA": "\U0001F1E8\U0001F1FF", "HUNGARY": "\U0001F1ED\U0001F1FA",
    "GREECE": "\U0001F1EC\U0001F1F4", "PORTUGAL": "\U0001F1F5\U0001F1F9",
    "IRELAND": "\U0001F1EE\U0001F1EA", "NETHERLANDS": "\U0001F1F3\U0001F1F1",
    "BELGIUM": "\U0001F1E7\U0001F1EA", "SWEDEN": "\U0001F1F8\U0001F1EA",
    "NORWAY": "\U0001F1F3\U0001F1F4", "DENMARK": "\U0001F1E9\U0001F1F0",
    "FINLAND": "\U0001F1EB\U0001F1EE", "SWITZERLAND": "\U0001F1E8\U0001F1ED",
    "AUSTRIA": "\U0001F1E6\U0001F1F9", "BULGARIA": "\U0001F1E7\U0001F1EC",
    "SERBIA": "\U0001F1F7\U0001F1F8", "CROATIA": "\U0001F1E8\U0001F1ED",
    "SLOVENIA": "\U0001F1E8\U0001F1F0", "SLOVAKIA": "\U0001F1F8\U0001F1F0",
    "ALBANIA": "\U0001F1E6\U0001F1F1", "NORTH MACEDONIA": "\U0001F1F2\U0001F1F0",
    "MOLDOVA": "\U0001F1F2\U0001F1E9", "BELARUS": "\U0001F1E7\U0001F1FE",
    "BANGLADESH": "\U0001F1E7\U0001F1E9", "SRI LANKA": "\U0001F1F8\U0001F1F1",
    "NEPAL": "\U0001F1F3\U0001F1F0", "BHUTAN": "\U0001F1E7\U0001F1F5",
    "MALDIVES": "\U0001F1EE\U0001F1F3", "AFGHANISTAN": "\U0001F1E6\U0001F1EB",
    "KYRGYZSTAN": "\U0001F1F0\U0001F1EC", "TAJIKISTAN": "\U0001F1EF\U0001F1EF",
    "TURKMENISTAN": "\U0001F1F9\U0001F1B2", "MONGOLIA": "\U0001F1F2\U0001F1F3",
    "DOMINICAN REPUBLIC": "\U0001F1E9\U0001F1F4", "CUBA": "\U0001F1E8\U0001F1FA",
    "JAMAICA": "\U0001F1EC\U0001F1E8", "HAITI": "\U0001F1ED\U0001F1F9",
    "COLOMBIA": "\U0001F1E8\U0001F1F4", "CHILE": "\U0001F1E8\U0001F1F1",
    "PERU": "\U0001F1F5\U0001F1F1", "ARGENTINA": "\U0001F1E6\U0001F1F7",
    "ECUADOR": "\U0001F1EA\U0001F1E8", "BOLIVIA": "\U0001F1E7\U0001F1EB",
    "PARAGUAY": "\U0001F1F5\U0001F1EB", "URUGUAY": "\U0001F1F5\U0001F1FA",
    "VENEZUELA": "\U0001F1FB\U0001F1EA", "PANAMA": "\U0001F1F5\U0001F1F1",
    "COSTA RICA": "\U0001F1E8\U0001F1F7", "HONDURAS": "\U0001F1F3\U0001F1E8",
    "GUATEMALA": "\U0001F1EC\U0001F1F1", "EL SALVADOR": "\U0001F1F8\U0001F1F1",
    "NICARAGUA": "\U0001F1F3\U0001F1EA", "BELIZE": "\U0001F1E7\U0001F1FF",
    "NEW ZEALAND": "\U0001F1F3\U0001F1FF", "FIJI": "\U0001F1EB\U0001F1EF",
}
COUNTRY_NAME_BY_FLAG = {v: k for k, v in COUNTRY_FLAGS.items()}

# OTP extraction patterns, ordered most-specific first.
OTP_PATTERNS = [
    re.compile(r"(?:your\s+)?(?:verification|confirm|security|access|login)?\s*"
               r"code(?:\s+is)?[:\s]+(\d{4,8})", re.I),
    re.compile(r"(?:otp|pin|token)\s*[:\s]+(\d{4,8})", re.I),
    re.compile(r"<#>\s*(\d{4,8})"),
    re.compile(r"(?:codigo|c[oó]digo)\s*[:\s]+(\d{4,8})", re.I),
    re.compile(r"\b(\d{4,8})\b"),
]


# =========================== PARSING HELPERS ===========================

# Header aliases -> column role. SMSCDRStats report pages label their columns
# differently between builds, so we map by name and only guess when a build
# ships no <thead> at all.
COLUMN_ROLES = {
    "date": "date",
    "time": "date",
    "datetime": "date",
    "received": "date",
    "date/time": "date",
    "range": "range",
    "country": "range",
    "number": "number",
    "num": "number",
    "phone": "number",
    "msisdn": "number",
    "client": "service",
    "cli": "service",
    "service": "service",
    "app": "service",
    "sender": "service",
    "originator": "service",
    "sms": "sms",
    "msg": "sms",
    "message": "sms",
    "text": "sms",
    "body": "sms",
    "content": "sms",
    "cost": "cost",
    "price": "cost",
    "currency": "cost",
    "status": "status",
}


def _clean(text):
    """Collapse whitespace and drop the usual 'don't share this' footers."""
    if not text:
        return ""
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", str(text)))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?i)don'?t\s+share\s+this\s+code.*$", "", text).strip()
    text = re.sub(r"(?i)do\s+not\s+disclose\s+it\s+to\s+anyone\.?", "", text).strip()
    return text.strip()


def _is_dateish(text):
    s = _clean(text)
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$", s))


def _looks_like_totals_row(cells):
    """DataTables appends a totals row (['$0.10','$0.10','...']) — skip it."""
    for cell in cells:
        s = str(cell or "").strip()
        if not s:
            continue
        if s.startswith(("$", "\u20ac", "\u00a3", "\u00a5")):
            return True
    return False


def _pick_phone(cells):
    """Longest digit run of 7+ that isn't a date or a price."""
    best = ""
    for cell in cells:
        s = _clean(cell)
        if not s or _is_dateish(s):
            continue
        digits = re.sub(r"\D", "", s)
        if len(digits) < 7:
            continue
        if s.startswith(("$", "\u20ac", "\u00a3", "\u00a5")):
            continue
        # "+2348024126325" (12-13 digits) beats a 14-digit date stamp.
        if 7 <= len(digits) <= 15 and len(digits) > len(re.sub(r"\D", "", best)):
            best = s
    return best or "N/A"


def _pick_service(cells):
    """Short non-numeric, non-date cell is usually the app/originator name."""
    for cell in cells:
        s = _clean(cell)
        if not s or len(s) > 24:
            continue
        if re.fullmatch(r"[\d\s\-\.\+()]+", s):
            continue
        if _is_dateish(s):
            continue
        if s.lower() in ("date", "number", "sms", "client", "cli", "range", "msg"):
            continue
        return s
    return "Temp Numbers"


def _pick_timestamp(cells):
    for cell in cells:
        s = _clean(cell)
        m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?", s)
        if m:
            return m.group(0).replace("T", " ")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pick_message(cells):
    """The SMS body is the longest free-text cell that contains a code."""
    best = ""
    best_score = -1
    for cell in cells:
        s = _clean(cell)
        if not s or _is_dateish(s):
            continue
        if re.fullmatch(r"[\d\s\-\.\+()]+", s):
            continue
        # Prefer cells that actually yield an OTP, then prefer longer text.
        has_code = 1 if extract_otp(s) else 0
        score = has_code * 10000 + len(s)
        if score > best_score:
            best_score = score
            best = s
    return best


def extract_otp(text):
    """Pull the OTP out of an SMS body. Returns None when there is no code."""
    text = _clean(text)
    if not text:
        return None
    for pattern in OTP_PATTERNS:
        m = pattern.search(text)
        if m:
            code = m.group(1)
            # Reject obvious non-OTPs (years, prices, long digit runs).
            if len(code) <= 8 and code not in ("2024", "2025", "2026"):
                return code
    return None


def _build_sms(cells, roles=None):
    """Turn one scraped table row into a normalized SMS dict.

    ``roles`` maps column index -> role, taken from the table header when the
    page provides one. Without it we fall back to cell heuristics.
    """
    if len(cells) < 2 or _looks_like_totals_row(cells):
        return None

    if roles:
        sms_cell = next(
            (cells[i] for i, role in roles.items() if role == "sms"
             and i < len(cells)), "")
        number = next(
            (_clean(cells[i]) for i, role in roles.items() if role == "number"
             and i < len(cells)), "")
        service = next(
            (_clean(cells[i]) for i, role in roles.items()
             if role == "service" and i < len(cells)), "")
        date_cell = next(
            (cells[i] for i, role in roles.items() if role == "date"
             and i < len(cells)), "")
        message = _clean(sms_cell)
        otp = extract_otp(message)
        if not otp:
            return None
        timestamp = _pick_timestamp([date_cell] if date_cell else cells)
        if not service:
            service = "Temp Numbers"
        return {
            "otp": otp,
            "service": service,
            "number": number or "N/A",
            "full_text": message[:500],
            "timestamp": timestamp,
        }

    message = _pick_message(cells)
    otp = extract_otp(message)
    if not otp:
        return None
    return {
        "otp": otp,
        "service": _pick_service(cells),
        "number": _pick_phone(cells),
        "full_text": message[:500],
        "timestamp": _pick_timestamp(cells),
    }


def _header_roles(table):
    """Read <thead> and map column index -> role."""
    thead = table.find("thead")
    if thead is None:
        return None
    titles = [th.get_text(" ", strip=True) for th in thead.find_all("th")]
    if not titles:
        return None
    roles = {}
    for idx, title in enumerate(titles):
        key = re.sub(r"[^a-z/ ]", "", title.strip().lower()).strip()
        role = COLUMN_ROLES.get(key)
        if role:
            roles[idx] = role
    # We need at least an SMS column and a number column to trust the header.
    if "sms" not in roles.values() or "number" not in roles.values():
        return None
    return roles


def _parse_report_html(page_html):
    """Parse the SMSCDRReports page into normalized SMS dicts."""
    results = []

    if BS4_AVAILABLE:
        soup = BeautifulSoup(page_html, "html.parser")
        tables = soup.find_all("table") or [None]
        for table in tables:
            rows = table.find_all("tr") if table is not None else soup.find_all("tr")
            roles = _header_roles(table) if table is not None else None
            for row in rows:
                cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
                sms = _build_sms(cells, roles)
                if sms:
                    results.append(sms)
            if results:
                return results

    # Regex fallback: every <tr> as a list of stripped cell texts.
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html,
                                re.I | re.S):
        cells = [
            _clean(m) for m in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>",
                                           row_html, re.I | re.S)
        ]
        sms = _build_sms(cells)
        if sms:
            results.append(sms)
    return results


# =========================== LOGIN ===========================


def _solve_captcha(page_html):
    """Solve the panel's arithmetic captcha.

    The question lives in the label bound to the `capt` input
    (``<label id="captcha-question">What is 1 + 5 = ?</label>``). Scanning the
    whole page for the first "a + b" picks up unrelated numbers (phone
    numbers, counts) and produces a wrong answer, so read the label first.
    """
    question = None
    if BS4_AVAILABLE:
        soup = BeautifulSoup(page_html, "html.parser")
        inp = soup.find("input", {"name": "capt"})
        label = None
        if inp is not None:
            if inp.get("id"):
                label = soup.find("label", {"for": inp["id"]})
            if label is None:
                label = inp.find_previous("label")
        if label is None:
            el = soup.find(id="captcha-question") or soup.find(id="captcha-label")
            if el is not None:
                label = el
        if label is not None:
            question = label.get_text(" ", strip=True)

    m = re.search(r"(\d+)\s*\+\s*(\d+)", question or "")
    if not m:
        # Fall back to the page-wide scan only when no label was found.
        m = re.search(r"(\d+)\s*\+\s*(\d+)", page_html or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return str(a + b), f"{a} + {b}"


def login(force=False):
    """Log into the panel as a client. Returns True on success.

    Respects the panel's one-login-per-minute limit; a second attempt inside
    the cooldown window is refused instead of burning the lockout.
    """
    global _last_login_attempt
    now = time.time()
    if not force and (now - _last_login_attempt) < LOGIN_COOLDOWN:
        wait = LOGIN_COOLDOWN - (now - _last_login_attempt)
        logger.info("Skipping login: panel rate limit, retry in %.0fs", wait)
        return False
    _last_login_attempt = time.time()

    logger.info("Logging in to %s (%s)...", PANEL_NAME, PANEL_URL)
    try:
        resp = session.get(LOGIN_URL, timeout=REQUEST_TIMEOUT)

        data = {"username": USERNAME, "password": PASSWORD}
        capt = _solve_captcha(resp.text)
        if capt:
            data["capt"], expression = capt
            logger.info("Captcha: %s = %s", expression, data["capt"])

        # Some builds use a CSRF token instead of the arithmetic captcha.
        if "capt" not in data and BS4_AVAILABLE:
            tok = BeautifulSoup(resp.text, "html.parser").find(
                "input", {"name": "_token"})
            if tok and tok.get("value"):
                data["_token"] = tok["value"]

        resp = session.post(SIGNIN_URL, data=data, timeout=REQUEST_TIMEOUT,
                            allow_redirects=True)
        final_url = resp.url.lower()
        page = resp.text.lower()

        if "login" in final_url or "signin" in final_url:
            # Surface the panel's own reason — it rate-limits and can report
            # bad credentials, and both are silent otherwise.
            reason = ""
            if BS4_AVAILABLE:
                soup = BeautifulSoup(resp.text, "html.parser")
                for sel in (".error", ".alert", "#message", ".text-danger"):
                    for el in soup.select(sel):
                        reason = el.get_text(" ", strip=True)[:160]
                        break
                    if reason:
                        break
            logger.warning("Login FAILED — %s", reason or f"final URL {resp.url[:80]}")
            return False

        # Not on a login page any more, so the session is established.
        if "smscdrstats" in final_url or "smsdashboard" in final_url \
                or "dashboard" in final_url:
            logger.info("Login OK (redirected to %s)", resp.url[:60])
            return True
        if 'type="password"' not in page and (
            "smscdrstats" in page or "side-nav" in page or "sms reports" in page
        ):
            logger.info("Login OK (dashboard content in response)")
            return True

        logger.info("Login OK (redirected away from login: %s)", resp.url[:60])
        return True
    except Exception as exc:
        logger.error("Login error: %s", exc)
        return False


# =========================== FETCH OTPS ===========================


def fetch_otps():
    """Scrape the report page. Returns a list of normalized SMS dicts."""
    for page_url in REPORT_PAGES:
        try:
            resp = session.get(page_url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("GET %s failed: %s", page_url, exc)
            continue

        # A redirect back to the login page means the session expired.
        if "login" in resp.url.lower() or "signin" in resp.url.lower():
            logger.warning("Session expired (redirected to login), re-logging in")
            login()  # self-limits via LOGIN_COOLDOWN
            return []  # every page needs the session; don't probe the rest

        if resp.status_code != 200:
            logger.warning("%s returned HTTP %s", page_url, resp.status_code)
            continue

        sms_list = _parse_report_html(resp.text)
        if sms_list:
            logger.info("Scraped %s SMS(s) from %s",
                        len(sms_list), page_url)
        else:
            logger.debug("No SMS rows parsed from %s", page_url)
        return sms_list

    return []


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


def send_to_groups(text, reply_markup=None):
    """Send the OTP to every configured OTP group."""
    sent = 0
    for gid in OTP_GROUPS:
        if _tg_send(gid, text, reply_markup):
            sent += 1
            logger.info("Group %s: sent", gid)
    return sent > 0


def forward_to_main_bot(text, otp_code):
    """Send the OTP straight to the owner's chat, with a copy button."""
    if not FORWARD_USER:
        return False
    kb = {"inline_keyboard": [[
        {"text": f"\U0001F4CB {otp_code}", "callback_data": f"copy_{otp_code}"},
        {"text": "\U0001F916 BOT", "url": BOT_LINK},
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
    service = _clean(sms.get("service", "Temp Numbers")) or "Temp Numbers"
    phone = sms.get("number", "N/A")
    otp = sms["otp"]
    ts = sms.get("timestamp", "")
    body = _clean(sms.get("full_text", ""))[:300]

    otp_display = f"{otp[:3]}-{otp[3:]}" if len(otp) == 6 else otp
    rule = "\u2501" * 15
    msg = (
        "<b>Anonmatrixx</b>\n"
        f"{rule}\n"
        f"\U0001F4CD <b>{html_mod.escape(service.upper())}</b> \U0001F7E2\n"
        f"\U0001F4F1 <code>{html_mod.escape(phone)}</code>\n"
        f"\U0001F511 <b>OTP:</b> <code>{html_mod.escape(otp_display)}</code>\n"
        f"\U0001F4E9 <b>Message:</b> <code>{html_mod.escape(body)}</code>\n"
        f"\u23F0 {html_mod.escape(ts)}\n"
        f"{rule}"
    )
    kb = {"inline_keyboard": [[
        {"text": "\U0001F4CB Copy Message",
         "callback_data": f"copy_{otp}"},
        {"text": "\U0001F916 BOT LINK", "url": BOT_LINK},
    ]]}

    sent_groups = send_to_groups(msg, kb)
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
        _clean(sms.get("full_text", ""))[:60],
    ])


def main():
    print("=" * 55)
    print(f"  \U0001F525 {PANEL_NAME} OTP Forwarder")
    print("=" * 55)
    print(f"  Panel:    {PANEL_URL}")
    print(f"  Page:     {REPORT_PAGES[0]}")
    print(f"  Groups:   {len(OTP_GROUPS)}")
    print(f"  Main bot: {FORWARD_USER or 'Not configured'}")
    print(f"  Poll:     Every {POLL_INTERVAL}s")
    print("=" * 55)
    print()

    if not login():
        logger.error("Login failed! Check the panel credentials in bot admin.")
        sys.exit(1)

    if OTP_GROUPS:
        _tg_send(
            OTP_GROUPS[0],
            f"\U0001F7E2 <b>{PANEL_NAME} Forwarder Started!</b>\n"
            f"Polling every {POLL_INTERVAL}s",
        )
    logger.info("Monitoring OTPs...")

    first_run = True
    total = 0
    while True:
        try:
            otps = fetch_otps()

            for sms in otps:
                key = _sms_key(sms)
                if key in _seen:
                    continue
                if first_run:
                    # Don't spam the groups with whatever is already in the
                    # report when the forwarder starts.
                    _seen.add(key)
                    continue
                if send_otp(sms):
                    _seen.add(key)
                    total += 1
                    logger.info("Sent OTP %s (total: %s)",
                                sms["otp"], total)
                else:
                    logger.warning(
                        "Delivery failed for OTP %s — will retry next poll",
                        sms["otp"],
                    )

            if first_run:
                logger.info("Init: %s existing SMS row(s) skipped",
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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Forwarder stopped.")
        sys.exit(0)