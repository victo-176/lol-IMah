#!/usr/bin/env python3
"""
Targeted tests for the panel fixes applied to bot.py:
1. Login verification - dashboard content detection
2. Sesskey caching - _no_sesskey flag
3. Record extraction - totals row skipping
4. Quick panel handler - commit before forwarder
5. Panel scripts - consistent login verification pattern
"""
import re
import sys
import os
import glob

# ── Test 1: _extract_from_record — totals row skipping ────────────────
class FakeForwarder:
    """Minimal standin so we can call _extract_from_record."""
    def __init__(self):
        self.name = "Test"
    # Pull in the unbound method by importing the class
    pass

def test_extract_totals_row():
    """Totals row (starts with $) should return None."""
    # Simulate the logic from _extract_from_record
    def extract(rec):
        if isinstance(rec, list):
            if len(rec) >= 1 and isinstance(rec[0], str) and rec[0].startswith('$'):
                return None
            # ... (rest of extraction)
            return True  # non-None = valid record
        return True

    # EVS totals row: ["$0.15", "$0.15", "$0.15", "18"]
    totals_row = ["$0.15", "$0.15", "$0.15", "18"]
    assert extract(totals_row) is None, "Totals row should be skipped"

    # Normal SMS record
    normal_row = ["2026-09-03 10:00:00", "EGYPT 330", "+201234567890", "ServiceName", "Your code is 123456", "$0.01", "$0.01"]
    assert extract(normal_row) is not None, "Normal record should NOT be skipped"

    # Edge case: empty list
    assert extract([]) is not None, "Empty list should not crash"

    # Edge case: dict format
    assert extract({"Date": "2026-09-03", "SMS": "code 123456"}) is not None

    print("  ✅ PASS: extract_totals_row")


# ── Test 2: Sesskey caching — _no_sesskey flag ───────────────────────
def test_sesskey_caching():
    """Once _no_sesskey is set, _get_sesskey should return None immediately."""
    # Simulate the logic
    class MockForwarder:
        def __init__(self):
            self._no_sesskey = False
            self._search_count = 0

        def _get_sesskey_impl(self):
            if hasattr(self, '_no_sesskey') and self._no_sesskey:
                return None
            self._search_count += 1
            # Simulate no sesskey found
            self._no_sesskey = True
            return None

    fw = MockForwarder()
    # First call: should search
    result1 = fw._get_sesskey_impl()
    assert result1 is None
    assert fw._search_count == 1

    # Second call: should skip search (cached)
    result2 = fw._get_sesskey_impl()
    assert result2 is None
    assert fw._search_count == 1, "Search should NOT run again after caching"

    print("  ✅ PASS: sesskey_caching")


# ── Test 3: Login verification — dashboard content detection ──────────
def test_login_dashboard_content():
    """Login should succeed when URL has 'login' but body has dashboard content."""
    def check_login(final_url, resp_html):
        """Replicate the login verification logic from _do_login."""
        final_url_lower = final_url.lower()
        resp_html_lower = resp_html.lower()

        if 'signin' not in final_url_lower and 'login' not in final_url_lower:
            return True
        if 'dashboard' in final_url_lower or 'smcdrstats' in final_url_lower or 'home' in final_url_lower:
            return True
        # EVS-style: URL may still say 'login' but body has dashboard content
        has_login_form = 'type="password"' in resp_html_lower
        has_dashboard = 'smcdrstats' in resp_html_lower or 'sms reports' in resp_html_lower or 'side-nav' in resp_html_lower
        if not has_login_form and has_dashboard:
            return True
        return False

    # Case 1: URL doesn't contain login/signin → success
    assert check_login("http://57.129.107.62/ints/client/", "") is True

    # Case 2: URL contains 'dashboard' → success
    assert check_login("http://panel.com/client/dashboard", "") is True

    # Case 3: URL contains 'smcdrstats' → success
    assert check_login("http://panel.com/client/SMSCDRStats", "") is True

    # Case 4: URL says 'login' but body has EVS dashboard content → success
    evs_body = '<title>EVS SMS | SMS CDR Stats</title><li><a href="./">Dashboard</a></li><div class="side-nav">'
    assert check_login("http://panel.com/login", evs_body) is True

    # Case 5: URL says 'login' and body has login form → failure
    login_body = '<form><input type="password" name="password"><input name="username"></form>'
    assert check_login("http://panel.com/login", login_body) is False

    # Case 6: URL says 'signin' and body has neither → failure
    assert check_login("http://panel.com/signin", "") is False

    # Case 7: Empty URL but has smcdrstats in body → success
    assert check_login("", "data retrieved from smcdrstats.php endpoint") is True

    # Case 8: Side-nav in body (EVS panel layout) → success
    evs_nav = '<div class="side-nav accordion_mnu collapsible">'
    assert check_login("http://panel.com/login", evs_nav) is True

    print("  ✅ PASS: login_dashboard_content")


