#!/usr/bin/env python3
"""Generate all panel scripts from the template. Run once, then delete this file."""

import os

PANELS = [
    ("evs_sms", "EVS SMS", "agent"),
    ("astra_sms", "Astra SMS", "client"),
    ("bolt", "Bolt", "client"),
    ("core_sms", "Core SMS", "client"),
    ("emo_sms", "Emo SMS", "client"),
    ("firesms", "Firesms", "client"),
    ("flex_sms", "Flex SMS", "client"),
    ("fly_sms", "Fly SMS", "client"),
    ("flyn_sms", "Flyn SMS", "client"),
    ("gaza_iprn", "Gaza IPRN", "client"),
    ("goat_sms", "Goat SMS", "client"),
    ("green_sms", "Green SMS", "client"),
    ("hadi", "Hadi", "client"),
    ("hi_sms", "Hi SMS", "client"),
    ("km_sms", "KM SMS", "client"),
    ("lamix", "Lamix", "client"),
    ("link_sms", "Link SMS", "client"),
    ("markoitech", "Markoitech", "client"),
    ("meteorite", "Meteorite", "client"),
    ("msi", "MSI", "client"),
    ("number_panel", "Number Panel", "client"),
    ("proof_sms", "Proof SMS", "client"),
    ("proton", "Proton", "client"),
    ("pscall", "PSCall", "client"),
    ("purple", "Purple", "client"),
    ("rexo_sms", "Rexo SMS", "client"),
    ("rez_sms", "Rez SMS", "client"),
    ("roxy", "Roxy", "client"),
    ("rsayel", "Rsayel", "client"),
    ("seven1tel", "Seven1tel", "client"),
    ("shark", "Shark", "client"),
    ("sniper_sms", "Sniper SMS", "client"),
    ("squad_sms", "Squad SMS", "client"),
    ("star_sms", "Star SMS", "client"),
    ("target_sms", "Target SMS", "client"),
    ("voicegate", "Voicegate", "client"),
    ("wolf", "Wolf", "client"),
    ("xap", "Xap", "client"),
    ("zento", "Zento", "client"),
    ("zyron_sms", "Zyron SMS", "client"),
    ("zone_sms", "Zone SMS", "client"),
]

