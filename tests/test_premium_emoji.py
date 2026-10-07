#!/usr/bin/env python3
"""Functional test of the premium-emoji code actually shipped in bot.py.

telebot is not installed in this sandbox, so bot.py cannot be imported. Instead
this extracts the real premium-emoji source region straight out of bot.py and
executes it against stub globals. That way we test the shipped code rather than
a hand-copied duplicate.

Run:  python3 tests/test_premium_emoji.py
"""
import os
import re
import sys
import types as pytypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot.py")
SRC = open(BOT, encoding="utf-8").read()
LINES = SRC.splitlines()


def region(start_marker, end_marker):
    """Return the source text between two markers (exclusive of end)."""
    s = next(i for i, l in enumerate(LINES) if l.startswith(start_marker))
    e = next(i for i, l in enumerate(LINES) if l.startswith(end_marker))
    return "\n".join(LINES[s:e])


def build_namespace():
    def premium_icon(name):
        """Mirror of the real lookup: named ids, then flags/icons (absent here)."""
        if not name:
            return None
        n = str(name).strip()
        if n.lower() in ns["PREMIUM_EMOJI_IDS"]:
            return ns["PREMIUM_EMOJI_IDS"][n.lower()]
        return None

    ns = {
        "re": re,
        "PREMIUM_EMOJI_OK": True,
        "UNICODE_FALLBACKS": {},
        "PREMIUM_EMOJI_IDS": {},
        # The shipped map region reads these; the real values are re-bound
        # below before premium_icon()'s region is exec'd.
        "PREMIUM_ICONS": {},
        "PREMIUM_FLAGS": {},
        "premium_icon": premium_icon,
        "logger": pytypes.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None,
            error=lambda *a, **k: None),
        "copy": __import__("copy"),
    }
    # The maps, the char->id derivation, the regex build, premiumize(),
    # _premiumize_arg() — all the shipped logic under test.
    exec(region("# =========================== PREMIUM EMOJI MAPS",
                "def premium_icon(name):"), ns)
    # Button helpers (_BTN_STRIP_RE + _derive_icon_id + _btn_text_and_icon).
    btn = region("_BTN_STRIP_RE = re.compile", "def ibtn(")
    exec(btn, ns)
    # The real lookup chain: _premium_id_for_glyph + premium_icon + pe.
    ns["PREMIUM_ICONS"] = {}
    ns["PREMIUM_FLAGS"] = {}
    exec(region("def _premium_id_for_glyph(glyph):", "def flag_icon_id("), ns)
    return ns