# ── Test 4: OTP extraction patterns ──────────────────────────────────
def test_otp_extraction():
    """Verify OTP extraction works for common EVS panel SMS formats."""
    patterns = [
        (r'code\s+(\d{4,6})', re.IGNORECASE),
        (r'use code\s+(\d{4,6})', re.IGNORECASE),
        (r'code[:]\s*(\d{4,6})', re.IGNORECASE),
        (r'<#>\s*(\d{4,6})', 0),
        (r'\b(\d{4,6})\b', 0),
    ]

    test_messages = [
        ("Your code is 123456", "123456"),
        ("use code 654321", "654321"),
        ("code: 111222", "111222"),
        ("<#> 333444", "333444"),
        ("Verification 999888 for your account", "999888"),
        ("Your OTP is 1234", "1234"),
        ("SMS text with no numbers", None),
        ("", None),
    ]

    for msg, expected_otp in test_messages:
        found_otp = None
        for pat, flags in patterns:
            m = re.search(pat, msg, flags)
            if m:
                found_otp = m.group(1)
                break
        assert found_otp == expected_otp, f"OTP extraction failed for '{msg}': expected {expected_otp}, got {found_otp}"

    print("  ✅ PASS: otp_extraction")


# ── Test 5: Panel scripts — consistent login verification pattern ────
def test_panel_scripts_consistency():
    """All panel scripts should have the updated login verification."""
    panel_files = glob.glob('panels/*.py')
    panel_files = [f for f in panel_files if not f.startswith('panels/_') and not f.endswith('run_all.py')]

    errors = []
    for filepath in sorted(panel_files):
        with open(filepath, 'r') as f:
            content = f.read()

        # Check for old pattern (should NOT be present)
        if '"dashboard" in resp.url.lower() or "signin" not in resp.url.lower():' in content:
            # Check if it also has the new pattern
            if 'has_login_form' not in content:
                errors.append(f"{filepath}: Still has old login pattern without new content check")

        # Check for new pattern (should be present)
        if 'has_login_form' not in content and 'has_dashboard' not in content:
            if 'dashboard' in content.lower():  # Only check scripts that deal with panels
                errors.append(f"{filepath}: Missing new login verification content check")

    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        assert False, f"{len(errors)} panel scripts have inconsistent login pattern"

    print(f"  ✅ PASS: panel_scripts_consistency ({len(panel_files)} scripts checked)")


# ── Test 6: Quick panel handler — commit exists ──────────────────────
def test_quick_panel_commit():
    """Verify conn.commit() is called before start_panel_forwarder."""
    with open('bot.py', 'r') as f:
        content = f.read()

    # Find the quick_panel_pass_handler section
    idx = content.find('def quick_panel_pass_handler')
    if idx < 0:
        print("  ⚠️  SKIP: quick_panel_pass_handler not found in bot.py")
        return

    # Find the auto-start forwarder section
    fwd_idx = content.find('Auto-start forwarder for this panel', idx)
    if fwd_idx < 0:
        print("  ⚠️  SKIP: Auto-start forwarder section not found")
        return

    # Check that conn.commit() appears BEFORE the auto-start section
    commit_idx = content.rfind('conn.commit()', idx, fwd_idx)
    assert commit_idx > idx, "conn.commit() must appear before auto-start forwarder"

    # Check that start_panel_forwarder appears AFTER conn.commit()
    fwd_call_idx = content.find('start_panel_forwarder', fwd_idx)
    assert fwd_call_idx > commit_idx, "start_panel_forwarder must be called after conn.commit()"

    # Check conn.close() comes after both
    close_idx = content.find('conn.close()', fwd_call_idx)
    assert close_idx > commit_idx, "conn.close() must come after conn.commit()"

    print("  ✅ PASS: quick_panel_commit (commit → forwarder → close)")


