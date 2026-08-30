#!/usr/bin/env python3
"""
MATRIXX PREMIUM SMS BOT – Final Fixed Version
- /start works reliably with error handling
- Premium emoji IDs for WhatsApp (5233354831984353090) and Togo flag (5294097669688415562)
- Number assignment message uses premium emojis in a clean layout
- OTPs delivered to both user DM and groups
- All previous fixes retained   
"""

import os
import sys
import time
import json
import re
import sqlite3
import threading
import traceback
import logging
import random
import requests
import hashlib
import uuid
import copy
from datetime import datetime
from collections import defaultdict

import telebot
from telebot import types

try:
    import socketio
    import engineio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    logging.warning("SocketIO not installed – OTP monitoring disabled.")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# =========================== CONFIGURATION ===========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8779205330:AAE9hAye3DIqmNIdEphJSZ52l89-6DEyIrw")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8848549813"))
EXTRA_ADMINS = [8018626840, 8653648506]

WSS_URL = "wss://ivasms.qzz.io:2087/socket.io/?token=eyJpdiI6InlUVmNva1RlSU8vMWZaVm1zTTB1QUE9PSIsInZhbHVlIjoicDZMSXNxWmJGZC81Qy9BbzhBUVR3N0hLTXpiU0xXdDUrZXBmNjd0MmZsS295ZGZ4ay9qcktSQ1p4cDFZVlJTYlQ4dFFBcUo1TzZaMHdEUXZxVy8xTXFKQng4ekoyU0FzL2VkRkhDRkQ2Wkdxc0s2TmpoSi9acGlydi9sN0FhMVJISHQ3TUJOSXNFamNndTlrVWRMeFpLTU83VkZROEtLUGtQbld0aU5JcGRLQ2lPL3dHdzk1ZXlXc3pYMy84VkduU3Z1dmllSlBDQ3RKVElEc215QTBvRVkyVkVHclQ0Z3ExOFVWNFpkb3lMdWpHeDhWTG1yWllUbEgwemtQYTNyL2ROQmZuRlp3M1VDbjc3RWdNK1JKRU5abGRHNFR0d1VWZE13K2tOdjVxSEE0clpWbUxPZDFvaXdJUjhtS3AvTllKY2dDNCs3b0N6QWptck9zN3Z0MDFqaUh0bVFZOUNMdTNITEVKWnMwdHJ3aHc5V29HL2s5OGZqN3NINmg1VEpyTHQwdXllV1NXR2hDZzVKSXpIblJUcUFZVlZ0NDhTNm1aeEhscXlyVVZDRVNlRFQvUngxQmNTL0FiZCtUOVB4SllwVmc4RjBtUDZLZDBKblh6WERjVWFXdk91Vk1aNVJwcGVFTGhxN3QrWmF5VVNRSTZWUG1PTXowNEptTmk1bE16TGZtRWZPZGN6aGUxSk5MWUtsSzJnPT0iLCJtYWMiOiI5YzdiYTE3M2E3OTViMDlmMmU4Yjc1N2FlZmMwNmUzOWU5NDE1ZDIyMWY0Yzk4ZjgzNGU4MDU3Yjg2YzMxZjY3IiwidGFnIjoiIn0%3D&user=81d1d9839bdd2141f706d3cf6ee686ef"
WSS_HEADERS = {
    "Origin": "https://ivasms.qzz.io",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://ivasms.qzz.io/",
}

ALLOWED_SERVICES = {
    "whatsapp", "facebook", "tiktok", "google", "instagram", "telegram",
    "twitter", "discord", "line", "viber", "skype", "snapchat", "amazon",
    "apple", "microsoft", "linkedin", "uber", "airbnb", "netflix", "spotify",
    "youtube", "github", "pinterest", "paypal", "booking", "tala", "olx",
    "stcpay", "unknown"
}
REFERRAL_REWARD = 0.10
MIN_WITHDRAWAL = 1.0
MAX_WITHDRAWAL = 5.0
ADMIN_IDS = [ADMIN_ID, *EXTRA_ADMINS]
DB_PATH = "bot.db"

# ======================== THREAD SAFETY & PERSISTENCE ========================
# Thread lock for all SQLite write operations
_db_lock = threading.Lock()

def _persist_db():
    """No-op — SQLite file persists on disk automatically."""
    pass

def _get_conn():
    """Get a SQLite connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

# =========================== LOGGING ===========================
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
logger = logging.getLogger(__name__)

# =========================== PREMIUM EMOJI LOADER ===========================
EMOJI_FILE = "emoji.txt"

# Hardcoded premium emoji IDs for specific elements
PREMIUM_EMOJI_IDS = {
    "whatsapp": "5233354831984353090",
    "togo": "5294097669688415562",
    # Add more if needed
}

def load_premium_emojis(path=EMOJI_FILE):
    icons, flags = {}, {}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return icons, flags
    for key, val in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"(\d{15,})"', content):
        if re.fullmatch(r"[A-Z]{2}(?:_2)?", key):
            flags[key.split('_')[0]] = val
        else:
            icons[key.lower()] = val
    for val, key in re.findall(r'(\d{15,})\s+-\s+([A-Za-z0-9_]+)', content):
        icons[key.lower()] = val
    return icons, flags

PREMIUM_ICONS, PREMIUM_FLAGS = load_premium_emojis()
# Toggle for premium emoji – set to False if Telegram keeps rejecting custom emoji
PREMIUM_EMOJI_OK = os.getenv("PREMIUM_EMOJI", "1") == "1"

# Explicit Unicode fallbacks for when premium emoji IDs aren't available.
# Only mapped where a specific visual symbol is needed — no blanket replacements.
UNICODE_FALLBACKS = {
    "stars": "\U0001F451", "star": "\u2B50", "wave": "\U0001F44B",
    "stats": "\U0001F4CA", "lock": "\U0001F510", "top": "\U0001F3C6",
    "chart_up": "\U0001F4C8", "chart_down": "\U0001F4C9",
    "wrench": "\U0001F6E0\uFE0F", "people": "\U0001F465", "users": "\U0001F465",
    "card": "\U0001F4B3", "record": "\U0001F534", "live": "\U0001F7E2",
    "ban": "\U0001F6AB", "cancel": "\u274C", "cross": "\u274C",
    "checkmark": "\u2705", "verified": "\u2705",
    "exclamation": "\u2757", "double_excl": "\u203C\uFE0F",
    "question": "\u2753", "warning_yellow": "\u26A0\uFE0F",
    "warning_red": "\U0001F6A8", "urgent": "\U0001F6A8",
    "breaking": "\U0001F4F0", "announcement": "\U0001F4E2",
    "bell": "\U0001F514", "pin": "\U0001F4CC",
    "dollar": "\U0001F4B5", "euro": "\U0001F4B6",
    "fire": "\U0001F525", "explosion": "\U0001F4A5",
    "secret": "\U0001F512", "flash": "\u26A1",
    "chat": "\U0001F4AC", "support": "\U0001F3A7",
    "headphones": "\U0001F3A7", "admin": "\U0001F6E1\uFE0F",
    "settings": "\u2699\uFE0F", "refresh": "\U0001F504",
    "back": "\u2B05\uFE0F", "link": "\U0001F517",
    "new_badge": "\U0001F195", "strelka_right": "\u27A1\uFE0F",
    "phone": "\U0001F4DE", "earth": "\U0001F30D",
    "calendar": "\U0001F4C5", "withdraw": "\U0001F4B8",
    "referral": "\U0001F91D", "default": "\U0001F4F1",
    "archive": "\U0001F4C2", "hourglass": "\u23F3",
}

def premium_icon(name):
    if not name:
        return None
    n = str(name).strip()
    # Check hardcoded IDs first
    if n.lower() in PREMIUM_EMOJI_IDS:
        return PREMIUM_EMOJI_IDS[n.lower()]
    return PREMIUM_FLAGS.get(n) or PREMIUM_ICONS.get(n.lower())

def pe(name, fallback=None, emoji_id=None):
    """Return a safe <tg-emoji> tag with given ID or fallback.

    If *name* is already a numeric emoji-id string it is used directly.
    Otherwise it is resolved via premium_icon().
    Falls back to UNICODE_FALLBACKS for the matching icon name,
    never strips or re-encodes the text.
    """
    if not PREMIUM_EMOJI_OK:
        return fallback or UNICODE_FALLBACKS.get(str(name).lower(), "•") if name else (fallback or "•")
    eid = emoji_id
    if not eid:
        n_str = str(name).strip() if name else ""
        if n_str and n_str.isdigit():
            eid = n_str
        else:
            eid = premium_icon(name)
    # Resolve the Unicode fallback from the dictionary
    fb = fallback or UNICODE_FALLBACKS.get(str(name).lower(), "•") if name else (fallback or "•")
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'
    return fb

def flag_icon_id(iso):
    return premium_icon(iso) or premium_icon("XX")

def app_icon_id(app_name):
    return premium_icon(app_name) or premium_icon(app_name.lower()) or premium_icon("DEFAULT")

def flag_emoji_html(iso):
    """Return unicode flag emoji for the country ISO code."""
    if iso and len(str(iso)) == 2:
        code = str(iso).upper()
        return "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in code)
    return "🌍"

def app_emoji_html(app_name):
    eid = app_icon_id(app_name)
    if eid and PREMIUM_EMOJI_OK:
        fb = {"whatsapp": "💬", "telegram": "✈️", "facebook": "📘", "tiktok": "🎵",
              "google": "🔍", "instagram": "📸", "twitter": "🐦", "discord": "🎮",
              "default": "📱"}.get(str(app_name).lower(), "📱")
        return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'
    return {"whatsapp": "💬", "telegram": "✈️", "facebook": "📘", "tiktok": "🎵",
            "google": "🔍", "instagram": "📸", "twitter": "🐦", "discord": "🎮",
            "default": "📱"}.get(str(app_name).lower() if app_name else "", "📱")

# =========================== LIVE CHAT STEP HANDLERS ===========================
# =========================== CUSTOM BUTTON HELPERS ===========================
_old_inline_dict = types.InlineKeyboardButton.to_dict
def _new_inline_dict(self):
    d = _old_inline_dict(self)
    for attr in ("style", "icon_custom_emoji_id"):
        val = getattr(self, attr, None)
        if val and attr not in d:
            d[attr] = val
    if getattr(self, "custom_copy_text", None) and not d.get("copy_text"):
        d["copy_text"] = {"text": str(self.custom_copy_text)}
        d.pop("callback_data", None)
    return d
types.InlineKeyboardButton.to_dict = _new_inline_dict

_old_kb_dict = types.KeyboardButton.to_dict
def _new_kb_dict(self):
    d = _old_kb_dict(self)
    for attr in ("style", "icon_custom_emoji_id"):
        val = getattr(self, attr, None)
        if val and attr not in d:
            d[attr] = val
    return d
types.KeyboardButton.to_dict = _new_kb_dict

def ibtn(text, callback_data=None, url=None, style=None, copy_text_str=None, icon=None, icon_id=None):
    if icon_id is None:
        icon_id = premium_icon(icon)
    kwargs = {"text": text}
    if copy_text_str:
        kwargs["callback_data"] = "fake_copy_btn"
    else:
        if callback_data:
            kwargs["callback_data"] = callback_data
        if url:
            kwargs["url"] = url
    try:
        copy_btn = types.CopyTextButton(text=str(copy_text_str)) if copy_text_str and hasattr(types, "CopyTextButton") else None
        return types.InlineKeyboardButton(
            text=text, url=url,
            callback_data=None if copy_btn else callback_data,
            copy_text=copy_btn, style=style, icon_custom_emoji_id=icon_id
        )
    except TypeError:
        b = types.InlineKeyboardButton(**kwargs)
        if style:
            b.style = style
        if icon_id:
            b.icon_custom_emoji_id = icon_id
        if copy_text_str:
            b.custom_copy_text = copy_text_str
        return b

def rbtn(text, style=None, icon=None, icon_id=None):
    if icon_id is None:
        icon_id = premium_icon(icon)
    try:
        return types.KeyboardButton(text=text, style=style, icon_custom_emoji_id=icon_id)
    except TypeError:
        b = types.KeyboardButton(text=text)
        if style:
            b.style = style
        if icon_id:
            b.icon_custom_emoji_id = icon_id
        return b

def raw_btn(text, url=None, callback_data=None, style=None, icon=None):
    b = {"text": text}
    if url:
        b["url"] = url
    if callback_data:
        b["callback_data"] = callback_data
    if style:
        b["style"] = style
    # Note: icon_custom_emoji_id omitted for raw API calls (no safe wrapper)
    return b

# =========================== DB SETUP ===========================
def init_db():
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            country_code TEXT,
            assigned_number TEXT,
            is_banned INTEGER DEFAULT 0,
            private_combo_country TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            balance REAL DEFAULT 0.0,
            remove_cc INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS combos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_code TEXT,
            combo_index INTEGER DEFAULT 1,
            numbers TEXT,
            app_name TEXT DEFAULT 'WhatsApp',
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(country_code, combo_index)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS otp_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT,
            otp TEXT,
            full_message TEXT,
            timestamp TEXT,
            assigned_to INTEGER,
            service TEXT,
            country TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reward_claimed INTEGER DEFAULT 1,
            UNIQUE(referred_id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            address TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            admin_reason TEXT,
            admin_id INTEGER
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_code TEXT NOT NULL,
            method_name TEXT NOT NULL,
            solution TEXT,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(country_code, method_name)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS private_combos (
            user_id INTEGER, country_code TEXT, numbers TEXT,
            PRIMARY KEY (user_id, country_code)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS force_sub_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_url TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            country TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS response_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT,
            response_time REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS leaderboard (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            count INTEGER DEFAULT 0
        )''')
        # Seen OTP hashes table - replaces JSON file storage for deduplication
        c.execute('''CREATE TABLE IF NOT EXISTS seen_otps (
            hash TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_seen_otps_ts ON seen_otps(timestamp)")

        c.execute('''CREATE TABLE IF NOT EXISTS traffic_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT,
            country TEXT,
            count INTEGER DEFAULT 1,
            UNIQUE(app_name, country)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            status TEXT,
            payment_method TEXT,
            phone TEXT,
            full_name TEXT,
            address TEXT,
            admin_id INTEGER,
            admin_reason TEXT,
            processed_at TIMESTAMP,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS otp_counts (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS sms_panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            url TEXT,
            login_type TEXT DEFAULT 'client',
            username TEXT,
            password TEXT,
            enabled INTEGER DEFAULT 1,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        owner_id = ADMIN_IDS[0]
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (owner_id,))
        for eid in EXTRA_ADMINS:
            c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (eid,))
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('force_sub_enabled', '0')")
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('otp_groups', '[]')")
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('watermark', 'MATRIXX PREMIUM')")
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('support_link', 'https://t.me/Jibohu1')")
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('cooldown', '60')")
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('num_per_request', '5')")
        c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('maintenance', '0')")
        # Ensure no duplicate numbers across users (migration for existing DBs)
        try:
            c.execute("SELECT user_id, assigned_number FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
            rows = c.fetchall()
            seen = {}
            for uid, num in rows:
                if num in seen:
                    c.execute("UPDATE users SET assigned_number=NULL WHERE user_id=?", (uid,))
                    logger.info(f"Cleared duplicate number {num} from user {uid} (already assigned to {seen[num]})")
                else:
                    seen[num] = uid
        except Exception:
            pass

        # Migrations for existing tables
        for table, col_def in (
            ("withdrawal_requests", "admin_id INTEGER"),
            ("withdrawal_requests", "admin_reason TEXT"),
            ("withdrawal_requests", "processed_at TIMESTAMP"),
        ):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
            if col_def.split()[0] not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")

        # Add app_name column to combos if missing
        cols = [r[1] for r in c.execute("PRAGMA table_info(combos)")]
        if "app_name" not in cols:
            c.execute("ALTER TABLE combos ADD COLUMN app_name TEXT DEFAULT 'WhatsApp'")

        # Add remove_cc column to users if missing
        user_cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        if "remove_cc" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN remove_cc INTEGER DEFAULT 0")

        # === Startup health check: verify all tables exist ===
        required_tables = [
            'users', 'combos', 'otp_logs', 'referrals', 'withdrawals',
            'admins', 'methods', 'bot_settings', 'private_combos',
            'force_sub_channels', 'user_activity', 'response_times',
            'balances', 'leaderboard', 'traffic_log', 'withdrawal_requests',
            'otp_counts', 'seen_otps'
        ]
        existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in required_tables:
            if table not in existing:
                logger.warning(f"Health check: missing table '{table}' - will be created on next init")
        missing = [t for t in required_tables if t not in existing]
        if not missing:
            logger.info(f"Health check passed: all {len(required_tables)} tables present")
        else:
            logger.warning(f"Health check: {len(missing)} missing tables: {missing}")

        # === One-time migration: import JSON seen-hashes into DB ===
        json_files = ['seen_messages.json', 'choice_seen.json']
        for jf in json_files:
            try:
                if os.path.exists(jf):
                    with open(jf, 'r') as f:
                        hashes = json.load(f)
                    if hashes:
                        for h in hashes:
                            c.execute("INSERT OR IGNORE INTO seen_otps (hash, timestamp) VALUES (?, datetime('now'))", (str(h),))
                        logger.info(f"Migrated {len(hashes)} hashes from {jf} to seen_otps table")
                        # Rename old file as backup
                        os.rename(jf, jf + '.bak')
            except Exception as e:
                logger.warning(f"Migration from {jf} failed (may not exist): {e}")

        conn.commit()
        conn.close()
        logger.info("Database initialized")

init_db()

# =========================== SEEN OTP HELPERS (DB-backed deduplication) ===========================
# ======================== SMS PANEL DB FUNCTIONS ========================
def get_all_sms_panels():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, url, login_type, username, enabled FROM sms_panels")
        rows = c.fetchall()
        conn.close()
    return rows

def get_sms_panel(panel_id):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, url, login_type, username, password, enabled, created FROM sms_panels WHERE id=?", (panel_id,))
        row = c.fetchone()
        conn.close()
    return row

def save_sms_panel(name, url, login_type, username, password):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO sms_panels (name, url, login_type, username, password) VALUES (?, ?, ?, ?, ?)",
                  (name, url, login_type, username, password))
        panel_id = c.lastrowid
        conn.commit()
        conn.close()
    return panel_id

def toggle_sms_panel(panel_id):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE sms_panels SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?", (panel_id,))
        conn.commit()
        conn.close()
    # Start or stop the forwarder thread
    panel = get_sms_panel(panel_id)
    if panel and panel[6]:  # enabled
        try:
            start_panel_forwarder(panel_id)
        except Exception as e:
            logger.error(f"Failed to start panel {panel_id}: {e}")
    else:
        stop_panel_forwarder(panel_id)

def delete_sms_panel(panel_id):
    stop_panel_forwarder(panel_id)
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM sms_panels WHERE id=?", (panel_id,))
        conn.commit()
        conn.close()

def is_otp_seen(hash_val):
    """Check if an OTP hash has already been processed."""
    if not hash_val:
        return False
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT 1 FROM seen_otps WHERE hash=?", (str(hash_val),))
        row = c.fetchone()
        conn.close()
        return row is not None

def mark_otp_seen(hash_val):
    """Mark an OTP hash as processed (insert with current timestamp)."""
    if not hash_val:
        return
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO seen_otps (hash, timestamp) VALUES (?, datetime('now'))", (str(hash_val),))
        conn.commit()
        conn.close()

def cleanup_old_seen_otps(days=7):
    """Remove seen_otps entries older than N days to keep table small."""
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM seen_otps WHERE timestamp < datetime('now', ?)", (f'-{days} days',))
        deleted = c.rowcount
        conn.commit()
        conn.close()
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} old seen_otps entries (older than {days} days)")

def seen_otps_count():
    """Return total number of seen OTP hashes."""
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM seen_otps")
        count = c.fetchone()[0] or 0
        conn.close()
        return count

# =========================== HELPER FUNCTIONS ===========================
def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    _persist_db()

def get_all_admins():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def add_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_admin(user_id):
    if user_id == ADMIN_IDS[0]:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    removed = c.rowcount > 0
    conn.commit()
    conn.close()
    return removed

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, username="", first_name="", last_name="", country_code=None, assigned_number=None, private_combo_country=None, balance=None):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        existing = get_user(user_id)
        if existing:
            country_code = country_code if country_code is not None else existing[4]
            assigned_number = assigned_number if assigned_number is not None else existing[5]
            private_combo_country = private_combo_country if private_combo_country is not None else existing[7]
            balance = balance if balance is not None else (existing[10] if len(existing) > 10 else 0.0)
        else:
            if country_code is None: country_code = ""
            if assigned_number is None: assigned_number = ""
            if private_combo_country is None: private_combo_country = ""
            if balance is None: balance = 0.0
        c.execute("""REPLACE INTO users
            (user_id, username, first_name, last_name, country_code, assigned_number, is_banned, private_combo_country, join_date, last_active, balance, remove_cc)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT is_banned FROM users WHERE user_id=?), 0), ?,
                    COALESCE((SELECT join_date FROM users WHERE user_id=?), CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, ?,
                    COALESCE((SELECT remove_cc FROM users WHERE user_id=?), 0))""",
            (user_id, username, first_name, last_name, country_code, assigned_number, user_id, private_combo_country, user_id, balance, user_id))
        conn.commit()
        conn.close()
        log_user_activity(user_id, "user_update", "Profile updated")
        _persist_db()

def get_remove_cc(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT remove_cc FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else 0

def toggle_remove_cc(user_id):
    current = get_remove_cc(user_id)
    new_val = 0 if current else 1
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET remove_cc=? WHERE user_id=?", (new_val, user_id))
        conn.commit()
        conn.close()
    _persist_db()
    return new_val

def is_banned(user_id):
    user = get_user(user_id)
    return user and user[6] == 1

def ban_user(user_id):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned=1, assigned_number=NULL WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    log_user_activity(user_id, "user_banned", "User banned by admin")
    return True

def unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    log_user_activity(user_id, "user_unbanned", "User unbanned by admin")
    return True

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned=0")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_user_by_number(number):
    """Find user by assigned number - try multiple formats for matching."""
    if not number:
        return None
    clean = re.sub(r'\D', '', str(number))  # digits only
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Debug: log all assigned numbers
    c.execute("SELECT user_id, assigned_number FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
    all_nums = c.fetchall()
    if all_nums:
        logger.debug(f"get_user_by_number: searching '{clean}' in {[(u,n) for u,n in all_nums]}")
    else:
        logger.warning(f"get_user_by_number: NO users have assigned numbers! Cannot match '{clean}'")
    # Try exact match first
    c.execute("SELECT user_id FROM users WHERE assigned_number=?", (clean,))
    row = c.fetchone()
    if row:
        conn.close()
        return row[0]
    # Try without leading zeros
    c.execute("SELECT user_id FROM users WHERE assigned_number=?", (clean.lstrip('0'),))
    row = c.fetchone()
    if row:
        conn.close()
        return row[0]
    # Try with + prefix
    c.execute("SELECT user_id FROM users WHERE assigned_number=?", ('+' + clean,))
    row = c.fetchone()
    if row:
        conn.close()
        return row[0]
    # Try fuzzy: get all assigned numbers and check if any is a suffix/prefix match
    c.execute("SELECT user_id, assigned_number FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
    for uid, anum in c.fetchall():
        clean_anum = re.sub(r'\D', '', str(anum))
        if not clean_anum:
            continue
        # Check if one contains the other (for country code differences)
        if clean.endswith(clean_anum) or clean_anum.endswith(clean):
            conn.close()
            return uid
        if clean.startswith(clean_anum) or clean_anum.startswith(clean):
            # Only match if the remaining part is at least 5 digits
            diff = abs(len(clean) - len(clean_anum))
            if diff >= 0 and min(len(clean), len(clean_anum)) >= 5:
                conn.close()
                return uid
    conn.close()
    return None

def get_app_for_number(number):
    """Look up which app a phone number is assigned to from combos."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT app_name FROM combos")
        for row in c.fetchall():
            app_name = row[0] if row[0] else "WhatsApp"
            # Check if this number exists in this combo
            c2 = conn.cursor()
            c2.execute("SELECT numbers FROM combos WHERE app_name=?", (app_name,))
            for r in c2.fetchall():
                nums = json.loads(r[0])
                if number in [clean_number(n) for n in nums]:
                    conn.close()
                    return app_name
        conn.close()
    except Exception as e:
        logger.debug(f"get_app_for_number error: {e}")
    return "WhatsApp"

