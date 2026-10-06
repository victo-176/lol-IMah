#!/usr/bin/env python3
"""Premium Telegram country-flag helper shared by the standalone panel scripts.

Resolves a country NAME (e.g. "NIGERIA") to a premium custom-emoji
<tg-emoji> tag using the same emoji.txt the main bot loads, and falls back
to the panel's plain unicode flag whenever no premium id exists.
"""
import os
import re

_FLAG_ID_RE = re.compile(r'(?:"([A-Za-z_][A-Za-z0-9_]*)"|([A-Za-z_][A-Za-z0-9_]*))\s*:\s*"(\d{15,})"')
_IDS = None


def _load_ids():
    """ISO-2 -> premium emoji id, merged from every emoji.txt candidate."""
    global _IDS
    if _IDS is not None:
        return _IDS
    ids = {}
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, os.pardir, "emoji.txt"), "emoji.txt"):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            continue
        for m in _FLAG_ID_RE.finditer(content):
            key = m.group(1) or m.group(2)
            if re.fullmatch(r"[A-Z]{2}", key):
                ids[key] = m.group(3)
    _IDS = ids
    return ids


def _iso_from_flag(flag):
    """Regional-indicator pair -> ISO-2 code (None when not a flag)."""
    ris = []
    for ch in flag or "":
        cp = ord(ch)
        if 0xD0020 <= cp <= 0xD007F:      # off-plane tag chars: skip
            continue
        if 0x1F1E6 <= cp <= 0x1F1FF:
            ris.append(chr(cp - 0x1F1E6 + 65))
    if len(ris) == 2:
        return "".join(ris)
    return None


def flag_html(country_flags, country, fallback="\U0001F30D"):
    """Premium <tg-emoji> HTML flag for a country NAME, else unicode flag."""
    uni = (country_flags or {}).get(country) or fallback
    iso = _iso_from_flag(uni)
    eid = _load_ids().get(iso) if iso else None
    if eid:
        return '<tg-emoji emoji-id="%s">%s</tg-emoji>' % (eid, uni)
    return uni