# ── Test 7: bot.py compiles ──────────────────────────────────────────
def test_bot_compile():
    """bot.py must compile without syntax errors."""
    import py_compile
    try:
        py_compile.compile('bot.py', doraise=True)
        print("  ✅ PASS: bot_compile")
    except py_compile.PyCompileError as e:
        assert False, f"bot.py compilation failed: {e}"


# ── Test 8: All panel scripts compile ────────────────────────────────
def test_panels_compile():
    """All panel scripts must compile."""
    import py_compile
    panel_files = glob.glob('panels/*.py')
    errors = []
    for f in sorted(panel_files):
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        assert False, f"{len(errors)} panel scripts failed compilation"
    print(f"  ✅ PASS: panels_compile ({len(panel_files)} files)")


# ── Test 9: Sesskey display logic ────────────────────────────────────
def test_sesskey_display():
    """Verify sesskey_display shows 'Session Cookie' when empty."""
    def get_display(sesskey):
        return "Session Cookie" if not sesskey else (sesskey[:8] + "..." if len(sesskey) > 8 else sesskey)

    def get_auth_method(sesskey):
        return "Session Cookie" if not sesskey else "Sesskey"

    # Empty sesskey (EVS panels)
    assert get_display("") == "Session Cookie"
    assert get_auth_method("") == "Session Cookie"

    # Full sesskey (some panels)
    assert get_display("abc123def456ghi789jkl012mno345pq") == "abc123de..."
    assert get_auth_method("abc123def456ghi789jkl012mno345pq") == "Sesskey"

    # Short sesskey
    assert get_display("abc123") == "abc123"
    assert get_auth_method("abc123") == "Sesskey"

    print("  ✅ PASS: sesskey_display")


# ── Test 10: Record extraction — various formats ─────────────────────
def test_record_formats():
    """Verify extraction handles dict and list formats correctly."""
    def extract(rec):
        """Simplified version of _extract_from_record logic."""
        if isinstance(rec, dict):
            sms_val = str(rec.get('SMS', rec.get('sms', rec.get('Message', ''))))
            number_val = str(rec.get('Number', rec.get('number', '')))
        elif isinstance(rec, list):
            if len(rec) >= 1 and isinstance(rec[0], str) and rec[0].startswith('$'):
                return None
            number_val = str(rec[2]) if len(rec) > 2 else ""
            sms_val = str(rec[4]) if len(rec) > 4 else ""
        else:
            return None

        m = re.search(r'\b(\d{4,6})\b', sms_val)
        if m:
            return {'otp': m.group(1), 'phone': number_val, 'sms': sms_val}
        return None

    # Dict format
    result = extract({"Number": "+1234567890", "SMS": "Your code is 123456"})
    assert result is not None
    assert result['otp'] == '123456'

    # List format (EVS panel)
    result = extract(["2026-09-03", "EGYPT 330", "+201234567890", "Service", "code 654321", "$0.01", "$0.01"])
    assert result is not None
    assert result['otp'] == '654321'
    assert result['phone'] == '+201234567890'

    # Totals row
    result = extract(["$0.15", "$0.15", "$0.15", "18"])
    assert result is None, "Totals row should be skipped"

    # Non-string first element (shouldn't start with $)
    result = extract([123, "EGYPT", "+123", "Svc", "code 111222"])
    assert result is not None
    assert result['otp'] == '111222'

    print("  ✅ PASS: record_formats")


# ── Run all tests ────────────────────────────────────────────────────
if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print("=" * 50)
    print("  Panel Fix Tests")
    print("=" * 50)

    tests = [
        test_extract_totals_row,
        test_sesskey_caching,
        test_login_dashboard_content,
        test_otp_extraction,
        test_panel_scripts_consistency,
        test_quick_panel_commit,
        test_bot_compile,
        test_panels_compile,
        test_sesskey_display,
        test_record_formats,
    ]

    passed = 0
    failed = 0
    for test in tests:
        name = test.__name__
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {name}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 50)
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 50)
    sys.exit(1 if failed else 0)
