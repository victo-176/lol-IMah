#!/usr/bin/env python3
"""Verify the admin 'Add Panel -> API' path for every supported style.

Covers: detect_api_style, build_api_panel_config, save_panel_format_config,
save_sms_panel (name-keyed upsert) and SMSPanelForwarder construction -- i.e.
the exact sequence _finish_add_panel runs. No network is touched.
"""
import os
import sys
import tempfile

sys.path.insert(0, ".")

import bot  # noqa: E402
from all_formats import build_api_panel_config, detect_api_style  # noqa: E402

# Redirect the DB to a throwaway file so nothing touches real data.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
bot.DB_PATH = _tmp.name
bot.init_db()

CASES = [
    ("Dream SMS", "http://49.13.121.155/api/v1/messages", "TOKEN", "bearer_json"),
    ("CRAPI Panel", "http://1.2.3.4/crapi/viewstats", "TOK", "crapi"),
    ("QueryToken", "http://5.6.7.8/api.php?token=abc", "TOK", "query_token"),
    ("Bearer", "http://9.9.9.9/v2/messages", "TOK", "bearer_json"),
    ("Augustel", "http://augestel.com/api/v1/iprn", "TOK", "augestel_iprn"),
]

fails = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  " + name)
    else:
        print("  FAIL  " + name + "  " + str(detail))
        fails.append(name)


print("=== API panel add path ===")
for name, url, tok, want_style in CASES:
    try:
        style = detect_api_style(url)
        _pid, cfg = build_api_panel_config(name, url, tok)
        bot.save_panel_format_config(name, cfg)
        panel_id = bot.save_sms_panel(name, url, "api", tok, "")
        fw = bot.SMSPanelForwarder(panel_id, name, url, "api", tok, "")
        resolved = bot.get_panel_config(name)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(f"{name}: no exception", False, repr(e))
        continue
    check(f"{name}: style detected", style == want_style, f"{style} != {want_style}")
    check(f"{name}: forwarder type is api", fw.panel_cfg.get("type") == "api",
          str(fw.panel_cfg.get("type")))
    check(f"{name}: resolved cfg is api", resolved.get("type") == "api",
          str(resolved.get("type")))
    check(f"{name}: resolved style matches", resolved.get("api_style") == style,
          f"{resolved.get('api_style')} != {style}")

print()
print("=== name-keyed upsert (re-add updates, no dup rows) ===")
before = len(bot.get_all_sms_panels())
bot.save_sms_panel("Dream SMS", "http://new-host/api/v1/messages", "api", "NEWTOK", "")
after = len(bot.get_all_sms_panels())
check("re-adding same name does not duplicate", after == before, f"{before} -> {after}")
row = [p for p in bot.get_all_sms_panels() if p[1] == "Dream SMS"]
check("re-add updated the url", row and row[0][2] == "http://new-host/api/v1/messages",
      str(row))

print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL API PANEL ADD CHECKS PASSED")
sys.exit(0)
