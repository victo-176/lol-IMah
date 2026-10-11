#!/usr/bin/env python3
"""
Telegram 4096-char limit: long forwarded messages must be split into chunks.

Covers the real splitter (split_html_message) and the real send paths
(post_otp_group + send_html_safe) against a fake transport that enforces the
same 4096-char limit Telegram enforces, plus the retry/backoff behaviour.
"""
import json
import os
import re
import sys
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

botmod.CHUNK_RETRY_BACKOFF = 0.0  # keep the retry test fast

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)


LIMIT = botmod.TELEGRAM_TEXT_LIMIT
check("limit is 4096", LIMIT == 4096, str(LIMIT))

# ------------------------------------------------------------------ splitter
print("\n=== split_html_message ===")

short = "<b>Hi</b> your code is <code>123456</code>"
check("3000 chars -> 1 chunk",
      len(botmod.split_html_message("x" * 3000)) == 1)
check("short message unchanged", botmod.split_html_message(short) == [short])

exact = "y" * LIMIT
chunks = botmod.split_html_message(exact)
check("exactly 4096 -> 1 chunk", len(chunks) == 1, str(len(chunks)))
check("exactly 4096 chunk is the text", chunks == [exact])

long_body = ("Full SMS body line with details. " * 200)  # ~6200 chars
chunks = botmod.split_html_message(long_body)
check("6000+ chars -> 2 chunks", len(chunks) == 2, str(len(chunks)))
check("all chunks within limit", all(len(c) <= LIMIT for c in chunks),
      str([len(c) for c in chunks]))
check("joined content equals original",
      " ".join(chunks).strip() == long_body.strip(),
      f"{len(' '.join(chunks))} vs {len(long_body)}")

# newline preference
lines = "".join("line %d " % i + "payload " * 10 + "\n" for i in range(60))
chunks = botmod.split_html_message(lines)
check("multi-line long body splits", len(chunks) > 1, str(len(chunks)))
check("chunk boundaries prefer newlines", chunks[1].startswith("line "),
      repr(chunks[1][:20]))
src_words = set(lines.split())
check("no chunk ends mid-word",
      all(c.split()[-1] in src_words for c in chunks[:-1]),
      repr([c.split()[-1] for c in chunks[:-1]][-3:]))

# never split inside a tag / entity, tags balanced per chunk
emoji = '<tg-emoji emoji-id="5233354831984353090">🙂</tg-emoji>'
tagged = ("<b>BODY:</b> " + (emoji + " code &amp; details " * 30) * 80)
chunks = botmod.split_html_message(tagged)
check("emoji-heavy body splits", len(chunks) > 1, str(len(chunks)))
check("every chunk within limit", all(len(c) <= LIMIT for c in chunks),
      str([len(c) for c in chunks]))
open_tags = re.findall(r'<tg-emoji[^>]*>(?!.*</tg-emoji>)', "".join(chunks))
check("no tag split across chunks", not open_tags, str(open_tags[:2]))
unbalanced = [c for c in chunks if c.count("<b>") != c.count("</b>")
              or c.count("<tg-emoji") != c.count("</tg-emoji>")]
check("every chunk has balanced tags", not unbalanced, str(unbalanced[:1]))
def _no_tags(s):
    # Whitespace at a chunk boundary is dropped on purpose (Telegram renders
    # it identically), so compare with all whitespace removed.
    return re.sub(r"\s+", "", re.sub(r"</?(?:b|tg-emoji)[^>]*>", "", s))


check("rejoining chunks reproduces the text", _no_tags("".join(chunks)) == _no_tags(tagged),
      f"{len(_no_tags(''.join(chunks)))} vs {len(_no_tags(tagged))}")

# long single word (unsplittable atom) still yields chunks
url_body = "see http://x.tld/" + ("a" * 5000)
chunks = botmod.split_html_message(url_body)
check("huge single word still within limit", all(len(c) <= LIMIT for c in chunks),
      str([len(c) for c in chunks]))

# ------------------------------------------------------------------ transport
print("\n=== post_otp_group with the 4096 limit ===")

sent_payloads = []
state = {"fail_times": {}, "rejected_long": 0}


class FakeResp:
    def __init__(self, status=200, text='{"ok":true,"result":{"message_id":42}}'):
        self.status_code = status
        self.text = text


