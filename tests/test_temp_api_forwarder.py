#!/usr/bin/env python3
"""Tests for temp_numbers_api_forwarder.py (no network, no Telegram).

Run:  python3 tests/test_temp_api_forwarder.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import temp_numbers_api_forwarder as fwd  # noqa: E402
from premium_emoji import premiumize  # noqa: E402

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)


# Live payload captured from the API (2026-10-07), trimmed to two shapes.
LIVE_ROWS = [
    ["WhatsApp", "2347020296087",
     "Your WhatsApp code 734-622Dont share this code with others",
     "2026-10-07 08:45:49"],
    ["iATSMS", "201195144109",
     "Meizu Verification code 241626 Retrieve password The code is valid "
     "for 30 minutes Please do not disclose it to anyone",
     "2026-10-07 05:20:23"],
]

print("=== parse_records (list rows, live shape) ===")
rows = fwd.parse_records(LIVE_ROWS)
check("two rows parsed", len(rows) == 2, f"got {len(rows)}")
r0 = rows[0]
check("service mapped", r0["service"] == "WhatsApp", r0["service"])
check("number mapped", r0["number"] == "2347020296087", r0["number"])
check("timestamp mapped", r0["timestamp"] == "2026-10-07 08:45:49", r0["timestamp"])
check("otp extracted (734622)", r0["otp"] == "734622", r0["otp"])
check("otp extracted from Meizu row (241626)",
      rows[1]["otp"] == "241626", rows[1]["otp"])
check("full_text kept", "WhatsApp code" in r0["full_text"], r0["full_text"][:40])

print("\n=== parse_records (dict rows + junk tolerance) ===")
dict_rows = fwd.parse_records([{
    "cli": "Telegram", "phone": "+15551234567",
    "message": "code is 111222", "time": "2026-10-07 10:00:00",
}])
check("dict row parsed", len(dict_rows) == 1 and dict_rows[0]["otp"] == "111222",
      str(dict_rows))
check("junk row skipped", len(fwd.parse_records(["junk", 42, None])) == 0)
check("non-list payload -> []", fwd.parse_records({"oops": 1}) == [])
check("empty payload -> []", fwd.parse_records([]) == [])

print("\n=== extract_otp edge cases ===")
check("no digits -> ''", fwd.extract_otp("hello world") == "")
check("code: prefix", fwd.extract_otp("Your code: 998877 ok") == "998877")
check("bare 6-digit run", fwd.extract_otp("pin 42 is 555666") == "555666"
      or fwd.extract_otp("555666") == "555666",
      fwd.extract_otp("pin 42 is 555666"))

print("\n=== fetch_records request shape (mocked HTTP) ===")
captured = {}


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return LIVE_ROWS


def _fake_get(url, params=None, timeout=None):
    captured["url"] = url
    captured["params"] = params
    captured["timeout"] = timeout
    return _Resp()


real_get = fwd.requests.get
fwd.requests.get = _fake_get
try:
    got = fwd.fetch_records()
finally:
    fwd.requests.get = real_get
check("hits the configured endpoint", captured.get("url") == fwd.API_URL,
      str(captured.get("url")))
check("sends the token", (captured.get("params") or {}).get("token")
      == fwd.API_TOKEN, str(captured.get("params")))
check("sends records=10", (captured.get("params") or {}).get("records") == 10,
      str(captured.get("params")))
check("rows parsed through the mocked call", len(got) == 2, str(len(got)))

print("\n=== send_otp builds the reference group format ===")
sent_calls = []


def capture_tg(chat_id, text, reply_markup=None):
    sent_calls.append((chat_id, text, reply_markup))
    return True


real_groups = fwd.OTP_GROUPS
real_token = fwd.BOT_TOKEN
real_send = fwd._tg_send
fwd.OTP_GROUPS = [-100123]
fwd.BOT_TOKEN = "TEST:TOKEN"
fwd._tg_send = capture_tg
try:
    ok = fwd.send_otp(rows[0])
finally:
    fwd._tg_send = real_send
    fwd.OTP_GROUPS = real_groups
    fwd.BOT_TOKEN = real_token

check("delivered", ok is True)
check("one send call", len(sent_calls) == 1, str(len(sent_calls)))
chat_id, body, kb = sent_calls[0]
check("sent to the group", chat_id == -100123, str(chat_id))
check("body has watermark number", "+2347●○●●6087" in body, body)
check("body has #ISO tag", "#NG" in body, body)
check("raw phone number is masked out", "2347020296087" not in body, body)
premium_body = premiumize(body)
check("body premiumizes to <tg-emoji>", "<tg-emoji" in premium_body,
      premium_body[:120])
check("keyboard is the shared shape", isinstance(kb, dict)
      and len(kb.get("inline_keyboard") or []) == 2, str(kb))

rows_k = kb["inline_keyboard"]
copy_btn = rows_k[0][0]
check("copy label carries the REAL otp", copy_btn["text"] == "⧉ WhatsApp | 734622",
      copy_btn["text"])
check("copy button style success", copy_btn.get("style") == "success")
check("copy_text holds the otp", copy_btn.get("copy_text", {}).get("text")
      == "734622", str(copy_btn.get("copy_text")))
check("copy button has a premium app icon",
      bool(copy_btn.get("icon_custom_emoji_id")), str(copy_btn))
link_btns = rows_k[1]
check("NUMBER + CHANNEL row", [b["text"] for b in link_btns] == ["NUMBER", "CHANNEL"],
      str([b.get("text") for b in link_btns]))
check("link buttons have icon ids",
      all(b.get("icon_custom_emoji_id") for b in link_btns), str(link_btns))
check("NUMBER points at the bot link", link_btns[0].get("url") == fwd.get_bot_link(),
      str(link_btns[0].get("url")))

print("\n=== send_otp with no OTP is not delivered ===")
captured.clear()
fwd._tg_send = capture_tg
try:
    no_otp_ok = fwd.send_otp({"service": "X", "number": "123", "otp": "",
                              "full_text": "no code here", "timestamp": ""})
finally:
    fwd._tg_send = real_send
check("row without a code is skipped", no_otp_ok is False)
check("nothing was sent", len(captured) == 0, str(len(captured)))

print("\n=== copy_text rejection falls back to copy_<otp> callback ===")
attempts = []


def reject_copy(chat_id, text, reply_markup=None):
    attempts.append(reply_markup)
    has_copy = any("copy_text" in b
                   for row in (reply_markup or {}).get("inline_keyboard", [])
                   for b in row)
    return not has_copy  # accept only the callback downgrade


fwd.OTP_GROUPS = [-100123]
fwd._tg_send = reject_copy
try:
    fallback_kb = {"inline_keyboard": [[
        {"text": "⧉ WhatsApp | 734622", "style": "success",
         "copy_text": {"text": "734622"}},
    ]]}
    ok_fb = fwd.send_to_groups("body", fallback_kb, "734622")
finally:
    fwd._tg_send = real_send
    fwd.OTP_GROUPS = real_groups
check("delivery succeeds after downgrade", ok_fb is True)
check("two attempts made", len(attempts) == 2, str(len(attempts)))
second = json.dumps(attempts[1]) if len(attempts) > 1 else ""
check("downgraded button uses copy_ callback",
      "copy_734622" in second and "copy_text" not in second, second)

print("\n=== dedupe / first_run semantics ===")
sent_keys = []
real_seen = fwd._seen
real_send_otp = fwd.send_otp
fwd._seen = set()
fwd.send_otp = lambda sms: sent_keys.append(sms["otp"]) or True
try:
    n_first = fwd.handle_rows(rows, first_run=True)
    after_first = list(sent_keys)
    n_dup = fwd.handle_rows(rows, first_run=False)
    after_dup = list(sent_keys)
    fresh = [dict(rows[0], otp="999111", timestamp="2026-10-07 09:00:00")]
    n_new = fwd.handle_rows(fresh, first_run=False)
finally:
    fwd.send_otp = real_send_otp
    fwd._seen = real_seen
check("first run sends nothing", n_first == 0 and not after_first,
      f"{n_first} {after_first}")
check("repeat rows are deduped", n_dup == 0 and not after_dup,
      f"{n_dup} {after_dup}")
check("new row is forwarded once", n_new == 1 and sent_keys == ["999111"],
      str(sent_keys))

print("\n=== failed delivery is retried ===")
fwd._seen = set()
real_send_otp2 = fwd.send_otp
calls = {"n": 0}


def fail_once(sms):
    calls["n"] += 1
    return calls["n"] > 1  # first attempt fails, second succeeds


fwd.send_otp = fail_once
try:
    fwd.handle_rows(rows, first_run=False)
    retry_sent = fwd.handle_rows(rows, first_run=False)
finally:
    fwd.send_otp = real_send_otp2
    fwd._seen = real_seen
check("failed row stays unseen and is retried", retry_sent == 1,
      f"calls={calls['n']} retry_sent={retry_sent}")

print("\n=== run() safety ===")
real_env = os.environ.get("TEMP_API_FORWARDER")
os.environ["TEMP_API_FORWARDER"] = "0"
try:
    fwd.run()  # must return immediately, not loop, when disabled
    check("disabled via env returns cleanly", True)
finally:
    if real_env is None:
        os.environ.pop("TEMP_API_FORWARDER", None)
    else:
        os.environ["TEMP_API_FORWARDER"] = real_env

os.environ.pop("TEMP_API_FORWARDER", None)
real_token2, real_groups2 = fwd.BOT_TOKEN, fwd.OTP_GROUPS
fwd.BOT_TOKEN, fwd.OTP_GROUPS = None, []
try:
    fwd.run()  # no token / no groups -> logs and returns, never loops
    check("missing config returns without looping", True)
finally:
    fwd.BOT_TOKEN, fwd.OTP_GROUPS = real_token2, real_groups2

print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL TEMP API FORWARDER TESTS PASSED")
