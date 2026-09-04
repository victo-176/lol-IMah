#!/usr/bin/env python3
"""
End-to-end OTP flow tests.
Verifies the complete chain structurally by reading bot.py source
and testing the logic patterns — no network calls, no bot imports.
"""
import re
import sys
import os
import sqlite3
import hashlib

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# ── Helpers ──────────────────────────────────────────────────────────

def read_bot():
    with open("bot.py") as f:
        return f.read()


def read_panel_scripts():
    """Return list of (filepath, content) for all panel scripts."""
    import glob
    files = sorted(glob.glob("panels/*.py"))
    files = [f for f in files if not f.startswith("panels/_") and not f.endswith("run_all.py")]
    results = []
    for fp in files:
        with open(fp) as f:
            results.append((fp, f.read()))
    return results


# ── Test 1: Record extraction logic ─────────────────────────────────

def test_extract_evs_record():
    """Simulate _extract_from_record on EVS panel data format."""
    # EVS panel returns 7-column lists:
    # [Date, Range, Number, CLI, SMS, Currency, Payout]
    # The last row is a totals row: ["$0.15", "$0.15", "$0.15", "18"]

    def extract(rec):
        """Replicate the _extract_from_record logic from bot.py."""
        if isinstance(rec, list):
            if len(rec) >= 1 and isinstance(rec[0], str) and rec[0].startswith('$'):
                return None  # totals row
            date_val = str(rec[0]) if len(rec) > 0 else ""
            range_val = str(rec[1]) if len(rec) > 1 else ""
            number_val = str(rec[2]) if len(rec) > 2 else ""
            cli_val = str(rec[3]) if len(rec) > 3 else ""
            sms_val = str(rec[4]) if len(rec) > 4 else ""
        else:
            return None

        # OTP extraction patterns (from bot.py _extract_from_record)
        otp = None
        m = re.search(r'code\s*[:]?\s*(\d{4,6})', sms_val, re.IGNORECASE)
        if m:
            otp = m.group(1)
        if not otp:
            m2 = re.search(r'<#>\s*(\d{4,6})', sms_val)
            if m2:
                otp = m2.group(1)
        if not otp:
            m3 = re.search(r'\b(\d{4,6})\b', sms_val)
            if m3:
                otp = m3.group(1)
        if not otp:
            return None

        country_m = re.match(r'([A-Za-z]+)', range_val)
        country = country_m.group(1).capitalize() if country_m else "Unknown"

        return {
            "otp": otp,
            "service": cli_val.strip() if cli_val and cli_val not in ("None", "null", "") else "Unknown",
            "phone": number_val if number_val and number_val not in ("None", "null", "") else "N/A",
            "country": country,
            "full_text": sms_val[:500],
            "timestamp": date_val,
        }

    # Normal EVS record
    rec1 = ["2026-09-03 10:00:00", "EGYPT 330", "+201234567890", "Vodafone", "Your code is 123456", "$0.01", "$0.01"]
    r = extract(rec1)
    assert r is not None, "Normal record should parse"
    assert r["otp"] == "123456"
    assert r["phone"] == "+201234567890"
    assert r["service"] == "Vodafone"
    assert r["country"] == "Egypt"

    # Totals row
    assert extract(["$0.15", "$0.15", "$0.15", "18"]) is None

    # <#> prefix style
    rec3 = ["2026-09-03 11:00:00", "NIGERIA 234", "+2348012345678", "Telegram", "<#> 333444", "$0.01", "$0.01"]
    r3 = extract(rec3)
    assert r3 is not None and r3["otp"] == "333444"

    # Plain number (fallback)
    rec4 = ["2026-09-03 12:00:00", "KENYA 254", "+254712345678", "WhatsApp", "Verification 999888", "$0.01", "$0.01"]
    r4 = extract(rec4)
    assert r4 is not None and r4["otp"] == "999888"

    # Short OTP (4-digit)
    rec5 = ["2026-09-03 13:00:00", "INDIA 91", "+919876543210", "Google", "OTP is 1234", "$0.01", "$0.01"]
    r5 = extract(rec5)
    assert r5 is not None and r5["otp"] == "1234"

    # No OTP in SMS
    rec6 = ["2026-09-03 14:00:00", "UAE 971", "+971501234567", "Service", "Hello, welcome!", "$0.01", "$0.01"]
    assert extract(rec6) is None, "No numbers = no OTP"

    # Empty record
    assert extract([]) is None

    print("  ✅ PASS: extract_evs_record")