def main():
    ns = build_namespace()
    premiumize = ns["premiumize"]
    _premiumize_arg = ns["_premiumize_arg"]
    _btn_text_and_icon = ns["_btn_text_and_icon"]
    pe = ns["pe"]
    premium_icon = ns["premium_icon"]
    body_ids = ns["PREMIUM_BODY_IDS"]
    named = ns["PREMIUM_NAMED"]
    global_map = ns["GLOBAL_BODY_EMOJIS"]

    checks = []
    def check(name, cond, extra=""):
        checks.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}: {name} {extra}")

    print("=== map integrity ===")
    check("named map loaded", len(named) == 22, f"({len(named)})")
    check("global map loaded", len(global_map) == 79, f"({len(global_map)})")
    check("body map non-empty", len(body_ids) > 0, f"({len(body_ids)})")

    check("every named id is 15-19 digits",
          all(re.fullmatch(r"\d{15,19}", i) for _c, i in named.values()))
    check("every global id is 15-19 digits",
          all(re.fullmatch(r"\d{15,19}", i) for i in global_map.values()))

    print("\n=== conflict resolution: named wins ===")
    # The five chars the operator mapped twice.
    LOCK = "\U0001F510"
    PHONE = "\U0001F4F1"
    WORLD = "\U0001F310"
    CROSS = "\u274C"
    CHART = "\U0001F4CA"
    FIRE = "\U0001F525"
    check("named 'lock' id wins for U+1F510",
          body_ids[LOCK] == named["lock"][1], "(%s)" % body_ids[LOCK])
    check("named 'phone' id wins for U+1F4F1",
          body_ids[PHONE] == named["phone"][1], "(%s)" % body_ids[PHONE])
    check("named 'world' id wins for U+1F310",
          body_ids[WORLD] == named["world"][1], "(%s)" % body_ids[WORLD])
    check("named 'no' id wins for U+274C",
          body_ids[CROSS] == named["no"][1], "(%s)" % body_ids[CROSS])
    check("first-named wins for U+1F4CA (admin before graph)",
          body_ids[CHART] == named["admin"][1], "(%s)" % body_ids[CHART])
    check("global-only chars still present (e.g. fire)",
          body_ids[FIRE] == global_map[FIRE])

    print("\n=== premiumize upgrades every mapped glyph (no misses) ===")
    misses = []
    for ch in body_ids:
        out = premiumize(f"hi {ch} there")
        if f'<tg-emoji emoji-id="{body_ids[ch]}">{ch}</tg-emoji>' not in out:
            misses.append(ch)
    check("all mapped glyphs upgrade", not misses, f"(misses: {misses[:5]})")

    print("\n=== idempotent / no double-wrap ===")
    sample = "✅ Done 🔐 Locked ❌ Failed"
    once = premiumize(sample)
    twice = premiumize(once)
    check("second pass is a no-op", once == twice)
    check("no nested tg-emoji", "<tg-emoji" not in
          re.sub(r'<tg-emoji emoji-id="\d+">[^<]*</tg-emoji>', '', once))

    print("\n=== existing tg-emoji tags preserved verbatim ===")
    existing = '<tg-emoji emoji-id="9999999999999999">📌</tg-emoji> keep'
    out = premiumize(existing)
    check("existing tag untouched", existing in out, f"(got {out})")
    check("other emoji still upgraded next to it",
          '<tg-emoji emoji-id="' in premiumize("📌 and ✅"))

    print("\n=== multi-codepoint emoji match whole ===")
    # U+26A0 U+FE0F must not be split into U+26A0 + VS16
    warn = "⚠️"
    out = premiumize(f"x {warn} y")
    check("warning sign upgraded as one unit",
          f'<tg-emoji emoji-id="{global_map[warn]}">{warn}</tg-emoji>' in out,
          f"(got {out})")
    check("no stray lone U+26A0 tag", 'emoji-id="5336944168944047463">⚠<' not in out)

    print("\n=== parse_mode gating (no raw tags on plain sends) ===")
    html_kw = {"parse_mode": "HTML"}
    check("HTML parse_mode upgrades", "<tg-emoji" in
          _premiumize_arg("✅ ok", html_kw))
    check("no parse_mode leaves text alone",
          _premiumize_arg("✅ ok", {}) == "✅ ok")
    check("MarkdownV2 leaves text alone",
          _premiumize_arg("✅ ok", {"parse_mode": "MarkdownV2"}) == "✅ ok")
    check("lowercase html upgrades",
          "<tg-emoji" in _premiumize_arg("✅ ok", {"parse_mode": "html"}))
    check("non-str passthrough", _premiumize_arg(None, html_kw) is None)

    print("\n=== button labels ===")
    txt, icon_id = _btn_text_and_icon("✅ Confirm", None, None)
    check("button strips tg-emoji tags", "<tg-emoji" not in txt, f"(got {txt})")
    check("button keeps plain glyph", txt == "✅ Confirm")
    check("button derives icon from leading emoji",
          icon_id == body_ids["✅"], f"(got {icon_id})")
    _t, named_icon = _btn_text_and_icon("Any", "ok", None)
    check("explicit icon name resolves",
          named_icon == named["ok"][1], f"(got {named_icon})")
    _t, forced = _btn_text_and_icon("Any", None, "1234567890123456789")
    check("explicit icon_id is never overridden", forced == "1234567890123456789")
    _t, none_icon = _btn_text_and_icon("Plain text", None, None)
    check("plain label gets no bogus icon", none_icon is None)
    ROCKET = "\U0001F680"
    _t, lead = _btn_text_and_icon("  " + ROCKET + " Go", None, None)
    check("leading spaces tolerated when deriving", lead == body_ids[ROCKET])

    print("\n=== pe() glyph fallback (names resolved via their glyph) ===")
    # earth/minus/warning have no id under their name, but their glyph is in
    # the premium body map, so pe() must still emit a premium tag.
    for nm, glyph in (("earth", "\U0001F30D"), ("minus", "\u2796"),
                      ("warning", "\u26A0\ufe0f")):
        out = pe(nm, glyph)
        check(f"pe({nm!r}) resolves via glyph",
              out == f'<tg-emoji emoji-id="{body_ids[glyph]}">{glyph}</tg-emoji>',
              f"(got {out})")
    # Named entries still win over any glyph-derived answer.
    check("named id beats glyph", pe("lock", LOCK) == f'<tg-emoji emoji-id="{named["lock"][1]}">{LOCK}</tg-emoji>')
    check("numeric name still used directly",
          pe("4969841369850840381", PHONE) == f'<tg-emoji emoji-id="4969841369850840381">{PHONE}</tg-emoji>')
    # No id anywhere -> plain glyph, no tag, no exception (never an error).
    check("unknown name falls back to plain glyph",
          pe("clock", "\U0001F550") == "\U0001F550")
    check("no fallback and no id -> bullet", pe("nosuchthing") == "\u2022")
    check("empty name -> bullet", pe(None) == "\u2022")
    check("premium_icon(None) is None", premium_icon(None) is None)

    print("\n=== tag balance (HTML safety) ===")
    unbalanced = 0
    for ch in list(body_ids)[:40]:
        out = premiumize(f"a{ch}b <b>x</b> <code>1{ch}2</code>")
        if out.count("<tg-emoji") != out.count("</tg-emoji>"):
            unbalanced += 1
    check("tags balanced across html contexts", unbalanced == 0,
          f"({unbalanced} unbalanced)")

    passed = sum(1 for _, ok in checks if ok)
    print(f"\n{passed}/{len(checks)} checks passed")
    if passed != len(checks):
        print("FAILED CHECKS:")
        for n, ok in checks:
            if not ok:
                print("  -", n)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())