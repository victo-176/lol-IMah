#!/usr/bin/env python3
"""
Functional test for the 4-format admin "Add Panel" wizard (all_formats.py).

Drives the REAL handlers in bot.py for every format — captcha, no-captcha,
API (auto-detected style) and live socket — with only Telegram stubbed, then
checks that the saved panel config is what the forwarder actually consumes.
No network, no Telegram API calls.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import types as pytypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import importlib.util
spec = importlib.util.spec_from_file_location("botmod", "bot.py")
botmod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(botmod)
except SystemExit:
    pass

import all_formats as af

_tmpdir = tempfile.mkdtemp()
botmod.DB_PATH = os.path.join(_tmpdir, "test.db")
try:
    botmod.init_db()
except Exception as e:
    print(f"init_db warning: {e}")

ADMIN = 424242
botmod.add_admin(ADMIN)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)


# ------------------------------------------------------------------ stubs
sent = []


def _record(text, *a, **kw):
    sent.append(str(text))
    return pytypes.SimpleNamespace(text=str(text))


botmod.bot.reply_to = _record
botmod.bot.edit_message_text = lambda text, *a, **kw: _record(text)
botmod.bot.answer_callback_query = lambda *a, **kw: None
botmod.start_panel_forwarder = lambda pid: None  # no threads / no network


class Msg:
    content_type = "text"

    def __init__(self, chat_id, text, uid=ADMIN):
        self.text = text
        self.chat = pytypes.SimpleNamespace(id=chat_id)
        self.from_user = pytypes.SimpleNamespace(id=uid, username="admin", first_name="Admin")


def mkcall(data, chat_id, uid=ADMIN):
    return pytypes.SimpleNamespace(
        data=data, id="cb1",
        from_user=pytypes.SimpleNamespace(id=uid),
        message=pytypes.SimpleNamespace(chat=pytypes.SimpleNamespace(id=chat_id),
                                        message_id=77,
                                        from_user=pytypes.SimpleNamespace(id=uid)))


def find_handler(name):
    for h in botmod.bot.message_handlers:
        fn = h.get("function") if isinstance(h, dict) else getattr(h, "callback", None)
        if getattr(fn, "__name__", "") == name:
            return h
    return None


print("=== all_formats.py module ===")
r = subprocess.run([sys.executable, "all_formats.py"], capture_output=True, text=True)
check("all_formats.py self-test passes", r.returncode == 0, r.stderr[-200:])
check("detect: augestel_iprn",
      af.detect_api_style("https://augestel.com/api/v1/iprn/messages") == "augestel_iprn")
check("detect: crapi", af.detect_api_style("http://147.135.212.197/crapi/st/viewstats") == "crapi")
check("detect: query_token", af.detect_api_style("http://h/x.php") == "query_token")
check("detect: bearer_json", af.detect_api_style("https://h/v1/sms") == "bearer_json")
check("signin resolve", af.resolve_signin_url("http://5.5.5.5/ints/login") == "http://5.5.5.5/ints/signin")


# ------------------------------------------------------------------ helpers
def run_captcha_wizard(chat_id, kind, name, login_url, user, pwd):
    """Drive the real handlers: name -> format -> url -> role -> user -> pwd."""
    botmod.set_state(chat_id, "add_sms_panel_name")
    botmod.sms_panel_name_handler(Msg(chat_id, name))
    botmod.panel_format_handler(mkcall(f"panel_format|{kind}", chat_id))
    botmod.sms_panel_login_url_handler(Msg(chat_id, login_url))
    botmod.sms_panel_type_handler(mkcall("sms_panel_type|client", chat_id))
    botmod.sms_panel_username_handler(Msg(chat_id, user))
    botmod.sms_panel_password_handler(Msg(chat_id, pwd))


def panel_row(name):
    conn = sqlite3.connect(botmod.DB_PATH)
    row = conn.execute(
        "SELECT id, name, url, login_type, username, password FROM sms_panels WHERE name=?",
        (name,)).fetchone()
    conn.close()
    return row


print("\n=== wizard: AUTO CAPTCHA panel ===")
run_captcha_wizard(101, "captcha", "EVS Test", "http://57.129.107.62/ints/login", "evsuser", "evspass")
row = panel_row("EVS Test")
check("panel row saved", bool(row), "no row")
if row:
    check("login_type client", row[3] == "client", str(row[3]))
    check("username stored", row[4] == "evsuser")
    check("password stored", row[5] == "evspass")
wcfg = botmod.get_panel_format_config("EVS Test")
check("wizard config stored", bool(wcfg))
check("format cfg type standard", wcfg.get("type") == "standard", str(wcfg.get("type")))
check("format cfg signin_path /ints/signin", wcfg.get("signin_path") == "/ints/signin",
      str(wcfg.get("signin_path")))
check("captcha flag false", wcfg.get("no_captcha") is False)
cfg = botmod.get_panel_config("EVS Test")
check("forwarder cfg login_url is a PATH", cfg.get("login_url") == "/ints/login",
      str(cfg.get("login_url")))
check("forwarder cfg signin_url is a PATH", cfg.get("signin_url") == "/ints/signin",
      str(cfg.get("signin_url")))
check("forwarder cfg keeps captcha pattern", bool(re.findall(cfg["captcha_pattern"], "What is 3 + 4?")))
check("sesskey pages include sms_path", any("SMSCDRStats" in p for p in cfg.get("sesskey_pages", [])))
check("state cleared after save", botmod.get_state(Msg(101, "x")) is None)
h = find_handler("sms_panel_login_url_handler")
if h:
    botmod.set_state(101, {"add_sms_panel_step": "login_url", "panel_name": "EVS Test"})
    check("telebot dispatch matches login_url handler",
          botmod.bot._test_message_handler(h, Msg(101, "http://x/login")) is True)
    check("telebot dispatch ignores wrong state",
          botmod.bot._test_message_handler(h, Msg(999, "http://x/login")) is False)
    botmod.clear_state(Msg(101, "x"))
else:
    check("login_url handler registered", False)

print("\n=== wizard: NO CAPTCHA panel ===")
run_captcha_wizard(102, "nocaptcha", "Dream Test", "http://49.13.121.155/login?next=/cdrs", "tok", "")
row = panel_row("Dream Test")
check("panel row saved", bool(row))
wcfg = botmod.get_panel_format_config("Dream Test")
check("no_captcha flag true", wcfg.get("no_captcha") is True)
cfg = botmod.get_panel_config("Dream Test")
check("captcha pattern never matches", re.findall(cfg["captcha_pattern"], "What is 3 + 4?") == [],
      str(cfg["captcha_pattern"]))
check("signin derived from /login", cfg.get("signin_url") == "/signin", str(cfg.get("signin_url")))

print("\n=== wizard: API panel (auto-detected style) ===")
chat = 103
botmod.set_state(chat, "add_sms_panel_name")
botmod.sms_panel_name_handler(Msg(chat, "Augustel Test"))
botmod.panel_format_handler(mkcall("panel_format|api", chat))
botmod.sms_panel_api_url_handler(Msg(chat, "https://augestel.com/api/v1/iprn/messages"))
st = botmod.get_state(Msg(chat, "x"))
check("step=token after api url", st.get("add_sms_panel_step") == "token", str(st.get("add_sms_panel_step")))
check("style detected augestel_iprn", st.get("api_style") == "augestel_iprn", str(st.get("api_style")))
botmod.sms_panel_token_handler(Msg(chat, "sk_live_123"))
row = panel_row("Augustel Test")
check("api panel row saved", bool(row))
if row:
    check("api login_type", row[3] == "api", str(row[3]))
    check("token stored as username", row[4] == "sk_live_123")
wcfg = botmod.get_panel_format_config("Augustel Test")
check("api cfg type api", wcfg.get("type") == "api", str(wcfg.get("type")))
check("api cfg api_style", wcfg.get("api_style") == "augestel_iprn", str(wcfg.get("api_style")))
check("numbers_api derived", "numbers" in (wcfg.get("numbers_api") or ""), str(wcfg.get("numbers_api")))
cfg = botmod.get_panel_config("Augustel Test")
check("forwarder sees api_style", cfg.get("api_style") == "augestel_iprn")

print("\n=== wizard: LIVE SOCKET panel ===")
chat = 104
botmod.set_state(chat, "add_sms_panel_name")
botmod.sms_panel_name_handler(Msg(chat, "Socket Test"))
botmod.panel_format_handler(mkcall("panel_format|socket", chat))
botmod.sms_panel_ws_url_handler(Msg(chat, "wss://live.example.com/livesms?token=abc"))
row = panel_row("Socket Test")
check("socket panel row saved", bool(row))
if row:
    check("socket login_type", row[3] == "socket", str(row[3]))
    check("socket url stored", row[2] == "wss://live.example.com/livesms?token=abc", str(row[2]))
wcfg = botmod.get_panel_format_config("Socket Test")
check("socket cfg type socket", wcfg.get("type") == "socket")
check("socket ws_url stored", wcfg.get("ws_url", "").startswith("wss://"))
check("no state left after socket save", botmod.get_state(Msg(104, "x")) is None)


# ------------------------------------------------------------------ forwarder
print("\n=== forwarder: API styles (headers/params/parsing) ===")


class FakeResp:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None, **kw):
        self.calls.append({"url": url, "headers": dict(headers or {}),
                           "params": dict(params or {}), "timeout": timeout})
        return self.resp


REC = {"time": "2026-09-17T17:28:27.625Z", "cli": "Melbet", "number": "2349154635248",
       "content": "Do not share your confirmation code with anyone: 64492",
       "range": "NIGERIA - Melbet sep17", "status": "pending"}


def make_fw(name, url, style, token="TOK"):
    _, c = af.build_api_panel_config(name, url, token)
    if style:
        assert c.get("api_style") == style, c.get("api_style")
    botmod.save_panel_format_config(name, c)
    fw = botmod.SMSPanelForwarder(77, name, url, "api", token, "")
    return fw, c


fw, c = make_fw("aug style", "https://augestel.com/api/v1/iprn/messages", "augestel_iprn", "sk_live_123")
fs = FakeSession(FakeResp(200, {"records": [REC]}))
fw.session = fs
out = fw._style_api_fetch()
check("augestel: parsed 1 record", len(out) == 1, str(out)[:120])
check("augestel: otp extracted", out and out[0]["otp"] == "64492", str(out and out[0].get("otp")))
check("augestel: Bearer header", fs.calls[0]["headers"].get("Authorization") == "Bearer sk_live_123",
      str(fs.calls[0]["headers"]))
check("augestel: hits api_url", fs.calls[0]["url"] == "https://augestel.com/api/v1/iprn/messages")

fw, c = make_fw("crapi style", "http://147.135.212.197/crapi/st/viewstats", "crapi", "CRTOK")
fs = FakeSession(FakeResp(200, {"data": [REC]}))
fw.session = fs
out = fw._style_api_fetch()
check("crapi: parsed", len(out) == 1)
check("crapi: token in params", fs.calls[0]["params"].get("token") == "CRTOK",
      str(fs.calls[0]["params"]))
check("crapi: no Authorization header", "Authorization" not in fs.calls[0]["headers"])

fw, c = make_fw("query style", "http://host.tld/data.php", "query_token", "QTOK")
fs = FakeSession(FakeResp(200, [REC]))
fw.session = fs
out = fw._style_api_fetch()
check("query_token: list payload parsed", len(out) == 1)
check("query_token: token param", fs.calls[0]["params"].get("token") == "QTOK")

fw, c = make_fw("bearer style", "https://h.tld/v1/sms", "bearer_json", "BTOK")
fs = FakeSession(FakeResp(401, {"error": "nope"}))
fw.session = fs
check("bearer_json: 401 -> validate False", fw._style_api_validate() is False)
check("bearer_json: 401 -> fetch None", fw._style_api_fetch() is None)
fs2 = FakeSession(FakeResp(200, {"messages": [REC]}))
fw.session = fs2
check("bearer_json: validate True on 200", fw._style_api_validate() is True)

print("\n=== forwarder: socket mode ===")
fw = botmod.SMSPanelForwarder(78, "Socket Test", "wss://live.example.com/livesms?token=abc", "socket", "", "")
check("socket cfg picked up", fw.panel_cfg.get("type") == "socket", str(fw.panel_cfg.get("type")))
check("socket login is a no-op (True)", fw._do_login() is True)
sms = fw._parse_socket_frame(json.dumps(
    {"message": "Your WhatsApp code is 451-025", "number": "2348012345678", "cli": "WhatsApp"}))
check("socket JSON frame parsed", bool(sms), "no sms")
check("socket otp", sms and sms["otp"] == "451025", str(sms and sms.get("otp")))
check("socket phone", sms and sms["phone"] == "2348012345678", str(sms and sms.get("phone")))
check("socket service", sms and sms["service"] == "WhatsApp", str(sms and sms.get("service")))
sms2 = fw._parse_socket_frame("Melbet: code 64492 to +2349011112222")
check("socket plain frame parsed", bool(sms2) and sms2["otp"] == "64492", str(sms2))
sms3 = fw._parse_socket_frame("482913")
check("socket bare-code frame -> otp", bool(sms3) and sms3["otp"] == "482913", str(sms3))
check("socket control frame ignored", fw._parse_socket_frame('{"type":"ping"}') is None)

print("\n=== forwarder: captcha web panel honours wizard paths ===")
fw = botmod.SMSPanelForwarder(79, "EVS Test", "http://57.129.107.62", "client", "evsuser", "evspass")
check("web cfg type standard", fw.panel_cfg.get("type") == "standard", str(fw.panel_cfg.get("type")))
check("web cfg not api", fw.panel_cfg.get("type") != "api")
check("web login path used", fw.panel_cfg.get("login_url") == "/ints/login")

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL ALL_FORMATS TESTS PASSED")
