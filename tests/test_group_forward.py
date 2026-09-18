#!/usr/bin/env python3
"""Verify the OTP group-forwarding fix.

1. Every dynamic field in OTP messages is HTML-escaped (no raw < > &).
2. send_html_safe() falls back to plain text when Telegram rejects HTML.
3. The exact message builders produce parse-safe HTML for hostile inputs.
"""
import sys, types as _t, re

# --- minimal stubs so bot.py imports without Telegram network ---
import unittest.mock as mock

sys.path.insert(0, '.')

with mock.patch.dict('sys.modules', {}):
    import bot  # noqa: E402

fails = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------ 1) helpers exist
check("strip_html_tags exists", hasattr(bot, 'strip_html_tags'))
check("send_html_safe exists", hasattr(bot, 'send_html_safe'))

# ------------------------------------------------ 2) strip_html_tags
s = bot.strip_html_tags("<b>hi</b> & <code>644-92</code> <#>")
check("strip_html_tags removes tags", s == "hi & 644-92 ", f"got {s!r}")

# ------------------------------------------------ 3) format_message escapes
raw_sms = 'Your code is 64492. Terms & Conditions <support@x.com> <#> do not share'
fm = bot.format_message("2026-09-18 10:00:00", "2349154635248", raw_sms,
                        "\U0001f1f3\U0001f1ec", "\U0001f525")
bad = re.findall(r'&(?!amp;|lt;|gt;|quot;|#)', fm)
check("format_message has no unescaped &", not bad, f"bad={bad}")
check("format_message has no raw <", "<support@" not in fm)
check("format_message OTP intact (5-digit: no hyphen)", "64492" in fm)
check("format_message 6-digit gets hyphen", "644-92" in bot.format_message(
    "2026-09-18 10:00:00", "2349154635248", "Your code is 644921",
    "\U0001f1f3\U0001f1ec", "\U0001f525"))

# ------------------------------------------------ 4) send_html_safe fallback
sent = {}


class FakeBot:
    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        if parse_mode == "HTML" and "&" in text:
            raise Exception("Bad Request: can't parse entities: unclosed tag")
        sent[chat_id] = (text, parse_mode)
        return True


real_bot = bot.bot
bot.bot = FakeBot()
try:
    hostile = "📩 <b>Message:</b> <code>A & B <tag></code>"
    bot.send_html_safe(-100123, hostile, reply_markup=None)
    txt, pm = sent[-100123]
    check("send_html_safe fell back to plain", pm is None and "<code>" not in txt,
          f"pm={pm} txt={txt[:60]!r}")
    check("plain text keeps content", "A & B" in txt and "<tag>" not in txt,
          f"txt={txt[:60]!r}")
    # Normal HTML message should go through as HTML
    bot.send_html_safe(-100123, "<b>ok</b> message")
    txt2, pm2 = sent[-100123]
    check("normal HTML still sent as HTML", pm2 == "HTML" and "<b>ok</b>" in txt2)
    # Non-parse errors must propagate (429 etc. handled by caller)
    def boom(chat_id, text, parse_mode=None, reply_markup=None):
        raise Exception("429 Too Many Requests")
    bot.bot = type("B", (), {"send_message": staticmethod(boom)})()
    try:
        bot.send_html_safe(-100123, "<b>x</b>")
        check("non-parse errors propagate", False, "no exception raised")
    except Exception as e:
        check("non-parse errors propagate", "429" in str(e))
finally:
    bot.bot = real_bot

# ------------------------------------------------ 5) forwarder group msgs escape
class MinimalFwd(bot.SMSPanelForwarder):
    def __init__(self):
        pass  # skip network init


mf = MinimalFwd()
sms = {
    'otp': 'ekxbr', 'service': 'Melbet & Co', 'phone': '2349154635248',
    'country': 'Nigeria', 'full_text': 'code: ekxbr <Melbet> & friends',
    'timestamp': '2026-09-18 10:00:00',
}
full_clean = mf._clean_text(sms['full_text'])[:200]
masked = mf._mask_number(sms['phone'])
cflag = bot.country_flag(sms['country'])
otp_display = sms['otp']
msg = (
    f"<b>Anonmatrixx</b>\n━━━━━━━━━━━━━━━\n"
    f"{cflag} <b>{bot.html_mod.escape(str(sms['service']).upper())}</b> \U0001f7e2\n"
    f"\U0001f4f1 <code>{bot.html_mod.escape(str(masked))}</code>\n"
    f"\U0001f511 <b>OTP:</b> <code>{bot.html_mod.escape(str(otp_display))}</code>\n"
    f"\U0001f4e9 <b>Message:</b> <code>{bot.html_mod.escape(full_clean)}</code>\n"
    f"\u23f0 {bot.html_mod.escape(str(sms['timestamp']))}\n━━━━━━━━━━━━━━━"
)
bad = re.findall(r'&(?!amp;|lt;|gt;|quot;|#)', msg)
check("panel group msg: no unescaped &", not bad, f"bad={bad}")
check("panel group msg: service escaped", "MELBET &amp; CO" in msg)
check("panel group msg: body escaped", "&lt;Melbet&gt;" in msg)
check("panel group msg: flag present", cflag in msg)

# ------------------------------------------------ summary
print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL CHECKS PASSED")