def assign_number_to_user(user_id, number):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        # Check if number is already taken by another user
        c.execute("SELECT user_id FROM users WHERE assigned_number=? AND user_id!=?", (number, user_id))
        existing = c.fetchone()
        if existing:
            logger.warning(f"Number {number} already taken by user {existing[0]}, rejecting assignment to {user_id}")
            conn.close()
            return False
        c.execute("UPDATE users SET assigned_number=? WHERE user_id=?", (number, user_id))
        conn.commit()
        conn.close()
        log_user_activity(user_id, "number_assigned", f"Number {number} assigned")
        _persist_db()
        return True

def release_number(number):
    """Release a number from user AND delete it entirely from the stock."""
    if not number:
        return
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        # Remove from user assignment
        c.execute("UPDATE users SET assigned_number=NULL WHERE assigned_number=?", (number,))
        # Delete from combo stock entirely
        c.execute("SELECT id, numbers FROM combos")
        for row in c.fetchall():
            combo_id, nums_json = row
            try:
                nums = json.loads(nums_json)
                if number in nums:
                    nums.remove(number)
                    c.execute("UPDATE combos SET numbers=? WHERE id=?", (json.dumps(nums), combo_id))
                    logger.info(f"Deleted number {number} from stock combo {combo_id}")
            except Exception:
                pass
        # Also delete from private combos
        c.execute("SELECT user_id, numbers FROM private_combos")
        for row in c.fetchall():
            uid, nums_json = row
            try:
                nums = json.loads(nums_json)
                if number in nums:
                    nums.remove(number)
                    c.execute("UPDATE private_combos SET numbers=? WHERE user_id=?", (json.dumps(nums), uid))
                    logger.info(f"Deleted number {number} from private stock for user {uid}")
            except Exception:
                pass
        conn.commit()
        conn.close()
        _persist_db()

