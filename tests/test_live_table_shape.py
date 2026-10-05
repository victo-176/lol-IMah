#!/usr/bin/env python3
"""Pin the parser to the real tempnumbers.net table shape.

The header below was captured from the live panel's SMS report page:

    Date | Range | Number | CLI | SMS | Currency | My Payout | Total SMS

If the parser stops mapping these columns correctly, this fails.
Run:  python3 tests/test_live_table_shape.py
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "b.db")
conn = sqlite3.connect(db)
conn.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
conn.execute(
    "CREATE TABLE sms_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,"
    " url TEXT, login_type TEXT, username TEXT, password TEXT,"
    " sesskey TEXT DEFAULT '', enabled INTEGER DEFAULT 1)")
conn.execute("INSERT INTO bot_settings (key, value) VALUES ('otp_groups', '[-1001]')")
conn.execute(
    "INSERT INTO sms_panels (name, url, login_type, username, password)"
    " VALUES ('Number Panel', 'http://tempnumbers.net', 'client', 'u', 'p')")
conn.commit()
conn.close()

os.environ["DB_PATH"] = db
os.environ["BOT_TOKEN"] = "X"

import temp_numbers_panel as tnp  # noqa: E402

LIVE_HTML = (
    "<table><thead><tr><th>Date</th><th>Range</th><th>Number</th><th>CLI</th>"
    "<th>SMS</th><th>Currency</th><th>My Payout</th><th>Total SMS</th>"
    "</tr></thead><tbody>"
    "<tr><td>2026-10-05 12:00:01</td><td>NIGERIA 40968</td>"
    "<td>2348024126325</td><td>WhatsApp</td>"
    "<td>Your verification code is 123456</td><td>USD</td>"
    "<td>0.0001</td><td>1</td></tr>"
    "<tr><td>2026-10-05 12:00:02</td><td>EGYPT 20</td>"
    "<td>201001234567</td><td>Telegram</td>"
    "<td>Login code: 778899. Do not disclose it to anyone.</td><td>USD</td>"
    "<td>0.0001</td><td>1</td></tr>"
    "</tbody></table>"
)


def main():
    from bs4 import BeautifulSoup

    roles = tnp._header_roles(BeautifulSoup(LIVE_HTML, "html.parser").find("table"))
    print("roles from LIVE header:", roles)

    rows = tnp._parse_report_html(LIVE_HTML)
    print("rows parsed:", len(rows))
    for r in rows:
        print("  ", r)

    checks = [
        ("number column mapped", roles.get(2) == "number"),
        ("CLI column mapped to service", roles.get(3) == "service"),
        ("SMS column mapped", roles.get(4) == "sms"),
        ("both rows parsed", len(rows) == 2),
        ("otp 123456", bool(rows) and rows[0]["otp"] == "123456"),
        ("otp 778899", len(rows) > 1 and rows[1]["otp"] == "778899"),
        ("number not confused with Date", bool(rows) and rows[0]["number"] == "2348024126325"),
        ("service WhatsApp", bool(rows) and rows[0]["service"] == "WhatsApp"),
        ("service Telegram", len(rows) > 1 and rows[1]["service"] == "Telegram"),
        ("timestamp from Date column",
         bool(rows) and rows[0]["timestamp"] == "2026-10-05 12:00:01"),
        ("sms body captured",
         bool(rows) and "verification code" in rows[0]["full_text"]),
    ]

    print()
    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}: {n}")
    print()
    if failed:
        print("FAILURES:", failed)
        return 1
    print(f"ALL {len(checks)} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())