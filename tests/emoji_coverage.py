#!/usr/bin/env python3
"""Accurate premium-emoji coverage report for bot.py.

Two distinct paths produce premium emoji:

  A) pe('name', fallback) -> resolves 'name' through PREMIUM_EMOJI_IDS /
     emoji.txt (554 ids) and emits a <tg-emoji> tag. The literal glyph in the
     fallback slot never appears as raw text.
  B) bare unicode emoji inside message text -> only becomes premium when the
     character is in PREMIUM_BODY_IDS (the map just added).

This counts both, so the number reflects what actually ships.

Run:  python3 tests/emoji_coverage.py
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot.py")
EMOJI_TXT = os.path.join(ROOT, "emoji.txt")
SRC = open(BOT, encoding="utf-8").read()


def load_dict(name):
    for n in ast.parse(SRC, filename=BOT).body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(n.value)
    return {}


NAMED = load_dict("PREMIUM_NAMED")
GLOBAL = load_dict("GLOBAL_BODY_EMOJIS")
EXTRA = load_dict("EXTRA_BODY_EMOJIS")

BODY_IDS = {}
for _n, (_c, _i) in NAMED.items():
    BODY_IDS.setdefault(_c, _i)
for _c, _i in GLOBAL.items():
    BODY_IDS.setdefault(_c, _i)
for _c, _i in EXTRA.items():
    BODY_IDS.setdefault(_c, _i)


def emoji_txt_ids():
    """Mirror bot.py's load_premium_emojis()."""
    icons = {}
    try:
        content = open(EMOJI_TXT, encoding="utf-8").read()
    except Exception:
        return icons
    for val, key in re.findall(r"(\d{15,})\s+-\s+([A-Za-z0-9_]+)", content):
        icons[key.lower()] = val
    for key, val in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"(\d{15,})"', content):
        icons[key.lower()] = val
    return icons


TXT_IDS = emoji_txt_ids()
# premium_icon() now falls back to the name's own Unicode glyph, so any
# UNICODE_FALLBACKS name whose glyph is in the body map resolves too.
FALLBACKS = load_dict("UNICODE_FALLBACKS")
_ALTS = sorted(BODY_IDS, key=len, reverse=True)
GLYPH_RE = re.compile("(" + "|".join(re.escape(c) for c in _ALTS) + ")") if _ALTS else None


def glyph_resolvable(name):
    return glyph_resolvable_glob(FALLBACKS.get(str(name).lower()))


def glyph_resolvable_glob(glyph):
    if not glyph or GLYPH_RE is None:
        return False
    m = GLYPH_RE.match(glyph)
    return bool(m) and m.group(0) in BODY_IDS


# pe() can resolve any name present in either map, plus glyph-derived names.
PE_RESOLVABLE = set(TXT_IDS) | set(NAMED)
PE_RESOLVABLE |= {n for n in FALLBACKS if glyph_resolvable(n)}


def is_emojiish(ch):
    o = ord(ch)
    return (0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF
            or 0x2190 <= o <= 0x21FF or 0x2B00 <= o <= 0x2BFF
            or o in (0xFE0F, 0x20E3, 0x200D) or 0x1F1E6 <= o <= 0x1F1FF)


def emoji_runs(s):
    out, i = [], 0
    while i < len(s):
        if is_emojiish(s[i]):
            j = i
            while j < len(s) and (is_emojiish(s[j]) or s[j] in "‍️⃣"):
                j += 1
            out.append(s[i:j])
            i = j
            continue
        i += 1
    return out


def main():
    tree = ast.parse(SRC, filename=BOT)

    # The premium maps are lookup data, not user-visible copy: their own glyph
    # keys would otherwise be counted as "misses" and report false coverage.
    map_nodes = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in (
                        "PREMIUM_NAMED", "GLOBAL_BODY_EMOJIS",
                        "EXTRA_BODY_EMOJIS", "UNICODE_FALLBACKS"):
                    map_nodes.update(id(k) for k in n.value.keys)

    # Fallback args of pe(...) are already premium-eligible -> exclude them
    # from the "bare text" bucket.
    pe_fallbacks = set()
    pe_names_used = set()
    pe_name_glyphs = {}          # name -> glyphs passed as pe()'s 2nd arg
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "pe" and n.args:
            first = n.args[0]
            fb = None
            if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) \
                    and isinstance(n.args[1].value, str):
                fb = n.args[1].value
                pe_fallbacks.add(fb)
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                nm = first.value.strip().lower()
                pe_names_used.add(nm)
                if fb:
                    pe_name_glyphs.setdefault(nm, set()).add(fb)
    # A pe() call resolves if the name is known, or if the glyph it renders
    # carries a premium id (pe()'s own glyph fallback in bot.py).
    pe_names_ok = {nm for nm in pe_names_used
                   if nm in PE_RESOLVABLE
                   or any(glyph_resolvable_glob(g) for g in pe_name_glyphs.get(nm, ()))}

    bare = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if id(n) in map_nodes or n.value in pe_fallbacks:
                continue
            for run in emoji_runs(n.value):
                bare[run] = bare.get(run, 0) + 1

    bare_cov = {c: k for c, k in bare.items() if c in BODY_IDS}
    bare_unc = {c: k for c, k in bare.items() if c not in BODY_IDS}

    total_refs = sum(bare.values()) + len(pe_names_used)
    cov_refs = sum(bare_cov.values()) + len(pe_names_ok)

    print("=== path A: pe() name lookups ===")
    print(f"distinct pe() names used        : {len(pe_names_used)}")
    print(f"  resolvable to a premium id    : {len(pe_names_ok)}")
    unresolved = sorted(pe_names_used - pe_names_ok)
    print(f"  UNRESOLVED (no id anywhere)    : {len(unresolved)}")
    if unresolved:
        print(f"    {unresolved}")
    print()

    print("=== path B: bare emoji in message text ===")
    print(f"distinct bare glyphs            : {len(bare)}")
    print(f"  upgraded by body map           : {len(bare_cov)}")
    print(f"  still plain unicode           : {len(bare_unc)}")
    print()

    pct = (cov_refs / total_refs * 100) if total_refs else 0.0
    print(f"emoji.txt ids available         : {len(TXT_IDS)}")
    print(f"body map glyphs                 : {len(BODY_IDS)}")
    print(f"OVERALL premium coverage        : {cov_refs}/{total_refs} = {pct:.1f}%")
    print()
    print("=== top bare glyphs still plain (need an id from the operator) ===")
    for ch, k in sorted(bare_unc.items(), key=lambda kv: -kv[1])[:25]:
        print(f"  {ch!r:12s} x{k:<4d} {ch.encode('unicode_escape').decode()}")
    print()
    if len(pe_names_ok) == 0 or pct < 50:
        print("FAIL: premium emoji not meaningfully wired")
        return 1
    print("PASS: premium emoji wired through both paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())