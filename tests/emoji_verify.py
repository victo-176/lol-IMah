#!/usr/bin/env python3
"""Verify bot.py's premium emoji maps match the operator's supplied values EXACTLY.

Parses bot.py statically (telebot is not installed in the sandbox) and compares
against tests/fixtures/premium_emoji_source.py, a verbatim copy of the request.
A mistyped digit fails here instead of shipping an id Telegram would reject.
"""
import ast
import re
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot.py")
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))
from premium_emoji_source import OPERATOR_NAMED, OPERATOR_GLOBAL  # noqa: E402

EXPECTED_NAMED = OPERATOR_NAMED
EXPECTED_BODY = OPERATOR_GLOBAL


def load_dict(name):
    tree = ast.parse(open(BOT, encoding="utf-8").read(), filename=BOT)
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(n.value)
    return None


def main():
    named = load_dict("PREMIUM_NAMED")
    body = load_dict("GLOBAL_BODY_EMOJIS")
    fails = []

    if named is None:
        fails.append("PREMIUM_NAMED not found")
    if body is None:
        fails.append("GLOBAL_BODY_EMOJIS not found")
    if fails:
        print("FAILURES:", fails)
        return 1

    if named != EXPECTED_NAMED:
        for k in sorted(set(named) | set(EXPECTED_NAMED)):
            a, b = named.get(k), EXPECTED_NAMED.get(k)
            if a != b:
                print(f"  NAMED mismatch {k!r}: bot={a!r} expected={b!r}")
        fails.append("PREMIUM_NAMED does not match the supplied map")

    if body != EXPECTED_BODY:
        for k in sorted(set(body) | set(EXPECTED_BODY)):
            a, b = body.get(k), EXPECTED_BODY.get(k)
            if a != b:
                print(f"  BODY mismatch {k!r}: bot={a!r} expected={b!r}")
        fails.append("GLOBAL_BODY_EMOJIS does not match the supplied map")

    # No value expression tricks (a hand-edited dict should be pure literals).
    for name, d in (("PREMIUM_NAMED", named), ("GLOBAL_BODY_EMOJIS", body)):
        for k, v in d.items():
            if isinstance(v, tuple):
                if not re.fullmatch(r"\d{15,19}", v[1]):
                    fails.append(f"{name}[{k!r}] bad id {v[1]!r}")
            elif not re.fullmatch(r"\d{15,19}", v):
                fails.append(f"{name}[{k!r}] bad id {v!r}")

    print(f"PREMIUM_NAMED entries      : {len(named)} (expected {len(EXPECTED_NAMED)})")
    print(f"GLOBAL_BODY_EMOJIS entries: {len(body)} (expected {len(EXPECTED_BODY)})")
    print()
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
        return 1
    print("MAPS MATCH THE SUPPLIED DATA EXACTLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())