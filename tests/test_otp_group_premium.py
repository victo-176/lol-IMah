#!/usr/bin/env python3
"""The OTP group senders must go out with premium emoji, and the two copies of
the id maps must not drift.

The OTP group messages are posted with plain requests, so they never touch
bot.py's send_message wrapper. bot.py keeps an in-file copy of the maps (its
tests extract that source region); premium_emoji.py is the importable copy for
standalone scripts. These two must stay byte-identical.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot.py")
PANEL = os.path.join(ROOT, "temp_numbers_panel.py")
MODULE = os.path.join(ROOT, "premium_emoji.py")

MAPS = ("PREMIUM_NAMED", "GLOBAL_BODY_EMOJIS", "EXTRA_BODY_EMOJIS")


def load_dict(path, name):
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(n.value)
    raise SystemExit(f"{name} not found in {path}")


def main():
    sys.path.insert(0, ROOT)
    import premium_emoji

    fails = []

    # 1. The two copies of the maps must be identical.
    for name in MAPS:
        bot_map = load_dict(BOT, name)
        mod_map = getattr(premium_emoji, name)
        if bot_map != mod_map:
            only_bot = set(bot_map) - set(mod_map)
            only_mod = set(mod_map) - set(bot_map)
            diff = {k for k in set(bot_map) & set(mod_map) if bot_map[k] != mod_map[k]}
            fails.append(f"{name} differs: only-in-bot={sorted(only_bot)} "
                         f"only-in-module={sorted(only_mod)} differing={sorted(diff)}")
        else:
            print(f"PASS: {name} identical in bot.py and premium_emoji.py ({len(bot_map)})")

    # 2. bot.py's raw-API group sender must premiumize before posting.
    bot_src = open(BOT, encoding="utf-8").read()
    grp = re.search(r"def send_to_telegram_group\(.*?(?=\ndef )", bot_src, re.S)
    if not grp:
        fails.append("send_to_telegram_group not found")
    else:
        body = grp.group(0)
        if "premiumize(" not in body:
            fails.append("send_to_telegram_group does not call premiumize()")
        else:
            print("PASS: send_to_telegram_group premiumizes the OTP body")

    # 3. The temp-numbers panel sender must too, via the shared module.
    panel_src = open(PANEL, encoding="utf-8").read()
    if "import premium_emoji" not in panel_src and "from premium_emoji import" not in panel_src:
        fails.append("temp_numbers_panel.py does not import premium_emoji")
    else:
        print("PASS: temp_numbers_panel.py imports the shared module")
    sender = re.search(r"def _tg_send\(.*?(?=\ndef )", panel_src, re.S)
    if not sender:
        fails.append("_tg_send not found")
    elif "premiumize(" not in sender.group(0):
        fails.append("_tg_send does not premiumize the OTP body")
    else:
        print("PASS: _tg_send premiumizes the OTP body")

    # 4. Behaviour: a realistic group OTP body comes out fully premiumized,
    #    balanced, and not double-wrapped on a second pass.
    sample = ("🔥 <b>LIVE OTP</b>\n"
              "━━━━━━━━━━━━━━━\n"
              "\U0001F4DE <b>Number:</b> <code>+2348012345678</code>\n"
              "\U0001F450 <b>Service:</b> BOLT\n"
              "\U0001F30D <b>Country:</b> \U0001F1F3\U0001F1EC Nigeria\n"
              "\U0001F511 <b>Code:</b> <code>123-456</code>\n"
              "\U0001F4C5 <b>Time:</b> 2026-10-05 12:00")
    out = premium_emoji.premiumize(sample)
    if "<tg-emoji" not in out:
        fails.append("premiumize() produced no premium tags for a group OTP body")
    if out.count("<tg-emoji") != out.count("</tg-emoji>"):
        fails.append("premiumized body has unbalanced tags")
    if premium_emoji.premiumize(out) != out:
        fails.append("premiumize() is not idempotent on its own output")
    # The flag must stay a real country flag, not be mangled.
    if "\U0001F1F3\U0001F1EC" not in out:
        fails.append("country flag was altered by premiumize()")
    if "<code>+2348012345678</code>" not in out:
        fails.append("OTP value or its <code> wrapper was altered")
    print(f"PASS: group OTP body -> {out.count('<tg-emoji')} premium emoji, "
          f"tags balanced, idempotent, OTP intact")

    # 5. A no-id glyph degrades to plain unicode instead of erroring.
    if premium_emoji.premiumize("\U0001F3F0 castle") != "\U0001F3F0 castle":
        fails.append("a glyph with no id should pass through unchanged")
    print("PASS: glyphs with no id pass through as plain unicode")

    print()
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  - " + f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
