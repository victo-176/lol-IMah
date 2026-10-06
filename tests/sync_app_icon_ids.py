#!/usr/bin/env python3
"""Add the operator's app premium-emoji ids to emoji.txt.

bot.py's load_premium_emojis() reads `id - name` lines into PREMIUM_ICONS
with a lowercased, slugified key, and premium_icon()/app_icon_id() resolve
service names through that map — so the app list ships as those lines.

The slug matches runtime normalisation: lowercased, every run of characters
outside [a-z0-9] collapsed to a single "_", leading/trailing "_" stripped
("Apple Music" -> "apple_music", "7-Zip" -> "7_zip", "C#" -> "c").

Idempotent: re-running adds nothing.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tests", "fixtures", "app_icon_ids.txt")
EMOJI_TXT = os.path.join(ROOT, "emoji.txt")

SECTION = ("\n---\n\nSection 6 — App premium icon ids (`id - name`, loaded "
           "into PREMIUM_ICONS for app_icon_id())\n\n```\n")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def main():
    pairs = []
    for line in open(SOURCE, encoding="utf-8"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, eid = (p.strip() for p in line.split("|"))
        if not re.fullmatch(r"\d{15,}", eid):
            continue
        key = slug(name)
        if not key:
            print(f"skip: cannot key {name!r}")
            continue
        pairs.append((key, eid))

    if not pairs:
        print("no app icon ids parsed from fixture")
        return 1

    content = open(EMOJI_TXT, encoding="utf-8").read()
    have_lines = set(re.findall(r"(\d{15,}\s+-\s+[A-Za-z0-9_]+)", content))

    added = []
    for key, eid in pairs:
        line = f"{eid} - {key}"
        if line in have_lines:
            continue
        added.append(line)
        have_lines.add(line)

    if not added:
        print("emoji.txt already contains every supplied app icon id")
        return 0
    with open(EMOJI_TXT, "a", encoding="utf-8") as fh:
        fh.write(SECTION)
        for line in added:
            fh.write(line + "\n")
        fh.write("```\n")
    print(f"appended {len(added)} app icon ids to emoji.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