def get_combo(country_code, combo_index=1, user_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if user_id:
        c.execute("SELECT numbers FROM private_combos WHERE user_id=? AND country_code=?", (user_id, country_code))
        row = c.fetchone()
        if row:
            conn.close()
            return json.loads(row[0])
    c.execute("SELECT numbers FROM combos WHERE country_code=? AND combo_index=?", (country_code, combo_index))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else []

def save_combo(country_code, numbers, user_id=None, app_name="WhatsApp", broadcast=False):
    """Save combo. If broadcast=True and user_id is None, notify all users & groups."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if user_id:
        c.execute("REPLACE INTO private_combos (user_id, country_code, numbers) VALUES (?, ?, ?)",
                  (user_id, country_code, json.dumps(numbers)))
        conn.commit()
        conn.close()
        return
    else:
        # Public combo – determine next index
        c.execute("SELECT MAX(combo_index) FROM combos WHERE country_code=?", (country_code,))
        max_index = c.fetchone()[0]
        next_index = 1 if max_index is None else max_index + 1
        c.execute("INSERT INTO combos (country_code, combo_index, numbers, app_name) VALUES (?, ?, ?, ?)",
                  (country_code, next_index, json.dumps(numbers), app_name))
        conn.commit()
        conn.close()
        if broadcast:
            # Broadcast stock update (function defined later after bot init)
            broadcast_stock_update(country_code, app_name, len(numbers))
        return

def get_all_combos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT country_code, combo_index, app_name FROM combos ORDER BY country_code, combo_index")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_combo(country_code, combo_index=None):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
    if combo_index:
        c.execute("DELETE FROM combos WHERE country_code=? AND combo_index=?", (country_code, combo_index))
    else:
        c.execute("DELETE FROM combos WHERE country_code=?", (country_code,))
    conn.commit()
    conn.close()

def get_available_numbers(country_code, combo_index=1, user_id=None):
    all_numbers = get_combo(country_code, combo_index, user_id)
    if not all_numbers:
        return []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT assigned_number FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
    used_numbers = set(r[0] for r in c.fetchall())
    conn.close()
    return [num for num in all_numbers if num not in used_numbers]

def log_otp(number, otp, full_message, assigned_to=None):
    service = detect_service(full_message)
    country_name, iso, _ = get_country_info(number)
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO otp_logs (number, otp, full_message, timestamp, assigned_to, service, country) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (number, otp, full_message, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), assigned_to, service, country_name))
        conn.commit()
        conn.close()

def get_otp_logs_for_number(number, limit=5):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if number:
        c.execute("SELECT otp, full_message, timestamp FROM otp_logs WHERE number=? ORDER BY id DESC LIMIT ?", (number, limit))
    else:
        c.execute("SELECT otp, full_message, timestamp FROM otp_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_total_otp_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM otp_logs")
    return c.fetchone()[0] or 0

def log_user_activity(user_id, action, details=""):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO user_activity (user_id, action, details, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                  (user_id, action, details))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Activity log failed: {e}")

def get_force_sub_channels(enabled_only=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if enabled_only:
        c.execute("SELECT id, channel_url, description FROM force_sub_channels WHERE enabled=1")
    else:
        c.execute("SELECT id, channel_url, description FROM force_sub_channels")
    rows = c.fetchall()
    conn.close()
    return rows

def add_force_sub_channel(channel_url, description=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO force_sub_channels (channel_url, description, enabled) VALUES (?, ?, 1)",
                  (channel_url.strip(), description.strip()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_force_sub_channel(channel_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM force_sub_channels WHERE id=?", (channel_id,))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def toggle_force_sub_channel(channel_id):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
    c.execute("UPDATE force_sub_channels SET enabled = 1 - enabled WHERE id=?", (channel_id,))
    conn.commit()
    conn.close()

def get_methods_by_country(country_code=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if country_code:
        c.execute("SELECT id, country_code, method_name, solution, added_by, added_at FROM methods WHERE country_code=? ORDER BY method_name", (country_code,))
    else:
        c.execute("SELECT id, country_code, method_name, solution, added_by, added_at FROM methods ORDER BY country_code, method_name")
    rows = c.fetchall()
    conn.close()
    return rows

def add_method(country_code, method_name, solution, admin_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO methods (country_code, method_name, solution, added_by) VALUES (?, ?, ?, ?)",
                  (country_code, method_name.strip(), solution.strip(), admin_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_method(method_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM methods WHERE id=?", (method_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_all_methods_grouped():
    methods = get_methods_by_country()
    grouped = defaultdict(list)
    for m_id, cc, name, solution, added_by, added_at in methods:
        grouped[cc].append((name, solution))
    return grouped

def get_referral_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
    return c.fetchone()[0] or 0

def get_top_referrers(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT referrer_id, COUNT(*) as cnt, SUM(?) as total_reward FROM referrals GROUP BY referrer_id ORDER BY cnt DESC LIMIT ?",
              (REFERRAL_REWARD, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def process_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return False
    referrer = get_user(referrer_id)
    if not referrer or is_banned(referrer_id):
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
    if c.fetchone():
        conn.close()
        return False
    try:
        c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
        new_balance = (referrer[10] if len(referrer) > 10 else 0.0) + REFERRAL_REWARD
        c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, referrer_id))
        conn.commit()
        log_user_activity(referrer_id, "referral_reward", f"Earned ${REFERRAL_REWARD:.2f} from user {referred_id}")
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def create_withdrawal_request(user_id, amount, method, details):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
    req_id = str(uuid.uuid4())[:8]
    status = "pending"
    timestamp = datetime.now().isoformat()
    phone = details.get("phone") or details.get("upi_id") or ""
    full_name = details.get("full_name") or details.get("account_holder") or ""
    address = details.get("address") or ""
    extras = {k: v for k, v in details.items() if k not in ("phone", "full_name", "address") and v not in (None, "")}
    if extras:
        if address:
            extras["address"] = address
        address = json.dumps(extras, ensure_ascii=False)
    c.execute("""INSERT INTO withdrawal_requests
        (id, user_id, amount, status, payment_method, phone, full_name, address, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (req_id, user_id, amount, status, method, phone, full_name, address, timestamp))
    conn.commit()
    conn.close()
    log_user_activity(user_id, "withdrawal_requested", f"{method} ${amount:.2f}")
    return req_id

def get_pending_withdrawals():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, payment_method, timestamp FROM withdrawal_requests WHERE status='pending'")
    rows = c.fetchall()
    conn.close()
    return rows

def approve_withdrawal(req_id, admin_id, reason=""):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
    c.execute("SELECT user_id, amount FROM withdrawal_requests WHERE id=? AND status='pending'", (req_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Not found"
    user_id, amount = row
    user = get_user(user_id)
    balance = user[10] if user and len(user) > 10 else 0.0
    if balance < amount:
        conn.close()
        return False, "Insufficient balance"
    new_balance = balance - amount
    c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
    c.execute("UPDATE withdrawal_requests SET status='approved', admin_id=?, admin_reason=?, processed_at=CURRENT_TIMESTAMP WHERE id=?",
              (admin_id, reason, req_id))
    conn.commit()
    conn.close()
    log_user_activity(user_id, "withdrawal_approved", f"Amount: ${amount:.2f}")
    return True, new_balance

def reject_withdrawal(req_id, admin_id, reason):
    with _db_lock:
        conn = _get_conn()
        c = conn.cursor()
    c.execute("UPDATE withdrawal_requests SET status='rejected', admin_id=?, admin_reason=?, processed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
              (admin_id, reason, req_id))
    if c.rowcount == 0:
        conn.close()
        return False, "Not found"
    c.execute("SELECT user_id, amount FROM withdrawal_requests WHERE id=?", (req_id,))
    row = c.fetchone()
    if row:
        log_user_activity(row[0], "withdrawal_rejected", f"Reason: {reason}")
    conn.commit()
    conn.close()
    return True, "Rejected"

def get_dashboard_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE timestamp > datetime('now', '-1 day')")
    active_users_24h = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned=0")
    total_users = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM otp_logs")
    total_otps = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM otp_logs WHERE timestamp LIKE ?", (datetime.now().strftime("%Y-%m-%d") + '%',))
    otps_today = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
    banned = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
    active_assign = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM combos")
    combos = c.fetchone()[0] or 0
    conn.close()
    return {
        'active_users_24h': active_users_24h,
        'total_users': total_users,
        'total_otps': total_otps,
        'otps_today': otps_today,
        'banned_users': banned,
        'active_assignments': active_assign,
        'total_combos': combos
    }

def get_uptime():
    delta = datetime.now() - BOT_START_TIME
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    seconds = delta.seconds % 60
    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    return f"{hours}h {minutes}m {seconds}s"

# =========================== COUNTRY MAP ===========================
COUNTRY_CODES = {
    "1": ("USA/Canada", "US"), "7": ("Russia", "RU"), "20": ("Egypt", "EG"),
    "27": ("South Africa", "ZA"), "30": ("Greece", "GR"), "31": ("Netherlands", "NL"),
    "32": ("Belgium", "BE"), "33": ("France", "FR"), "34": ("Spain", "ES"),
    "36": ("Hungary", "HU"), "39": ("Italy", "IT"), "40": ("Romania", "RO"),
    "41": ("Switzerland", "CH"), "43": ("Austria", "AT"), "44": ("United Kingdom", "GB"),
    "45": ("Denmark", "DK"), "46": ("Sweden", "SE"), "47": ("Norway", "NO"),
    "48": ("Poland", "PL"), "49": ("Germany", "DE"), "51": ("Peru", "PE"),
    "52": ("Mexico", "MX"), "53": ("Cuba", "CU"), "54": ("Argentina", "AR"),
    "55": ("Brazil", "BR"), "56": ("Chile", "CL"), "57": ("Colombia", "CO"),
    "58": ("Venezuela", "VE"), "60": ("Malaysia", "MY"), "61": ("Australia", "AU"),
    "62": ("Indonesia", "ID"), "63": ("Philippines", "PH"), "64": ("New Zealand", "NZ"),
    "65": ("Singapore", "SG"), "66": ("Thailand", "TH"), "81": ("Japan", "JP"),
    "82": ("South Korea", "KR"), "84": ("Vietnam", "VN"), "86": ("China", "CN"),
    "90": ("Turkey", "TR"), "91": ("India", "IN"), "92": ("Pakistan", "PK"),
    "93": ("Afghanistan", "AF"), "94": ("Sri Lanka", "LK"), "95": ("Myanmar", "MM"),
    "98": ("Iran", "IR"), "211": ("South Sudan", "SS"), "212": ("Morocco", "MA"),
    "213": ("Algeria", "DZ"), "216": ("Tunisia", "TN"), "218": ("Libya", "LY"),
    "220": ("Gambia", "GM"), "221": ("Senegal", "SN"), "222": ("Mauritania", "MR"),
    "223": ("Mali", "ML"), "224": ("Guinea", "GN"), "225": ("Ivory Coast", "CI"),
    "226": ("Burkina Faso", "BF"), "227": ("Niger", "NE"), "228": ("Togo", "TG"),
    "229": ("Benin", "BJ"), "230": ("Mauritius", "MU"), "231": ("Liberia", "LR"),
    "232": ("Sierra Leone", "SL"), "233": ("Ghana", "GH"), "234": ("Nigeria", "NG"),
    "235": ("Chad", "TD"), "236": ("Central African Rep", "CF"), "237": ("Cameroon", "CM"),
    "238": ("Cape Verde", "CV"), "239": ("Sao Tome", "ST"), "240": ("Equatorial Guinea", "GQ"),
    "241": ("Gabon", "GA"), "242": ("Congo", "CG"), "243": ("DR Congo", "CD"),
    "244": ("Angola", "AO"), "245": ("Guinea-Bissau", "GW"), "248": ("Seychelles", "SC"),
    "249": ("Sudan", "SD"), "250": ("Rwanda", "RW"), "251": ("Ethiopia", "ET"),
    "252": ("Somalia", "SO"), "253": ("Djibouti", "DJ"), "254": ("Kenya", "KE"),
    "255": ("Tanzania", "TZ"), "256": ("Uganda", "UG"), "257": ("Burundi", "BI"),
    "258": ("Mozambique", "MZ"), "260": ("Zambia", "ZM"), "261": ("Madagascar", "MG"),
    "262": ("Reunion", "RE"), "263": ("Zimbabwe", "ZW"), "264": ("Namibia", "NA"),
    "265": ("Malawi", "MW"), "266": ("Lesotho", "LS"), "267": ("Botswana", "BW"),
    "268": ("Eswatini", "SZ"), "269": ("Comoros", "KM"), "350": ("Gibraltar", "GI"),
    "351": ("Portugal", "PT"), "352": ("Luxembourg", "LU"), "353": ("Ireland", "IE"),
    "354": ("Iceland", "IS"), "355": ("Albania", "AL"), "356": ("Malta", "MT"),
    "357": ("Cyprus", "CY"), "358": ("Finland", "FI"), "359": ("Bulgaria", "BG"),
    "370": ("Lithuania", "LT"), "371": ("Latvia", "LV"), "372": ("Estonia", "EE"),
    "373": ("Moldova", "MD"), "374": ("Armenia", "AM"), "375": ("Belarus", "BY"),
    "376": ("Andorra", "AD"), "377": ("Monaco", "MC"), "378": ("San Marino", "SM"),
    "380": ("Ukraine", "UA"), "381": ("Serbia", "RS"), "382": ("Montenegro", "ME"),
    "383": ("Kosovo", "XK"), "385": ("Croatia", "HR"), "386": ("Slovenia", "SI"),
    "387": ("Bosnia", "BA"), "389": ("North Macedonia", "MK"), "420": ("Czech Republic", "CZ"),
    "421": ("Slovakia", "SK"), "423": ("Liechtenstein", "LI"), "500": ("Falkland Islands", "FK"),
    "501": ("Belize", "BZ"), "502": ("Guatemala", "GT"), "503": ("El Salvador", "SV"),
    "504": ("Honduras", "HN"), "505": ("Nicaragua", "NI"), "506": ("Costa Rica", "CR"),
    "507": ("Panama", "PA"), "509": ("Haiti", "HT"), "591": ("Bolivia", "BO"),
    "592": ("Guyana", "GY"), "593": ("Ecuador", "EC"), "595": ("Paraguay", "PY"),
    "597": ("Suriname", "SR"), "598": ("Uruguay", "UY"), "670": ("Timor-Leste", "TL"),
    "673": ("Brunei", "BN"), "674": ("Nauru", "NR"), "675": ("Papua New Guinea", "PG"),
    "676": ("Tonga", "TO"), "677": ("Solomon Islands", "SB"), "678": ("Vanuatu", "VU"),
    "679": ("Fiji", "FJ"), "680": ("Palau", "PW"), "685": ("Samoa", "WS"),
    "686": ("Kiribati", "KI"), "687": ("New Caledonia", "NC"), "688": ("Tuvalu", "TV"),
    "689": ("French Polynesia", "PF"), "691": ("Micronesia", "FM"), "692": ("Marshall Islands", "MH"),
    "850": ("North Korea", "KP"), "852": ("Hong Kong", "HK"), "853": ("Macau", "MO"),
    "855": ("Cambodia", "KH"), "856": ("Laos", "LA"), "960": ("Maldives", "MV"),
    "961": ("Lebanon", "LB"), "962": ("Jordan", "JO"), "963": ("Syria", "SY"),
    "964": ("Iraq", "IQ"), "965": ("Kuwait", "KW"), "966": ("Saudi Arabia", "SA"),
    "967": ("Yemen", "YE"), "968": ("Oman", "OM"), "970": ("Palestine", "PS"),
    "971": ("UAE", "AE"), "972": ("Israel", "IL"), "973": ("Bahrain", "BH"),
    "974": ("Qatar", "QA"), "975": ("Bhutan", "BT"), "976": ("Mongolia", "MN"),
    "977": ("Nepal", "NP"), "992": ("Tajikistan", "TJ"), "993": ("Turkmenistan", "TM"),
    "994": ("Azerbaijan", "AZ"), "995": ("Georgia", "GE"), "996": ("Kyrgyzstan", "KG"),
    "998": ("Uzbekistan", "UZ"),
}

# Country flag emoji mapping (ISO code -> flag emoji)
COUNTRY_FLAGS = {
    'LAOS': '🇱🇦', 'LEBANON': '🇱🇧', 'NIGERIA': '🇳🇬', 'GHANA': '🇬🇭',
    'KENYA': '🇰🇪', 'SOUTH AFRICA': '🇿🇦', 'EGYPT': '🇪🇬', 'MOROCCO': '🇲🇦',
    'TUNISIA': '🇹🇳', 'ALGERIA': '🇩🇿', 'LIBYA': '🇱🇾', 'UAE': '🇦🇪',
    'SAUDI ARABIA': '🇸🇦', 'KUWAIT': '🇰🇼', 'QATAR': '🇶🇦', 'OMAN': '🇴🇲',
    'BAHRAIN': '🇧🇭', 'JORDAN': '🇯🇴', 'ISRAEL': '🇮🇱', 'TURKEY': '🇹🇷',
    'INDIA': '🇮🇳', 'PAKISTAN': '🇵🇰', 'BANGLADESH': '🇧🇩', 'SRI LANKA': '🇱🇰',
    'NEPAL': '🇳🇵', 'BHUTAN': '🇧🇹', 'MALDIVES': '🇲🇻', 'AFGHANISTAN': '🇦🇫',
    'PHILIPPINES': '🇵🇭', 'INDONESIA': '🇮🇩', 'MALAYSIA': '🇲🇾', 'SINGAPORE': '🇸🇬',
    'THAILAND': '🇹🇭', 'VIETNAM': '🇻🇳', 'CAMBODIA': '🇰🇭', 'MYANMAR': '🇲🇲',
    'USA': '🇺🇸', 'UK': '🇬🇧', 'CANADA': '🇨🇦', 'AUSTRALIA': '🇦🇺',
    'GERMANY': '🇩🇪', 'FRANCE': '🇫🇷', 'SPAIN': '🇪🇸', 'ITALY': '🇮🇹',
    'BRAZIL': '🇧🇷', 'MEXICO': '🇲🇽', 'ARGENTINA': '🇦🇷', 'COLOMBIA': '🇨🇴',
    'TANZANIA': '🇹🇿', 'UGANDA': '🇺🇬', 'RWANDA': '🇷🇼', 'DRC': '🇨🇩',
    'CONGO': '🇨🇬', 'ANGOLA': '🇦🇴', 'MOZAMBIQUE': '🇲🇿', 'ZIMBABWE': '🇿🇼',
    'ZAMBIA': '🇿🇲', 'MALAWI': '🇲🇼', 'MADAGASCAR': '🇲🇬',
}


def get_country_info(number):
    number = re.sub(r'\D', '', str(number))
    best = None
    for code in COUNTRY_CODES:
        if number.startswith(code) and (best is None or len(code) > len(best)):
            best = code
    if best:
        name, iso = COUNTRY_CODES[best]
        return name, iso, None
    return "Unknown", "UN", None

def detect_country_from_number(number):
    digits = re.sub(r'\D', '', str(number))
    if not digits:
        return None
    best = None
    for code in COUNTRY_CODES:
        if digits.startswith(code) and (best is None or len(code) > len(best)):
            best = code
    return best

def clean_number(number):
    return re.sub(r'\D', '', str(number))

def mask_number(number):
    number = str(number).strip()
    if len(number) > 8:
        return number[:4] + "••••" + number[-5:]
    return number

def extract_otp(message):
    patterns = [
        r'(?:code|رمز|كود|verification|تحقق|otp|pin)[:\s]+[‎]?(\d{3,8}(?:[- ]\d{3,4})?)',
        r'(\d{3})[- ](\d{3,4})',
        r'\b(\d{4,8})\b',
        r'[‎](\d{3,8})',
    ]
    for pat in patterns:
        match = re.search(pat, message, re.IGNORECASE)
        if match:
            if len(match.groups()) > 1:
                return ''.join(match.groups())
            return match.group(1).replace(' ', '').replace('-', '')
    nums = re.findall(r'\d{4,8}', message)
    return nums[0] if nums else "N/A"

def detect_service(message):
    message_lower = message.lower()
    services = {
        "whatsapp": ["whatsapp", "واتساب", "واتس"],
        "facebook": ["facebook", "فيسبوك", "fb"],
        "instagram": ["instagram", "انستقرام", "انستا"],
        "telegram": ["telegram", "تيليجرام", "تلي"],
        "twitter": ["twitter", "تويتر", "twitter.com", "x.com"],
        "google": ["google", "gmail", "جوجل", "جميل"],
        "discord": ["discord", "ديسكورد"],
        "line": ["line", "لاين"],
        "viber": ["viber", "فايبر"],
        "skype": ["skype", "سكايب"],
        "snapchat": ["snapchat", "سناب"],
        "tiktok": ["tiktok", "تيك توك", "تيك"],
        "amazon": ["amazon", "امازون"],
        "apple": ["apple", "ابل", "icloud"],
        "microsoft": ["microsoft", "مايكروسوفت"],
        "linkedin": ["linkedin", "لينكد"],
        "uber": ["uber", "اوبر"],
        "airbnb": ["airbnb", "ايربنب"],
        "netflix": ["netflix", "نتفلكس"],
        "spotify": ["spotify", "سبوتيفاي"],
        "youtube": ["youtube", "يوتيوب"],
        "github": ["github", "جيت هاب"],
        "pinterest": ["pinterest", "بنتريست"],
        "paypal": ["paypal", "باي بال"],
        "booking": ["booking", "بوكينج"],
        "tala": ["tala", "تالا"],
        "olx": ["olx", "اوليكس"],
        "stcpay": ["stcpay", "stc"],
    }
    ranked = []
    for service, keywords in services.items():
        for kw in keywords:
            ranked.append((len(kw), service, kw))
    ranked.sort(reverse=True)
    for _, service, kw in ranked:
        if len(kw) <= 2:
            if re.search(r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])', message_lower):
                return service
        elif kw in message_lower:
            return service
    return "unknown"

def load_data():
    data = {}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM bot_settings")
    for k, v in c.fetchall():
        data[k] = v
    conn.close()
    data["watermark"] = get_setting("watermark") or "MATRIXX PREMIUM"
    return data

# =========================== BOT INIT ===========================
bot = telebot.TeleBot(BOT_TOKEN)
BOT_START_TIME = datetime.now()

# ---- Premium emoji safe-send wrappers ----
_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">([^<]*)</tg-emoji>')

def _strip_premium_text(text):
    return _TG_EMOJI_RE.sub(r'\1', text) if isinstance(text, str) else text

def _strip_markup_icons(markup):
    try:
        for row in getattr(markup, "keyboard", []):
            for btn in row:
                if getattr(btn, "icon_custom_emoji_id", None):
                    btn.icon_custom_emoji_id = None
    except Exception:
        pass
    return markup

def _premium_rejected(err):
    msg = str(err).lower()
    return ("custom emoji" in msg or "custom_emoji" in msg
            or "parse" in msg or "entity" in msg
            or "tg-emoji" in msg)

_orig_send_message = bot.send_message
def _safe_send_message(chat_id, text, *args, **kwargs):
    try:
        return _orig_send_message(chat_id, text, *args, **kwargs)
    except Exception as e:
        if not _premium_rejected(e):
            raise
        logger.warning(f"Telegram rejected premium emoji on send_message: {e}")
        cleaned = copy.copy(kwargs)
        if cleaned.get("reply_markup") is not None:
            cleaned["reply_markup"] = _strip_markup_icons(cleaned["reply_markup"])
        return _orig_send_message(chat_id, _strip_premium_text(text), *args, **cleaned)
bot.send_message = _safe_send_message

_orig_edit_message_text = bot.edit_message_text
def _safe_edit_message_text(text, chat_id=None, message_id=None, *args, **kwargs):
    try:
        return _orig_edit_message_text(text, chat_id=chat_id, message_id=message_id, *args, **kwargs)
    except Exception as e:
        if not _premium_rejected(e):
            raise
        logger.warning(f"Telegram rejected premium emoji on edit_message_text: {e}")
        cleaned = copy.copy(kwargs)
        if cleaned.get("reply_markup") is not None:
            cleaned["reply_markup"] = _strip_markup_icons(cleaned["reply_markup"])
        return _orig_edit_message_text(_strip_premium_text(text), chat_id=chat_id, message_id=message_id, *args, **cleaned)
bot.edit_message_text = _safe_edit_message_text

# =========================== BROADCAST STOCK UPDATE (placed after bot init) ===========================
def broadcast_stock_update(country_code, app_name, number_count):
    """Send a stock update notification to all users and OTP groups."""
    iso = COUNTRY_CODES.get(country_code, (country_code, "UN"))[1]
    flag_html = flag_emoji_html(iso)
    name = COUNTRY_CODES.get(country_code, (country_code, "UN"))[0]
    app_emoji = app_emoji_html(app_name)
    msg = (f"📦 <b>New Stock Added!</b>\n"
           f"{flag_html} <b>Country:</b> {name}\n"
           f"{app_emoji} <b>App:</b> {app_name}\n"
           f"📞 <b>Numbers:</b> {number_count}\n"
           f"━━━━━━━━━━━━━━━\n"
           f"🔄 <b>Update your list now!</b>")

    # Send to all users
    for uid in get_all_users():
        try:
            bot.send_message(uid, msg, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to send stock update to {uid}: {e}")

    # Send to OTP groups
    groups = json.loads(get_setting('otp_groups') or '[]')
    for gid in groups:
        try:
            bot.send_message(gid, msg, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to send stock update to group {gid}: {e}")

# =========================== FORCE SUB CHECK ===========================
def force_sub_check(user_id):
    if get_setting('force_sub_enabled') != '1':
        return True
    channels = get_force_sub_channels(enabled_only=True)
    if not channels:
        return True
    for _, url, _ in channels:
        try:
            if url.startswith("https://t.me/"):
                ch = "@" + url.split("/")[-1]
            elif url.startswith("@"):
                ch = url
            else:
                continue
            member = bot.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logger.warning(f"Force sub check error: {e}")
            return False
    return True

def force_sub_markup():
    channels = get_force_sub_channels(enabled_only=True)
    if not channels:
        return None
    markup = types.InlineKeyboardMarkup()
    for _, url, desc in channels:
        text = desc if desc else "Subscribe"
        markup.add(ibtn(text, url=url, style="primary", icon="announcement"))
    markup.add(ibtn("Verified", callback_data="check_sub", style="success", icon="checkmark"))
    return markup

# =========================== SENDING FUNCTIONS ===========================
def send_otp_to_user_and_group(date_str, number, sms, app_name=None):
    otp = extract_otp(sms)
    country_name, iso, _ = get_country_info(number)
    flag_html = flag_emoji_html(iso)
    service = app_name if app_name else detect_service(sms)
    app_emoji = app_emoji_html(service)

    if ALLOWED_SERVICES and service.lower() not in ALLOWED_SERVICES:
        logger.info(f"Filtered: {service}")
        return

    user_id = get_user_by_number(number)
    logger.info(f"IVASMS: get_user_by_number('{number}') => {user_id}")
    try:
        log_otp(number, otp, sms, user_id)
    except Exception as e:
        logger.error(f"log_otp failed: {e}")
    # Credit user $0.006 per OTP received
    new_balance = 0.0
    if user_id:
        try:
            u = get_user(user_id)
            if u:
                cur_bal = u[10] if len(u) > 10 else 0.0
                new_balance = cur_bal + 0.006
            else:
                new_balance = 0.006
            # Use direct UPDATE to avoid overwriting other fields
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
            conn.commit()
            conn.close()
            logger.info(f"Balance updated for {user_id}: ${new_balance}")
        except Exception as bal_err:
            logger.error(f"Balance credit failed for {user_id}: {bal_err}")

    if user_id:
        try:
            markup = types.InlineKeyboardMarkup()
            markup.row(ibtn("Owner", url="https://t.me/Jibohu1", style="primary", icon="admin"),
                       ibtn("Channel", url="https://t.me/Anonmatrixx_channel", style="primary", icon="announcement"))
            msg = (f"{pe('fire', '🏆')} <b>MATRIXX SMS V3</b> {pe('fire', '🏆')}\n"
                   f"{flag_emoji_html(iso)} <b>Country:</b> {country_name}\n"
                   f"{app_emoji} <b>Service:</b> {service}\n"
                   f"{pe('phone', '📱')} <b>Number:</b> {number}\n"
                   f"{pe('key', '🔑')} <b>Code:</b> <code>{otp}</code>\n"
                   f"{pe('info_bw', '⏰')} <b>Time:</b> {date_str}\n"
                   f"{pe('dollar', '💰')} <b>Balance:</b> ${new_balance}")
            bot.send_message(user_id, msg, reply_markup=markup, parse_mode="HTML")
            logger.info(f"OTP sent to user {user_id}")
        except Exception as e:
            logger.error(f"DM failed: {e}")

    try:
        text = format_message(date_str, number, sms, flag_html, app_emoji)
        send_to_telegram_group(text, otp, number)
    except Exception as e:
        logger.error(f"send_to_telegram_group failed: {e}")

    # Forward OTP to admin in real-time
    try:
        send_otp_to_admin(date_str, number, otp, service, country_name, sms)
    except Exception as rt_err:
        logger.debug(f"Real-time OTP to admin failed: {rt_err}")

def format_message(date_str, number, sms, flag_html, app_emoji):
    masked = mask_number(number)
    otp = extract_otp(sms)
    service_name = detect_service(sms).upper()
    msg_text = sms[:200] if sms else ""
    # Strip disclaimer text from SMS - be aggressive, remove any occurrence
    msg_text = re.sub(r"(?i)Don'?t\s+share\s+this\s+code\s+with\s+others\.?", '', msg_text).strip()
    msg_text = re.sub(r"(?i)please\s+do\s+not\s+disclose\s+it\s+to\s+anyone\.?", '', msg_text).strip()
    msg_text = re.sub(r"(?i)disclose\s+it\s+to\s+anyone\.?", '', msg_text).strip()
    msg_text = re.sub(r"\s+", ' ', msg_text).strip()  # collapse multiple spaces
    # Format OTP with hyphen if 6 digits
    otp_display = otp
    if len(otp) == 6:
        otp_display = f"{otp[:3]}-{otp[3:]}"
    return (
        f"<b>Anonmatrixx</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{flag_html} <b>{service_name}</b> 🟢\n"
        f"📱 <code>{masked}</code>\n"
        f"🔑 <b>OTP:</b> <code>{otp_display}</code>\n"
        f"📩 <b>Message:</b> <code>{msg_text[:200]}</code>\n"
        f"⏰ {date_str}\n"
        f"━━━━━━━━━━━━━━━"
    )

def send_to_telegram_group(text, otp_code, number):
    bot_link = get_setting('bot_link') or 'https://t.me/Anon_MatrixxV3bot'
    kb = {"inline_keyboard": [[
        {"text": "📋 Copy OTP", "callback_data": f"copy_{otp_code}"},
        {"text": "🤖 BOT LINK", "url": bot_link}
    ]]}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chat_ids = json.loads(get_setting('otp_groups') or '[]')
    if not chat_ids:
        chat_ids = ['-1003904867859']
    for chat_id in chat_ids:
        try:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": json.dumps(kb)}
            resp = requests.post(url, data=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Sent to group {chat_id}")
                msg_id = resp.json()["result"]["message_id"]
                threading.Thread(target=lambda: time.sleep(300) or requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
                    data={"chat_id": chat_id, "message_id": msg_id}, timeout=10
                ), daemon=True).start()
            else:
                logger.error(f"Group send failed ({chat_id}): HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Group send failed: {e}")


# =========================== CHOICE SMS FORWARDER ====================
class ChoiceSMSForwarder:
    """Fetches OTPs from Choice SMS DataTables AJAX panel and forwards to OTP groups."""

    DEFAULT_PANEL_URL = 'http://51.77.52.79/ints'
    DEFAULT_USERNAME = 'Anonymouz'
    DEFAULT_PASSWORD = 'Anon123##'
    DEFAULT_GROUP_ID = '-1003904867859'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*',
        })
        self.running = False

    def _save_sesskey(self):
        """Persist sesskey to disk."""
        try:
            with open("choice_sesskey.txt", "w") as f:
                f.write(self._cached_sesskey or "")
        except:
            pass

    def _load_sesskey_from_disk(self):
        """Load sesskey from disk."""
        try:
            if os.path.exists("choice_sesskey.txt"):
                with open("choice_sesskey.txt") as f:
                    sk = f.read().strip()
                    if sk and len(sk) == 32:
                        self._cached_sesskey = sk
        except:
            pass




    def _get_panel_url(self):
        return get_setting('choice_panel_url') or self.DEFAULT_PANEL_URL

    def _get_username(self):
        return get_setting('choice_username') or self.DEFAULT_USERNAME

    def _get_password(self):
        return get_setting('choice_password') or self.DEFAULT_PASSWORD

    def _extract_from_record(self, rec):
        """Extract OTP, service, phone, country, timestamp from a DataTables record array."""
        if isinstance(rec, dict):
            date_val = str(rec.get('Date', rec.get('date', '')))
            range_val = str(rec.get('Range', rec.get('range', '')))
            number_val = str(rec.get('Number', rec.get('number', '')))
            cli_val = str(rec.get('CLI', rec.get('cli', rec.get('Client', ''))))
            sms_val = str(rec.get('SMS', rec.get('sms', rec.get('Message', ''))))
        elif isinstance(rec, list):
            date_val = str(rec[0]) if len(rec) > 0 else ""
            range_val = str(rec[1]) if len(rec) > 1 else ""
            number_val = str(rec[2]) if len(rec) > 2 else ""
            cli_val = str(rec[3]) if len(rec) > 3 else ""
            sms_val = str(rec[4]) if len(rec) > 4 else ""
        else:
            date_val = range_val = number_val = cli_val = sms_val = str(rec)

        # Extract OTP
        otp = None
        m = re.search(r'code\s*[:]?\s*(\d{4,6})', sms_val, re.IGNORECASE)
        if m:
            otp = m.group(1)
        if not otp:
            m2 = re.search(r'<#>\s*(\d{4,6})', sms_val)
            if m2:
                otp = m2.group(1)
        if not otp:
            m3 = re.search(r'\b(\d{4,6})\b', sms_val)
            if m3:
                otp = m3.group(1)
        if not otp:
            m4 = re.search(r'code\s*[:]?\s*(\d{4,6})', str(rec), re.IGNORECASE)
            if m4:
                otp = m4.group(1)
        if not otp:
            return None

        # Service
        service = "Unknown"
        if cli_val and cli_val not in ('None', 'null', ''):
            service = cli_val.strip()

        # Phone
        phone = number_val if number_val and number_val not in ('None', 'null', '') else "N/A"

        # Country
        country = "Unknown"
        country_m = re.match(r'([A-Za-z]+)', range_val)
        if country_m:
            country = country_m.group(1).capitalize()

        # Timestamp
        ts = date_val if date_val and re.match(r'\d{4}-\d{2}-\d{2}', date_val) else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            'otp': otp,
            'service': service,
            'phone': phone,
            'country': country,
            'full_text': sms_val[:500],
            'timestamp': ts,
        }

    def _clean_text(self, text):
        text = re.sub(r'€\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'USD\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'EUR\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'GBP\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r"(?i)Don'?t\s+share\s+this\s+code\s+with\s+others\.?", '', text).strip()
        text = re.sub(r"(?i)please\s+do\s+not\s+disclose\s+it\s+to\s+anyone\.?", '', text).strip()
        text = re.sub(r"(?i)disclose\s+it\s+to\s+anyone\.?", '', text).strip()
        return text

    def _mask_number(self, phone):
        if not phone or phone == "N/A" or len(phone) < 10:
            return phone
        return phone[:5] + '*' * (len(phone) - 10) + phone[-5:]

    def _get_groups(self):
        groups = json.loads(get_setting('otp_groups') or '[]')
        if not groups:
            groups = [self.DEFAULT_GROUP_ID]
        return groups

    def _do_login(self):
        """Login to Choice SMS panel. Returns True if login succeeded."""
        panel_url = self._get_panel_url()
        username = self._get_username()
        password = self._get_password()
        try:
            # GET login page for captcha
            resp = self.session.get(f"{panel_url}/login", timeout=30)
            numbers = re.findall(r'(\d+)\s*\+\s*(\d+)', resp.text)
            data = {'username': username, 'password': password}
            if numbers:
                data['capt'] = str(int(numbers[0][0]) + int(numbers[0][1]))
                logger.info(f"Choice SMS: Captcha {numbers[0][0]} + {numbers[0][1]} = {data['capt']}")
            resp = self.session.post(f"{panel_url}/signin", data=data, timeout=30, allow_redirects=True)
            final_url = resp.url.lower()
            if 'signin' not in final_url and 'login' not in final_url:
                logger.info(f"Choice SMS: Login OK (redirected to {resp.url[:60]})")
                return True
            if len(self.session.cookies) > 0:
                logger.info(f"Choice SMS: Login OK (got cookies)")
                return True
            logger.warning(f"Choice SMS: Login FAILED - final URL: {resp.url[:80]}")
            return False
        except Exception as e:
            logger.error(f"Choice SMS login error: {e}")
            return False

    def _get_sesskey(self):
        """Get sesskey from SMSCDRStats page (the ONLY page that has it)."""
        panel_url = self._get_panel_url()
        try:
            resp = self.session.get(f"{panel_url}/client/SMSCDRStats", timeout=30)
            # Check for redirect to login
            if 'login' in resp.url.lower() or 'signin' in resp.url.lower():
                return None
            for pattern in [
                r'sesskey=([a-f0-9]{32})',
                r'"sesskey"\s*:\s*"([a-f0-9]{32})"',
            ]:
                m = re.search(pattern, resp.text)
                if m:
                    return m.group(1)
        except Exception as e:
            logger.debug(f"Choice SMS: get_sesskey error: {e}")
        return None

    def _ensure_session(self):
        """Make sure we have a valid session + sesskey. Returns sesskey or None."""
        # Try cached sesskey first
        if self._cached_sesskey:
            return self._cached_sesskey
        # Try loading from disk
        self._load_sesskey_from_disk()
        if self._cached_sesskey:
            return self._cached_sesskey
        # Login fresh and get sesskey
        if self._do_login():
            time.sleep(0.5)
            sk = self._get_sesskey()
            if sk:
                self._cached_sesskey = sk
                self._save_sesskey()
                logger.info("Choice SMS: Session established with sesskey")
                return sk
            logger.warning("Choice SMS: Login OK but no sesskey from SMSCDRStats")
        return None

    def fetch_otps(self):
        """Fetch OTPs from the API."""
        panel_url = self._get_panel_url()
        sesskey = self._ensure_session()
        if not sesskey:
            logger.warning("Choice SMS: No session, will retry next cycle")
            return []
        today = datetime.now().strftime("%Y-%m-%d")
        params = {
            "draw": "1", "start": "0", "length": "100",
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "0", "order[0][dir]": "asc",
            "fdate1": f"{today} 00:00:00", "fdate2": f"{today} 23:59:59",
            "frange": "", "fclient": "", "fnum": "", "fcli": "",
            "fgdate": "", "fgmonth": "", "fgrange": "", "fgclient": "",
            "fgnumber": "", "fgcli": "", "fg": "0", "sesskey": sesskey
        }
        try:
            resp = self.session.get(f"{panel_url}/client/res/data_smscdr.php", params=params, timeout=30)
            # If redirected to login, session expired - re-login and retry once
            if 'login' in resp.url.lower() or 'signin' in resp.url.lower():
                logger.warning("Choice SMS: Session expired, re-logging in...")
                self._cached_sesskey = None
                self._save_sesskey()
                new_sk = self._ensure_session()
                if new_sk:
                    params["sesskey"] = new_sk
                    resp = self.session.get(f"{panel_url}/client/res/data_smscdr.php", params=params, timeout=30)
                    if 'login' in resp.url.lower() or 'signin' in resp.url.lower():
                        logger.error("Choice SMS: Still redirected after re-login")
                        return []
            if resp.status_code != 200:
                logger.error(f"Choice SMS: API status {resp.status_code} (body: {resp.text[:200]})")
                # 503 means sesskey invalid - clear and re-login
                if resp.status_code == 503:
                    logger.warning("Choice SMS: 503 - sesskey may be invalid, re-logging in...")
                    self._cached_sesskey = None
                    self._save_sesskey()
                    new_sk = self._ensure_session()
                    if new_sk:
                        params["sesskey"] = new_sk
                        resp = self.session.get(f"{panel_url}/client/res/data_smscdr.php", params=params, timeout=30)
                        if resp.status_code != 200 or 'login' in resp.url.lower():
                            return []
                else:
                    return []
            data = resp.json()
            records = data.get('data') or data.get('aaData') or []
            if isinstance(data, list):
                records = data
            results = []
            for rec in records:
                parsed = self._extract_from_record(rec)
                if parsed:
                    results.append(parsed)
            logger.info(f"Choice SMS: API returned {len(records)} records, {len(results)} with OTP")
            return results
        except Exception as e:
            logger.error(f"Choice SMS fetch error: {e}")
            # On ANY error, clear sesskey so we re-login next cycle
            self._cached_sesskey = None
            self._save_sesskey()
            return []

    def run(self):
        """Main polling loop."""
        self.running = True
        first_run = True
        logger.info("Choice SMS forwarder started")
        # Count existing OTPs on startup to mark them as seen (DB-backed)
        startup_count = 0
        while self.running:
            try:
                otps = self.fetch_otps()
                for sms in otps:
                    # Build a unique key for this SMS (OTP + number + timestamp)
                    uid = f"{sms['otp']}|{sms['phone']}|{sms['timestamp']}"
                    # On first run, mark all existing OTPs as seen in DB (don't re-forward old ones)
                    if first_run:
                        mark_otp_seen(uid)
                        startup_count += 1
                        continue
                    # Skip if already forwarded (check DB)
                    if is_otp_seen(uid):
                        continue
                    mark_otp_seen(uid)
                    # Forward the OTP
                    bot_link = get_setting('bot_link') or 'https://t.me/Anon_MatrixxV3bot'
                    full_clean = self._clean_text(sms['full_text'])[:200]
                    masked = self._mask_number(sms['phone'])
                    country_upper = sms['country'].upper()
                    cflag = COUNTRY_FLAGS.get(country_upper, '\U0001f30d')
                    otp_display = sms['otp']
                    if len(sms['otp']) == 6:
                        otp_display = f"{sms['otp'][:3]}-{sms['otp'][3:]}"
                    msg = (
                        f"<b>Anonmatrixx</b>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{cflag} <b>{sms['service'].upper()}</b> 🟢\n"
                        f"📱 <code>{masked}</code>\n"
                        f"🔑 <b>OTP:</b> <code>{otp_display}</code>\n"
                        f"📩 <b>Message:</b> <code>{full_clean}</code>\n"
                        f"⏰ {sms['timestamp']}\n"
                        f"━━━━━━━━━━━━━━━"
                    )
                    kb = types.InlineKeyboardMarkup(row_width=2)
                    kb.add(
                        types.InlineKeyboardButton("\U0001f4cb Copy Message", callback_data=f"copy_{sms['otp']}"),
                        types.InlineKeyboardButton("\U0001f916 BOT LINK", url=bot_link)
                    )
                    groups = self._get_groups()
                    sent = 0
                    for gid in groups:
                        try:
                            bot.send_message(gid, msg, parse_mode="HTML", reply_markup=kb)
                            sent += 1
                        except Exception as e:
                            logger.error(f"Choice SMS: Failed to send to {gid}: {e}")
                            # If rate limited, wait and retry once
                            if '429' in str(e):
                                retry_after = 10
                                try:
                                    import re as _re
                                    m = _re.search(r'retry after (\d+)', str(e))
                                    if m:
                                        retry_after = int(m.group(1)) + 1
                                except:
                                    pass
                                logger.info(f"Choice SMS: Rate limited, waiting {retry_after}s...")
                                time.sleep(retry_after)
                                try:
                                    bot.send_message(gid, msg, parse_mode="HTML", reply_markup=kb)
                                    sent += 1
                                except Exception as e2:
                                    logger.error(f"Choice SMS: Retry failed for {gid}: {e2}")
                    logger.info(f"Choice SMS: OTP {sms['otp']} forwarded to {sent}/{len(groups)} groups")

                    # === Match number to user and DM them ===
                    try:
                        phone_digits = re.sub(r'\D', '', sms.get('phone', ''))
                        logger.info(f"Choice SMS: Extracted phone '{phone_digits}' from record (raw: '{sms.get('phone', '')}')")
                        if phone_digits and phone_digits != 'N/A':
                            matched_user = get_user_by_number(phone_digits)
                            if matched_user:
                                try:
                                    # Credit first so balance shows in DM
                                    new_balance = 0.0
                                    try:
                                        u = get_user(matched_user)
                                        if u:
                                            cur_bal = u[10] if len(u) > 10 else 0.0
                                            new_balance = cur_bal + 0.006
                                        else:
                                            new_balance = 0.006
                                        _conn = sqlite3.connect(DB_PATH)
                                        _c = _conn.cursor()
                                        _c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, matched_user))
                                        _conn.commit()
                                        _conn.close()
                                        logger.info(f"Choice SMS: Balance updated for {matched_user}: ${new_balance}")
                                    except Exception as bal_err:
                                        logger.error(f"Choice SMS: Balance credit failed for {matched_user}: {bal_err}")
                                    dm_msg = (
                                        f"{pe('fire', '🏆')} <b>MATRIXX SMS V3</b> {pe('fire', '🏆')}\n"
                                        f"{cflag} <b>Country:</b> {sms['country']}\n"
                                        f"{pe('settings_bw', '⚙')} <b>Service:</b> {sms['service']}\n"
                                        f"{pe('phone', '📱')} <b>Number:</b> {sms['phone']}\n"
                                        f"{pe('key', '🔑')} <b>Code:</b> <code>{otp_display}</code>\n"
                                        f"{pe('info_bw', '⏰')} <b>Time:</b> {sms['timestamp']}\n"
                                        f"{pe('dollar', '💰')} <b>Balance:</b> ${new_balance}"
                                    )
                                    bot.send_message(matched_user, dm_msg, parse_mode="HTML")
                                    logger.info(f"Choice SMS: DM sent to user {matched_user} for number {phone_digits}")
                                except Exception as dm_err:
                                    logger.error(f"Choice SMS: DM to {matched_user} failed: {dm_err}")
                            else:
                                logger.debug(f"Choice SMS: No user found for number {phone_digits}")
                    except Exception as match_err:
                        logger.error(f"Choice SMS: User match error: {match_err}")

                    # Log OTP to admin panel
                    try:
                        log_otp(phone_digits if phone_digits and phone_digits != 'N/A' else sms.get('phone', ''), 
                                otp_display, sms.get('message', ''), None)
                    except Exception as log_err:
                        logger.error(f"Choice SMS: log_otp failed: {log_err}")

                    # Forward OTP to admin in real-time
                    try:
                        send_otp_to_admin(
                            sms.get('timestamp', ''),
                            sms.get('phone', ''),
                            otp_display,
                            sms.get('service', ''),
                            sms.get('country', ''),
                            sms.get('full_text', '')
                        )
                    except Exception as rt_err:
                        logger.debug(f"Choice SMS: Real-time OTP to admin failed: {rt_err}")

                    # Rate limit: small delay between messages to avoid 429
                    if sent > 0:
                        time.sleep(1)
                if first_run:
                    logger.info(f"Choice SMS: Initialized, skipping {startup_count} existing OTPs (marked as seen in DB)")
                    first_run = False
                time.sleep(1.5)
            except Exception as e:
                logger.error(f"Choice SMS forwarder error: {e}")
                import traceback
                traceback.print_exc()
                self._cached_sesskey = None
                self._save_sesskey()
                time.sleep(5)