COUNTRY_FLAGS = '''COUNTRY_FLAGS = {
    "EGYPT": "\U0001f1ea\U0001f1ec", "GHANA": "\U0001f1ec\U0001f1ed", "NIGERIA": "\U0001f1f3\U0001f1ec", "KENYA": "\U0001f1f0\U0001f1ea",
    "SOUTH AFRICA": "\U0001f1ff\U0001f1e6", "MOROCCO": "\U0001f1f2\U0001f1e6", "UAE": "\U0001f1e6\U0001f1ea", "INDIA": "\U0001f1ee\U0001f1f3",
    "PAKISTAN": "\U0001f1f5\U0001f1f0", "TURKEY": "\U0001f1f9\U0001f1f7", "USA": "\U0001f1fa\U0001f1f8", "UK": "\U0001f1ec\U0001f1e7",
    "CANADA": "\U0001f1e8\U0001f1e6", "AUSTRALIA": "\U0001f1e6\U0001f1fa", "GERMANY": "\U0001f1e9\U0001f1ea", "FRANCE": "\U0001f1eb\U0001f1f7",
    "SPAIN": "\U0001f1ea\U0001f1f8", "ITALY": "\U0001f1ee\U0001f1f9", "BRAZIL": "\U0001f1e7\U0001f1f7", "MEXICO": "\U0001f1f2\U0001f1fd",
    "ARGENTINA": "\U0001f1e6\U0001f1f7", "LAOS": "\U0001f1f1\U0001f1e6", "LEBANON": "\U0001f1f1\U0001f1e7", "JORDAN": "\U0001f1ef\U0001f1f4",
    "ISRAEL": "\U0001f1ee\U0001f1f1", "SAUDI ARABIA": "\U0001f1f8\U0001f1e6", "KUWAIT": "\U0001f1f0\U0001f1fc", "QATAR": "\U0001f1f6\U0001f1e6",
    "OMAN": "\U0001f1f4\U0001f1f2", "BAHRAIN": "\U0001f1e7\U0001f1ed", "RUSSIA": "\U0001f1f7\U0001f1fa", "CHINA": "\U0001f1e8\U0001f1f3",
    "JAPAN": "\U0001f1ef\U0001f1f5", "SOUTH KOREA": "\U0001f1f0\U0001f1f7", "SINGAPORE": "\U0001f1f8\U0001f1ec", "MALAYSIA": "\U0001f1f2\U0001f1fe",
    "INDONESIA": "\U0001f1ee\U0001f1e9", "PHILIPPINES": "\U0001f1f5\U0001f1ed", "VIETNAM": "\U0001f1fb\U0001f1f3", "THAILAND": "\U0001f1f9\U0001f1ed",
    "CAMBODIA": "\U0001f1f0\U0001f1ed", "MYANMAR": "\U0001f1f2\U0001f1f2", "BANGLADESH": "\U0001f1e7\U0001f1e9", "SRI LANKA": "\U0001f1f1\U0001f1f0",
    "NEPAL": "\U0001f1f3\U0001f1f5", "NEW ZEALAND": "\U0001f1f3\U0001f1ff", "SWITZERLAND": "\U0001f1e8\U0001f1ed", "SWEDEN": "\U0001f1f8\U0001f1ea",
    "NORWAY": "\U0001f1f3\U0001f1f4", "DENMARK": "\U0001f1e9\U0001f1f0", "FINLAND": "\U0001f1eb\U0001f1ee", "IRELAND": "\U0001f1ee\U0001f1ea",
    "PORTUGAL": "\U0001f1f5\U0001f1f9", "GREECE": "\U0001f1ec\U0001f1f7", "POLAND": "\U0001f1f5\U0001f1f1", "UKRAINE": "\U0001f1fa\U0001f1e6",
    "ROMANIA": "\U0001f1f7\U0001f1f4", "CZECHIA": "\U0001f1e8\U0001f1ff", "HUNGARY": "\U0001f1ed\U0001f1fa", "SLOVAKIA": "\U0001f1f8\U0001f1f0",
    "SLOVENIA": "\U0001f1f8\U0001f1ee", "CROATIA": "\U0001f1ed\U0001f1f7", "BOSNIA": "\U0001f1e7\U0001f1e6", "SERBIA": "\U0001f1f7\U0001f1f8",
    "ALBANIA": "\U0001f1e6\U0001f1f1", "BULGARIA": "\U0001f1e7\U0001f1ec", "AFGHANISTAN": "\U0001f1e6\U0001f1eb", "ALGERIA": "\U0001f1e9\U0001f1ff",
    "ANGOLA": "\U0001f1e6\U0001f1f4", "ARMENIA": "\U0001f1e6\U0001f1f2", "AUSTRIA": "\U0001f1e6\U0001f1f9", "AZERBAIJAN": "\U0001f1e6\U0001f1ff",
    "BELARUS": "\U0001f1e7\U0001f1fe", "BELGIUM": "\U0001f1e7\U0001f1ea", "BELIZE": "\U0001f1e7\U0001f1ff", "BENIN": "\U0001f1e7\U0001f1ef",
    "BHUTAN": "\U0001f1e7\U0001f1f9", "BOLIVIA": "\U0001f1e7\U0001f1f4", "BOTSWANA": "\U0001f1e7\U0001f1fc", "BRUNEI": "\U0001f1e7\U0001f1f3",
    "BURKINA": "\U0001f1e7\U0001f1eb", "BURUNDI": "\U0001f1e7\U0001f1ee", "CAMEROON": "\U0001f1e8\U0001f1f2", "CHAD": "\U0001f1f9\U0001f1e9",
    "CHILE": "\U0001f1e8\U0001f1f1", "COLOMBIA": "\U0001f1e8\U0001f1f4", "CONGO": "\U0001f1e8\U0001f1ec", "COSTA RICA": "\U0001f1e8\U0001f1f7",
    "CUBA": "\U0001f1e8\U0001f1fa", "CYPRUS": "\U0001f1e8\U0001f1fe", "DJIBOUTI": "\U0001f1e9\U0001f1ef", "DOMINICAN REPUBLIC": "\U0001f1e9\U0001f1f4",
    "ECUADOR": "\U0001f1ea\U0001f1e8", "EL SALVADOR": "\U0001f1f8\U0001f1fb", "ESTONIA": "\U0001f1ea\U0001f1ea", "ETHIOPIA": "\U0001f1ea\U0001f1f9",
    "FIJI": "\U0001f1eb\U0001f1ef", "GABON": "\U0001f1ec\U0001f1e6", "GAMBIA": "\U0001f1ec\U0001f1f2", "GEORGIA": "\U0001f1ec\U0001f1ea",
    "GUATEMALA": "\U0001f1ec\U0001f1f9", "GUINEA": "\U0001f1ec\U0001f1f3", "GUYANA": "\U0001f1ec\U0001f1fe", "HAITI": "\U0001f1ed\U0001f1f9",
    "HONDURAS": "\U0001f1ed\U0001f1f3", "ICELAND": "\U0001f1ee\U0001f1f8", "JAMAICA": "\U0001f1ef\U0001f1f2", "KAZAKHSTAN": "\U0001f1f0\U0001f1f0",
    "KYRGYZSTAN": "\U0001f1f0\U0001f1ec", "LATVIA": "\U0001f1f1\U0001f1fb", "LESOTHO": "\U0001f1f1\U0001f1f8", "LIBERIA": "\U0001f1f1\U0001f1f7",
    "LIBYA": "\U0001f1f1\U0001f1fe", "LITHUANIA": "\U0001f1f1\U0001f1f9", "LUXEMBOURG": "\U0001f1f1\U0001f1fa", "MADAGASCAR": "\U0001f1f2\U0001f1ec",
    "MALAWI": "\U0001f1f2\U0001f1fc", "MALDIVES": "\U0001f1f2\U0001f1fb", "MALI": "\U0001f1f2\U0001f1f1", "MALTA": "\U0001f1f2\U0001f1f9",
    "MAURITANIA": "\U0001f1f2\U0001f1f7", "MAURITIUS": "\U0001f1f2\U0001f1fa", "MOLDOVA": "\U0001f1f2\U0001f1e9", "MONACO": "\U0001f1f2\U0001f1e8",
    "MONGOLIA": "\U0001f1f2\U0001f1f3", "MONTENEGRO": "\U0001f1f2\U0001f1ea", "MOZAMBIQUE": "\U0001f1f2\U0001f1ff", "NAMIBIA": "\U0001f1f3\U0001f1e6",
    "NICARAGUA": "\U0001f1f3\U0001f1ee", "NIGER": "\U0001f1f3\U0001f1ea", "NORTH MACEDONIA": "\U0001f1f2\U0001f1f0", "PALESTINE": "\U0001f1f5\U0001f1f8",
    "PANAMA": "\U0001f1f5\U0001f1e6", "PARAGUAY": "\U0001f1f5\U0001f1fe", "PERU": "\U0001f1f5\U0001f1ea", "RWANDA": "\U0001f1f7\U0001f1fc",
    "SENEGAL": "\U0001f1f8\U0001f1f3", "SIERRA LEONE": "\U0001f1f8\U0001f1f1", "SOMALIA": "\U0001f1f8\U0001f1f4", "SOUTH SUDAN": "\U0001f1f8\U0001f1f8",
    "SYRIA": "\U0001f1f8\U0001f1fe", "TAJIKISTAN": "\U0001f1f9\U0001f1ef", "TANZANIA": "\U0001f1f9\U0001f1ff", "TOGO": "\U0001f1f9\U0001f1ec",
    "TUNISIA": "\U0001f1f9\U0001f1f3", "TURKMENISTAN": "\U0001f1f9\U0001f1f2", "UGANDA": "\U0001f1fa\U0001f1ec", "URUGUAY": "\U0001f1fa\U0001f1fe",
    "UZBEKISTAN": "\U0001f1fa\U0001f1ff", "VENEZUELA": "\U0001f1fb\U0001f1ea", "YEMEN": "\U0001f1fe\U0001f1ea",
    "ZAMBIA": "\U0001f1ff\U0001f1f2", "ZIMBABWE": "\U0001f1ff\U0001f1fc"
}'''