def fake_post(url, data=None, timeout=None):
    payload = dict(data or {})
    sent_payloads.append(payload)
    body = payload.get("text", "")
    if len(body) > LIMIT:
        state["rejected_long"] += 1
        return FakeResp(400, '{"ok":false,"description":"Bad Request: message is too long"}')
    key = payload.get("chat_id")
    n = state["fail_times"].get(key, 0)
    if n:
        state["fail_times"][key] = n - 1
        return FakeResp(400, '{"ok":false,"description":"Bad Request: bogus failure"}')
    return FakeResp(200, json.dumps({"ok": True, "result": {"message_id": 40 + len(sent_payloads)}}))


botmod.requests.post = fake_post
botmod.premiumize = lambda t, force=False: t
botmod._schedule_delete = lambda *a, **k: None
botmod.get_setting = lambda k, d=None: {"otp_groups": '["-1001"]'}.get(k, d)

kb = {"inline_keyboard": [[{"text": "Copy", "copy_text": {"text": "123456"}}]]}
big_text = "Message line with &amp; entity " * 220  # ~7000 chars with an entity

sent_payloads.clear()
ok, rate, mid = botmod.post_otp_group("-1001", big_text, kb, "123456", tag="TEST")
check("long message sends ok", ok, f"ok={ok} rate={rate}")
check("sent as 2 chunks", len(sent_payloads) == 2, str(len(sent_payloads)))
check("both chunks within limit",
      all(len(p["text"]) <= LIMIT for p in sent_payloads),
      str([len(p["text"]) for p in sent_payloads]))
check("no chunk rejected by the transport", state["rejected_long"] == 0,
      str(state["rejected_long"]))
check("first chunk has no keyboard", "reply_markup" not in sent_payloads[0])
check("last chunk keeps the keyboard", "reply_markup" in sent_payloads[-1])
check("entity never split", all("&amp;" in p["text"] or "amp;" not in p["text"]
                                for p in sent_payloads))
joined = " ".join(p["text"] for p in sent_payloads)
check("chunk content covers the whole message", joined.count("Message") == 220,
      str(joined.count("Message")))
check("returns first message id", mid == 41, str(mid))

# single-chunk messages behave exactly as before
sent_payloads.clear()
ok, rate, mid = botmod.post_otp_group("-1001", short, kb, "123456", tag="TEST")
check("short message = one call", ok and len(sent_payloads) == 1, str(len(sent_payloads)))
check("short message keeps keyboard", "reply_markup" in sent_payloads[0])
check("short message keeps parse_mode", sent_payloads[0].get("parse_mode") == "HTML")

print("\n=== retry behaviour ===")
sent_payloads.clear()
state["fail_times"]["-1002"] = 1  # first chunk fails once, then succeeds
ok, rate, mid = botmod.post_otp_group("-1002", big_text, kb, "123456", tag="TEST")
check("chunk retried after a failure", ok, f"ok={ok}")
check("one extra attempt was made", len(sent_payloads) == 3, str(len(sent_payloads)))

sent_payloads.clear()
state["fail_times"]["-1003"] = 99  # every attempt fails
ok, rate, mid = botmod.post_otp_group("-1003", big_text, kb, "123456", tag="TEST")
check("gives up after 3 attempts", not ok and rate == 0, f"ok={ok} rate={rate}")
check("exactly 3 attempts on the first chunk", len(sent_payloads) == 3,
      str(len(sent_payloads)))
state["fail_times"]["-1003"] = 0

print("\n=== send_html_safe chunking ===")
dm_calls = []


class FakeTeleBot:
    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        if len(text) > LIMIT:
            raise Exception("Bad Request: message is too long")
        dm_calls.append({"text": text, "parse_mode": parse_mode, "reply_markup": reply_markup})
        return pytypes.SimpleNamespace(text=text)


real_bot = botmod.bot
botmod.bot = FakeTeleBot()
try:
    dm_text = "<b>Full SMS</b> " + ("body content " * 400)
    botmod.send_html_safe(777, dm_text, reply_markup={"inline_keyboard": []})
    check("DM split into chunks", len(dm_calls) == 2, str(len(dm_calls)))
    check("DM chunks within limit", all(len(c["text"]) <= LIMIT for c in dm_calls),
          str([len(c["text"]) for c in dm_calls]))
    check("DM keeps HTML parse mode", all(c["parse_mode"] == "HTML" for c in dm_calls))
    check("DM keyboard on last chunk only",
          dm_calls[0]["reply_markup"] is None and dm_calls[1]["reply_markup"] is not None)
    dm_calls.clear()
    botmod.send_html_safe(778, "<b>ok</b> message")
    check("short DM is one call", len(dm_calls) == 1, str(len(dm_calls)))
    check("short DM keeps HTML", dm_calls[0]["parse_mode"] == "HTML")
finally:
    botmod.bot = real_bot

print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL LONG-MESSAGE TESTS PASSED")