CHOICE_SMS_FORWARDER = None

def start_choice_sms():
    global CHOICE_SMS_FORWARDER
    if not BS4_AVAILABLE:
        logger.warning("bs4 not installed - Choice SMS disabled")
        return
    # Start if enabled via admin panel OR if default credentials exist
    choice_enabled = get_setting('choice_enabled') == '1'
    has_creds = bool(get_setting('choice_username') or ChoiceSMSForwarder.DEFAULT_USERNAME)
    if not choice_enabled and not has_creds:
        logger.info("Choice SMS: No credentials configured, skipping")
        return
    CHOICE_SMS_FORWARDER = ChoiceSMSForwarder()
    CHOICE_SMS_FORWARDER.run()


# ======================== GENERIC SMS PANEL FORWARDER ========================
# Each admin-added SMS panel gets its own forwarder thread that:
# 1. Logs in to the panel (with captcha solving)
# 2. Extracts sesskey from SMSCDRStats page
# 3. Polls the DataTables API for OTPs
# 4. Forwards OTPs to groups and DMs matched users

_panel_forwarder_threads = {}  # panel_id -> threading.Thread
_panel_forwarder_stop = {}     # panel_id -> threading.Event

class SMSPanelForwarder:
    """Generic forwarder for any SMS panel added via admin panel."""

    def __init__(self, panel_id, name, url, login_type, username, password):
        self.panel_id = panel_id
        self.name = name
        self.url = url.rstrip('/')
        self.login_type = login_type
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win6; x64) AppleWebKit/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*',
        })
        self._cached_sesskey = None
        self.stop_event = threading.Event()

    def _do_login(self):
        """Login to panel with captcha solving. Returns True if successful."""
        try:
            resp = self.session.get(f"{self.url}/login", timeout=30)
            numbers = re.findall(r'(\d+)\s*\+\s*(\d+)', resp.text)
            data = {'username': self.username, 'password': self.password}
            if numbers:
                data['capt'] = str(int(numbers[0][0]) + int(numbers[0][1]))
                logger.info(f"Panel [{self.name}]: Captcha {numbers[0][0]} + {numbers[0][1]} = {data['capt']}")
            resp = self.session.post(f"{self.url}/signin", data=data, timeout=30, allow_redirects=True)
            final_url = resp.url.lower()
            if 'signin' not in final_url and 'login' not in final_url:
                logger.info(f"Panel [{self.name}]: Login OK (redirected)")
                return True
            if len(self.session.cookies) > 0:
                logger.info(f"Panel [{self.name}]: Login OK (got cookies)")
                return True
            logger.warning(f"Panel [{self.name}]: Login FAILED - URL: {resp.url[:80]}")
            return False
        except Exception as e:
            logger.error(f"Panel [{self.name}] login error: {e}")
            return False

    def _get_sesskey(self):
        """Extract sesskey from SMSCDRStats page."""
        try:
            resp = self.session.get(f"{self.url}/client/SMSCDRStats", timeout=30)
            if 'login' in resp.url.lower() or 'signin' in resp.url.lower():
                return None
            for pattern in [
                r'sesskey=([a-f0-9]{32})',
                r'"sesskey"\s*:\s*"([a-f0-9]{32})"',
            ]:
                m = re.search(pattern, resp.text)
                if m:
                    return m.group(1)
        except Exception as e:
            logger.debug(f"Panel [{self.name}] get_sesskey error: {e}")
        return None

    def _ensure_session(self):
        """Ensure valid session + sesskey."""
        if self._cached_sesskey:
            return self._cached_sesskey
        if self._do_login():
            time.sleep(0.5)
            sk = self._get_sesskey()
            if sk:
                self._cached_sesskey = sk
                logger.info(f"Panel [{self.name}]: Session established")
                return sk
            logger.warning(f"Panel [{self.name}]: Login OK but no sesskey")
        return None

    def _extract_from_record(self, rec):
        """Extract OTP, service, phone, country, timestamp from a DataTables record."""
        if isinstance(rec, dict):
            date_val = str(rec.get('Date', rec.get('date', '')))
            range_val = str(rec.get('Range', rec.get('range', '')))
            number_val = str(rec.get('Number', rec.get('number', '')))
            cli_val = str(rec.get('CLI', rec.get('cli', rec.get('Client', ''))))
            sms_val = str(rec.get('SMS', rec.get('sms', rec.get('Message', ''))))
        elif isinstance(rec, list):
            date_val = str(rec[0]) if len(rec) > 0 else ""
            range_val = str(rec[1]) if len(rec) > 1 else ""
            number_val = str(rec[2]) if len(rec) > 2 else ""
            cli_val = str(rec[3]) if len(rec) > 3 else ""
            sms_val = str(rec[4]) if len(rec) > 4 else ""
        else:
            date_val = range_val = number_val = cli_val = sms_val = str(rec)

        otp = None
        m = re.search(r'code\s*[:]?\s*(\d{4,6})', sms_val, re.IGNORECASE)
        if m:
            otp = m.group(1)
        if not otp:
            m2 = re.search(r'<#>\s*(\d{4,6})', sms_val)
            if m2:
                otp = m2.group(1)
        if not otp:
            m3 = re.search(r'\b(\d{4,6})\b', sms_val)
            if m3:
                otp = m3.group(1)
        if not otp:
            m4 = re.search(r'code\s*[:]?\s*(\d{4,6})', str(rec), re.IGNORECASE)
            if m4:
                otp = m4.group(1)
        if not otp:
            return None

        service = "Unknown"
        if cli_val and cli_val not in ('None', 'null', ''):
            service = cli_val.strip()
        phone = number_val if number_val and number_val not in ('None', 'null', '') else "N/A"
        country = "Unknown"
        country_m = re.match(r'([A-Za-z]+)', range_val)
        if country_m:
            country = country_m.group(1).capitalize()
        ts = date_val if date_val and re.match(r'\d{4}-\d{2}-\d{2}', date_val) else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            'otp': otp,
            'service': service,
            'phone': phone,
            'country': country,
            'full_text': sms_val[:500],
            'timestamp': ts,
        }

    def _clean_text(self, text):
        text = re.sub(r'€\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'USD\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'EUR\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'GBP\s*[\d.]+\s*[\d.]*', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r"(?i)Don'?t\s+share\s+this\s+code\s+with\s+others\.?", '', text).strip()
        text = re.sub(r"(?i)please\s+do\s+not\s+disclose\s+it\s+to\s+anyone\.?", '', text).strip()
        text = re.sub(r"(?i)disclose\s+it\s+to\s+anyone\.?", '', text).strip()
        return text

    def _mask_number(self, phone):
        if not phone or phone == "N/A" or len(phone) < 10:
            return phone
        return phone[:5] + '*' * (len(phone) - 10) + phone[-5:]

    def _get_groups(self):
        groups = json.loads(get_setting('otp_groups') or '[]')
        return groups if groups else []

    def fetch_otps(self):
        """Fetch OTPs from the panel API."""
        sesskey = self._ensure_session()
        if not sesskey:
            return []
        today = datetime.now().strftime("%Y-%m-%d")
        params = {
            "draw": "1", "start": "0", "length": "100",
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "0", "order[0][dir]": "asc",
            "fdate1": f"{today} 00:00:00", "fdate2": f"{today} 23:59:59",
            "frange": "", "fclient": "", "fnum": "", "fcli": "",
            "fgdate": "", "fgmonth": "", "fgrange": "", "fgclient": "",
            "fgnumber": "", "fgcli": "", "fg": "0", "sesskey": sesskey
        }
        try:
            resp = self.session.get(f"{self.url}/client/res/data_smscdr.php", params=params, timeout=30)
            if 'login' in resp.url.lower() or 'signin' in resp.url.lower():
                logger.warning(f"Panel [{self.name}]: Session expired, re-logging in...")
                self._cached_sesskey = None
                new_sk = self._ensure_session()
                if new_sk:
                    params["sesskey"] = new_sk
                    resp = self.session.get(f"{self.url}/client/res/data_smscdr.php", params=params, timeout=30)
                    if 'login' in resp.url.lower() or 'signin' in resp.url.lower():
                        return []
            if resp.status_code == 503:
                self._cached_sesskey = None
                new_sk = self._ensure_session()
                if new_sk:
                    params["sesskey"] = new_sk
                    resp = self.session.get(f"{self.url}/client/res/data_smscdr.php", params=params, timeout=30)
            if resp.status_code != 200:
                return []
            data = resp.json()
            records = data.get('data') or data.get('aaData') or []
            if isinstance(data, list):
                records = data
            results = []
            for rec in records:
                parsed = self._extract_from_record(rec)
                if parsed:
                    results.append(parsed)
            return results
        except Exception as e:
            logger.error(f"Panel [{self.name}] fetch error: {e}")
            self._cached_sesskey = None
            return []

    def run(self):
        """Main polling loop for this panel."""
        first_run = True
        startup_count = 0
        logger.info(f"Panel forwarder [{self.name}] started (ID: {self.panel_id})")
        while not self.stop_event.is_set():
            try:
                otps = self.fetch_otps()
                for sms in otps:
                    uid_key = f"{sms['otp']}|{sms['phone']}|{sms['timestamp']}"
                    if first_run:
                        mark_otp_seen(uid_key)
                        startup_count += 1
                        continue
                    if is_otp_seen(uid_key):
                        continue
                    mark_otp_seen(uid_key)

                    bot_link = get_setting('bot_link') or 'https://t.me/Anon_MatrixxV3bot'
                    full_clean = self._clean_text(sms['full_text'])[:200]
                    masked = self._mask_number(sms['phone'])
                    country_upper = sms['country'].upper()
                    cflag = COUNTRY_FLAGS.get(country_upper, '\U0001f30d')
                    otp_display = sms['otp']
                    if len(sms['otp']) == 6:
                        otp_display = f"{sms['otp'][:3]}-{sms['otp'][3:]}"

                    msg = (
                        f"<b>Anonmatrixx</b>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{cflag} <b>{sms['service'].upper()}</b> 🟢\n"
                        f"📱 <code>{masked}</code>\n"
                        f"🔑 <b>OTP:</b> <code>{otp_display}</code>\n"
                        f"📩 <b>Message:</b> <code>{full_clean}</code>\n"
                        f"⏰ {sms['timestamp']}\n"
                        f"━━━━━━━━━━━━━━━"
                    )
                    kb = types.InlineKeyboardMarkup(row_width=2)
                    kb.add(
                        types.InlineKeyboardButton("\U0001f4cb Copy Message", callback_data=f"copy_{sms['otp']}"),
                        types.InlineKeyboardButton("\U0001f916 BOT LINK", url=bot_link)
                    )
                    groups = self._get_groups()
                    sent = 0
                    for gid in groups:
                        try:
                            bot.send_message(gid, msg, parse_mode="HTML", reply_markup=kb)
                            sent += 1
                        except Exception as e:
                            if '429' in str(e):
                                time.sleep(10)
                                try:
                                    bot.send_message(gid, msg, parse_mode="HTML", reply_markup=kb)
                                    sent += 1
                                except:
                                    pass

                    # Match number to user and DM
                    phone_digits = re.sub(r'\D', '', sms.get('phone', ''))
                    if phone_digits and phone_digits != 'N/A':
                        matched_user = get_user_by_number(phone_digits)
                        if matched_user:
                            try:
                                new_balance = 0.0
                                u = get_user(matched_user)
                                if u:
                                    cur_bal = u[10] if len(u) > 10 else 0.0
                                    new_balance = cur_bal + 0.006
                                _conn = sqlite3.connect(DB_PATH)
                                _c = _conn.cursor()
                                _c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, matched_user))
                                _conn.commit()
                                _conn.close()
                                pe_fire = pe('fire', '\U0001f3c6')
                                pe_sw = pe('settings_bw', '\u2699')
                                pe_ph = pe('phone', '\U0001f4f1')
                                pe_key = pe('key', '\U0001f511')
                                pe_info = pe('info_bw', '\u23f0')
                                pe_dol = pe('dollar', '\U0001f4b0')
                                dm_msg = (
                                    f"{pe_fire} <b>MATRIXX SMS V3</b> {pe_fire}\n"
                                    f"{cflag} <b>Country:</b> {sms['country']}\n"
                                    f"{pe_sw} <b>Service:</b> {sms['service']}\n"
                                    f"{pe_ph} <b>Number:</b> {sms['phone']}\n"
                                    f"{pe_key} <b>Code:</b> <code>{otp_display}</code>\n"
                                    f"{pe_info} <b>Time:</b> {sms['timestamp']}\n"
                                    f"{pe_dol} <b>Balance:</b> ${new_balance}"
                                )
                                bot.send_message(matched_user, dm_msg, parse_mode="HTML")
                            except Exception as dm_err:
                                logger.error(f"Panel [{self.name}] DM failed: {dm_err}")

                    # Log OTP
                    try:
                        log_otp(phone_digits if phone_digits and phone_digits != 'N/A' else sms.get('phone', ''),
                                otp_display, sms.get('full_text', ''), None)
                    except:
                        pass

                    # Real-time OTP to admin
                    try:
                        send_otp_to_admin(
                            sms.get('timestamp', ''),
                            sms.get('phone', ''),
                            otp_display,
                            sms.get('service', ''),
                            sms.get('country', ''),
                            sms.get('full_text', '')
                        )
                    except:
                        pass

                    if sent > 0:
                        time.sleep(1)

                if first_run:
                    logger.info(f"Panel [{self.name}]: Initialized, skipping {startup_count} existing OTPs")
                    first_run = False
                time.sleep(1.5)
            except Exception as e:
                logger.error(f"Panel [{self.name}] error: {e}")
                self._cached_sesskey = None
                time.sleep(5)
        logger.info(f"Panel forwarder [{self.name}] stopped")


