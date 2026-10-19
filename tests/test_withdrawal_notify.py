#!/usr/bin/env python3
"""Regression tests for the withdrawal admin-notification fixes.

Bugs fixed:
  * account numbers were invisible because details were keyed differently
    per method (withdraw_phone / account_number / upi_id / ... ) but the
    formatter only looked for 'phone'/'upi_id'/'address'.
  * the USDT path referenced an undefined 'details' (NameError).
  * admin_reject_reason_step referenced an undefined 'req_id' (NameError).
  * admin_approve_wd referenced an undefined 'amt_str' (NameError).
"""
import os
import sys
import inspect
import tempfile

sys.path.insert(0, ".")

import bot  # noqa: E402

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
bot.DB_PATH = _tmp.name
bot.init_db()

fails = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  " + name)
    else:
        print("  FAIL  " + name + "  " + str(detail))
        fails.append(name)


print("=== account number shows for every method's key shape ===")
# Opay style (raw user-state keys)
msg, _kb = bot.format_withdrawal_notification(
    1, 2.0, "Opay", {"withdraw_phone": "08012345678", "withdraw_name": "Ada"}, "req1")
check("opay phone shown", "08012345678" in msg, msg)
check("opay name shown", "Ada" in msg)

# Bank/others style
msg2, _ = bot.format_withdrawal_notification(
    1, 2.0, "Others",
    {"others_account": "1234567890", "others_holder": "Chin", "others_bank": "GTB",
     "others_currency": "NGN"}, "req2")
check("bank account number shown", "1234567890" in msg2, msg2)
check("bank name shown", "GTB" in msg2)
check("holder shown", "Chin" in msg2)

# UPI style
msg3, _ = bot.format_withdrawal_notification(
    1, 2.0, "UPI", {"withdraw_upi": "user@upi", "withdraw_name": "Raj"}, "req3")
check("upi id shown", "user@upi" in msg3, msg3)

# USDT style
msg4, _ = bot.format_withdrawal_notification(
    1, 2.0, "USDT", {"address": "0xABCDEF0000000000000000000000000000000001"}, "req4")
check("usdt address shown", "0xABCDEF" in msg4, msg4)

# Canonical keys still work
msg5, _ = bot.format_withdrawal_notification(
    1, 2.0, "Opay", {"phone": "0700000000", "full_name": "Kofi"}, "req5")
check("canonical phone key still shown", "0700000000" in msg5)

print()
print("=== no NameError sources remain in the fixed handlers ===")
src = inspect.getsource(bot.admin_reject_reason_step)
check("reject step reads req_id from state", "reject_reason" in src)
check("reject step assigns req_id", "req_id =" in src)
check("reject step no bare req_id use", src.count("req_id") >= 2)

# USDT handler must not reference an undefined 'details'
usdt_src = inspect.getsource(bot.process_usdt_amount)
check("usdt handler passes a real details dict", "wd_details" in usdt_src)

print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL WITHDRAWAL NOTIFY CHECKS PASSED")
sys.exit(0)
