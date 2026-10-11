#!/usr/bin/env python3
"""
Regression test: crapi viewstats panels added via the API wizard.

Real symptom (Temp Numbers panel added through Add Panel > API):
the endpoint returns LIST rows [service, number, text, time], which the
generic path used to shove through the SMSCDRStats column mapper, producing
  phone  = the whole SMS body
  service= the timestamp
  ts     = "now"  (destabilises the dedupe key -> same OTP re-posted every poll)
while the built-in forwarder posted the same OTP in the clean format, so the
group saw each code twice, once as rubbish.

Checks:
  1. list rows parse to the right phone/service/otp/timestamp
  2. the rendered group message is the reference format with the REAL otp
  3. the dedupe key is stable across polls (no re-posting)
  4. saving a panel twice does not create duplicate rows (one forwarder only)
  5. the built-in Temp Numbers forwarder yields when a panel covers its endpoint
"""
import os
import re
import sqlite3
import sys
import tempfile

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


# The exact row shape the crapi viewstats endpoint returns for Meizu.
CRAPI_ROW = ["Meizu", "2347020296087",
             "Meizu Verification code 539982 Verification code login "
             "The code is valid for 30 minutes Please do not disclose it to anyone",
             "2026-10-11 09:48:02"]

fw = botmod.SMSPanelForwarder(1, "Temp Numbers", "http://147.135.212.197/crapi/st/viewstats",
                              "api", "TOK", "")

print("=== 1. list row parses correctly ===")
sms = fw._dreamsms_parse([fw._style_list_row(CRAPI_ROW, "crapi")])[0]
check("phone is the number, not the body", sms["phone"] == "2347020296087", str(sms["phone"]))
check("service is the cli, not the timestamp", sms["service"] == "Meizu", str(sms["service"]))
check("otp extracted", sms["otp"] == "539982", str(sms["otp"]))
check("timestamp kept from the row", sms["timestamp"] == "2026-10-11 09:48:02",
      str(sms["timestamp"]))
check("full_text preserved", sms["full_text"].startswith("Meizu Verification code"))

print("\n=== 2. rendered group message is the reference format ===")
iso = botmod._otp_group_iso(sms["phone"], sms["country"])
msg, kb = botmod.build_otp_group_message(sms["phone"], sms["otp"], sms["service"], iso)
plain = re.sub(r"<[^>]+>", "", msg)
check("body is one short line, not the SMS dump", len(plain) < 60, repr(plain))
check("no SMS body leaked into the text", "disclose" not in plain, repr(plain))
check("watermark number rendered", "●" in plain, repr(plain))
check("copy button carries the real otp",
      kb["inline_keyboard"][0][0].get("copy_text", {}).get("text") == "539982",
      str(kb["inline_keyboard"][0][0]))

print("\n=== 3. dedupe key is stable across polls ===")


def key(s):
    return "|".join([str(s.get("otp")), str(s.get("phone")),
                     str(s.get("timestamp")), str(s.get("full_text"))[:60]])


k1 = key(sms)
k2 = key(fw._dreamsms_parse([fw._style_list_row(CRAPI_ROW, "crapi")])[0])
check("same row twice -> same key (no re-post)", k1 == k2, f"{k1} vs {k2}")

# An unparseable timestamp must keep its raw value, never become "now".
weird = fw._dreamsms_parse([fw._style_list_row(
    ["Meizu", "2347020296087", "code 445566", "17/10/2026 09:48"], "crapi")])[0]
w1 = key(weird)
w2 = key(fw._dreamsms_parse([fw._style_list_row(
    ["Meizu", "2347020296087", "code 445566", "17/10/2026 09:48"], "crapi")])[0])
check("odd timestamp format stays stable", w1 == w2, f"{w1} vs {w2}")
check("odd timestamp keeps raw value", weird["timestamp"] == "17/10/2026 09:48",
      str(weird["timestamp"]))

print("\n=== 4. re-adding a panel does not duplicate the row ===")
pid1 = botmod.save_sms_panel("Temp Numbers", "http://147.135.212.197/crapi/st/viewstats",
                             "api", "TOK", "")
pid2 = botmod.save_sms_panel("temp numbers", "http://147.135.212.197/crapi/st/viewstats",
                             "api", "TOK2", "")
conn = sqlite3.connect(botmod.DB_PATH)
n = conn.execute("SELECT COUNT(*) FROM sms_panels WHERE name LIKE 'Temp Numbers'").fetchone()[0]
row = conn.execute("SELECT username FROM sms_panels WHERE id=?", (pid2,)).fetchone()
conn.close()
check("same row id on re-add", pid1 == pid2, f"{pid1} vs {pid2}")
check("only one row exists", n == 1, str(n))
check("re-add updated credentials in place", row and row[0] == "TOK2", str(row))

print("\n=== 5. built-in forwarder yields to an admin-added panel ===")
# A DIFFERENT endpoint must not be suppressed.
check("unrelated endpoint not suppressed",
      botmod._endpoint_covered_by_panel("http://9.9.9.9/crapi/other/viewstats") is False)
check("this panel's endpoint is covered",
      botmod._endpoint_covered_by_panel("http://147.135.212.197/crapi/st/viewstats") is True)
check("trailing slash still matches",
      botmod._endpoint_covered_by_panel("http://147.135.212.197/crapi/st/viewstats/") is True)
# A disabled panel must not suppress the built-in forwarder.
conn = sqlite3.connect(botmod.DB_PATH)
conn.execute("UPDATE sms_panels SET enabled=0 WHERE id=?", (pid1,))
conn.commit()
conn.close()
check("disabled panel does not suppress built-in",
      botmod._endpoint_covered_by_panel("http://147.135.212.197/crapi/st/viewstats") is False)

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL CRAPI LIST-ROW TESTS PASSED")
