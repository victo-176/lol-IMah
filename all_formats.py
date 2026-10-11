#!/usr/bin/env python3
"""
all_formats.py — Panel addition logic for all 4 formats
────────────────────────────────────────────────────────
Standalone reference / drop-in helpers for OTP bot panel wizards.

Formats
  1) captcha     — INTS-style login (username + password + math captcha)
  2) nocaptcha   — login without captcha (DreamSMS / client CDR style)
  3) api         — REST API (auto-detects 3+ styles):
                     • augestel_iprn  — Bearer + /api/v1/iprn/messages|numbers
                     • crapi         — token + /crapi/.../viewstats
                     • query_token   — token in query string / .php
                     • bearer_json   — generic Authorization: Bearer
  4) socket      — Live WebSocket (wss://... with token)

Usage (inside your bot):
  from all_formats import (
      detect_api_style,
      build_api_panel_config,
      build_login_panel_config,
      build_socket_panel_config,
      resolve_signin_url,
      solve_math_captcha,
  )

This file does NOT contain bot tokens, DB passwords, or AutoPay keys.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse


# ═══════════════════════════════════════════════════════════
#  Shared helpers
# ═══════════════════════════════════════════════════════════

def solve_math_captcha(html: str) -> str:
    """Solve simple 'What is X + Y' / 'X - Y' captchas on INTS login pages."""
    try:
        m = re.search(r"(\d+)\s*\+\s*(\d+)", html or "")
        if m:
            return str(int(m.group(1)) + int(m.group(2)))
    except Exception:
        pass
    try:
        m = re.search(r"(\d+)\s*-\s*(\d+)", html or "")
        if m:
            return str(int(m.group(1)) - int(m.group(2)))
    except Exception:
        pass
    return "0"


def origin_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    p = urlparse(raw)
    if not p.netloc:
        return raw.rstrip("/")
    return f"{p.scheme}://{p.netloc}"


def resolve_signin_url(login_url: str, html: str = "") -> str:
    """
    From login page URL + optional HTML, get POST signin URL.
    EVS example: form action='signin' on /ints/login → /ints/signin
    """
    login_url = (login_url or "").strip()
    if html:
        m = re.search(r"""<form[^>]+action=["']([^"']+)["']""", html, re.I)
        if m:
            return urljoin(login_url, m.group(1).strip())
        m = re.search(
            r"""action=["']([^"']*(?:signin|sign-in|login)[^"']*)["']""",
            html,
            re.I,
        )
        if m:
            return urljoin(login_url, m.group(1).strip())
    # Fallbacks
    if "/ints/login" in login_url:
        return login_url.replace("/ints/login", "/ints/signin")
    if login_url.endswith("/login"):
        return login_url[:-6] + "/signin"
    origin = origin_from_url(login_url)
    return origin + "/ints/signin"


def slug_id(prefix: str, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:40]
    if not base:
        base = str(int(time.time()))
    return f"{prefix}_{base}"


# ═══════════════════════════════════════════════════════════
#  Format 1 & 2 — Login panels (captcha / no-captcha)
# ═══════════════════════════════════════════════════════════

