#!/usr/bin/env python3
"""Every id in EXTRA_BODY_EMOJIS must come from emoji.txt, not be invented.

EXTRA_BODY_EMOJIS is the only premium map in bot.py that was filled in by
matching glyphs to ids the operator already had, so it needs its own check:
each id must exist in emoji.txt and must equal the id emoji.txt holds for the
name recorded in the comment on that line. An invented id would ship a
custom emoji Telegram rejects.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot.py")
EMOJI_TXT = os.path.join(ROOT, "emoji.txt")


def load_extra():
    src = open(BOT, encoding="utf-8").read()
    tree = ast.parse(src, filename=BOT)
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "EXTRA_BODY_EMOJIS":
                    return ast.literal_eval(n.value)
    raise SystemExit("EXTRA_BODY_EMOJIS not found in bot.py")


def emoji_txt_ids():
    """Mirror bot.py's load_premium_emojis()."""
    content = open(EMOJI_TXT, encoding="utf-8").read()
    icons = {}
    for key, val in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"(\d{15,})"', content):
        icons.setdefault(key.split("_")[0], val)
    for val, key in re.findall(r"(\d{15,})\s+-\s+([A-Za-z0-9_]+)", content):
        icons[key.lower()] = val
    return icons


def comment_pairs():
    """(name, id) from each map line's trailing '# name' comment."""
    src = open(BOT, encoding="utf-8").read()
    block = re.search(r"EXTRA_BODY_EMOJIS = \{(.*?)\n\}", src, re.S)
    if not block:
        raise SystemExit("EXTRA_BODY_EMOJIS block not found")
    out = []
    for line in block.group(1).splitlines():
        eid = re.search(r'"(\d{15,})"', line)
        name = re.search(r"#\s*([A-Za-z0-9_]+)\s*$", line)
        if eid and name:
            out.append((name.group(1), eid.group(1)))
    return out


def main():
    extra = load_extra()
    txt = emoji_txt_ids()
    fails = []
    if not extra:
        fails.append("EXTRA_BODY_EMOJIS is empty")

    bad_fmt = [g for g, i in extra.items() if not re.fullmatch(r"\d{15,19}", i)]
    if bad_fmt:
        fails.append(f"ids not 15-19 digits: {bad_fmt}")

    for glyph, eid in extra.items():
        # An id that appears anywhere in emoji.txt is at least real.
        if eid not in set(txt.values()):
            fails.append(f"{glyph!r} id {eid} does not exist in emoji.txt")

    pairs = comment_pairs()
    if len(pairs) != len(extra):
        fails.append(f"{len(pairs)} annotated entries for {len(extra)} map entries")
    for name, eid in pairs:
        if txt.get(name) != eid:
            fails.append(f"{name!r} is {txt.get(name)} in emoji.txt but bot.py uses {eid}")

    print(f"EXTRA_BODY_EMOJIS entries : {len(extra)}")
    print(f"emoji.txt ids             : {len(txt)}")
    print(f"all ids resolve in emoji.txt: {not fails}")
    print()
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  - " + f)
        return 1
    print("PASS: every extra body emoji id is the operator's own")
    return 0


if __name__ == "__main__":
    sys.exit(main())