def gen_panel(filename, display_name, default_login_type):
    return f'''#!/usr/bin/env python3
"""
{display_name} OTP Bot
Reads ALL credentials from main bot database. NO hardcoded passwords.
Admin adds panel via bot admin, then runs this script.

Usage: python panels/{filename}.py
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
PANEL_NAME = "{display_name}"
DEFAULT_LOGIN_TYPE = "{default_login_type}"

DB_PATH = os.environ.get("DB_PATH", "data/ivasms_bot.db")
POLL_INTERVAL = 3

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
    errors.append(f"Panel '{{PANEL_NAME}}' not found in database — add via bot admin > SMS Panels")
else:
    if not PANEL.get("url"):
        errors.append("Panel URL is empty")
    if not PANEL.get("username"):
        errors.append("Panel username is empty")
    if not PANEL.get("password"):
        errors.append("Panel password is empty")

if errors:
    print("=" * 50)
    print(f"  {{PANEL_NAME}} — CONFIGURATION ERRORS")
    print("=" * 50)
    for i, e in enumerate(errors, 1):
        print(f"  {{i}}. {{e}}")
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
    f"{{LOGIN_TYPE}}/res/data_smscdr.php",
    "agent/res/data_smscdr.php",
    "client/res/data_smscdr.php",
]
LOGIN_URL = f"{{PANEL_URL}}/login"
SIGNIN_URL = f"{{PANEL_URL}}/signin"

# =========================== SETUP ===========================
logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{{PANEL_NAME}}] %(message)s")
logger = logging.getLogger(__name__)

session = requests.Session()
session.headers.update({{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*",
}})

last_sms_hashes = set()
total_otps_sent = 0
first_run = True

# =========================== COUNTRY FLAGS ===========================
{COUNTRY_FLAGS}

COUNTRIES_LIST = "|".join(re.escape(c) for c in COUNTRY_FLAGS.keys())
COUNTRY_PATTERN = re.compile(r"(" + COUNTRIES_LIST + ")", re.IGNORECASE)


# =========================== TELEGRAM ===========================
def send_to_groups(text, reply_markup=None):
    sent = 0
    for gid in OTP_GROUPS:
        try:
            payload = {{"chat_id": gid, "text": text, "parse_mode": "HTML"}}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            r = requests.post(f"https://api.telegram.org/bot{{BOT_TOKEN}}/sendMessage", data=payload, timeout=10)
            if r.status_code == 200:
                sent += 1
        except Exception as exc:
            logger.error(f"Telegram error to {{gid}}: {{exc}}")
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

    flag = COUNTRY_FLAGS.get(country, "\\U0001f30d")
    phone = sms.get("number", "N/A")
    otp = sms["otp"]
    service = sms.get("service", "Unknown")
    ts = sms.get("timestamp", "")
    clean = re.sub(r"\\s+", " ", sms["full_text"]).strip()[:300]

    msg = (
        f"\\U0001f525 {{country}} {{service.upper()}} OTP!\\n"
        f"\\U0001f4c5 {{ts}}\\n"
        f"\\U0001f5fa\\ufe0f {{country}} {{flag}}\\n"
        f"\\U0001f4f1 {{service}}\\n"
        f"\\U0001f4de {{phone}}\\n"
        f"\\U0001f511 {{otp}}\\n\\n"
        f"\\U0001f4e9 {{clean}}"
    )
    kb = {{"inline_keyboard": [[{{"text": "\\U0001f916 Bot", "url": BOT_LINK}}]]}}
    return send_to_groups(msg, json.dumps(kb))


# =========================== LOGIN ===========================
def login():
    logger.info(f"Logging in to {{PANEL_NAME}}...")
    try:
        resp = session.get(LOGIN_URL, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        nums = re.findall(r"(\\d+)\\s*\\+\\s*(\\d+)", soup.get_text())
        data = {{"username": USERNAME, "password": PASSWORD}}
        if nums:
            data["capt"] = str(int(nums[0][0]) + int(nums[0][1]))
            logger.info(f"Captcha: {{nums[0][0]}} + {{nums[0][1]}} = {{data['capt']}}")
        resp = session.post(SIGNIN_URL, data=data, timeout=30, allow_redirects=True)
        if "dashboard" in resp.url.lower() or "signin" not in resp.url.lower():
            logger.info("Login successful!")
            return True
        logger.warning(f"Login failed ({{resp.url[:80]}})")
        return False
    except Exception as exc:
        logger.error(f"Login error: {{exc}}")
        return False


# =========================== FETCH OTPS ===========================
def fetch_otps():
    sms_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for date in [today, yesterday]:
        params = {{
            "draw": "1", "start": "0", "length": "100",
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "0", "order[0][dir]": "asc",
            "fdate1": f"{{date}} 00:00:00", "fdate2": f"{{date}} 23:59:59",
            "frange": "", "fclient": "", "fnum": "", "fcli": "",
            "fgdate": "", "fgmonth": "", "fgrange": "", "fgclient": "",
            "fgnumber": "", "fgcli": "", "fg": "0",
        }}
        for path in API_PATHS:
            try:
                resp = session.get(f"{{PANEL_URL}}/{{path}}", params=params, timeout=30)
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
                        re.search(r"code\\s+(\\d{{4,6}})", full, re.I)
                        or re.search(r"use code\\s+(\\d{{4,6}})", full, re.I)
                        or re.search(r"code[:]\\s*(\\d{{4,6}})", full, re.I)
                        or re.search(r"<#>\\s*(\\d{{4,6}})", full, re.I)
                        or re.search(r"(\\d{{4,6}})", full)
                    )
                    if m:
                        sms_list.append({{
                            "otp": m.group(1),
                            "service": str(rec[3] or "Unknown"),
                            "full_text": full,
                            "timestamp": str(rec[0] or ""),
                            "range": str(rec[1] or ""),
                            "number": str(rec[2] or "N/A"),
                        }})
                break
            except (requests.RequestException, json.JSONDecodeError):
                continue
    if sms_list:
        logger.info(f"Found {{len(sms_list)}} OTPs")
    return sms_list


# =========================== MAIN ===========================
def main():
    global total_otps_sent, last_sms_hashes, first_run

    print("=" * 50)
    print(f"  {{PANEL_NAME}} OTP Bot")
    print("=" * 50)
    print(f"  Panel: {{PANEL_URL}}")
    print(f"  Type:  {{LOGIN_TYPE}}")
    print(f"  Groups: {{len(OTP_GROUPS)}}")
    print("=" * 50)

    if not login():
        logger.error("Login failed! Check credentials in bot admin panel.")
        return

    send_to_groups(f"\\U0001f7e2 {{PANEL_NAME}} Started!")
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
                            logger.info(f"\\u2705 Sent {{sms['otp']}} (Total: {{total_otps_sent}})")
                    else:
                        last_sms_hashes.add(h)
            if first_run:
                logger.info(f"Init: {{len(last_sms_hashes)}} existing OTPs loaded")
                first_run = False
        except Exception as exc:
            logger.error(f"Loop error: {{exc}}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    os.makedirs("panels", exist_ok=True)
    count = 0
    for fname, dname, ltype in PANELS:
        path = f"panels/{fname}.py"
        with open(path, "w") as f:
            f.write(gen_panel(fname, dname, ltype))
        count += 1
    print(f"Generated {count} panel scripts in panels/")
