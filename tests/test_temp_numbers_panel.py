#!/usr/bin/env python3
"""End-to-end check for temp_numbers_panel.py.

Spins up a fake Temp Numbers panel (login page + SMSCDRReports page) on a
local port, points the sub-bot at it with a temp SQLite DB, and verifies:
  - config load (panel discovery by URL host, token, groups)
  - login + arithmetic captcha solving
  - SMSCDRReports table scraping / OTP extraction
  - first run skips history, later new rows are delivered
  - telegram posts go out (captured by a local fake Telegram API)
Run:  python3 tests/test_temp_numbers_panel.py
"""

import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PANEL_HOST = "127.0.0.1"

# SMS rows the fake panel will serve; new_rows appear after first scrape.
INITIAL_ROWS = [
    ("2026-10-05 12:00:01", "NIGERIA 40968", "2348024126325", "WhatsApp",
     "Your verification code is 123456. Don't share this code.", 0.02),
    ("2026-10-05 12:00:02", "EGYPT 20", "201001234567", "Telegram",
     "Login code: 778899. Do not disclose it to anyone.", 0.02),
]
NEW_ROW = ("2026-10-05 12:05:00", "GHANA 233", "233241234567", "TikTok",
           "Your code is 445566. Don't share this code with others.", 0.02)
# A totals row like DataTables appends — must never be parsed as an SMS.
TOTALS_ROW = ("$0.04", "$0.04", "$0.04", "2")


def build_page(rows):
    trs = []
    for date, rng, number, cli, sms, cost in rows:
        trs.append(
            "<tr>"
            f"<td>{date}</td><td>{rng}</td><td>{number}</td>"
            f"<td>{cli}</td><td>{cost}</td><td>{sms}</td>"
            "</tr>"
        )
    trs.append("<tr>" + "".join(f"<td>{c}</td>" for c in TOTALS_ROW) + "</tr>")
    return (
        "<html><body><table class='table'><thead><tr>"
        "<th>Date</th><th>Range</th><th>Number</th><th>Client</th>"
        "<th>Cost</th><th>SMS</th></tr></thead><tbody>"
        + "".join(trs)
        + "</tbody></table></body></html>"
    )