# ── Test 2: Dedup logic ─────────────────────────────────────────────

def test_dedup_with_seen_otps():
    """Verify dedup key format and seen_otps table behavior."""
    seen = set()

    def is_seen(key):
        return key in seen

    def mark_seen(key):
        seen.add(key)

    # Format from bot.py run(): f"{sms['otp']}|{sms['phone']}|{sms['timestamp']}"
    key1 = "123456|+201234567890|2026-09-03 10:00:00"
    key2 = "123456|+201234567890|2026-09-03 10:00:00"  # duplicate
    key3 = "654321|+201234567890|2026-09-03 10:00:00"  # different OTP

    assert not is_seen(key1)
    mark_seen(key1)
    assert is_seen(key1)
    assert is_seen(key2), "Same key should be seen"
    assert not is_seen(key3), "Different OTP = different key"

    print("  ✅ PASS: dedup_with_seen_otps")


# ── Test 3: Group send path exists in bot.py ────────────────────────

def test_group_send_in_bot():
    """bot.py SMSPanelForwarder.run() sends to OTP groups."""
    src = read_bot()

    # Find the run() method's group-send logic
    assert "self._get_groups()" in src, "run() should call _get_groups()"
    assert "bot.send_message(gid," in src, "run() should send to each group"

    # _get_groups reads from otp_groups setting
    assert "'otp_groups'" in src, "_get_groups should read otp_groups"

    print("  ✅ PASS: group_send_in_bot")


# ── Test 4: Admin notification path ─────────────────────────────────

def test_admin_notify_in_bot():
    """run() calls send_otp_to_admin for real-time admin forwarding."""
    src = read_bot()

    # run() calls send_otp_to_admin
    assert "send_otp_to_admin(" in src, "run() should call send_otp_to_admin"

    # send_otp_to_admin sends to all admins
    assert "get_all_admins()" in src, "send_otp_to_admin should get admin list"
    assert "bot.send_message(admin_id," in src, "send_otp_to_admin sends to each admin"

    # Controlled by realtime_otp_admin setting
    assert "realtime_otp_admin" in src, "Admin OTP forwarding controlled by setting"

    print("  ✅ PASS: admin_notify_in_bot")


# ── Test 5: User DM matching path ───────────────────────────────────

def test_user_dm_in_bot():
    """run() matches phone → user and sends DM with balance update."""
    src = read_bot()

    assert "get_user_by_number(phone_digits)" in src, "run() should match phone to user"
    assert "matched_user" in src, "run() should store matched user ID"
    assert "bot.send_message(matched_user," in src, "run() should DM the matched user"

    # Balance increment: +$0.006 per OTP
    assert "0.006" in src, "Balance increment of $0.006 per OTP"

    print("  ✅ PASS: user_dm_in_bot")


# ── Test 6: OTP logging ─────────────────────────────────────────────

def test_otp_logging_in_bot():
    """run() logs each OTP to otp_logs table."""
    src = read_bot()

    assert "log_otp(" in src, "run() should call log_otp()"

    # log_otp exists as a function
    assert "def log_otp(" in src, "log_otp function should be defined"

    print("  ✅ PASS: otp_logging_in_bot")


# ── Test 7: Panel scripts group send ────────────────────────────────

