#!/usr/bin/env python3
"""Tests for konekta_api_forwarder.py (no network, no Telegram).

Run:  python3 tests/test_konekta_forwarder.py
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import konekta_api_forwarder as kf  # noqa: E402
from premium_emoji import premiumize  # noqa: E402

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)


print("=== configuration defaults (the given credentials) ===")
check("default API url",
      kf.API_URL == "http://51.77.216.195/crapi/konek/viewstats", kf.API_URL)
check("default API token",
      kf.API_TOKEN == "Qk5RRUlBUzR3T5Z3RINVeXVleYpKj4ZJdWeJSHeLVoFld2dlhouZSQ==",
      kf.API_TOKEN[:12] + "...")
check("default records = 10", kf.RECORDS == 10, str(kf.RECORDS))

print("\n=== fetch_records: live API shapes (mocked HTTP) ===")
captured = {}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_get(url, params=None, timeout=None):
    captured["url"] = url
    captured["params"] = params
    return _Resp(captured["payload"])


LIVE_ROWS = [
    ["WhatsApp", "2347020296087",
     "Your WhatsApp code 734-622Dont share this code with others",
     "2026-10-07 08:45:49"],
    ["Konekta", "233201195144",
     "Meizu Verification code 241626 Retrieve password",
     "2026-10-07 05:20:23"],
]

real_get = kf.requests.get
kf.requests.get = _fake_get
try:
    captured["payload"] = LIVE_ROWS
    rows = kf.fetch_records()
    check("list payload parsed", len(rows) == 2, str(len(rows)))
    check("otp extracted", rows[0]["otp"] == "734622", rows[0]["otp"])

    captured["payload"] = {"status": "error", "msg": "No Records Found"}
    empty = kf.fetch_records()
    check("'No Records Found' -> [] (no crash)", empty == [], str(empty))

    # The REAL success payload observed live (2026-10-07 19:10): a dict
    # with status/total/data, rows keyed dt/num/cli/message — this shape
    # was previously dropped wholesale, so nothing reached the group.
    captured["payload"] = {
        "status": "success", "total": 1,
        "data": [{
            "dt": "2026-10-07 19:02:26", "num": "263787140515",
            "cli": "PayPal",
            "message": "# PayPal Your security code is 980088 Your code "
                       "expires in 10 minutes Please dont reply 33p3o0TedB",
            "payout": "0.015",
        }],
    }
    ok_rows = kf.fetch_records()
    check("success dict payload parsed", len(ok_rows) == 1,
          str(len(ok_rows)))
    check("num -> number", ok_rows and ok_rows[0]["number"] == "263787140515",
          str(ok_rows and ok_rows[0].get("number")))
    check("dt -> timestamp",
          ok_rows and ok_rows[0]["timestamp"] == "2026-10-07 19:02:26",
          str(ok_rows and ok_rows[0].get("timestamp")))
    check("cli -> service", ok_rows and ok_rows[0]["service"] == "PayPal",
          str(ok_rows and ok_rows[0].get("service")))
    check("otp extracted from 'code is 980088'",
          ok_rows and ok_rows[0]["otp"] == "980088",
          str(ok_rows and ok_rows[0].get("otp")))
    captured["payload"] = {"status": "success", "total": 0, "data": []}
    check("success with empty data -> []", kf.fetch_records() == [])

    captured["payload"] = {"status": "error", "msg": "Invalid Authtype"}
    auth = kf.fetch_records()
    check("auth error -> [] (logged, no crash)", auth == [], str(auth))

    captured["payload"] = {"status": "error", "msg": "Not Authorized"}
    check("missing token -> [] (no crash)", kf.fetch_records() == [])
    check("sends the token", captured["params"].get("token") == kf.API_TOKEN,
          str(captured["params"]))
    check("sends records", captured["params"].get("records") == 10,
          str(captured["params"]))
    check("hits the configured endpoint", captured["url"] == kf.API_URL,
          captured["url"])
finally:
    kf.requests.get = real_get

print("\n=== send_otp builds the reference group format ===")
sent_calls = []


def capture_tg(chat_id, text, reply_markup=None):
    sent_calls.append((chat_id, text, reply_markup))
    return True


real_groups, real_token, real_send = kf.OTP_GROUPS, kf.BOT_TOKEN, kf._tg_send
kf.OTP_GROUPS = [-1004435037471]
kf.BOT_TOKEN = "TEST:TOKEN"
kf._tg_send = capture_tg
try:
    ok = kf.send_otp(rows[0])
finally:
    kf._tg_send, kf.OTP_GROUPS, kf.BOT_TOKEN = real_send, real_groups, real_token

check("delivered", ok is True)
check("one send call", len(sent_calls) == 1, str(len(sent_calls)))
chat_id, body, kb = sent_calls[0]
check("sent to the group", chat_id == -1004435037471, str(chat_id))
check("body has watermark number", "+2347●○●○6087" in body, body)
check("body has #ISO tag", "#NG" in body, body)
check("raw phone number is masked out", "2347020296087" not in body, body)
check("body premiumizes to <tg-emoji>", "<tg-emoji" in premiumize(body))
rows_k = kb["inline_keyboard"]
copy_btn = rows_k[0][0]
check("copy label carries the REAL otp", copy_btn["text"] == "⧉ WhatsApp | 734622",
      copy_btn["text"])
check("copy_text holds the otp", copy_btn.get("copy_text", {}).get("text")
      == "734622", str(copy_btn.get("copy_text")))
check("copy button has a premium app icon",
      bool(copy_btn.get("icon_custom_emoji_id")), str(copy_btn))
link_btns = rows_k[1]
check("NUMBER + CHANNEL row",
      [b["text"] for b in link_btns] == ["NUMBER", "CHANNEL"], str(link_btns))
check("CHANNEL points at the new channel",
      link_btns[1].get("url") == "https://t.me/Anonmatrixx_channel",
      str(link_btns[1].get("url")))
check("link buttons carry icon ids",
      all(b.get("icon_custom_emoji_id") for b in link_btns), str(link_btns))

print("\n=== copy_text rejection falls back to copy_<otp> callback ===")
attempts = []


def reject_copy(chat_id, text, reply_markup=None):
    attempts.append(reply_markup)
    has_copy = any("copy_text" in b
                   for row in (reply_markup or {}).get("inline_keyboard", [])
                   for b in row)
    return not has_copy


kf.OTP_GROUPS = [-1001]
kf._tg_send = reject_copy
try:
    fallback_kb = {"inline_keyboard": [[
        {"text": "⧉ WhatsApp | 734622", "style": "success",
         "copy_text": {"text": "734622"}},
    ]]}
    ok_fb = kf.send_to_groups("body", fallback_kb, "734622")
finally:
    kf._tg_send, kf.OTP_GROUPS = real_send, real_groups
check("delivery succeeds after downgrade", ok_fb is True)
check("two attempts made", len(attempts) == 2, str(len(attempts)))

print("\n=== dedupe / delivery semantics ===")
sent_keys = []
real_seen, real_send_otp = kf._seen, kf.send_otp
kf._seen = set()
kf.send_otp = lambda sms: sent_keys.append(sms["otp"]) or True
try:
    # The panel's current records must reach the group immediately (this
    # is what "didn't drop in otp grp" was about) — no startup skip.
    n_first = kf.handle_rows(rows)
    after_first = list(sent_keys)
    n_dup = kf.handle_rows(rows)
    after_dup = list(sent_keys)
    fresh = [dict(rows[0], otp="999111", timestamp="2026-10-07 09:00:00")]
    n_new = kf.handle_rows(fresh)
finally:
    kf.send_otp = real_send_otp
    kf._seen = real_seen
check("current records are posted immediately",
      n_first == 2 and after_first == ["734622", "241626"],
      f"{n_first} {after_first}")
check("repeat rows are deduped", n_dup == 0 and after_dup == ["734622", "241626"],
      f"{n_dup} {after_dup}")
check("new row is forwarded once", n_new == 1 and sent_keys[-1] == "999111",
      str(sent_keys))

print("\n=== failed delivery is retried ===")
kf._seen = set()
calls = {"n": 0}


def fail_once(sms):
    calls["n"] += 1
    return calls["n"] > 1


kf.send_otp = fail_once
try:
    kf.handle_rows(rows)
    retry_sent = kf.handle_rows(rows)
finally:
    kf.send_otp = real_send_otp
    kf._seen = real_seen
check("failed row stays unseen and is retried", retry_sent == 1,
      f"calls={calls['n']} retry_sent={retry_sent}")

print("\n=== state isolation from the temp numbers forwarder ===")
import temp_numbers_api_forwarder as tf  # noqa: E402
check("separate dedupe sets", kf._seen is not tf._seen)
check("separate send functions", kf.send_otp is not tf.send_otp)

print("\n=== heartbeat ===")
hb = []
kf._tg_send = lambda gid, text, reply_markup=None: hb.append((gid, text)) or True
kf.OTP_GROUPS = [-1004435037471]
try:
    kf._heartbeat()
finally:
    kf._tg_send = real_send
    kf.OTP_GROUPS = real_groups
check("heartbeat posted to the first group", hb and hb[0][0] == -1004435037471,
      str(hb))
check("heartbeat announces the panel", "KONEKTA" in (hb[0][1] if hb else ""),
      str(hb))

print("\n=== run() safety ===")
real_env = os.environ.get("KONEKTA_FORWARDER")
os.environ["KONEKTA_FORWARDER"] = "0"
try:
    kf.run()
    check("disabled via env returns cleanly", True)
finally:
    if real_env is None:
        os.environ.pop("KONEKTA_FORWARDER", None)
    else:
        os.environ["KONEKTA_FORWARDER"] = real_env

# Missing config must NOT abort the forwarder (the old early return left
# the group completely silent): run() logs once and retries every poll.
os.environ.pop("KONEKTA_FORWARDER", None)
real_rc, real_poll = kf.resolve_config, kf.POLL_INTERVAL
kf.resolve_config = lambda: (None, [])
kf.POLL_INTERVAL = 0.05
retry_thread = threading.Thread(target=kf.run, daemon=True)
retry_thread.start()
time.sleep(0.3)
check("run() retries instead of exiting on missing config",
      retry_thread.is_alive(),
      "thread died" if not retry_thread.is_alive() else "")
check("resolve_config with no settings still yields the default group",
      real_rc()[1] == [-1004435037471], str(real_rc()[1]))
# the daemon thread stays parked on the never-ready config; process exit
# cleans it up.

print("\n=== default group fallback (bot.py seeds otp_groups as '[]') ===")
import temp_numbers_api_forwarder as tf_mod  # noqa: E402
real_gs = tf_mod.get_setting
tf_mod.get_setting = lambda k, d=None: "[]" if k == "otp_groups" else None
try:
    fb_groups = kf.get_otp_groups()
finally:
    tf_mod.get_setting = real_gs
check("empty otp_groups falls back to bot.py's default group",
      fb_groups == [-1004435037471], str(fb_groups))

print("\n=== _tg_send retries without premium tags on HTTP 400 ===")


class _Resp:
    def __init__(self, code, body):
        self.status_code = code
        self.text = body


post_calls = []


def _fake_post(url, data=None, timeout=None):
    post_calls.append(dict(data))
    if len(post_calls) == 1:
        return _Resp(400, "Bad Request: cannot parse entities")
    return _Resp(200, "OK")


real_post, real_token3 = kf.requests.post, kf.BOT_TOKEN
kf.BOT_TOKEN = "TEST:TOKEN"
kf.requests.post = _fake_post
try:
    premium_text = ('<tg-emoji emoji-id="5294422158762592930">🇿🇼</tg-emoji>'
                    ' #ZW +2637●○●○0515')
    ok_retry = kf._tg_send(-1001, premium_text, {"inline_keyboard": []})
finally:
    kf.requests.post = real_post
check("retried and delivered", ok_retry is True, str(ok_retry))
check("two API calls made", len(post_calls) == 2, str(len(post_calls)))
check("retry stripped the tg-emoji tags",
      len(post_calls) == 2 and "<tg-emoji" not in post_calls[1]["text"],
      str(post_calls[1].get("text")) if len(post_calls) > 1 else "")
check("retry kept the plain glyphs",
      len(post_calls) == 2 and "🇿🇼" in post_calls[1]["text"],
      str(post_calls[1].get("text")) if len(post_calls) > 1 else "")

post_calls.clear()
kf.requests.post = _fake_post
try:
    ok_plain = kf._tg_send(-1001, "plain text without premium tags")
finally:
    kf.requests.post = real_post
    kf.BOT_TOKEN = real_token3
check("plain-text failure does not retry",
      ok_plain is False and len(post_calls) == 1,
      f"{ok_plain} {len(post_calls)}")

print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL KONEKTA FORWARDER TESTS PASSED")
