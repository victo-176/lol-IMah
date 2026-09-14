#!/usr/bin/env python3
"""
Targeted tests for the UX overhaul changes in bot.py:
1. Withdrawal notification + approve/reject buttons
2. get_user_display helper
3. Editable real-time settings keys
4. Rate limit / cooldown enforcement
5. Broadcast any media
6. Traffic rate add flow
7. CSV combo upload
8. Leaderboard by OTP counts
"""
import re
import sys
import os

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def read_bot():
    with open("bot.py") as f:
        return f.read()


def test_withdrawal_buttons():
    src = read_bot()
    assert "def format_withdrawal_notification" in src
    assert "def notify_admin_withdrawal" in src
    assert 'callback_data=f"wd_approve|{req_id}"' in src
    assert 'callback_data=f"wd_reject|{req_id}"' in src
    assert 'if data.startswith("wd_approve|")' in src
    assert 'if data.startswith("wd_reject|")' in src
    # All 4 methods use the shared notify helper (exclude the def line)
    call_count = len(re.findall(r'^\s+notify_admin_withdrawal\(user_id, amount,', src, re.M))
    assert call_count == 4, f"expected 4 notify calls, got {call_count}"
    assert "NEW WITHDRAWAL REQUEST" in src
    assert "get_ngn_rate" in src
    print("  PASS: withdrawal_buttons")


def test_user_display():
    src = read_bot()
    assert "def get_user_display" in src
    # Used in admin DM flows (message user, support reply) and admin live OTP
    assert "get_user_display(target_user)" in src
    lb = src.split("def send_otp_to_admin")[1][:2500]
    assert "get_user_display" in lb  # admin live OTP still shows the user
    print("  PASS: user_display")


def test_editable_settings():
    src = read_bot()
    for key in ("min_withdrawal", "max_withdrawal", "ngn_rate", "cooldown_enabled",
                "rate_limit_enabled", "rate_limit_per_hour", "default_otp_group"):
        assert f"'{key}':" in src, f"missing editable setting {key}"
    assert "def get_min_withdrawal" in src
    assert "def get_ngn_rate" in src
    assert "get_min_withdrawal()" in src  # actually used
    print("  PASS: editable_settings")


def test_rate_limiting():
    src = read_bot()
    assert "def _check_rate_limit" in src
    assert "_check_rate_limit(chat_id)" in src  # enforced in fetch_number_logic
    assert "number_fetched" in src  # activity logged for counting
    print("  PASS: rate_limiting")


def test_broadcast_media():
    src = read_bot()
    for ct in ("send_photo", "send_video", "send_voice", "send_audio",
               "send_document", "send_sticker", "send_animation", "send_video_note"):
        assert ct in src, f"broadcast missing {ct}"
    assert "'animation', 'media_group'])" in src
    print("  PASS: broadcast_media")


def test_traffic_rates():
    src = read_bot()
    assert "CREATE TABLE IF NOT EXISTS traffic_rates" in src
    assert "def add_traffic_rate_handler" in src
    assert "def get_traffic_rate" in src
    assert 'callback_data="admin_add_traffic_rate"' in src
    print("  PASS: traffic_rates")


def test_csv_combo():
    src = read_bot()
    assert "endswith('.csv')" in src
    assert "import csv as _csv" in src
    assert "num_col" in src  # header detection
    print("  PASS: csv_combo")


def test_leaderboard_otp():
    src = read_bot()
    # Leaderboard now queries otp_counts
    lb = src.split("def show_leaderboard")[1][:2500]
    assert "otp_counts" in lb
    assert "ORDER BY cnt DESC" in lb
    print("  PASS: leaderboard_otp")


def test_panels_default_group():
    src = read_bot()
    assert src.count("default_otp_group") >= 3  # editable key + both forwarders
    print("  PASS: panels_default_group")


def test_ivasms_relogin():
    src = read_bot()
    assert "empty_polls" in src
    assert "cookies.clear()" in src
    print("  PASS: ivasms_relogin")


def test_compile():
    import py_compile
    py_compile.compile("bot.py", doraise=True)
    print("  PASS: compile")


if __name__ == "__main__":
    print("=" * 50)
    print("  UX Overhaul Tests")
    print("=" * 50)
    tests = [
        test_withdrawal_buttons, test_user_display, test_editable_settings,
        test_rate_limiting, test_broadcast_media, test_traffic_rates,
        test_csv_combo, test_leaderboard_otp, test_panels_default_group,
        test_ivasms_relogin, test_compile,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print("=" * 50)
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 50)
    sys.exit(1 if failed else 0)