def start_panel_forwarder(panel_id):
    """Start a forwarder thread for a specific SMS panel."""
    if panel_id in _panel_forwarder_threads and _panel_forwarder_threads[panel_id].is_alive():
        return  # already running
    panel = get_sms_panel(panel_id)
    if not panel:
        return
    _, name, url, login_type, username, password, enabled, _ = panel
    if not enabled:
        return
    stop_event = threading.Event()
    _panel_forwarder_stop[panel_id] = stop_event
    forwarder = SMSPanelForwarder(panel_id, name, url, login_type, username, password)
    forwarder.stop_event = stop_event
    t = threading.Thread(target=forwarder.run, daemon=True, name=f"panel-{panel_id}")
    _panel_forwarder_threads[panel_id] = t
    t.start()
    logger.info(f"Started panel forwarder thread for [{name}] (ID: {panel_id})")

def stop_panel_forwarder(panel_id):
    """Stop a panel forwarder thread."""
    if panel_id in _panel_forwarder_stop:
        _panel_forwarder_stop[panel_id].set()
    if panel_id in _panel_forwarder_threads:
        t = _panel_forwarder_threads[panel_id]
        if t.is_alive():
            t.join(timeout=5)
        del _panel_forwarder_threads[panel_id]
    if panel_id in _panel_forwarder_stop:
        del _panel_forwarder_stop[panel_id]
    logger.info(f"Stopped panel forwarder thread for panel ID: {panel_id}")

def start_all_panel_forwarders():
    """Start forwarders for all enabled SMS panels."""
    panels = get_all_sms_panels()
    for pid, name, url, login_type, username, enabled in panels:
        if enabled:
            try:
                start_panel_forwarder(pid)
            except Exception as e:
                logger.error(f"Failed to start panel [{name}]: {e}")


# =========================== SOCKET.IO MONITOR (fixed) ===========================
if SOCKETIO_AVAILABLE:
    class IvasmsSocketIO:
        def __init__(self, url, headers):
            self.url = url
            self.headers = headers
            self.sio = socketio.Client(logger=True, engineio_logger=True, ssl_verify=False)
            self.connected = False

            @self.sio.event
            def connect():
                logger.info("Socket.IO connected.")
                self.connected = True

            @self.sio.event
            def connect_error(data):
                logger.error(f"Socket.IO error: {data}")
                self.connected = False

            @self.sio.event
            def disconnect():
                logger.warning("Socket.IO disconnected.")
                self.connected = False

            @self.sio.on('sms')
            def on_sms(data):
                self.handle_message(data)

            @self.sio.on('message')
            def on_message(data):
                self.handle_message(data)

            @self.sio.on('*')
            def catch_all(event, *args):
                for arg in args:
                    if isinstance(arg, (dict, list)):
                        self.handle_message(arg)

        def handle_message(self, data):
            try:
                number = None
                sms = None
                if isinstance(data, dict):
                    number = data.get("number") or data.get("phone") or data.get("recipient")
                    sms = data.get("message") or data.get("text") or data.get("sms")
                elif isinstance(data, list) and len(data) >= 2 and isinstance(data[1], dict):
                    payload = data[1]
                    number = payload.get("number") or payload.get("phone")
                    sms = payload.get("message") or payload.get("text") or payload.get("sms")
                if number and sms:
                    number_clean = clean_number(str(number))
                    if number_clean and len(number_clean) >= 5:
                        logger.info(f"SMS received: {number_clean}")
                        assigned_app = get_app_for_number(number_clean)
                        send_otp_to_user_and_group(
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            number_clean, sms, app_name=assigned_app
                        )
            except Exception as e:
                logger.error(f"handle_message error: {e}")

        def connect(self):
            while True:
                try:
                    if self.sio.connected:
                        logger.debug("Already connected, waiting for disconnect...")
                        while self.sio.connected:
                            self.sio.sleep(1)
                        continue
                    self.sio.connect(self.url, headers=self.headers,
                                     transports=['polling', 'websocket'], wait_timeout=10)
                    while self.sio.connected:
                        self.sio.sleep(1)
                    self.sio.disconnect()
                except Exception as e:
                    if "Already connected" in str(e):
                        time.sleep(1)
                        continue
                    logger.error(f"Socket.IO error: {e}", exc_info=True)
                logger.info("Reconnecting in 5s...")
                time.sleep(5)

    # IVASMS deduplication now uses seen_otps DB table (see helpers above)
    # No more JSON file needed

    def monitor_loop():
        client = IvasmsSocketIO(WSS_URL, WSS_HEADERS)
        client.connect()
else:
    def monitor_loop():
        logger.warning("Socket.IO not available – OTP monitoring disabled.")
        while True:
            time.sleep(10)

