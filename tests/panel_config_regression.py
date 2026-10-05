#!/usr/bin/env python3
"""Regression guard: PANEL_LOGIN_CONFIGS must be untouched by other edits."""
import ast
import subprocess
import sys

BOT = "bot.py"


def load_dict(src, name):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(n.value)
    raise SystemExit(f"{name} not found")


def main():
    head = subprocess.run(["git", "show", f"HEAD:{BOT}"],
                          capture_output=True, text=True, check=True).stdout
    work = open(BOT, encoding="utf-8").read()
    old = load_dict(head, "PANEL_LOGIN_CONFIGS")
    new = load_dict(work, "PANEL_LOGIN_CONFIGS")
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    print(f"committed entries : {len(old)}")
    print(f"working  entries  : {len(new)}")
    print(f"added             : {added}")
    print(f"removed           : {removed}")
    print(f"changed           : {changed}")
    if removed or changed:
        print("FAIL: existing panel config was modified")
        return 1
    print("PASS: no existing panel config changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