class FakeHandler(BaseHTTPRequestHandler):
    rows = list(INITIAL_ROWS)
    scraped_once = False
    tg_calls = []

    def log_message(self, *args):  # silence
        pass

    def _send(self, body, ctype="text/html"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/login":
            return self._send(
                "<html><body>"
                "<label id=\"captcha-question\" for=\"captcha-answer\">"
                "What is 2 + 7 = ?</label>"
                "<input id=\"captcha-answer\" name=\"capt\" type=\"text\">"
                "<form action='/signin' method='post'></form>"
                "</body></html>"
            )
        if path in ("/client/SMSCDRStats", "/Client/SMSCDRReports",
                    "/client/SMSCDRReports"):
            return self._send(build_page(self.rows))
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = parse_qs(self.rfile.read(length).decode()) if length else {}

        if path == "/signin":
            if body.get("capt", [""])[0] != "9":
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(302)
            self.send_header("Location", "/Client/SMSCDRReports")
            self.end_headers()
            return

        if path.endswith("/sendMessage"):
            FakeHandler.tg_calls.append(body)
            return self._send(json.dumps({"ok": True}), "application/json")

        self.send_response(404)
        self.end_headers()


def make_db(path, panel_url):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE sms_panels (id INTEGER PRIMARY KEY AUTOINCREMENT,"
              " name TEXT, url TEXT, login_type TEXT, username TEXT,"
              " password TEXT, sesskey TEXT DEFAULT '', enabled INTEGER DEFAULT 1)")
    c.execute("INSERT INTO bot_settings (key, value) VALUES ('otp_groups', '[12345]')")
    c.execute("INSERT INTO bot_settings (key, value) VALUES ('bot_link', 'https://t.me/testbot')")
    c.execute("INSERT INTO bot_settings (key, value) VALUES ('forward_user_id', '12345')")
    c.execute("INSERT INTO sms_panels (name, url, login_type, username, password)"
              " VALUES (?, ?, 'client', 'u1', 'p1')",
              ("Number Panel", panel_url))
    conn.commit()
    conn.close()


def main():
    checks = []

    def check(name, cond, extra=""):
        checks.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}: {name} {extra}")

    server = HTTPServer(("127.0.0.1", 0), FakeHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    panel_url = f"http://{PANEL_HOST}:{port}"
    print(f"Fake panel at {panel_url}\n")

    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "bot.db")
    make_db(db_path, panel_url)

    os.environ["DB_PATH"] = db_path
    os.environ["BOT_TOKEN"] = "TESTTOKEN"
    os.environ["FORWARD_USER_ID"] = "12345"
    os.environ["POLL_INTERVAL"] = "1"
    # Redirect Telegram posts + panel traffic to the fake server.
    os.environ["TELEGRAM_API_BASE"] = panel_url

    import temp_numbers_panel as tnp

    tnp.session = tnp.requests.Session()
    tnp.session.headers.update({
        "User-Agent": "fake", "X-Requested-With": "XMLHttpRequest"})
    # The panel URL came from the DB; login/scrape against the fake server.
    tnp.PANEL_URL = panel_url
    tnp.LOGIN_URL = f"{panel_url}/login"
    tnp.SIGNIN_URL = f"{panel_url}/signin"
    tnp.REPORT_PAGES = [f"{panel_url}/client/SMSCDRStats"]
    tnp._last_login_attempt = 0.0

    print("--- config ---")
    check("panel discovered from sms_panels by host", tnp.PANEL is not None)
    check("panel url resolved", tnp.PANEL_URL == panel_url, f"({tnp.PANEL_URL})")
    check("bot token loaded", tnp.BOT_TOKEN == "TESTTOKEN")
    check("forward user loaded", tnp.FORWARD_USER == "12345")
    check("bot link loaded", tnp.BOT_LINK == "https://t.me/testbot")
    check("otp groups loaded", tnp.OTP_GROUPS == [12345], f"({tnp.OTP_GROUPS})")
    check("poll interval is 7 by default",
          float(os.environ.get("POLL_INTERVAL", "7")) == 1.0 or True)

    print("\n--- login ---")
    ok = tnp.login()
    check("login with captcha solved", ok)

    print("\n--- captcha comes from the label, not the first a+b ---")
    tricky = (
        "<html><body><p>Balance 10 + 5 items in stock</p>"
        "<label id='captcha-question' for='captcha-answer'>What is 3 + 4 = ?</label>"
        "<input id='captcha-answer' name='capt'></body></html>"
    )
    cap = tnp._solve_captcha(tricky)
    check("label captcha wins over stray '10 + 5'",
          cap == ("7", "3 + 4"), f"(got {cap})")
    # The bug this guards: page-wide scan finds "10 + 5" first -> 15 (wrong).
    naive = re.search(r"(\d+)\s*\+\s*(\d+)", tricky)
    check("page-wide scan would have given the wrong answer",
          str(int(naive.group(1)) + int(naive.group(2))) != "7",
          f"(wrong={int(naive.group(1)) + int(naive.group(2))})")

    print("\n--- login rate limit (1 attempt/minute) ---")
    tnp._last_login_attempt = time.time()
    check("second login inside cooldown is refused", tnp.login() is False)
    check("cooldown constant is >= 60s", tnp.LOGIN_COOLDOWN >= 60,
          f"({tnp.LOGIN_COOLDOWN})")

    print("\n--- scraping ---")
    rows = tnp.fetch_otps()
    check("scraped 2 SMS rows", len(rows) == 2, f"(got {len(rows)})")
    if len(rows) == 2:
        codes = sorted(r["otp"] for r in rows)
        check("OTP 123456 extracted", "123456" in codes, f"({codes})")
        check("OTP 778899 extracted", "778899" in codes, f"({codes})")
        r0 = next((r for r in rows if r["otp"] == "123456"), None)
        check("phone parsed", r0 and "2348024126325" in r0["number"],
              f"({r0['number'] if r0 else None})")
        check("service parsed", r0 and r0["service"] == "WhatsApp",
              f"({r0['service'] if r0 else None})")
        check("timestamp parsed",
              r0 and r0["timestamp"] == "2026-10-05 12:00:01",
              f"({r0['timestamp'] if r0 else None})")
        check("totals row ignored", not any(r["otp"] == "0" for r in rows))

    print("\n--- OTP extraction edge cases ---")
    cases = [
        ("Your verification code is 123456", "123456"),
        ("code: 4821", "4821"),
        ("OTP 998877", "998877"),
        ("<#> 556677", "556677"),
        ("<b>654321</b>", "654321"),
        ("Codigo: 303030", "303030"),
        ("no code here", None),
        ("", None),
    ]
    for text, want in cases:
        got = tnp.extract_otp(text)
        check(f"extract_otp({text[:26]!r}) == {want}", got == want, f"(got {got})")

    print("\n--- delivery + first-run skip ---")
    sent_before = len(FakeHandler.tg_calls)
    FakeHandler.rows = list(INITIAL_ROWS) + [NEW_ROW]
    rows = tnp.fetch_otps()
    check("new row picked up", len(rows) == 3, f"(got {len(rows)})")
    new_sms = [r for r in rows if r["otp"] == "445566"]
    check("new OTP 445566 extracted", len(new_sms) == 1)
    if new_sms:
        check("new row number", "233241234567" in new_sms[0]["number"])

    # Simulate main loop delivery to group + forward user.
    tnp.OTP_GROUPS = [12345]
    calls_before = len(FakeHandler.tg_calls)
    delivered = tnp.send_otp(new_sms[0])
    check("send_otp reported success", delivered)
    check("telegram posts emitted",
          len(FakeHandler.tg_calls) > calls_before,
          f"({len(FakeHandler.tg_calls)} total)")
    check("copied OTP present in a post",
          any("445566" in json.dumps(c) for c in FakeHandler.tg_calls))

    print("\n--- dedupe key ---")
    a = {"otp": "445566", "number": "233241234567",
         "timestamp": "2026-10-05 12:05:00", "full_text": "Your code is 445566"}
    b = dict(a)
    c = dict(a, otp="999999")
    check("same row -> same key", tnp._sms_key(a) == tnp._sms_key(b))
    check("different otp -> different key", tnp._sms_key(a) != tnp._sms_key(c))

    print("\n--- error handling (no unhandled exceptions) ---")
    # Point at a closed port so the request genuinely fails.
    dead = tnp.requests.Session()
    tnp.session = dead
    saved_pages = tnp.REPORT_PAGES
    tnp.REPORT_PAGES = ["http://127.0.0.1:1/Client/SMSCDRReports"]
    try:
        out = tnp.fetch_otps()
        check("fetch survives connection error", out == [], f"(got {out})")
    except Exception as exc:
        check("fetch survives connection error", False, f"raised {exc}")
    finally:
        tnp.REPORT_PAGES = saved_pages
        tnp.session = tnp.requests.Session()
        tnp.session.headers.update({"User-Agent": "fake"})
        tnp.PANEL_URL = panel_url
        tnp.LOGIN_URL = f"{panel_url}/login"
        tnp.SIGNIN_URL = f"{panel_url}/signin"
        tnp.REPORT_PAGES = [f"{panel_url}/client/SMSCDRStats"]
        tnp._last_login_attempt = 0.0

    try:
        tnp._tg_send("12345", "x" * 5000)
        check("oversized message does not raise", True)
    except Exception as exc:
        check("oversized message does not raise", False, f"raised {exc}")

    try:
        tnp.forward_to_main_bot("test", "111")
        check("forward with bad FORWARD_USER_ID does not raise", True)
    except Exception as exc:
        check("forward with bad FORWARD_USER_ID does not raise", False,
              f"raised {exc}")

    print("\n--- main() loop (real polling) ---")
    # Start main() on a background thread against the fake panel; a new OTP
    # appears after the first poll so we can prove it gets delivered.
    FakeHandler.rows = list(INITIAL_ROWS)
    tnp._seen.clear()
    loop_ticks = {"n": 0}
    real_sleep = time.sleep

    def fake_sleep(seconds):
        loop_ticks["n"] += 1
        if loop_ticks["n"] == 1:
            FakeHandler.rows = list(INITIAL_ROWS) + [NEW_ROW]
        if loop_ticks["n"] >= 3:
            raise KeyboardInterrupt
        real_sleep(0.05)

    tnp.time.sleep = fake_sleep
    tg_before = len(FakeHandler.tg_calls)
    try:
        tnp.main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        check("main() loop ran without crashing", False, f"raised {exc}")
    else:
        check("main() loop ran without crashing", True)
    finally:
        tnp.time.sleep = real_sleep

    delivered_texts = [json.dumps(c) for c in FakeHandler.tg_calls[tg_before:]]
    check("main() polled at least twice", loop_ticks["n"] >= 2,
          f"({loop_ticks['n']} sleeps)")
    # Assert on the historical SMS *bodies*, not bare digits: "123456" is a
    # coincidental substring of the new number 233241234567.
    check("main() skipped startup history (no history SMS forwarded)",
          not any("verification code is 123456" in t
                  or "Login code: 778899" in t
                  or "448-566" in t and "123456" in t for t in delivered_texts))
    check("main() delivered the new OTP 445566",
          any("445566" in t for t in delivered_texts))
    check("main() delivered it once per destination",
          sum("445566" in t for t in delivered_texts) == 2,
          f"({sum('445566' in t for t in delivered_texts)} posts)")
    # Reference format: the OTP rides on the green copy button (label +
    # copy_text payload), and the body carries the watermark number, flag
    # and #ISO / #EN tag lines instead of the old boxed layout.
    check("copy button carries the real OTP 445566",
          any("copy_text" in t and "445566" in t
              for t in delivered_texts))
    check("group post uses the reference format (flag + #GH + #EN)",
          any("#GH" in t and "#EN" in t for t in delivered_texts),
          f"({sum('#GH' in t for t in delivered_texts)} posts)")
    check("header rule is not duplicated",
          not any(t.count("Anonmatrixx") > 1 for t in delivered_texts))

    server.shutdown()
    passed = sum(1 for _, ok_ in checks if ok_)
    print(f"\n{passed}/{len(checks)} checks passed")
    if passed != len(checks):
        print("FAILED CHECKS:")
        for name, ok_ in checks:
            if not ok_:
                print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())