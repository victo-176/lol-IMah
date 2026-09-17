#!/usr/bin/env python3
"""
Functional test for the Dream SMS API panel integration.
Loads bot.py and runs simulated /api/v1/messages records through the real
SMSPanelForwarder._dreamsms_parse path (no network, no Telegram calls).
"""
import os, sys, sqlite3, tempfile, importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

spec = importlib.util.spec_from_file_location("botmod", "bot.py")
botmod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(botmod)
except SystemExit:
    pass

_tmpdir = tempfile.mkdtemp()
botmod.DB_PATH = os.path.join(_tmpdir, "test.db")
try:
    botmod.init_db()
except Exception as e:
    print(f"init_db warning: {e}")

failures = []

def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)

# ---- 1. Config registry ----
cfg = botmod.get_panel_config("Dream SMS")
check("config resolves for 'Dream SMS'", cfg.get("type") == "api", str(cfg.get("type")))
check("api_path is /api/v1/messages", cfg.get("api_path") == "/api/v1/messages", str(cfg.get("api_path")))
cfg2 = botmod.get_panel_config("dream sms")
check("config resolves lowercase", cfg2.get("type") == "api")
cfg3 = botmod.get_panel_config("Some Other Panel")
check("other panels keep SMSCDRStats default", cfg3.get("type") is None and "login_fields" in cfg3)

# ---- 2. Forwarder construction ----
fw = botmod.SMSPanelForwarder(999, "Dream SMS", "http://49.13.121.155", "api", "TOKEN123", "")
check("panel_cfg detected api (by name)", fw.panel_cfg.get("type") == "api", fw.panel_cfg.get("type"))
fw2 = botmod.SMSPanelForwarder(998, "Unknown Panel", "http://1.2.3.4", "api", "TOKEN123", "")
check("panel_cfg detected api (by login_type)", fw2.panel_cfg.get("type") == "api", fw2.panel_cfg.get("type"))
fw3 = botmod.SMSPanelForwarder(997, "Bolt", "http://93.190.143.35/ints", "client", "u", "p")
check("web panels unchanged (no api type)", fw3.panel_cfg.get("type") is None, str(fw3.panel_cfg.get("type")))

# ---- 3. Record parsing through the real method ----
# Real shapes captured live from the Dream SMS API (2026-09-17):
#   keys: cli, content, number, payout, range, status, time
#   codes can be ALPHANUMERIC: 'ekxbr', '63xc3c', plus numeric '64492'
records = [
    # real record #1 — alphanumeric code
    {"time": "2026-09-17T17:32:31.730Z", "cli": "Melbet", "number": "2349154635248",
     "content": "Do not share your confirmation code with anyone: ekxbr",
     "range": "NIGERIA - Melbet sep17", "payout": "0.0100", "status": "pending"},
    # real record #2 — code embedded mid-sentence
    {"time": "2026-09-17T17:32:12.999Z", "cli": "Melbet", "number": "2349154635248",
     "content": "Do not pass your one-time password to log in to 63xc3c on to others",
     "range": "NIGERIA - Melbet sep17", "payout": "0.0100", "status": "pending"},
    # numeric code (classic)
    {"time": "2026-09-17T17:28:27.625Z", "cli": "Melbet", "number": "2349154635248",
     "content": "Do not share your confirmation code with anyone: 64492",
     "range": "NIGERIA - Melbet sep17", "payout": "0.0100", "status": "pending"},
    # alternate field-name variants (tolerant mapping)
    {"id": 2, "recipient": "2348024126325", "originator": "Telegram", "text": "<#> 773456 use to verify", "date": "2026-09-17T13:00:10Z"},
    {"id": 3, "phone": "2348012345678", "sender": "WhatsApp", "body": "451-025 is your WhatsApp code", "time": "2026-09-17T13:05:00Z"},
    # credentials-style message (password extractor)
    {"time": "2026-09-17T17:29:38.696Z", "cli": "Melbet", "number": "2349154635248",
     "content": "Username: 1807118365 Password: psphebs2 Do not share this information.",
     "range": "NIGERIA - Melbet sep17", "status": "pending"},
    # junk rows that must be skipped
    {"id": 4, "number": "abc", "message": "no digits here 1234"},
    {"id": 5, "cli": "OnlySender", "message": "no number field"},
    {"id": 6, "number": "+2348099449500", "message": "hello welcome, no code"},
]
parsed = fw._dreamsms_parse(records)
check("6 valid records parsed", len(parsed) == 6, f"got {len(parsed)}")
p0 = parsed[0] if len(parsed) > 0 else {}
check("alphanumeric OTP extracted (ekxbr)", p0.get("otp") == "ekxbr", str(p0.get("otp")))
check("mid-sentence alphanumeric OTP (63xc3c)", len(parsed) > 1 and parsed[1].get("otp") == "63xc3c", str(parsed[1].get("otp") if len(parsed) > 1 else None))
check("phone normalized", p0.get("phone") == "2349154635248", str(p0.get("phone")))
check("service from cli", p0.get("service") == "Melbet", str(p0.get("service")))
check("country from range field", p0.get("country") == "Nigeria", str(p0.get("country")))
check("flag lookup still works after capitalize", bool(botmod.COUNTRY_FLAGS.get(p0.get("country", "").upper())))
check("millisecond timestamp normalized", p0.get("timestamp") == "2026-09-17 17:32:31", str(p0.get("timestamp")))
if len(parsed) > 2:
    check("numeric OTP (64492)", parsed[2].get("otp") == "64492", str(parsed[2].get("otp")))
if len(parsed) > 3:
    check("alt field names mapped (recipient/text)", parsed[3].get("otp") == "773456", str(parsed[3].get("otp")))
    check("alt phone mapped", parsed[3].get("phone") == "2348024126325", str(parsed[3].get("phone")))
if len(parsed) > 4:
    check("dashed OTP joined", parsed[4].get("otp") == "451025", str(parsed[4].get("otp")))
if len(parsed) > 5:
    check("password-style code extracted", parsed[5].get("otp") == "psphebs2", str(parsed[5].get("otp")))

# ---- 4. Country fallback from phone prefix ----
rec_ng = [{"number": "2348099449578", "message": "code 111222", "cli": "X"}]
p_ng = fw._dreamsms_parse(rec_ng)
check("country fallback via prefix (234->Nigeria)", p_ng and p_ng[0].get("country").lower().startswith("niger"), str(p_ng[0].get("country") if p_ng else None))

# ---- 5. Empty/error handling ----
check("empty records -> []", fw._dreamsms_parse([]) == [])
check("None records -> []", fw._dreamsms_parse(None) == [])
check("non-dict rows skipped", fw._dreamsms_parse(["junk", 42, None]) == [])

# ---- 6. URL normalization ----
fw4 = botmod.SMSPanelForwarder(996, "Dream SMS", "http://49.13.121.155/api/v1", "api", "TOK", "")
check("URL with /api/v1 accepted (no crash in init)", fw4.url.endswith("/api/v1"))

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL DREAM SMS TESTS PASSED")
