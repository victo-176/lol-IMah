#!/usr/bin/env python3
"""Add the operator's country-flag custom emoji ids to emoji.txt.

bot.py's load_premium_emojis() only treats a `"XX": "id"` entry as a FLAG
(uppercase two letters, quoted). The `id - name` list format would land in
PREMIUM_ICONS with a lowercased key and never reach flag_icon_id(), so this
writes the quoted uppercase form.

Idempotent: re-running adds nothing.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tests", "fixtures", "flag_ids_source.txt")
EMOJI_TXT = os.path.join(ROOT, "emoji.txt")

SECTION = ("\n---\n\nSection 5 — Country flag emoji (quoted so the loader treats "
           "them as flags, not icons)\n\n```\n")


def iso_from_glyph(glyph):
    """🇳🇬 -> NG. Returns None for tag-sequence flags (England/Scotland/Wales)."""
    if len(glyph) == 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in glyph):
        return "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in glyph)
    return None


def slug_for_glyph(glyph):
    if iso_from_glyph(glyph):
        return iso_from_glyph(glyph)
    # Tag-sequence flags (black flag + tag chars) are keyed by their letters.
    letters = "".join(chr(ord(c) - 0xE0000 + ord("A")) for c in glyph
                      if 0xE0000 <= ord(c) <= 0xE007F)
    return ("TAG_" + letters) if letters else None


def main():
    pairs = []
    for line in open(SOURCE, encoding="utf-8"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, glyph, eid = (p.strip() for p in line.split("|"))
        if not re.fullmatch(r"\d{15,}", eid):
            continue
        key = slug_for_glyph(glyph)
        if not key:
            print(f"skip: cannot key {name} ({glyph!r})")
            continue
        pairs.append((key, eid))

    content = open(EMOJI_TXT, encoding="utf-8").read()
    have = set(re.findall(r'"([A-Z]{2}(?:_2)?|[A-Z][A-Z0-9_]*)"\s*:', content))
    have |= set(re.findall(r"\b\d{15,}\b", content))

    added = []
    for key, eid in pairs:
        if eid in have:
            continue
        added.append(f'"{key}": "{eid}",')
        have.add(eid)

    if not added:
        print("emoji.txt already contains every supplied flag id")
        return 0
    with open(EMOJI_TXT, "a", encoding="utf-8") as fh:
        fh.write(SECTION)
        for line in added:
            fh.write(line + "\n")
        fh.write("```\n")
    print(f"appended {len(added)} flag ids to emoji.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