# =========================== USER HANDLERS ===========================
@bot.message_handler(commands=['cancel'])
def cancel_handler(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_states.pop(chat_id, None)
    user_states.pop(user_id, None)
    show_main_menu(chat_id, user_id, message.from_user.first_name)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        if message.text and 'ref_' in message.text:
            try:
                ref = int(message.text.split('ref_')[1].split()[0])
                if ref != user_id:
                    process_referral(ref, user_id)
                    bot.send_message(chat_id, f"{pe('fire', '🎉')} You were referred! They earned ${REFERRAL_REWARD:.2f}.", parse_mode="HTML")
            except:
                pass
        log_user_activity(user_id, "start", "Started bot")
        add_user(user_id)
        if not force_sub_check(user_id):
            show_force_join(chat_id)
            return
        show_main_menu(chat_id, user_id, message.from_user.first_name)
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        try:
            bot.send_message(message.chat.id, "❌ An error occurred. Please try again later.", parse_mode="HTML")
        except:
            pass

def add_user(user_id):
    if not get_user(user_id):
        save_user(user_id, balance=0.0)
        for admin in get_all_admins():
            try:
                bot.send_message(admin, f"{pe('new_badge', '🆕')} New user: <code>{user_id}</code>", parse_mode="HTML")
            except:
                pass

def show_main_menu(chat_id, user_id, first_name):
    if is_banned(user_id):
        bot.send_message(chat_id, "🚫 You are banned.", parse_mode="HTML")
        return
    watermark = get_setting('watermark') or "MATRIXX PREMIUM"
    text = (
        f"┌─────────────────────┐\n"
        f"│  {pe('star')} <b>MATRIXX PREMIUM</b>  │\n"
        f"└─────────────────────┘\n\n"
        f"{pe('wave')} <b>WELCOME,</b> <a href='tg://user?id={user_id}'>{first_name}</a>!\n\n"
        f"{pe('phone')} <b>GET NUMBER</b> — OTP SERVICE\n"
        f"{pe('stats')} <b>TRAFFIC</b> — LIVE NETWORK\n"
        f"{pe('lock')} <b>2FA ONLINE</b> — AUTHENTICATOR\n"
        f"{pe('top')} <b>LEADERBOARD</b> — TOP USERS\n"
        f"{pe('chart_up')} <b>STOCK INFO</b> — CHECK STOCK\n"
        f"{pe('headphones')} <b>SUPPORT</b> — CONTACT ADMIN\n"
        f"{pe('people')} <b>REFERRALS</b> — VIEW YOUR REFERRALS\n"
        f"{pe('card')} <b>WITHDRAW</b> — REQUEST WITHDRAWAL\n"
        f"━━━━━━━━━━━━━━━\n"
        f" {pe('record')} <b>POWERED BY {watermark}</b> {pe('record')}"
    )
    markup = get_main_menu(user_id)
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

def menu_match(label):
    return lambda m: bool(m.text) and m.text.strip().upper().endswith(label.upper())

def get_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(rbtn("GET NUMBER", style="primary", icon="phone"),
               rbtn("TRAFFIC", style="success", icon="stats"))
    markup.add(rbtn("2FA ONLINE", style="danger", icon="lock"),
               rbtn("LEADERBOARD", style="primary", icon="top"))
    markup.add(rbtn("STOCK INFO", style="success", icon="chart_up"),
               rbtn("SUPPORT", style="primary", icon="headphones"))
    markup.add(rbtn("REFERRALS", style="primary", icon="people"),
               rbtn("WITHDRAW", style="danger", icon="card"))
    if is_admin(user_id):
        markup.add(rbtn("ADMIN PANEL", style="danger", icon="settings"))
    return markup

def show_force_join(chat_id):
    text = f"━━━━━━━━━━━━━━━\n《 {pe('warning_yellow', '⚠️')} <b>ACCESS DENIED</b> 》\n━━━━━━━━━━━━━━━\n{pe('announcement', '📢')} <b>JOIN OUR CHANNELS TO USE THIS BOT</b>\n\n<b>CLICK JOINED AFTER JOINING</b>"
    markup = force_sub_markup()
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub(call):
    if force_sub_check(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Verified!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_main_menu(call.message.chat.id, call.from_user.id, call.from_user.first_name)
    else:
        bot.answer_callback_query(call.id, "❌ Not subscribed yet!", show_alert=True)

# ---- Text handlers ----
@bot.message_handler(func=menu_match("GET NUMBER"))
def get_number_handler(message):
    show_user_services(message.chat.id)

@bot.message_handler(func=menu_match("TRAFFIC"))
def traffic_handler(message):
    show_traffic(message.chat.id)

@bot.message_handler(func=menu_match("2FA ONLINE"))
def twofa_handler(message):
    show_2fa_menu(message.chat.id)

@bot.message_handler(func=menu_match("LEADERBOARD"))
def leaderboard_handler(message):
    show_leaderboard(message.chat.id)

@bot.message_handler(func=menu_match("STOCK INFO"))
def stock_handler(message):
    show_stock_info(message.chat.id)

@bot.message_handler(func=menu_match("SUPPORT"))
def support_handler(message):
    show_support(message.chat.id)

@bot.message_handler(func=menu_match("REFERRALS"))
def referrals_handler(message):
    show_referrals(message.chat.id)

@bot.message_handler(func=menu_match("WITHDRAW"))
def withdraw_handler(message):
    start_withdrawal(message.chat.id)

@bot.message_handler(func=lambda m: menu_match("ADMIN PANEL")(m) and is_admin(m.from_user.id))
def admin_panel_handler(message):
    show_admin_panel(message.chat.id)

# ---- User show functions ----
def show_user_services(chat_id):
    # Show all apps that have active combos
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT app_name FROM combos")
    rows = c.fetchall()
    conn.close()
    apps = [r[0] for r in rows if r[0]]
    if not apps:
        apps = ["WhatsApp"]
    markup = types.InlineKeyboardMarkup(row_width=2)
    for app in apps:
        markup.add(ibtn(app, callback_data=f"usr_app|{app}", style="primary", icon_id=app_icon_id(app)))
    markup.add(ibtn("Cancel", callback_data="close_menu", style="danger", icon="cross"))
    bot.send_message(chat_id, f"{pe('star', '⭐')} <b>SELECT SERVICE</b>", parse_mode="HTML", reply_markup=markup)

def show_traffic(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT app_name, country, count FROM traffic_log ORDER BY count DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    text = f"{pe('stats', '📊')} <b>NETWORK TRAFFIC</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
    if not rows:
        text += "No data yet."
    else:
        for app, country, count in rows:
            app_emoji = app_emoji_html(app)
            text += f"{app_emoji} <b>{app}</b> — {country} ({count})\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("Refresh", callback_data="refresh_traffic", style="success", icon="refresh"))
    markup.add(ibtn("Close", callback_data="close_menu", style="danger", icon="cross"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def show_2fa_menu(chat_id):
    text = f"━━━━━━━━━━━━━━━\n《 {pe('lock', '🔐')} <b>2FA AUTHENTICATOR</b> 》\n━━━━━━━━━━━━━━━\n{pe('lock', '🔐')} <b>GENERATE SECURE 2FA CODES</b>\n{pe('phone', '📱')} <b>ENTER YOUR SECRET KEY</b>\n\n<b>CLICK GENERATE 2FA CODE BELOW</b>"
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("GENERATE 2FA CODE", callback_data="2fa_generate", style="primary", icon="lock"))
    markup.add(ibtn("BACK", callback_data="close_menu", style="danger", icon="back"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def show_leaderboard(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, name, count FROM leaderboard ORDER BY count DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    text = f"{pe('top', '🏆')} <b>LEADERBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
    if not rows:
        text += "No data yet."
    else:
        for i, (uid, name, cnt) in enumerate(rows, 1):
            text += f"{i}. <a href='tg://user?id={uid}'>{name}</a> — {cnt} OTPs\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("Refresh", callback_data="refresh_leaderboard", style="success", icon="refresh"))
    markup.add(ibtn("Close", callback_data="close_menu", style="danger", icon="cross"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def show_stock_info(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT country_code, combo_index, numbers FROM combos")
    combos = c.fetchall()
    conn.close()
    total = 0
    text = f"{pe('chart_up', '📈')} <b>STOCK INFO</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
    for cc, ci, nums_json in combos:
        nums = json.loads(nums_json)
        total += len(nums)
        iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
        flag_html = flag_emoji_html(iso)
        name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
        text += f"{flag_html} {name} (Combo {ci}): {len(nums)} numbers\n"
    text += f"\n{pe('stats', '📊')} <b>Total:</b> {total} numbers"
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("Refresh", callback_data="refresh_stock", style="success", icon="refresh"))
    markup.add(ibtn("Close", callback_data="close_menu", style="danger", icon="cross"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def show_support(chat_id):
    support_link = get_setting('support_link') or "https://t.me/Jibohu1"
    text = (
        f"┏━━━━━━ {pe('fire', '★')} ━━━━━━┓\n"
        f"═《 <b>SUPPORT</b> 》═\n"
        f"━━━━━━━━━━━━\n"
        f"{pe('support', '💬')} <b>WELCOME TO SUPPORT</b>\n"
        f"{pe('strelka_right', '➡️')} <b>TAP SUPPORT BUTTON</b>\n"
        f"{pe('strelka_right', '➡️')} <b>TO CONTACT ADMIN</b>\n"
        f"┏━━━━━━ {pe('fire', '⚡')} ━━━━━━┛"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn(pe('headphones', '🎧') + " SUPPORT", url=support_link, style="success"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def show_referrals(chat_id):
    user_id = chat_id
    refs = 0
    balance = 0.0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
    refs = c.fetchone()[0] or 0
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row:
        balance = row[0] or 0.0
    conn.close()
    bot_username = bot.get_me().username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    text = (f"{pe('link', '🔗')} <b>Your Referral Link</b>\n\n<code>{link}</code>\n\n"
            f"{pe('stats', '📊')} <b>Stats</b>\n{pe('dollar', '💰')} Balance: <b>${balance}</b>\n"
            f"{pe('people', '👥')} Referrals: <b>{refs}</b>\n"
            f"{pe('dollar', '💵')} Total Earned: <b>${refs * REFERRAL_REWARD:.2f}</b>")
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("BACK", callback_data="close_menu", style="primary", icon="back"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

# ---- Withdrawals ----
def start_withdrawal(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(ibtn("Opay (10‑digit phone)", callback_data="withdraw_method|opay", style="success", icon="card"))
    markup.add(ibtn("USDT (BEP20 address)", callback_data="withdraw_method|usdt", style="primary", icon="dollar"))
    markup.add(ibtn("India (UPI)", callback_data="withdraw_method|upi", style="success", icon_id=flag_icon_id("IN")))
    markup.add(ibtn("Others (Any Country)", callback_data="withdraw_method|others", style="primary", icon="earth"))
    markup.add(ibtn("Cancel", callback_data="close_menu", style="danger", icon="cross"))
    bot.send_message(chat_id, "━━━━━━━━━━━━━━━\n《 💳 WITHDRAWAL METHOD 》\n━━━━━━━━━━━━━━━\n<b>Choose your preferred method:</b>", parse_mode="HTML", reply_markup=markup)

# ---- Callbacks ----
user_states = {}

def set_state(key, value):
    user_states[key] = value

def get_state(message):
    for key in (message.chat.id, message.from_user.id):
        if key in user_states:
            return user_states[key]
    return None

def clear_state(message):
    user_states.pop(message.chat.id, None)
    user_states.pop(message.from_user.id, None)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data
    try:
        _dispatch_callback(call, data, chat_id, msg_id, user_id)
    except Exception as e:
        logger.error(f"Callback error ({data}): {e}", exc_info=True)
        try:
            bot.answer_callback_query(call.id, f"Error: {str(e)[:50]}", show_alert=True)
        except:
            pass
    finally:
        try:
            bot.answer_callback_query(call.id)
        except:
            pass

def _dispatch_callback(call, data, chat_id, msg_id, user_id):
    if get_setting('maintenance') == '1' and not is_admin(user_id):
        if data not in ["check_sub", "close_menu"]:
            bot.answer_callback_query(call.id, "Bot is under maintenance.", show_alert=True)
            return

        else:
            bot.answer_callback_query(call.id, "❌ No admin configured.", show_alert=True)
        return

    if data == "close_menu":
        try:
            bot.delete_message(chat_id, msg_id)
        except:
            pass
        return

    if data == "refresh_leaderboard":
        show_leaderboard(chat_id)
        return
    if data == "refresh_stock":
        show_stock_info(chat_id)
        return
    if data == "refresh_traffic":
        show_traffic(chat_id)
        return

    if data == "2fa_generate":
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="close_menu", style="danger", icon="back"))
        bot.edit_message_text("━━━━━━━━━━━━━━━\n《 🔑 ENTER 2FA KEY 》\n━━━━━━━━━━━━━━━\n📝 SEND YOUR SECRET KEY\n\nEXAMPLE: <code>JBSWY3DPEHPK3PXP</code>",
                              chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        bot.register_next_step_handler_by_chat_id(chat_id, process_2fa_code)
        return

    if data.startswith("withdraw_method|"):
        method = data.split("|")[1]
        if method == "opay":
            bot.edit_message_text("━━━━━━━━━━━━━━━\n《 💳 OPAY WITHDRAWAL 》\n━━━━━━━━━━━━━━━\n<b>Send your 10-digit Opay phone number:</b>",
                                  chat_id, msg_id, parse_mode="HTML")
            bot.register_next_step_handler_by_chat_id(chat_id, process_opay_phone)
        elif method == "usdt":
            bot.edit_message_text("━━━━━━━━━━━━━━━\n《 💎 USDT BEP20 WITHDRAWAL 》\n━━━━━━━━━━━━━━━\n<b>Send your USDT BEP20 address (0x...):</b>",
                                  chat_id, msg_id, parse_mode="HTML")
            bot.register_next_step_handler_by_chat_id(chat_id, process_usdt_address)
        elif method == "upi":
            bot.edit_message_text("━━━━━━━━━━━━━━━\n《 🇮🇳 UPI WITHDRAWAL 》\n━━━━━━━━━━━━━━━\n<b>Send your UPI ID (e.g., user@upi):</b>",
                                  chat_id, msg_id, parse_mode="HTML")
            bot.register_next_step_handler_by_chat_id(chat_id, process_upi_id)
        elif method == "others":
            bot.edit_message_text("━━━━━━━━━━━━━━━\n《 🌍 OTHER COUNTRY WITHDRAWAL 》\n━━━━━━━━━━━━━━━\n<b>Send your country name or currency code (e.g., India, EUR):</b>",
                                  chat_id, msg_id, parse_mode="HTML")
            bot.register_next_step_handler_by_chat_id(chat_id, process_others_country)
        return

    if data.startswith("usr_app|"):
        app = data.split("|")[1]
        show_user_countries(chat_id, app, msg_id)
        return

    if data.startswith("usr_cnt|"):
        _, app, country_key = data.split("|")
        fetch_number_logic(chat_id, app, country_key, msg_id)
        return

    if data.startswith("toggle_cc|"):
        parts = data.split("|")
        _, app, country_key, number = parts
        new_state = toggle_remove_cc(user_id)
        if new_state:
            bot.answer_callback_query(call.id, "CC ON — prefix removed", show_alert=False)
        else:
            bot.answer_callback_query(call.id, "CC OFF — prefix restored", show_alert=False)
        _show_number_display(chat_id, msg_id, number, country_key, app)
        return

    if data.startswith("chg_local|"):
        _, app, country_key = data.split("|")
        fetch_number_logic(chat_id, app, country_key, msg_id)
        return

    if is_admin(user_id):
        if data.startswith("combo_app|"):
            combo_app_selection(call)
            return
        handle_admin_callback(call, data, chat_id, msg_id)
    else:
        if data.startswith("copy_"):
            otp = data.split("_", 1)[1]
            bot.answer_callback_query(call.id, f"✅ OTP: {otp}", show_alert=True)

def show_user_countries(chat_id, app_name, message_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT country_code, combo_index, numbers FROM combos")
    combos = c.fetchall()
    conn.close()
    countries = {}
    for cc, ci, nums_json in combos:
        nums = json.loads(nums_json)
        if nums:
            iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
            name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
            key = cc
            if key not in countries:
                countries[key] = {"name": name, "iso": iso, "count": 0}
            countries[key]["count"] += len(nums)
    if not countries:
        bot.edit_message_text("❌ No numbers available.", chat_id, message_id, parse_mode="HTML")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cc, info in countries.items():
        markup.add(ibtn(f"{info['name']} ({info['count']})",
                        callback_data=f"usr_cnt|{app_name}|{cc}", style="primary",
                        icon_id=flag_icon_id(info["iso"])))
    markup.add(ibtn("Back", callback_data="close_menu", style="danger", icon="back"))
    app_emoji = app_emoji_html(app_name)
    bot.edit_message_text(f"{app_emoji} <b>{app_name}</b>\n\n📍 <b>SELECT COUNTRY:</b>",
                          chat_id, message_id, parse_mode="HTML", reply_markup=markup)

def _strip_cc(number, country_key):
    """Strip the country code prefix from a number when CC mode is active."""
    cc_len = len(str(country_key))
    if len(str(number)) > cc_len:
        return str(number)[cc_len:]
    return str(number)

def _show_number_display(chat_id, message_id, number, country_key, app_name):
    """Display the assigned number with CC toggle and other buttons."""
    country_name = COUNTRY_CODES.get(country_key, (country_key, "Unknown"))[0]
    iso = COUNTRY_CODES.get(country_key, (country_key, "UN"))[1]
    flag = flag_emoji_html(iso)
    svc = app_emoji_html(app_name)

    remove_cc = get_remove_cc(chat_id)
    if remove_cc:
        display_number = _strip_cc(number, country_key)
        cc_btn_text = "🌍 CC ON"
    else:
        display_number = f"+{number}"
        cc_btn_text = "🌍 CC"

    msg_text = (
        f"📞 <b>Number:</b> <code>{display_number}</code>\n"
        f"{flag} <b>Country:</b> {country_name}\n"
        f"{svc} <b>Service:</b> {app_name}\n"
        f"⏳ <b>Status:</b> Waiting for SMS"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("View OTP", url="https://t.me/animatrixx_otp", style="primary", icon="eye"))
    markup.row(
        ibtn(cc_btn_text, callback_data=f"toggle_cc|{app_name}|{country_key}|{number}", style="success", icon="earth"),
        ibtn("Change Number", callback_data=f"chg_local|{app_name}|{country_key}", style="danger", icon="refresh"),
    )
    markup.row(ibtn("Back", callback_data="close_menu", style="primary", icon="back"))
    bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)

def fetch_number_logic(chat_id, app_name, country_key, message_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT numbers FROM combos WHERE country_code=? AND combo_index=1", (country_key,))
    row = c.fetchone()
    conn.close()
    if not row:
        bot.edit_message_text("❌ No numbers for this country.", chat_id, message_id, parse_mode="HTML")
        return
    numbers = json.loads(row[0])
    used = []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT assigned_number FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
    used = [r[0] for r in c.fetchall()]
    conn.close()
    available = [n for n in numbers if n not in used]
    if not available:
        bot.edit_message_text("❌ All numbers currently in use.", chat_id, message_id, parse_mode="HTML")
        return
    assigned = random.choice(available)
    # Release old number before assigning new one
    old_user = get_user(chat_id)
    if old_user and len(old_user) > 5 and old_user[5]:
        release_number(old_user[5])
    assign_number_to_user(chat_id, assigned)
    save_user(chat_id, country_code=country_key, assigned_number=assigned)

    _show_number_display(chat_id, message_id, assigned, country_key, app_name)

# ---- 2FA and withdrawal step handlers ----
def process_2fa_code(message):
    st = user_states.get(message.chat.id, {})
    try:
        import pyotp
    except ImportError:
        bot.send_message(message.chat.id, "❌ 2FA module not installed. Run: pip install pyotp", parse_mode="HTML")
        return
    secret_key = re.sub(r'[^A-Z2-7=]', '', message.text.upper())
    if len(secret_key) < 8:
        bot.send_message(message.chat.id, "❌ Invalid key. Send again or /cancel.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_2fa_code)
        return
    try:
        totp = pyotp.TOTP(secret_key)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)
        text = (f"━━━━━━━━━━━━━━━\n《 🔐 <b>2FA CODE</b> 》\n━━━━━━━━━━━━━━━\n"
                f"🔐 <b>CODE:</b> <code>{code}</code>\n━━━━━━━━━━━━━━━\n"
                f"⏰ EXPIRES IN: <b>{remaining}s</b>")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn(f"COPY: {code}", copy_text_str=code, style="success", icon="copy"))
        markup.add(ibtn("REFRESH", callback_data="2fa_generate", style="primary", icon="refresh"))
        markup.add(ibtn("BACK", callback_data="close_menu", style="danger", icon="back"))
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}", parse_mode="HTML")

def process_opay_phone(message):
    st = user_states.get(message.chat.id, {})
    phone = message.text.strip()
    if not re.match(r'^[789]\d{9}$', phone):
        bot.reply_to(message, "❌ Invalid phone. Must be 10 digits starting with 7,8,9.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_opay_phone)
        return
    set_state(message.chat.id, {"withdraw_phone": phone})
    bot.reply_to(message, "📝 Send your full name as registered on Opay:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_opay_name)

def process_opay_name(message):
    st = user_states.get(message.chat.id, {})
    name = message.text.strip()
    if len(name) < 2:
        bot.reply_to(message, "❌ Invalid name.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_opay_name)
        return
    state = user_states.get(message.chat.id, {})
    state["withdraw_name"] = name
    user_states[message.chat.id] = state
    bot.reply_to(message, "💰 Send the amount in USD (e.g., 10.00):", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_opay_amount)

def check_withdrawal_amount(user_id, amount):
    user = get_user(user_id)
    balance = user[10] if user and len(user) > 10 else 0.0
    if amount > balance:
        return f"❌ Insufficient balance. You have ${balance}."
    if amount < MIN_WITHDRAWAL:
        return f"❌ Minimum withdrawal is ${MIN_WITHDRAWAL:.2f}."
    if amount > MAX_WITHDRAWAL:
        return f"❌ Maximum withdrawal is ${MAX_WITHDRAWAL:.2f}."
    return None

def process_opay_amount(message):
    st = user_states.get(message.chat.id, {})
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Invalid amount.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_opay_amount)
        return
    user_id = message.chat.id
    error = check_withdrawal_amount(user_id, amount)
    if error:
        bot.reply_to(message, error, parse_mode="HTML")
        return
    details = user_states.get(user_id, {})
    req_id = create_withdrawal_request(user_id, amount, "opay", {
        "phone": details.get("withdraw_phone", ""),
        "full_name": details.get("withdraw_name", "")
    })
    bot.reply_to(message, f"✅ Withdrawal request of ${amount:.2f} via Opay submitted for approval.", parse_mode="HTML")
    for admin in get_all_admins():
        try:
            bot.send_message(admin, f"{pe('card', '💳')} <b>New Withdrawal</b>\nUser: <code>{user_id}</code>\nAmount: ${amount:.2f}\nMethod: Opay\nPhone: {details.get('withdraw_phone', '')}", parse_mode="HTML")
        except:
            pass
    user_states.pop(user_id, None)

def process_usdt_address(message):
    st = user_states.get(message.chat.id, {})
    address = message.text.strip()
    if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
        bot.reply_to(message, "❌ Invalid BEP20 address.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_usdt_address)
        return
    set_state(message.chat.id, {"withdraw_address": address})
    bot.reply_to(message, "💰 Send the amount in USD:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_usdt_amount)

def process_usdt_amount(message):
    st = user_states.get(message.chat.id, {})
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Invalid amount.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_usdt_amount)
        return
    user_id = message.chat.id
    error = check_withdrawal_amount(user_id, amount)
    if error:
        bot.reply_to(message, error, parse_mode="HTML")
        return
    address = user_states.get(user_id, {}).get("withdraw_address", "")
    req_id = create_withdrawal_request(user_id, amount, "usdt", {"address": address})
    bot.reply_to(message, f"✅ Withdrawal request of ${amount:.2f} via USDT submitted.", parse_mode="HTML")
    for admin in get_all_admins():
        try:
            bot.send_message(admin, f"{pe('card', '💳')} <b>New Withdrawal</b>\nUser: <code>{user_id}</code>\nAmount: ${amount:.2f}\nMethod: USDT\nAddress: {address}", parse_mode="HTML")
        except:
            pass
    user_states.pop(user_id, None)

def process_upi_id(message):
    st = user_states.get(message.chat.id, {})
    upi = message.text.strip()
    if '@' not in upi:
        bot.reply_to(message, "❌ Invalid UPI ID.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_upi_id)
        return
    set_state(message.chat.id, {"withdraw_upi": upi})
    bot.reply_to(message, "📝 Send your full name:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_upi_name)

def process_upi_name(message):
    st = user_states.get(message.chat.id, {})
    name = message.text.strip()
    if len(name) < 2:
        bot.reply_to(message, "❌ Invalid name.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_upi_name)
        return
    state = user_states.get(message.chat.id, {})
    state["withdraw_name"] = name
    user_states[message.chat.id] = state
    bot.reply_to(message, "💰 Send the amount in USD:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_upi_amount)

def process_upi_amount(message):
    st = user_states.get(message.chat.id, {})
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Invalid amount.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_upi_amount)
        return
    user_id = message.chat.id
    error = check_withdrawal_amount(user_id, amount)
    if error:
        bot.reply_to(message, error, parse_mode="HTML")
        return
    details = user_states.get(user_id, {})
    req_id = create_withdrawal_request(user_id, amount, "upi", {
        "upi_id": details.get("withdraw_upi", ""),
        "full_name": details.get("withdraw_name", "")
    })
    bot.reply_to(message, f"✅ Withdrawal request of ${amount:.2f} via UPI submitted.", parse_mode="HTML")
    for admin in get_all_admins():
        try:
            bot.send_message(admin, f"{pe('card', '💳')} <b>New Withdrawal</b>\nUser: <code>{user_id}</code>\nAmount: ${amount:.2f}\nMethod: UPI\nUPI: {details.get('withdraw_upi', '')}", parse_mode="HTML")
        except:
            pass
    user_states.pop(user_id, None)

def process_others_country(message):
    st = user_states.get(message.chat.id, {})
    raw = message.text.strip()
    currency = raw.upper() if re.match(r'^[A-Z]{3}$', raw) else None
    if not currency:
        country_map = {"india": "INR", "united states": "USD", "united kingdom": "GBP", "nigeria": "NGN", "europe": "EUR"}
        currency = country_map.get(raw.lower(), "USD")
    set_state(message.chat.id, {"others_currency": currency})
    bot.reply_to(message, "🌍 Currency: {currency}\n\n📝 Send the account holder's full name:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_holder)

def process_others_holder(message):
    st = user_states.get(message.chat.id, {})
    name = message.text.strip()
    if len(name) < 2:
        bot.reply_to(message, "❌ Invalid name.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_holder)
        return
    state = user_states.get(message.chat.id, {})
    state["others_holder"] = name
    user_states[message.chat.id] = state
    bot.reply_to(message, "🔢 Send the account number:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_account)

def process_others_account(message):
    st = user_states.get(message.chat.id, {})
    acc = message.text.strip()
    if len(acc) < 4:
        bot.reply_to(message, "❌ Account number too short.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_account)
        return
    state = user_states.get(message.chat.id, {})
    state["others_account"] = acc
    user_states[message.chat.id] = state
    bot.reply_to(message, "🏦 Send the bank name (or /skip):", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_bank)

def process_others_bank(message):
    st = user_states.get(message.chat.id, {})
    bank = "Not provided" if message.text.lower() == '/skip' else message.text.strip()
    state = user_states.get(message.chat.id, {})
    state["others_bank"] = bank
    user_states[message.chat.id] = state
    bot.reply_to(message, "💰 Send the amount in USD:", parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_amount)

def process_others_amount(message):
    st = user_states.get(message.chat.id, {})
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Invalid amount.", parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_others_amount)
        return
    user_id = message.chat.id
    error = check_withdrawal_amount(user_id, amount)
    if error:
        bot.reply_to(message, error, parse_mode="HTML")
        return
    details = user_states.get(user_id, {})
    req_id = create_withdrawal_request(user_id, amount, "others", {
        "currency": details.get("others_currency", "USD"),
        "account_holder": details.get("others_holder", ""),
        "account_number": details.get("others_account", ""),
        "bank_name": details.get("others_bank", "")
    })
    bot.reply_to(message, f"✅ Withdrawal request of ${amount:.2f} via Other submitted.", parse_mode="HTML")
    for admin in get_all_admins():
        try:
            bot.send_message(admin, f"{pe('card', '💳')} <b>New Withdrawal</b>\nUser: <code>{user_id}</code>\nAmount: ${amount:.2f}\nMethod: Others\nDetails: {details}", parse_mode="HTML")
        except:
            pass
    user_states.pop(user_id, None)

# =========================== ADMIN PANEL ===========================
def show_admin_panel(chat_id, message_id=None):
    if not is_admin(chat_id):
        return
    data = load_data()
    watermark = data.get("watermark", "MATRIXX PREMIUM")
    panels_count = len(get_all_sms_panels())
    admins_count = len(get_all_admins())
    text = (f"┌─────────────────────┐\n"
            f"│  {pe('star')} <b>ADMIN PANEL</b>  │\n"
            f"└─────────────────────┘\n\n"
            f"{pe('people', '👥')} Users: <code>{len(get_all_users())}</code>\n"
            f"{pe('archive', '📦')} Combos: <code>{len(get_all_combos())}</code>\n"
            f"{pe('phone', '📱')} OTPs Today: <code>{get_dashboard_stats()['otps_today']}</code>\n"
            f"{pe('link', '🔗')} SMS Panels: <code>{panels_count}</code>\n"
            f"{pe('admin', '🛡️')} Admins: <code>{admins_count}</code>\n"
            f"{pe('hourglass', '⏱️')} Uptime: <code>{get_uptime()}</code>\n"
            f"{pe('star', '⭐')} Watermark: <code>{watermark}</code>\n"
            f"━━━━━━━━━━━━━━━")
    markup = get_admin_menu()
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def get_admin_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        ibtn(f"{pe('stats', '📊')} Dashboard", callback_data="admin_dashboard", style="success", icon="stats"),
        ibtn(f"{pe('list', '📋')} Manage Combos", callback_data="admin_combos", style="primary", icon="list"),
        ibtn(f"{pe('phone', '📱')} Manage Numbers", callback_data="admin_numbers", style="primary", icon="phone"),
        ibtn(f"{pe('announcement', '📢')} OTP Groups", callback_data="admin_otp_groups", style="primary", icon="announcement"),
        ibtn(f"{pe('people', '👥')} Users", callback_data="admin_users", style="primary", icon="people"),
        ibtn(f"{pe('card', '💳')} Withdrawals", callback_data="admin_withdrawals", style="primary", icon="card"),
        ibtn(f"{pe('link', '🔗')} SMS Panels", callback_data="admin_sms_panels", style="primary", icon="link"),
        ibtn(f"{pe('settings', '⚙️')} Settings", callback_data="admin_settings", style="danger", icon="settings"),
        ibtn(f"{pe('admin', '🛡️')} Admins", callback_data="admin_manage_admins", style="primary", icon="admin"),
        ibtn(f"{pe('back', '⬅️')} Leave", callback_data="close_menu", style="danger", icon="back")
    ]
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons):
            markup.row(buttons[i], buttons[i+1])
        else:
            markup.row(buttons[i])
    return markup

# ---- Admin callbacks ----
def handle_admin_callback(call, data, chat_id, msg_id):
    if data == "admin_dashboard":
        stats = get_dashboard_stats()
        text = (f"{pe('stats', '📊')} <b>DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
                f"{pe('people', '👥')} Active (24h): <b>{stats['active_users_24h']}</b>\n"
                f"{pe('people', '👥')} Total Users: <b>{stats['total_users']}</b>\n"
                f"{pe('phone', '📱')} OTPs Today: <b>{stats['otps_today']}</b>\n"
                f"{pe('phone', '📱')} Total OTPs: <b>{stats['total_otps']}</b>\n"
                f"{pe('archive', '📦')} Combos: <b>{stats['total_combos']}</b>\n"
                f"{pe('hourglass', '⏱️')} Uptime: {get_uptime()}")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Refresh", callback_data="admin_dashboard", style="success", icon="refresh"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_combos":
        combos = get_all_combos()
        markup = types.InlineKeyboardMarkup(row_width=1)
        for cc, ci, app_name in combos:
            iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
            name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
            app_icon = app_emoji_html(app_name)
            markup.add(ibtn(f"{name} ({app_icon} {app_name})", callback_data=f"admin_view_combo|{cc}|{ci}", style="primary", icon_id=flag_icon_id(iso)))
        markup.add(ibtn("Add Combo (TXT)", callback_data="admin_add_combo_txt", style="success", icon="plus"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text("📦 <b>Combo Management</b>", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_add_combo_txt":
        set_state(chat_id, "waiting_combo_file")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_combos", style="danger", icon="back"))
        bot.edit_message_text("📤 <b>Add Combo</b>\n\nSend a .txt file with numbers (one per line).", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data.startswith("admin_view_combo|"):
        _, cc, ci = data.split("|")
        ci = int(ci)
        nums = get_combo(cc, ci)
        iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
        flag_html = flag_emoji_html(iso)
        name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT app_name FROM combos WHERE country_code=? AND combo_index=?", (cc, ci))
        row = c.fetchone()
        app_name = row[0] if row else "WhatsApp"
        conn.close()
        app_icon = app_emoji_html(app_name)
        text = f"📞 <b>{flag_html} {name} ({app_icon} {app_name})</b>\nTotal: {len(nums)}\n\n"
        for i, n in enumerate(nums[:20], 1):
            text += f"{i}. {n}\n"
        if len(nums) > 20:
            text += f"... and {len(nums)-20} more"
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Delete Combo", callback_data=f"admin_del_combo|{cc}|{ci}", style="danger", icon="trash"))
        markup.add(ibtn("Back", callback_data="admin_combos", style="primary", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data.startswith("admin_del_combo|"):
        _, cc, ci = data.split("|")
        ci = int(ci)
        delete_combo(cc, ci)
        bot.answer_callback_query(call.id, "✅ Combo deleted!", show_alert=True)
        handle_admin_callback(call, "admin_combos", chat_id, msg_id)
        return

    if data == "admin_numbers":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Add Numbers Manually", callback_data="admin_add_nums", style="success", icon="plus"))
        markup.add(ibtn("View All Numbers", callback_data="admin_view_all_nums", style="primary", icon="eye"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text("📞 <b>Manage Numbers</b>", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_add_nums":
        set_state(chat_id, "add_nums_country")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_numbers", style="danger", icon="back"))
        bot.edit_message_text("📞 <b>Add Numbers Manually</b>\n\nSend the country code (e.g., 1, 44):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_view_all_nums":
        combos = get_all_combos()
        if not combos:
            bot.answer_callback_query(call.id, "No combos.", show_alert=True)
            return
        text = "📞 <b>All Numbers</b>\n\n"
        total = 0
        for cc, ci, app_name in combos:
            nums = get_combo(cc, ci)
            total += len(nums)
            iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
            flag_html = flag_emoji_html(iso)
            name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
            app_icon = app_emoji_html(app_name)
            text += f"{flag_html} {name} ({app_icon} {app_name}) (Combo {ci}): {len(nums)}\n"
        text += f"\n📊 Total: {total}"
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Back", callback_data="admin_numbers", style="primary", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_otp_groups":
        groups = json.loads(get_setting('otp_groups') or '[]')
        text = "📢 <b>OTP Groups</b>\n\n"
        if not groups:
            text += "No groups configured."
        else:
            for i, g in enumerate(groups, 1):
                text += f"{i}. <code>{g}</code>\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Add Group", callback_data="admin_add_otp_group", style="success", icon="plus"))
        markup.add(ibtn("Remove Group", callback_data="admin_remove_otp_group", style="danger", icon="minus"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="primary", icon="back"))
        try:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"OTP groups edit error: {e}")
        return

    if data == "admin_add_otp_group":
        set_state(chat_id, "add_otp_group")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_otp_groups", style="danger", icon="back"))
        bot.edit_message_text("Send the group chat ID (e.g., -1001234567890):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_remove_otp_group":
        groups = json.loads(get_setting('otp_groups') or '[]')
        if not groups:
            bot.answer_callback_query(call.id, "No groups.", show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for g in groups:
            markup.add(ibtn(str(g), callback_data=f"admin_remove_otp_group_do|{g}", style="danger", icon="cross"))
        markup.add(ibtn("Back", callback_data="admin_otp_groups", style="primary", icon="back"))
        bot.edit_message_text("Select group to remove:", chat_id, msg_id, reply_markup=markup)
        return

    if data.startswith("admin_remove_otp_group_do|"):
        g = data.split("|", 1)[1]
        groups = json.loads(get_setting('otp_groups') or '[]')
        groups = [x for x in groups if str(x) != str(g)]
        set_setting('otp_groups', json.dumps(groups))
        bot.answer_callback_query(call.id, "✅ Removed.", show_alert=True)
        handle_admin_callback(call, "admin_otp_groups", chat_id, msg_id)
        return

    if data == "admin_users":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("List Users", callback_data="admin_list_users", style="primary", icon="people"))
        markup.add(ibtn("Ban/Unban", callback_data="admin_ban_unban", style="danger", icon="ban"))
        markup.add(ibtn("Manage Balance", callback_data="admin_manage_balance", style="success", icon="wallet"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="primary", icon="back"))
        bot.edit_message_text("👥 <b>User Management</b>", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_list_users":
        users = get_all_users()
        text = "👥 <b>Users</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
        if not users:
            text += "No users."
        else:
            for i, uid in enumerate(users[:20], 1):
                try:
                    u = bot.get_chat(uid)
                    name = u.first_name or "User"
                except:
                    name = "User"
                text += f"{i}. <code>{uid}</code> — {name}\n"
            if len(users) > 20:
                text += f"... and {len(users)-20} more"
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Back", callback_data="admin_users", style="primary", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_ban_unban":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Ban User", callback_data="admin_ban_user", style="danger", icon="ban"))
        markup.add(ibtn("Unban User", callback_data="admin_unban_user", style="success", icon="checkmark"))
        markup.add(ibtn("Back", callback_data="admin_users", style="primary", icon="back"))
        bot.edit_message_text("🚫 <b>Ban / Unban</b>", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_ban_user":
        set_state(chat_id, "ban_user")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_ban_unban", style="danger", icon="back"))
        bot.edit_message_text("Send the user ID to ban:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_unban_user":
        set_state(chat_id, "unban_user")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_ban_unban", style="danger", icon="back"))
        bot.edit_message_text("Send the user ID to unban:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_manage_balance":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Add Balance", callback_data="admin_add_balance", style="success", icon="plus"))
        markup.add(ibtn("Deduct Balance", callback_data="admin_deduct_balance", style="danger", icon="minus"))
        markup.add(ibtn("Back", callback_data="admin_users", style="primary", icon="back"))
        bot.edit_message_text("💰 <b>Manage Balance</b>", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_add_balance":
        set_state(chat_id, "add_balance")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_manage_balance", style="danger", icon="back"))
        bot.edit_message_text("Send <b>user_id</b> and <b>amount</b> (space separated):\nExample: 123456 10", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_deduct_balance":
        set_state(chat_id, "deduct_balance")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_manage_balance", style="danger", icon="back"))
        bot.edit_message_text("Send <b>user_id</b> and <b>amount</b> to deduct:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_withdrawals":
        pending = get_pending_withdrawals()
        text = "💳 <b>Pending Withdrawals</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
        if not pending:
            text += "No pending requests."
        else:
            for w in pending:
                req_id, uid, amount, method, ts = w
                text += f"ID: {req_id[:6]}\nUser: <code>{uid}</code>\n${amount:.2f} | {method}\n{ts}\n───────────\n"
            text += f"\nTotal: {len(pending)}"
        markup = types.InlineKeyboardMarkup(row_width=2)
        if pending:
            markup.add(ibtn("Approve", callback_data="admin_approve_withdrawal", style="success", icon="checkmark"))
            markup.add(ibtn("Reject", callback_data="admin_reject_withdrawal", style="danger", icon="cross"))
        markup.add(ibtn("Refresh", callback_data="admin_withdrawals", style="primary", icon="refresh"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_approve_withdrawal":
        pending = get_pending_withdrawals()
        if not pending:
            bot.answer_callback_query(call.id, "No pending.", show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for req_id, uid, amount, method, _ in pending:
            markup.add(ibtn(f"{uid} - ${amount:.2f} ({method})", callback_data=f"admin_approve_wd|{req_id}", style="success", icon="checkmark"))
        markup.add(ibtn("Back", callback_data="admin_withdrawals", style="primary", icon="back"))
        bot.edit_message_text("Select withdrawal to approve:", chat_id, msg_id, reply_markup=markup)
        return

    if data.startswith("admin_approve_wd|"):
        req_id = data.split("|")[1]
        success, result = approve_withdrawal(req_id, chat_id, "Approved")
        if success:
            bot.answer_callback_query(call.id, f"✅ Approved. New balance: ${result}", show_alert=True)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, amount FROM withdrawal_requests WHERE id=?", (req_id,))
            row = c.fetchone()
            conn.close()
            if row:
                try:
                    bot.send_message(row[0], f"{pe('checkmark', '✅')} <b>Withdrawal Approved</b>\n${row[1]:.2f} processed.", parse_mode="HTML")
                except:
                    pass
        else:
            bot.answer_callback_query(call.id, f"❌ {result}", show_alert=True)
        handle_admin_callback(call, "admin_withdrawals", chat_id, msg_id)
        return

    if data == "admin_reject_withdrawal":
        pending = get_pending_withdrawals()
        if not pending:
            bot.answer_callback_query(call.id, "No pending.", show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for req_id, uid, amount, method, _ in pending:
            markup.add(ibtn(f"{uid} - ${amount:.2f} ({method})", callback_data=f"admin_reject_wd|{req_id}", style="danger", icon="cross"))
        markup.add(ibtn("Back", callback_data="admin_withdrawals", style="primary", icon="back"))
        bot.edit_message_text("Select withdrawal to reject:", chat_id, msg_id, reply_markup=markup)
        return

    if data.startswith("admin_reject_wd|"):
        req_id = data.split("|")[1]
        set_state(chat_id, {"reject_reason": req_id})
        bot.edit_message_text("📝 Enter reason for rejection (or /skip):", chat_id, msg_id, parse_mode="HTML")
        bot.register_next_step_handler_by_chat_id(chat_id, admin_reject_reason_step)
        return


    if data == "admin_choice_sms":
        enabled = get_setting('choice_enabled') == '1'
        panel = get_setting('choice_panel_url') or 'Not set'
        user = get_setting('choice_username') or 'Not set'
        status = "🟢 Enabled" if enabled else "🔴 Disabled"
        text = (f"📡 <b>Choice SMS Forwarder</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Status: {status}\n"
                f"Panel: <code>{panel}</code>\n"
                f"Username: <code>{user}</code>\n"
                f"Password: <code>{'••••••' if get_setting('choice_password') else 'Not set'}</code>\n"
                f"━━━━━━━━━━━━━━━")
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Toggle On/Off", callback_data="admin_choice_toggle", style="success" if not enabled else "danger", icon="toggle"))
        markup.add(ibtn("Set Panel URL", callback_data="admin_choice_panel", style="primary", icon="link"))
        markup.add(ibtn("Set Username", callback_data="admin_choice_user", style="primary", icon="profile"))
        markup.add(ibtn("Set Password", callback_data="admin_choice_pass", style="primary", icon="lock"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_choice_toggle":
        enabled = get_setting('choice_enabled') == '1'
        set_setting('choice_enabled', '0' if enabled else '1')
        bot.answer_callback_query(call.id, f"Choice SMS {'ENABLED' if not enabled else 'DISABLED'}", show_alert=True)
        handle_admin_callback(call, "admin_choice_sms", chat_id, msg_id)
        return

    if data == "admin_choice_panel":
        set_state(chat_id, "choice_panel_url")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_choice_sms", style="danger", icon="back"))
        bot.edit_message_text("Send the panel URL (e.g., http://51.77.52.79/ints):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_choice_user":
        set_state(chat_id, "choice_username")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_choice_sms", style="danger", icon="back"))
        bot.edit_message_text("Send the panel username:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_choice_pass":
        set_state(chat_id, "choice_password")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_choice_sms", style="danger", icon="back"))
        bot.edit_message_text("Send the panel password:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_settings":
        rt_otp = get_setting('realtime_otp_admin') == '1'
        rt_label = "ON" if rt_otp else "OFF"
        rt_style = "success" if rt_otp else "danger"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Cooldown", callback_data="admin_set_cooldown", style="primary", icon="wrench"))
        markup.add(ibtn("Num per Request", callback_data="admin_set_num_req", style="primary", icon="phone"))
        markup.add(ibtn("Support Link", callback_data="admin_set_support", style="primary", icon="support"))
        markup.add(ibtn("Watermark", callback_data="admin_set_watermark", style="primary", icon="star"))
        markup.add(ibtn("Bot Link", callback_data="admin_set_botlink", style="primary", icon="link"))
        markup.add(ibtn("Force Subscribe", callback_data="admin_force_sub", style="primary", icon="lock"))
        markup.add(ibtn("Broadcast", callback_data="admin_broadcast", style="success", icon="announcement"))
        markup.add(ibtn(f"Real-time OTP [{rt_label}]", callback_data="admin_toggle_rt_otp", style=rt_style, icon="eye"))
        markup.add(ibtn("Maintenance", callback_data="admin_toggle_maintenance", style="danger", icon="wrench"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="primary", icon="back"))
        bot.edit_message_text("⚙️ <b>Settings</b>", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_set_botlink":
        set_state(chat_id, "set_botlink")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_settings", style="danger", icon="back"))
        bot.edit_message_text("Send the bot link (e.g., https://t.me/YourBot):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_set_cooldown":
        set_state(chat_id, "set_cooldown")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_settings", style="danger", icon="back"))
        bot.edit_message_text("Send new cooldown (seconds):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_set_num_req":
        set_state(chat_id, "set_num_req")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_settings", style="danger", icon="back"))
        bot.edit_message_text("Send new number per request:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_set_support":
        set_state(chat_id, "set_support")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_settings", style="danger", icon="back"))
        bot.edit_message_text("Send new support link:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_set_watermark":
        set_state(chat_id, "set_watermark")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_settings", style="danger", icon="back"))
        bot.edit_message_text("Send new watermark text:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_force_sub":
        enabled = get_setting('force_sub_enabled') == '1'
        channels = get_force_sub_channels(enabled_only=False)
        status_icon = f"{pe('checkmark', '✅')} Enabled" if enabled else f"{pe('cross', '❌')} Disabled"
        text = "🔗 <b>Force Subscribe</b>\n"
        text += f"Status: {status_icon}\n\n"
        if channels:
            for cid, url, desc in channels:
                text += f"• {desc or url} (ID:{cid})\n"
        else:
            text += "No channels."
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(ibtn("Toggle", callback_data="admin_toggle_force", style="success" if not enabled else "danger", icon="toggle"))
        markup.add(ibtn("Add Channel", callback_data="admin_add_force_channel", style="success", icon="plus"))
        markup.add(ibtn("Remove Channel", callback_data="admin_remove_force_channel", style="danger", icon="trash"))
        markup.add(ibtn("Back", callback_data="admin_settings", style="primary", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_toggle_force":
        enabled = get_setting('force_sub_enabled') == '1'
        set_setting('force_sub_enabled', '0' if enabled else '1')
        bot.answer_callback_query(call.id, f"Force Subscribe {'ENABLED' if not enabled else 'DISABLED'}", show_alert=True)
        handle_admin_callback(call, "admin_force_sub", chat_id, msg_id)
        return

    if data == "admin_add_force_channel":
        set_state(chat_id, "add_force_channel")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_force_sub", style="danger", icon="back"))
        bot.edit_message_text("Send channel URL (e.g., https://t.me/yourchannel or @yourchannel):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_remove_force_channel":
        channels = get_force_sub_channels(enabled_only=False)
        if not channels:
            bot.answer_callback_query(call.id, "No channels.", show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for cid, url, desc in channels:
            markup.add(ibtn(desc or url, callback_data=f"admin_del_force_ch|{cid}", style="danger", icon="cross"))
        markup.add(ibtn("Back", callback_data="admin_force_sub", style="primary", icon="back"))
        bot.edit_message_text("Select channel to remove:", chat_id, msg_id, reply_markup=markup)
        return

    if data.startswith("admin_del_force_ch|"):
        cid = int(data.split("|")[1])
        delete_force_sub_channel(cid)
        bot.answer_callback_query(call.id, "✅ Removed.", show_alert=True)
        handle_admin_callback(call, "admin_force_sub", chat_id, msg_id)
        return

    if data == "admin_toggle_maintenance":
        current = get_setting('maintenance') == '1'
        set_setting('maintenance', '0' if current else '1')
        bot.answer_callback_query(call.id, f"Maintenance {'ON' if not current else 'OFF'}", show_alert=True)
        handle_admin_callback(call, "admin_settings", chat_id, msg_id)
        return

    # === BROADCAST ===
    if data == "admin_broadcast":
        set_state(chat_id, "admin_broadcast_msg")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("Cancel", callback_data="admin_settings", style="danger", icon="back"))
        bot.edit_message_text("📢 <b>Broadcast Message</b>\n\nSend the message you want to broadcast to all users:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    # === REAL-TIME OTP TOGGLE ===
    if data == "admin_toggle_rt_otp":
        current = get_setting('realtime_otp_admin') == '1'
        set_setting('realtime_otp_admin', '0' if current else '1')
        bot.answer_callback_query(call.id, f"Real-time OTP {'ENABLED' if not current else 'DISABLED'}", show_alert=True)
        handle_admin_callback(call, "admin_settings", chat_id, msg_id)
        return

    # === SMS PANELS ===
    if data == "admin_sms_panels":
        panels = get_all_sms_panels()
        markup = types.InlineKeyboardMarkup(row_width=1)
        for pid, name, url, login_type, username, enabled in panels:
            status_icon = pe("checkmark") if enabled else pe("cross")
            markup.add(ibtn(status_icon + " " + name + " (" + login_type + ")", callback_data="admin_view_panel|" + str(pid), style="primary", icon="link"))
        markup.add(ibtn(pe("plus", "+") + " Add SMS Panel", callback_data="admin_add_sms_panel", style="success", icon="plus"))
        markup.add(ibtn(pe("back", "⬅") + " Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text(pe("link", "🔗") + " <b>SMS Panels</b>\n\nManage your SMS panel connections. Each panel auto-connects to SMSCDRStats for live OTP monitoring.", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_add_sms_panel":
        set_state(chat_id, "add_sms_panel_name")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn(pe("back", "⬅") + " Cancel", callback_data="admin_sms_panels", style="danger", icon="back"))
        bot.edit_message_text(pe("plus", "➕") + " <b>Add SMS Panel</b>\n\nSend the panel name (e.g., My Choice SMS):", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data.startswith("admin_view_panel|"):
        pid = int(data.split("|")[1])
        panel = get_sms_panel(pid)
        if not panel:
            bot.answer_callback_query(call.id, "Panel not found.", show_alert=True)
            return
        _, name, url, login_type, username, password, enabled, created = panel
        status_str = pe("checkmark", "✅") + " Enabled" if enabled else pe("cross", "❌") + " Disabled"
        text = (
            pe("link", "🔗") + " <b>SMS Panel</b>\n"
            "━━━━━━━━━━━━━━━\n"
            + pe("info_bw", "ℹ") + " <b>Name:</b> " + name + "\n"
            + pe("link", "🔗") + " <b>URL:</b> <code>" + url + "</code>\n"
            + pe("profile", "👤") + " <b>Type:</b> " + login_type.upper() + "\n"
            + pe("key", "🔑") + " <b>User:</b> <code>" + username + "</code>\n"
            + pe("checkmark", "✅") + " <b>Status:</b> " + status_str + "\n"
            + pe("calendar", "📅") + " <b>Added:</b> " + str(created) + "\n"
            "━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        toggle_label = pe("toggle", "🔘") + " Toggle On/Off"
        markup.add(ibtn(toggle_label, callback_data="admin_toggle_panel|" + str(pid), style="success" if not enabled else "danger", icon="toggle"))
        markup.add(ibtn(pe("trash", "🗑") + " Delete", callback_data="admin_del_panel|" + str(pid), style="danger", icon="trash"))
        markup.add(ibtn(pe("refresh", "🔄") + " Test Connection", callback_data="admin_test_panel|" + str(pid), style="primary", icon="refresh"))
        markup.add(ibtn(pe("back", "⬅") + " Back", callback_data="admin_sms_panels", style="primary", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data.startswith("admin_toggle_panel|"):
        pid = int(data.split("|")[1])
        toggle_sms_panel(pid)
        bot.answer_callback_query(call.id, "Toggled!", show_alert=True)
        handle_admin_callback(call, "admin_view_panel|" + str(pid), chat_id, msg_id)
        return

    if data.startswith("admin_del_panel|"):
        pid = int(data.split("|")[1])
        delete_sms_panel(pid)
        bot.answer_callback_query(call.id, "Deleted!", show_alert=True)
        handle_admin_callback(call, "admin_sms_panels", chat_id, msg_id)
        return

    if data.startswith("admin_test_panel|"):
        pid = int(data.split("|")[1])
        panel = get_sms_panel(pid)
        if not panel:
            bot.answer_callback_query(call.id, "Panel not found.", show_alert=True)
            return
        _, name, url, login_type, username, password, enabled, _ = panel
        bot.answer_callback_query(call.id, "Testing connection...", show_alert=False)
        try:
            import requests as _req
            sess = _req.Session()
            sess.verify = False
            login_url = url.rstrip("/") + "/login"
            resp = sess.get(login_url, timeout=15)
            nums = re.findall(r"(\d+)\s*\+\s*(\d+)", resp.text)
            data_dict = {"username": username, "password": password}
            if nums:
                data_dict["capt"] = str(int(nums[0][0]) + int(nums[0][1]))
            resp2 = sess.post(url.rstrip("/") + "/signin", data=data_dict, timeout=15, allow_redirects=True)
            if "signin" not in resp2.url.lower() and "login" not in resp2.url.lower():
                stats_resp = sess.get(url.rstrip("/") + "/client/SMSCDRStats", timeout=15)
                sk_match = re.search(r"sesskey=([a-f0-9]{32})", stats_resp.text)
                sesskey = sk_match.group(1) if sk_match else "N/A"
                bot.answer_callback_query(call.id, "Connected! Sesskey: " + sesskey[:8] + "...", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "Login failed - check credentials.", show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, "Error: " + str(e)[:80], show_alert=True)
        return

    # === ADMIN MANAGER ===
    if data == "admin_manage_admins":
        admins = get_all_admins()
        markup = types.InlineKeyboardMarkup(row_width=1)
        for aid in admins:
            user = get_user(aid)
            name = user[2] if user and user[2] else ("@" + user[1] if user and user[1] else str(aid))
            markup.add(ibtn(pe("admin", "🛡") + " " + name + " (" + str(aid) + ")", callback_data="admin_view_admin|" + str(aid), style="primary", icon="admin"))
        markup.add(ibtn(pe("plus", "+") + " Add Admin", callback_data="admin_add_admin", style="success", icon="plus"))
        markup.add(ibtn(pe("back", "⬅") + " Back", callback_data="admin_panel", style="danger", icon="back"))
        bot.edit_message_text(pe("admin", "🛡") + " <b>Admin Management</b>\n\nTotal admins: " + str(len(admins)), chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data == "admin_add_admin":
        set_state(chat_id, "add_new_admin")
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn(pe("back", "⬅") + " Cancel", callback_data="admin_manage_admins", style="danger", icon="back"))
        bot.edit_message_text(pe("plus", "➕") + " <b>Add Admin</b>\n\nSend the user ID to make them an admin:", chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data.startswith("admin_view_admin|"):
        aid = int(data.split("|")[1])
        user = get_user(aid)
        name = user[2] if user and user[2] else ("@" + user[1] if user and user[1] else str(aid))
        text = (
            pe("admin", "🛡") + " <b>Admin Info</b>\n"
            "━━━━━━━━━━━━━━━\n"
            + pe("info_bw", "ℹ") + " <b>Name:</b> " + name + "\n"
            + pe("phone", "📞") + " <b>ID:</b> <code>" + str(aid) + "</code>\n"
            "━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup()
        if aid != ADMIN_IDS[0]:
            markup.add(ibtn(pe("cross", "❌") + " Remove Admin", callback_data="admin_remove_admin|" + str(aid), style="danger", icon="cross"))
        markup.add(ibtn(pe("back", "⬅") + " Back", callback_data="admin_manage_admins", style="primary", icon="back"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        return

    if data.startswith("admin_remove_admin|"):
        aid = int(data.split("|")[1])
        if aid == ADMIN_IDS[0]:
            bot.answer_callback_query(call.id, "Cannot remove the main admin!", show_alert=True)
            return
        remove_admin(aid)
        bot.answer_callback_query(call.id, "Admin removed!", show_alert=True)
        handle_admin_callback(call, "admin_manage_admins", chat_id, msg_id)
        return

    if data == "admin_panel":
        show_admin_panel(chat_id, msg_id)
        return

    # Handle copy OTP buttons from OTP groups
    if data.startswith("copy_"):
        otp_text = data[5:]  # remove "copy_" prefix
        try:
            bot.answer_callback_query(call.id, f"Copied: {otp_text}", show_alert=True)
            bot.send_message(call.from_user.id, f"<code>{otp_text}</code>", parse_mode="HTML")
        except:
            bot.answer_callback_query(call.id, f"OTP: {otp_text}", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Unknown action.", show_alert=True)

# ---- Admin step handlers ----
@bot.message_handler(func=lambda msg: get_state(msg) == "waiting_combo_file" and is_admin(msg.from_user.id), content_types=['document'])
def handle_combo_file(message):
    if not is_admin(message.from_user.id):
        return
    doc = message.document
    if not doc.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ Only .txt files.", parse_mode="HTML")
        return
    try:
        file = bot.get_file(doc.file_id)
        content = bot.download_file(file.file_path).decode('utf-8')
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if not lines:
            bot.reply_to(message, "❌ Empty file.", parse_mode="HTML")
            return
        first = clean_number(lines[0])
        cc = detect_country_from_number(first)
        if not cc:
            bot.reply_to(message, "❌ Could not determine country.", parse_mode="HTML")
            return
        set_state(message.chat.id, {"combo_country": cc, "combo_numbers": lines, "step": "choose_app"})
        markup = types.InlineKeyboardMarkup(row_width=2)
        apps = ["WhatsApp", "Facebook", "Instagram", "Telegram", "Twitter", "Google", "TikTok", "Snapchat", "PayPal"]
        for app in apps:
            markup.add(ibtn(app, callback_data=f"combo_app|{app}", style="primary", icon_id=app_icon_id(app)))
        markup.add(ibtn("Cancel", callback_data="admin_combos", style="danger", icon="back"))
        bot.reply_to(message, "Select the app for this combo:", parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}", parse_mode="HTML")
        clear_state(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith("combo_app|") and is_admin(call.from_user.id))
def combo_app_selection(call):
    app = call.data.split("|")[1]
    state = user_states.get(call.from_user.id, {})
    if not state or state.get("step") != "choose_app":
        bot.answer_callback_query(call.id, "❌ No pending combo.", show_alert=True)
        return
    cc = state.get("combo_country")
    lines = state.get("combo_numbers")
    if not cc or not lines:
        bot.answer_callback_query(call.id, "❌ Missing combo data.", show_alert=True)
        return
    # Save with broadcast
    save_combo(cc, lines, app_name=app, broadcast=True)
    iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
    flag_html = flag_emoji_html(iso)
    name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
    app_icon = app_emoji_html(app)
    bot.edit_message_text(f"✅ Combo saved for {flag_html} {name} ({app_icon} {app}) – {len(lines)} numbers.",
                          call.message.chat.id, call.message.message_id, parse_mode="HTML")
    clear_state(call.message)
    handle_admin_callback(call, "admin_combos", call.message.chat.id, call.message.message_id)

def admin_reject_reason_step(message):
    st = user_states.get(message.chat.id, {})
    reason = message.text if message.text.lower() != '/skip' else "Rejected by admin"
    success, result = reject_withdrawal(req_id, message.chat.id, reason)
    if success:
        bot.send_message(message.chat.id, f"{pe('checkmark', '✅')} Withdrawal {req_id} rejected.", parse_mode="HTML")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, amount FROM withdrawal_requests WHERE id=?", (req_id,))
        row = c.fetchone()
        if row:
            try:
                bot.send_message(row[0], f"{pe('cross', '❌')} <b>Withdrawal Rejected</b>\nAmount: ${row[1]:.2f}\nReason: {reason}", parse_mode="HTML")
            except:
                pass
        conn.close()
    else:
        bot.send_message(message.chat.id, f"❌ {result}", parse_mode="HTML")
    clear_state(message)
    show_admin_panel(message.chat.id)

# ---- Choice SMS admin step handlers ----
@bot.message_handler(func=lambda msg: get_state(msg) == "choice_panel_url" and is_admin(msg.from_user.id))
def set_choice_panel_handler(message):
    url = message.text.strip().rstrip('/')
    set_setting('choice_panel_url', url)
    bot.reply_to(message, f"✅ Panel URL set to: {url}", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "choice_username" and is_admin(msg.from_user.id))
def set_choice_user_handler(message):
    set_setting('choice_username', message.text.strip())
    bot.reply_to(message, "✅ Username set.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "choice_password" and is_admin(msg.from_user.id))
def set_choice_pass_handler(message):
    set_setting('choice_password', message.text.strip())
    bot.reply_to(message, "✅ Password set.", parse_mode="HTML")
    clear_state(message)

# ---- Other admin step handlers ----
@bot.message_handler(func=lambda msg: get_state(msg) == "add_nums_country" and is_admin(msg.from_user.id))
def add_nums_country_handler(message):
    cc = message.text.strip()
    if cc not in COUNTRY_CODES:
        bot.reply_to(message, "❌ Invalid country code.", parse_mode="HTML")
        return
    set_state(message.chat.id, f"add_nums_numbers|{cc}")
    bot.reply_to(message, "Send numbers (one per line or comma separated):")

@bot.message_handler(func=lambda msg: isinstance(get_state(msg), str) and get_state(msg).startswith("add_nums_numbers|") and is_admin(msg.from_user.id))
def add_nums_numbers_handler(message):
    parts = get_state(message).split("|")
    cc = parts[1]
    raw = message.text.strip()
    nums = []
    for n in re.split(r'[\n,]+', raw):
        n_clean = re.sub(r'\D', '', n.strip())
        if n_clean and len(n_clean) >= 5:
            nums.append(n_clean)
    if not nums:
        bot.reply_to(message, "❌ No valid numbers.", parse_mode="HTML")
        return
    # Save with broadcast
    save_combo(cc, nums, broadcast=True)
    iso = COUNTRY_CODES.get(cc, (cc, "UN"))[1]
    flag_html = flag_emoji_html(iso)
    name = COUNTRY_CODES.get(cc, (cc, "UN"))[0]
    bot.reply_to(message, f"✅ Added {len(nums)} numbers to {flag_html} {name}.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "add_otp_group" and is_admin(msg.from_user.id))
def add_otp_group_handler(message):
    gid = message.text.strip()
    if not gid.startswith("-"):
        gid = "-" + gid.lstrip("-")
    groups = json.loads(get_setting('otp_groups') or '[]')
    if gid not in groups:
        groups.append(gid)
        set_setting('otp_groups', json.dumps(groups))
        bot.reply_to(message, f"✅ Group <code>{gid}</code> added.", parse_mode="HTML")
    else:
        bot.reply_to(message, "ℹ️ Already exists.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "ban_user" and is_admin(msg.from_user.id))
def ban_user_handler(message):
    try:
        uid = int(message.text.strip())
        ban_user(uid)
        bot.reply_to(message, f"✅ User {uid} banned.", parse_mode="HTML")
    except:
        bot.reply_to(message, "❌ Invalid ID.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "unban_user" and is_admin(msg.from_user.id))
def unban_user_handler(message):
    try:
        uid = int(message.text.strip())
        unban_user(uid)
        bot.reply_to(message, f"✅ User {uid} unbanned.", parse_mode="HTML")
    except:
        bot.reply_to(message, "❌ Invalid ID.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "add_balance" and is_admin(msg.from_user.id))
def add_balance_handler(message):
    parts = message.text.strip().split()
    if len(parts) != 2:
        bot.reply_to(message, "❌ Use: user_id amount", parse_mode="HTML")
        return
    try:
        uid = int(parts[0])
        amt = float(parts[1])
        user = get_user(uid)
        if not user:
            bot.reply_to(message, "❌ User not found.", parse_mode="HTML")
            return
        new_bal = (user[10] if len(user) > 10 else 0.0) + amt
        save_user(uid, balance=new_bal)
        bot.reply_to(message, f"✅ Added ${amt} to user {uid}. New balance: ${new_bal}", parse_mode="HTML")
        try:
            bot.send_message(uid, f"💰 <b>Balance Updated</b>\n+${amt}\nNew balance: ${new_bal}", parse_mode="HTML")
        except:
            pass
    except:
        bot.reply_to(message, "❌ Invalid input.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "deduct_balance" and is_admin(msg.from_user.id))
def deduct_balance_handler(message):
    parts = message.text.strip().split()
    if len(parts) != 2:
        bot.reply_to(message, "❌ Use: user_id amount", parse_mode="HTML")
        return
    try:
        uid = int(parts[0])
        amt = float(parts[1])
        user = get_user(uid)
        if not user:
            bot.reply_to(message, "❌ User not found.", parse_mode="HTML")
            return
        current = user[10] if len(user) > 10 else 0.0
        if amt > current:
            bot.reply_to(message, f"❌ User has only ${current:.2f}.", parse_mode="HTML")
            return
        new_bal = current - amt
        save_user(uid, balance=new_bal)
        bot.reply_to(message, f"✅ Deducted ${amt} from user {uid}. New balance: ${new_bal}", parse_mode="HTML")
        try:
            bot.send_message(uid, f"💰 <b>Balance Updated</b>\n-${amt}\nNew balance: ${new_bal}", parse_mode="HTML")
        except:
            pass
    except:
        bot.reply_to(message, "❌ Invalid input.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "set_botlink" and is_admin(msg.from_user.id))
def set_botlink_handler(message):
    link = message.text.strip()
    set_setting('bot_link', link)
    bot.reply_to(message, f"✅ Bot link set to: {link}", parse_mode="HTML")
    clear_state(message)


@bot.message_handler(func=lambda msg: get_state(msg) == "set_cooldown" and is_admin(msg.from_user.id))
def set_cooldown_handler(message):
    try:
        val = int(message.text.strip())
        set_setting('cooldown', str(val))
        bot.reply_to(message, f"✅ Cooldown set to {val}s.", parse_mode="HTML")
    except:
        bot.reply_to(message, "❌ Invalid number.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "set_num_req" and is_admin(msg.from_user.id))
def set_num_req_handler(message):
    try:
        val = int(message.text.strip())
        set_setting('num_per_request', str(val))
        bot.reply_to(message, f"✅ Num per request set to {val}.", parse_mode="HTML")
    except:
        bot.reply_to(message, "❌ Invalid number.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "set_support" and is_admin(msg.from_user.id))
def set_support_handler(message):
    link = message.text.strip()
    set_setting('support_link', link)
    bot.reply_to(message, f"✅ Support link updated.", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "set_watermark" and is_admin(msg.from_user.id))
def set_watermark_handler(message):
    text = message.text.strip()
    set_setting('watermark', text)
    bot.reply_to(message, f"✅ Watermark set to: {text}", parse_mode="HTML")
    clear_state(message)

@bot.message_handler(func=lambda msg: get_state(msg) == "add_force_channel" and is_admin(msg.from_user.id))
def add_force_channel_handler(message):
    url = message.text.strip()
    if not url.startswith("https://t.me/") and not url.startswith("@"):
        bot.reply_to(message, "❌ Invalid URL.", parse_mode="HTML")
        return
    if add_force_sub_channel(url, "Channel"):
        bot.reply_to(message, "✅ Channel added.", parse_mode="HTML")
    else:
        bot.reply_to(message, "❌ Already exists.", parse_mode="HTML")
    clear_state(message)


# ======================== BROADCAST ========================
@bot.message_handler(func=lambda msg: get_state(msg) == "admin_broadcast_msg" and is_admin(msg.from_user.id))
def broadcast_handler(message):
    """Admin broadcasts a message to all users with premium emojis."""
    text = message.text.strip()
    if not text:
        bot.reply_to(message, "❌ Message cannot be empty.", parse_mode="HTML")
        return
    clear_state(message)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned=0")
    users = c.fetchall()
    conn.close()
    if not users:
        bot.reply_to(message, "❌ No users to broadcast to.", parse_mode="HTML")
        return
    # Premium emoji broadcast message
    broadcast_msg = (
        f"{pe('announcement', '📢')} <b>{text}</b>"
    )
    sent = 0
    failed = 0
    for (uid,) in users:
        try:
            bot.send_message(uid, broadcast_msg, parse_mode="HTML")
            sent += 1
        except:
            failed += 1
    bot.reply_to(
        message,
        f"{pe('checkmark', '✅')} <b>Broadcast Sent!</b>\n\n"
        f"Sent: {sent} users\n"
        f"Failed: {failed}",
        parse_mode="HTML"
    )


# ======================== SMS PANEL ADD HANDLERS ========================
@bot.message_handler(func=lambda msg: get_state(msg) == "add_sms_panel_name" and is_admin(msg.from_user.id))
def sms_panel_name_handler(message):
    name = message.text.strip()
    if not name:
        bot.reply_to(message, "❌ Name cannot be empty.", parse_mode="HTML")
        return
    set_state(message.chat.id, {"add_sms_panel_step": "url", "panel_name": name})
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("Cancel", callback_data="admin_sms_panels", style="danger", icon="back"))
    bot.reply_to(message, pe("link", "🔗") + " Send the panel URL (e.g., http://51.77.52.79/ints):", parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda msg: isinstance(get_state(msg), dict) and get_state(msg).get("add_sms_panel_step") == "url" and is_admin(msg.from_user.id))
def sms_panel_url_handler(message):
    url = message.text.strip().rstrip("/")
    state = get_state(message.chat.id)
    state["panel_url"] = url
    state["add_sms_panel_step"] = "type"
    set_state(message.chat.id, state)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(ibtn("Agent", callback_data="sms_panel_type|agent", style="primary", icon="admin"))
    markup.add(ibtn("Client", callback_data="sms_panel_type|client", style="primary", icon="profile"))
    markup.add(ibtn("Cancel", callback_data="admin_sms_panels", style="danger", icon="back"))
    bot.reply_to(message, pe("info_bw", "ℹ") + " Is this an Agent or Client panel?", parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sms_panel_type|") and is_admin(call.from_user.id))
def sms_panel_type_handler(call):
    login_type = call.data.split("|")[1]
    state = get_state(call.message.chat.id)
    if not state:
        bot.answer_callback_query(call.id, "Session expired. Start over.", show_alert=True)
        return
    state["login_type"] = login_type
    state["add_sms_panel_step"] = "username"
    set_state(call.message.chat.id, state)
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("Cancel", callback_data="admin_sms_panels", style="danger", icon="back"))
    bot.edit_message_text(pe("key", "🔑") + " Send the panel username:", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda msg: isinstance(get_state(msg), dict) and get_state(msg).get("add_sms_panel_step") == "username" and is_admin(msg.from_user.id))
def sms_panel_username_handler(message):
    state = get_state(message.chat.id)
    state["panel_username"] = message.text.strip()
    state["add_sms_panel_step"] = "password"
    set_state(message.chat.id, state)
    markup = types.InlineKeyboardMarkup()
    markup.add(ibtn("Cancel", callback_data="admin_sms_panels", style="danger", icon="back"))
    bot.reply_to(message, pe("lock", "🔐") + " Send the panel password:", parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda msg: isinstance(get_state(msg), dict) and get_state(msg).get("add_sms_panel_step") == "password" and is_admin(msg.from_user.id))
def sms_panel_password_handler(message):
    state = get_state(message.chat.id)
    password = message.text.strip()
    name = state.get("panel_name", "Unnamed")
    url = state.get("panel_url", "")
    login_type = state.get("login_type", "client")
    username = state.get("panel_username", "")
    try:
        panel_id = save_sms_panel(name, url, login_type, username, password)
        clear_state(message)
        markup = types.InlineKeyboardMarkup()
        markup.add(ibtn("View Panels", callback_data="admin_sms_panels", style="success", icon="list"))
        markup.add(ibtn("Back", callback_data="admin_panel", style="primary", icon="back"))
        bot.reply_to(message,
            pe("checkmark", "✅") + " <b>SMS Panel Added!</b>\n\n"
            + pe("info_bw", "ℹ") + " Name: " + name + "\n"
            + pe("link", "🔗") + " URL: <code>" + url + "</code>\n"
            + pe("profile", "👤") + " Type: " + login_type.upper() + "\n"
            + pe("key", "🔑") + " User: <code>" + username + "</code>\n\n"
            "Panel is now active and will auto-connect to SMSCDRStats.",
            parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        clear_state(message)
        bot.reply_to(message, "❌ Error saving panel: " + str(e), parse_mode="HTML")

# ======================== ADD ADMIN HANDLER ========================
@bot.message_handler(func=lambda msg: get_state(msg) == "add_new_admin" and is_admin(msg.from_user.id))
def add_admin_handler(message):
    try:
        uid = int(message.text.strip())
        if uid == message.from_user.id:
            bot.reply_to(message, "❌ You are already an admin.", parse_mode="HTML")
            clear_state(message)
            return
        if add_admin(uid):
            markup = types.InlineKeyboardMarkup()
            markup.add(ibtn("View Admins", callback_data="admin_manage_admins", style="success", icon="admin"))
            markup.add(ibtn("Back", callback_data="admin_panel", style="primary", icon="back"))
            bot.reply_to(message,
                pe("checkmark", "✅") + " <b>Admin Added!</b>\n\n"
                + pe("admin", "🛡") + " User <code>" + str(uid) + "</code> is now an admin.",
                parse_mode="HTML", reply_markup=markup)
            try:
                bot.send_message(uid,
                    pe("admin", "🛡") + " <b>You are now an admin!</b>\n\n"
                    "Use /start to access the admin panel.",
                    parse_mode="HTML")
            except:
                pass
        else:
            bot.reply_to(message, "❌ User " + str(uid) + " is already an admin.", parse_mode="HTML")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID. Send a numeric ID.", parse_mode="HTML")
    clear_state(message)


# ======================== CHECK USER ========================
def get_otp_count_for_user(user_id):
    """Count OTPs where assigned_to matches user_id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM otp_logs WHERE assigned_to=?", (user_id,))
    count = c.fetchone()[0] or 0
    conn.close()
    return count


@bot.message_handler(func=lambda msg: msg.text and msg.text.strip().lower().startswith('/checkuser') and is_admin(msg.from_user.id))
def checkuser_handler(message):
    """Admin command: /checkuser <user_id> — shows balance and OTP count."""
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: /checkuser <user_id>", parse_mode="HTML")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID.", parse_mode="HTML")
        return

    user = get_user(uid)
    if not user:
        bot.reply_to(message, f"❌ User {uid} not found.", parse_mode="HTML")
        return

    # Extract fields by index: 0=user_id,1=username,2=first_name,3=last_name,
    # 4=country_code,5=assigned_number,6=is_banned,7=private_combo_country,
    # 8=join_date,9=last_active,10=balance,11=remove_cc
    username = user[1] or ""
    first_name = user[2] or ""
    country_code = user[4] or "N/A"
    assigned_number = user[5] or "None"
    is_banned = "Yes" if user[6] else "No"
    balance = user[10] if user[10] is not None else 0.0
    otp_count = get_otp_count_for_user(uid)

    display_name = first_name if first_name else (f"@{username}" if username else str(uid))
    username_display = f"@{username}" if username else "N/A"

    text = (
        f"👤 <b>User Info</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📛 Name: {display_name}\n"
        f"👤 Username: {username_display}\n"
        f"🌍 Country: {country_code}\n"
        f"📱 Number: {assigned_number}\n"
        f"💰 Balance: ${balance}\n"
        f"📊 OTPs Received: {otp_count}\n"
        f"🚫 Banned: {is_banned}\n"
        f"━━━━━━━━━━━━━━━"
    )

    bot.reply_to(message, text, parse_mode="HTML")


def send_otp_to_admin(timestamp, number, otp, service="", country="", full_msg=""):
    """Forward OTP to admin(s) in real-time with premium emojis."""
    if get_setting('realtime_otp_admin') != '1':
        return
    admins = get_all_admins()
    if not admins:
        return
    otp_display = otp
    if len(otp) == 6 and '-' not in otp:
        otp_display = f"{otp[:3]}-{otp[3:]}"
    service_upper = (service or "UNKNOWN").upper()
    rt_msg = (
        f"{pe('fire', '🔥')} <b>LIVE OTP {pe('fire', '🔥')}</b>\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"{pe('phone', '📞')} <b>Number:</b> <code>{number}</code>\n"
        f"{pe('star', '⭐')} <b>Service:</b> {service_upper}\n"
        f"{pe('earth', '🌍')} <b>Country:</b> {country}\n"
        f"{pe('key', '🔑')} <b>Code:</b> <code>{otp_display}</code>\n"
        f"{pe('calendar', '📅')} <b>Time:</b> {timestamp}"
    )
    for admin_id in admins:
        try:
            bot.send_message(admin_id, rt_msg, parse_mode="HTML")
        except:
            pass

# =========================== MAIN ===========================
def periodic_cleanup():
    """Background thread that cleans up old seen_otps every 6 hours."""
    while True:
        try:
            time.sleep(6 * 3600)  # 6 hours
            cleanup_old_seen_otps(days=7)
            count = seen_otps_count()
            logger.info(f"Periodic cleanup done. seen_otps table: {count} entries")
        except Exception as e:
            logger.error(f"Periodic cleanup error: {e}")

def main():
    # Log DB status on startup
    try:
        otp_count = get_total_otp_count()
        seen_count = seen_otps_count()
        logger.info(f"Startup DB status: {otp_count} OTP logs, {seen_count} seen hashes in DB")
    except Exception as e:
        logger.warning(f"Startup DB check failed: {e}")

    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=start_choice_sms, daemon=True).start()
    threading.Thread(target=periodic_cleanup, daemon=True).start()
    # Start forwarders for all admin-added SMS panels
    try:
        start_all_panel_forwarders()
    except Exception as e:
        logger.error(f"Failed to start panel forwarders: {e}")
    logger.info("Forwarders started (IVASMS + Choice SMS + Panels + cleanup)")
    logger.info("Bot polling started.")
    bot.infinity_polling()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