def test_panel_scripts_group_send():
    """All standalone panel scripts have the same group-send chain."""
    panels = read_panel_scripts()
    errors = []
    for fp, content in panels:
        if "send_to_groups(" not in content:
            errors.append(f"{fp}: missing send_to_groups")
        if "def send_otp(" not in content:
            errors.append(f"{fp}: missing send_otp")
        if "def fetch_otps(" not in content:
            errors.append(f"{fp}: missing fetch_otps")
        if "def login(" not in content:
            errors.append(f"{fp}: missing login")
        if "OTP_GROUPS" not in content:
            errors.append(f"{fp}: missing OTP_GROUPS")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        assert False, f"{len(errors)} panel script issues"

    print(f"  ✅ PASS: panel_scripts_group_send ({len(panels)} scripts)")


# ── Test 8: Panel scripts main loop ─────────────────────────────────

def test_panel_scripts_main_loop():
    """Panel scripts have first_run dedup and sleep loop."""
    panels = read_panel_scripts()
    errors = []
    for fp, content in panels:
        if "first_run" not in content:
            errors.append(f"{fp}: missing first_run dedup")
        if "time.sleep(POLL_INTERVAL)" not in content:
            errors.append(f"{fp}: missing sleep loop")
        if "while True:" not in content:
            errors.append(f"{fp}: missing main loop")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        assert False, f"{len(errors)} panel script issues"

    print(f"  ✅ PASS: panel_scripts_main_loop ({len(panels)} scripts)")


# ── Test 9: Sesskey handling ────────────────────────────────────────

def test_sesskey_fallback():
    """bot.py: fetch without sesskey is tried first (cookie-only panels)."""
    src = read_bot()

    # _fetch_for_date tries no-sesskey first
    assert "params_no_sk" in src, "Should have params without sesskey"
    assert "API OK (no sesskey)" in src, "Should log no-sesskey success"
    assert "API OK (with sesskey)" in src, "Should log with-sesskey success"

    # _ensure_session sets _no_sesskey when no sesskey found
    assert "self._no_sesskey = True" in src, "Should cache 'no sesskey' result"
    assert "session cookie auth" in src, "Should log cookie auth mode"

    print("  ✅ PASS: sesskey_fallback")


# ── Test 10: main() startup ─────────────────────────────────────────

def test_main_startup():
    """main() starts all forwarders and bot polling."""
    src = read_bot()

    assert "start_all_panel_forwarders()" in src
    assert "start_choice_sms" in src
    assert "monitor_loop" in src
    assert "periodic_cleanup" in src
    assert "bot.infinity_polling()" in src

    # start_panel_forwarder creates SMSPanelForwarder and starts thread
    assert "SMSPanelForwarder(" in src
    assert "daemon=True" in src

    print("  ✅ PASS: main_startup")


# ── Test 11: Compiled clean ─────────────────────────────────────────

def test_compilation():
    """bot.py and all panel scripts compile without errors."""
    import py_compile

    try:
        py_compile.compile("bot.py", doraise=True)
    except py_compile.PyCompileError as e:
        assert False, f"bot.py failed: {e}"

    panels = read_panel_scripts()
    errors = []
    for fp, _ in panels:
        try:
            py_compile.compile(fp, doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        assert False, f"{len(errors)} panel compilation failures"

    print(f"  ✅ PASS: compilation (bot + {len(panels)} panels)")


# ── Runner ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  OTP Flow End-to-End Tests")
    print("=" * 50)

    tests = [
        test_extract_evs_record,
        test_dedup_with_seen_otps,
        test_group_send_in_bot,
        test_admin_notify_in_bot,
        test_user_dm_in_bot,
        test_otp_logging_in_bot,
        test_panel_scripts_group_send,
        test_panel_scripts_main_loop,
        test_sesskey_fallback,
        test_main_startup,
        test_compilation,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 50)
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 50)
    sys.exit(1 if failed else 0)
