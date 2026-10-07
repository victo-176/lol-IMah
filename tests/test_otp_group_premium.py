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

MAPS = ("PREMIUM_NAMED", "GLOBAL_BODY_EMOJIS", "EXTRA_BODY_EMOJIS", "ICON_ALIASES")


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

    # 6. The TEMP EMAIL menu button: icon="mail" resolves to a real id.
    if premium_emoji.premium_icon("mail") != "5967280668885913944":
        fails.append("premium_icon('mail') does not resolve — TEMP EMAIL button gets no icon")
    else:
        print("PASS: TEMP EMAIL button icon resolves (mail -> envelope id)")

    # 7. Leaderboard ranks must premiumize, not render as plain unicode.
    ranks = premium_emoji.premiumize("1️⃣ Ali\n2️⃣ Bob\n3️⃣ Cy")
    if ranks.count("<tg-emoji") != 3:
        fails.append(f"leaderboard ranks not premiumized: {ranks!r}")
    else:
        print("PASS: leaderboard ranks 1/2/3 are premium")

    # 8. The group's no-parse_mode retry must not post raw <tg-emoji> tags.
    if 'payload2 = {"chat_id": chat_id, "text": strip_html_tags(text)' not in bot_src:
        fails.append("group retry still posts the premiumized text without parse_mode, "
                     "which shows raw <tg-emoji> tags in the group")
    else:
        print("PASS: group fallback strips tags instead of posting them")

    # 9. Every alias id must be an id the operator actually owns.
    known_ids = {i for _n, (_c, i) in premium_emoji.PREMIUM_NAMED.items()}
    known_ids |= set(premium_emoji.GLOBAL_BODY_EMOJIS.values())
    known_ids |= set(premium_emoji.EXTRA_BODY_EMOJIS.values())
    # An alias may also reuse an id the operator already has in emoji.txt
    # (clock_alarm reuses info_bw), so that counts as known too.
    try:
        txt = open(os.path.join(ROOT, "emoji.txt"), encoding="utf-8").read()
        known_ids |= set(re.findall(r"\b\d{15,}\b", txt))
    except OSError:
        pass
    unknown = {a: e for a, e in premium_emoji.ICON_ALIASES.items() if e not in known_ids}
    if unknown:
        fails.append(f"ICON_ALIASES point at ids the operator does not own: {unknown}")
    else:
        print("PASS: every icon alias points at a known operator id")

    # 10. The shared builder lays out the reference group post.
    text, kb = premium_emoji.build_otp_group_message(
        "+263771238206", "030061", "paypal", "ZW",
        number_link="https://t.me/num", channel_link="https://t.me/ch")
    if "#ZW" not in text or "#EN" in text or "#AR" in text:
        fails.append(f"builder text misses #ZW or still has a language tag: {text!r}")
    if "<tg-emoji" not in text:
        fails.append(f"builder text has no premium emoji: {text!r}")
    if "+2637....8206" not in text:
        fails.append(f"builder text misses the watermark number: {text!r}")
    if text.count("\n") != 0:
        fails.append(f"builder text should be exactly one line: {text!r}")
    if "030061" in text:
        fails.append(f"the demo OTP leaked into the message body: {text!r}")
    else:
        print("PASS: reference layout = flag #ISO app watermark-number")

    # 11. Green copy button with the REAL otp; blue NUMBER/CHANNEL buttons.
    copy_btn = kb["inline_keyboard"][0][0]
    row2 = kb["inline_keyboard"][1]
    if copy_btn.get("copy_text", {}).get("text") != "030061":
        fails.append(f"copy button does not carry the real OTP: {copy_btn}")
    if "PayPal | 030061" not in copy_btn["text"]:
        fails.append(f"copy label is not `Service | OTP`: {copy_btn['text']!r}")
    if copy_btn.get("style") != "success":
        fails.append(f"copy button is not green (style=success): {copy_btn}")
    if copy_btn.get("icon_custom_emoji_id") != "5364111181415996352":
        fails.append(f"copy button icon is not the PayPal app id: {copy_btn}")
    if (row2[0].get("url") != "https://t.me/num"
            or row2[1].get("url") != "https://t.me/ch"):
        fails.append(f"NUMBER/CHANNEL urls wrong: {row2}")
    if row2[0].get("style") != "primary" or row2[1].get("style") != "primary":
        fails.append(f"NUMBER/CHANNEL buttons are not blue (style=primary): {row2}")
    else:
        print("PASS: green copy button (real OTP) + blue NUMBER/CHANNEL buttons")

    # 12. The language tag (#AR/#EN) is no longer posted.
    t_jo, _ = premium_emoji.build_otp_group_message("+962781239030", "123456", "PayPal")
    if "#AR" in t_jo or "#EN" in t_jo:
        fails.append(f"language tag still present: {t_jo!r}")
    if "#JO" not in t_jo:
        fails.append(f"Jordan post misses #JO: {t_jo!r}")
    print("PASS: language tag removed (#AR/#EN never posted)")

    # 13. Every id in the app-icon fixture loads through the shared loader.
    expected = {}
    parsed = 0
    for line in open(os.path.join(ROOT, "tests", "fixtures", "app_icon_ids.txt"),
                     encoding="utf-8"):
        if "|" not in line:
            continue
        name, eid = (p.strip() for p in line.split("|"))
        parsed += 1
        expected[re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")] = eid
    missing = {k: v for k, v in expected.items()
               if premium_emoji.PREMIUM_ICONS.get(k) != v}
    if parsed != 150:
        fails.append(f"app icon fixture should hold 150 entries, has {parsed}")
    if missing:
        fails.append(f"app ids not loaded from emoji.txt: {missing}")
    else:
        print(f"PASS: all {len(expected)} app icon ids load from emoji.txt")

    # 14. Services resolve to their own app icon, never the fire fallback.
    for svc, eid in (("PayPal", "5364111181415996352"),
                     ("whatsapp", "5334998226636390258"),
                     ("Instagram", "5319160079465857105"),
                     ("X", "5330337435500951363")):
        got = premium_emoji.app_icon_id(svc)
        if got != eid:
            fails.append(f"app_icon_id({svc!r}) = {got}, want {eid}")
    if premium_emoji.app_icon_id("unknown") != "5967280668885913944":
        fails.append("unknown services should get the envelope id, not fire")
    else:
        print("PASS: services resolve to their app icon; unknown -> envelope")

    # 15. The copy fallback downgrades copy_text to a copy_<otp> callback.
    fb = premium_emoji.kb_without_copy(kb, "030061")
    fb_btn = fb["inline_keyboard"][0][0]
    if fb == kb or "copy_text" in fb_btn or fb_btn.get("callback_data") != "copy_030061":
        fails.append(f"kb_without_copy did not downgrade the copy button: {fb_btn}")
    else:
        print("PASS: copy button falls back to a copy_<otp> callback")

    # 16. Every sender builds and posts through the shared reference path.
    if bot_src.count("post_otp_group(gid, msg, kb") < 2:
        fails.append("Choice/panel forwarders do not both post via post_otp_group()")
    if "build_otp_group_message(" not in bot_src:
        fails.append("bot.py never builds the reference group format")
    if "build_otp_group_message(" not in panel_src:
        fails.append("temp_numbers_panel.py never builds the reference group format")
    if re.search(r"Copy Message", bot_src + panel_src):
        fails.append("the old 'Copy Message' button is still being sent")
    else:
        print("PASS: all three senders post the shared reference format")

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
