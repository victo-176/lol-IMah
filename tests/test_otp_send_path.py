#!/usr/bin/env python3
"""End-to-end check of the OTP group send path with a stub transport.

Exercises bot.py's real send_to_telegram_group / post_otp_group against a
fake requests.post, so the exact Telegram payload (reference format text +
keyboard) and every fallback (copy_text rejected, HTML parse rejected, 429)
are inspected without a live bot. Requires telebot, like the other tests
that import bot.py.
"""
import json
import sys

sys.path.insert(0, ".")

import bot  # noqa: E402

calls = []


class FakeResp:
    def __init__(self, status=200, text='{"ok":true,"result":{"message_id":42}}'):
        self.status_code = status
        self.text = text


def fake_post(url, data=None, timeout=None):
    calls.append((url.split("/")[-1], dict(data or {})))
    return FakeResp()


bot.requests.post = fake_post
settings = {"otp_groups": '["-1001"]', "bot_link": "https://t.me/bot"}
bot.get_setting = lambda k, d=None: settings.get(k, d)

fails = []


def check(name, cond, detail=""):
    print(("PASS: " if cond else "FAIL: ") + name + (" -- " + detail if not cond else ""))
    if not cond:
        fails.append(name)


# --- happy path: IVASMS sender -------------------------------------------------
text, kb = bot.build_otp_group_message(
    "+263771238206", "030061", "paypal", "ZW",
    number_link="https://t.me/num", channel_link="https://t.me/ch")
bot.send_to_telegram_group(text, "030061", "+263771238206", kb)

check("one sendMessage call", len(calls) == 1, str(len(calls)))
method, payload = calls[0]
body = payload.get("text", "")
check("body has one line (no language tag)", body.count("\n") == 0, repr(body))
check("body premiumized", "<tg-emoji" in body, body[:120])
check("body has #ZW, no #EN/#AR tag", "#ZW" in body and "#EN" not in body and "#AR" not in body, body)
check("body has watermark number", "+2637....8206" in body, body)
check("parse_mode kept", payload.get("parse_mode") == "HTML")

markup = json.loads(payload["reply_markup"])
copy_btn = markup["inline_keyboard"][0][0]
row2 = markup["inline_keyboard"][1]
check("copy_text carries real OTP", copy_btn.get("copy_text", {}).get("text") == "030061", str(copy_btn))
check("copy button green + app icon",
      copy_btn.get("style") == "success"
      and copy_btn.get("icon_custom_emoji_id") == "5364111181415996352", str(copy_btn))
check("copy label = Service | OTP", "PayPal | 030061" in copy_btn["text"], copy_btn["text"])
check("NUMBER/CHANNEL urls",
      row2[0].get("url") == "https://t.me/num" and row2[1].get("url") == "https://t.me/ch", str(row2))
check("link buttons blue with icons",
      all(b.get("style") == "primary" and b.get("icon_custom_emoji_id") for b in row2), str(row2))

# --- fallback 1: server rejects copy_text -> copy_<otp> callback ---------------
calls.clear()


def reject_copy(url, data=None, timeout=None):
    calls.append((url.split("/")[-1], dict(data or {})))
    if "copy_text" in (data or {}).get("reply_markup", ""):
        return FakeResp(400, '{"ok":false,"description":"Bad Request: REPLY_MARKUP_INVALID"}')
    return FakeResp()


bot.requests.post = reject_copy
ok, rate, mid = bot.post_otp_group("-1001", text, kb, "030061", tag="TEST")
check("sends after downgrading copy button", ok and mid == 42, f"ok={ok} mid={mid} rate={rate}")
check("exactly two attempts", len(calls) == 2, str(len(calls)))
first = json.loads(calls[0][1]["reply_markup"])["inline_keyboard"][0][0]
second = json.loads(calls[1][1]["reply_markup"])["inline_keyboard"][0][0]
check("first attempt used copy_text", "copy_text" in first, str(first))
check("second attempt uses copy_<otp>", second.get("callback_data") == "copy_030061", str(second))
check("second attempt keeps the label", second["text"] == first["text"], str(second))

# --- fallback 2: parse error -> tags stripped, no parse_mode -------------------
calls.clear()


def reject_html(url, data=None, timeout=None):
    calls.append((url.split("/")[-1], dict(data or {})))
    if (data or {}).get("parse_mode"):
        return FakeResp(400, '{"ok":false,"description":"Bad Request: can\'t parse entities: unclosed tag"}')
    return FakeResp()


bot.requests.post = reject_html
ok, rate, mid = bot.post_otp_group("-1001", text, kb, "030061", tag="TEST")
check("sends after stripping tags", ok, f"ok={ok}")
plain = calls[1]
check("retry has no parse_mode", "parse_mode" not in plain[1], str(list(plain[1].keys())))
check("retry text has no <tg-emoji>", "<tg-emoji" not in plain[1]["text"], plain[1]["text"][:80])
check("retry still carries the keyboard", "reply_markup" in plain[1])

# --- fallback 3: 429 -> rate hint ---------------------------------------------
calls.clear()


def rate_limited(url, data=None, timeout=None):
    calls.append((url.split("/")[-1], dict(data or {})))
    return FakeResp(429, '{"ok":false,"description":"Too Many Requests: retry after 7"}')


bot.requests.post = rate_limited
ok, rate, mid = bot.post_otp_group("-1001", text, kb, "030061", tag="TEST")
check("429 returns rate hint", not ok and rate == 8, f"ok={ok} rate={rate}")

# --- helpers ------------------------------------------------------------------
check("iso from number", bot._otp_group_iso("+962781239030", None) == "JO",
      bot._otp_group_iso("+962781239030", None))
check("iso from clean hint", bot._otp_group_iso("N/A", "zw") == "ZW",
      bot._otp_group_iso("N/A", "zw"))
check("iso from country name hint", bot._otp_group_iso("bad", "Zimbabwe") == "ZW",
      bot._otp_group_iso("bad", "Zimbabwe"))
links = bot._otp_group_links()
check("links resolve", links[0].startswith("http") and links[1].startswith("http"), str(links))

print()
print("ALL PASSED" if not fails else "FAILURES: " + ", ".join(fails))
sys.exit(1 if fails else 0)