def build_login_panel_config(
    name: str,
    login_url: str,
    username: str,
    password: str,
    *,
    no_captcha: bool = False,
    poll_interval: int = 4,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build config for captcha or no-captcha web panels.
    Returns (panel_id, config).
    """
    origin = origin_from_url(login_url)
    login_path = urlparse(login_url if "://" in login_url else origin + login_url).path or "/ints/login"
    signin_path = "/ints/signin"
    if "/konekta/" in login_path:
        signin_path = "/konekta/signin"
    elif login_path.endswith("/login"):
        signin_path = login_path[:-6] + "/signin"

    panel_id = slug_id("web" if no_captcha else "cap", name)
    config: Dict[str, Any] = {
        "name": name,
        "type": "standard",
        "base_url": origin,
        "login_url": login_url if "://" in (login_url or "") else origin + (login_path or "/ints/login"),
        "login_path": login_path,
        "signin_path": signin_path,
        "username": username,
        "password": password,
        "sms_path": "/ints/agent/SMSCDRStats",
        "ajax_path": "/ints/agent/res/data_smscdr.php",
        "num_col": 2,
        "sms_col": 5,
        "date_col": 0,
        "cli_col": 3,
        "poll_interval": int(poll_interval or 4),
        "enabled": True,
        "no_captcha": bool(no_captcha),
        "use_today_range": True,
    }
    return panel_id, config


# ═══════════════════════════════════════════════════════════
#  Format 3 — API panels (multi-style)
# ═══════════════════════════════════════════════════════════

def detect_api_style(api_url: str) -> str:
    """
    Return one of:
      augestel_iprn | crapi | query_token | bearer_json
    """
    u = (api_url or "").strip().lower()
    if "augestel" in u or "/api/v1/iprn" in u or "/iprn/" in u:
        return "augestel_iprn"
    if "/crapi/" in u or "viewstats" in u:
        return "crapi"
    if "token=" in u or u.endswith(".php"):
        return "query_token"
    return "bearer_json"


def _augestel_numbers_api(api_url: str) -> str:
    u = (api_url or "").strip()
    ul = u.lower()
    if "/messages" in ul:
        return u.replace("/messages", "/numbers")
    if ul.rstrip("/").endswith("/iprn"):
        return u.rstrip("/") + "/numbers"
    if "/iprn/" in ul:
        return u.rsplit("/", 1)[0] + "/numbers"
    return "https://augestel.com/api/v1/iprn/numbers"


def build_api_panel_config(
    name: str,
    api_url: str,
    api_token: str,
    *,
    poll_interval: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build config for API panel. Auto-detects style from URL.
    Any Augustel-format host works (not only augestel.com).
    """
    api_url = (api_url or "").strip()
    style = detect_api_style(api_url)
    panel_id = slug_id("api", name)
    base = api_url.rsplit("/", 1)[0] if "/" in api_url else api_url

    config: Dict[str, Any] = {
        "name": name,
        "type": "api",
        "api_style": style,
        "base_url": base,
        "api_url": api_url,
        "api_token": (api_token or "").strip(),
        "poll_interval": int(poll_interval or 3),
        "enabled": True,
        "num_col": 2,
        "sms_col": 5,
        "date_col": 0,
        "cli_col": 3,
    }
    if style == "augestel_iprn":
        # Normalize messages URL if user pasted only base IPRN path
        if api_url.rstrip("/").lower().endswith("/iprn"):
            config["api_url"] = api_url.rstrip("/") + "/messages"
        config["numbers_api"] = _augestel_numbers_api(config["api_url"])
    return panel_id, config


def api_auth_headers(style: str, token: str) -> Dict[str, str]:
    """Headers for each API style."""
    token = (token or "").strip()
    if style in ("augestel_iprn", "bearer_json"):
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
    if style == "crapi":
        return {"Accept": "application/json"}
    return {"Accept": "application/json"}


def api_request_params(style: str, token: str) -> Dict[str, str]:
    """Query params for styles that pass token in URL."""
    if style in ("crapi", "query_token"):
        return {"token": (token or "").strip()}
    return {}


# ═══════════════════════════════════════════════════════════
#  Format 4 — Live socket
# ═══════════════════════════════════════════════════════════

def build_socket_panel_config(
    name: str,
    ws_url: str,
    *,
    poll_interval: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    panel_id = slug_id("sock", name)
    config: Dict[str, Any] = {
        "name": name,
        "type": "socket",
        "ws_url": (ws_url or "").strip(),
        "base_url": "",
        "poll_interval": int(poll_interval or 3),
        "enabled": True,
    }
    return panel_id, config


# ═══════════════════════════════════════════════════════════
#  Wizard step machine (optional drop-in)
# ═══════════════════════════════════════════════════════════

"""
Suggested Telegram wizard flow (2-column menus in your bot):

  [ Auto Captcha ]  [ No Captcha ]
  [ API Panel    ]  [ Live Socket ]

1) captcha / nocaptcha
   login_url → username → password → test login → save

2) api
   name → api_url → api_token → detect_api_style → save

3) socket
   name → ws_url → quick handshake test → save
"""


def wizard_start(kind: str) -> Tuple[str, str]:
    """
    Returns (next_step, prompt_html).
    kind: captcha | nocaptcha | api | socket
    """
    kind = (kind or "captcha").lower()
    if kind == "api":
        return "api_name", (
            "➕ <b>ADD API PANEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Step 1: Send a <b>display name</b>\n\n"
            "Supports Augustel/IPRN, CRAPI, query-token, Bearer JSON."
        )
    if kind == "socket":
        return "sock_name", (
            "🔌 <b>ADD LIVE SOCKET PANEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Step 1: Send a <b>display name</b>"
        )
    if kind == "nocaptcha":
        return "login_url", (
            "🔓 <b>ADD NO-CAPTCHA PANEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Step 1: Send the <b>full login link</b>\n"
            "<code>http://host/login?next=/cdrs</code>"
        )
    return "login_url", (
        "➕ <b>ADD AUTO CAPTCHA PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Step 1: Send the <b>full login link</b>\n"
        "<code>http://host/ints/login</code>"
    )


# ═══════════════════════════════════════════════════════════
#  Quick self-test
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    assert solve_math_captcha("What is 9 + 0 = ?") == "9"
    assert resolve_signin_url(
        "http://57.129.107.62/ints/login",
        "<form action='signin' method='post'>",
    ) == "http://57.129.107.62/ints/signin"

    pid, cfg = build_api_panel_config(
        "Augustel",
        "https://augestel.com/api/v1/iprn/messages",
        "sk_test_xxx",
    )
    assert cfg["api_style"] == "augestel_iprn"
    assert "numbers" in cfg.get("numbers_api", "")

    pid2, cfg2 = build_api_panel_config(
        "CRAPI",
        "http://147.135.212.197/crapi/st/viewstats",
        "TOKEN",
    )
    assert cfg2["api_style"] == "crapi"

    pid3, cfg3 = build_login_panel_config(
        "EVS",
        "http://57.129.107.62/ints/login",
        "user",
        "pass",
        no_captcha=False,
    )
    assert cfg3["signin_path"] == "/ints/signin"

    print("all_formats.py OK")
    print("  API styles: augestel_iprn, crapi, query_token, bearer_json")
    print("  Login: captcha + nocaptcha")
    print("  Socket: wss panel")
