#!/usr/bin/env python3
"""Append the custom-emoji IDs from bot.py's maps to emoji.txt.

The map in bot.py (PREMIUM_NAMED / GLOBAL_BODY_EMOJIS) is the source of truth;
emoji.txt is the operator's lookup file. Any id present in the map but missing
from emoji.txt is appended in the same "<id> - <name>" format so both stay in
sync. Re-running is a no-op. bot.py prefers its own literal ids, so a stale
emoji.txt can never override them.
"""
import ast
import re
import sys
import unicodedata

EMOJI_TXT = "emoji.txt"
BOT = "bot.py"
SECTION = ("\n---\n\nSection 4 — Custom body emoji (mirrors PREMIUM_NAMED / "
           "GLOBAL_BODY_EMOJIS in bot.py)\n\n```\n")


def load_dict(name):
    tree = ast.parse(open(BOT, encoding="utf-8").read(), filename=BOT)
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(n.value)
    raise SystemExit(f"{name} not found in {BOT}")


def safe_name(glyph):
    """Build a stable slug from a (possibly multi-codepoint) glyph."""
    try:
        base = unicodedata.name(glyph[0])
    except (ValueError, IndexError):
        base = "U" + "".join(f"{ord(c):X}" for c in glyph)
    if "️" in glyph[1:]:
        base += ",vs16"
    elif len(glyph) > 1:
        base += ",seq"
    return "c_" + re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()


def main():
    content = open(EMOJI_TXT, encoding="utf-8").read()
    existing = set()
    for val in re.findall(r"\b(\d{15,})\b", content):
        existing.add(val)

    named = load_dict("PREMIUM_NAMED")
    # (id, glyph) everywhere: GLOBAL_BODY_EMOJIS is keyed by glyph.
    pairs = [(eid, glyph) for glyph, eid in named.values()]
    pairs += [(eid, glyph) for glyph, eid in load_dict("GLOBAL_BODY_EMOJIS").items()]
    seen_names = set(re.findall(r"^\d{15,}\s+-\s+([A-Za-z0-9_]+)", content, re.M))
    seen_names |= set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', content))

    added, used_names = [], set(seen_names)
    for eid, glyph in pairs:
        if eid in existing or glyph is None:
            continue
        nm, i = safe_name(glyph), 2
        while nm in used_names:
            nm = f"{safe_name(glyph)}_{i}"
            i += 1
        used_names.add(nm)
        added.append(f"{eid} - {nm}")

    if not added:
        print("emoji.txt already contains every id from the bot.py maps")
        return 0
    with open(EMOJI_TXT, "a", encoding="utf-8") as fh:
        fh.write(SECTION)
        for line in added:
            fh.write(line + "\n")
        fh.write("```\n")
    print(f"appended {len(added)} ids to {EMOJI_TXT}")
    for line in added:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
