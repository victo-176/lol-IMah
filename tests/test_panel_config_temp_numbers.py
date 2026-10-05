#!/usr/bin/env python3
"""Verify bot.py's PANEL_LOGIN_CONFIGS gains a valid 'temp numbers' entry
without importing bot.py (telebot is not installed in this sandbox).

Statically evaluates just the PANEL_LOGIN_CONFIGS literal.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(ROOT, "bot.py")
tree = ast.parse(open(path).read(), filename=path)

node = None
for n in tree.body:
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id == "PANEL_LOGIN_CONFIGS":
                node = n
                break
    if node:
        break

if node is None:
    print("FAIL: PANEL_LOGIN_CONFIGS not found at module level")
    sys.exit(1)

cfg = ast.literal_eval(node.value)
print(f"PANEL_LOGIN_CONFIGS parsed: {len(cfg)} entries")

failures = []

# The new entry must exist and be complete.
tn = cfg.get("temp numbers")
if not tn:
    failures.append("'temp numbers' entry missing")
else:
    print(f"'temp numbers' entry: {tn}")
    for key in ("login_url", "signin_url", "login_fields", "otp_endpoint"):
        if key not in tn:
            failures.append(f"'temp numbers' missing key {key}")
    if tn.get("otp_endpoint") != "/Client/SMSCDRReports":
        failures.append(
            f"otp_endpoint should scrape SMSCDRReports, got "
            f"{tn.get('otp_endpoint')!r}")
    if str(tn.get("poll_interval")) != "7":
        failures.append(
            f"poll_interval should be 7, got {tn.get('poll_interval')!r}")
    if tn["login_fields"].get("captcha") != "capt":
        failures.append("login_fields.captcha should be 'capt'")

# The pre-existing 'number panel' entry must be untouched.
np = cfg.get("number panel")
if not np or np.get("otp_endpoint") != "/client/res/data_smscdr.php":
    failures.append("existing 'number panel' entry was altered")

# The temp-numbers sub-bot must agree with the bot's config.
sys.path.insert(0, ROOT)
import tempfile  # noqa: E402
import sqlite3  # noqa: E402

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "bot.db")
conn = sqlite3.connect(db)
conn.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
conn.execute(
    "CREATE TABLE sms_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,"
    " url TEXT, login_type TEXT, username TEXT, password TEXT,"
    " sesskey TEXT DEFAULT '', enabled INTEGER DEFAULT 1)")
conn.execute("INSERT INTO bot_settings (key, value) VALUES ('otp_groups', '[-100123]')")
conn.execute(
    "INSERT INTO sms_panels (name, url, login_type, username, password)"
    " VALUES ('Number Panel', 'http://tempnumbers.net', 'client', 'u', 'p')")
conn.commit()
conn.close()

os.environ["DB_PATH"] = db
os.environ["BOT_TOKEN"] = "T"

import temp_numbers_panel as tnp  # noqa: E402

if tnp.PANEL_URL != "http://tempnumbers.net":
    failures.append(f"sub-bot panel url wrong: {tnp.PANEL_URL}")
if tnp.REPORT_PAGES[0] != "http://tempnumbers.net/Client/SMSCDRReports":
    failures.append(f"sub-bot scrapes wrong page: {tnp.REPORT_PAGES[0]}")
if tnp.POLL_INTERVAL != 7.0:
    failures.append(f"sub-bot poll interval should be 7s, got {tnp.POLL_INTERVAL}")
if tnp.OTP_GROUPS != [-100123]:
    failures.append(f"sub-bot groups wrong: {tnp.OTP_GROUPS}")

print(f"sub-bot: url={tnp.PANEL_URL} page={tnp.REPORT_PAGES[0]} "
      f"poll={tnp.POLL_INTERVAL}s groups={tnp.OTP_GROUPS}")

# The page the sub-bot scrapes must be the URL the user asked for.
assert "tempnumbers.net/Client/SMSCDRReports" in tnp.REPORT_PAGES[0]

if failures:
    print("\nFAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nALL CHECKS PASSED")