#!/usr/bin/env python3
"""
Functional test for multi-number-per-user flow.
Verifies that when a user is assigned several numbers (num_per_request > 1),
OTPs arriving on ANY of their numbers match the user, release/availability
handle CSV cells, and conflicts are still rejected.
"""
import os, sys, json, sqlite3, tempfile, importlib.util, types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Load bot.py as a module without starting polling
spec = importlib.util.spec_from_file_location("botmod", "bot.py")
botmod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(botmod)
except SystemExit:
    pass

# Redirect the DB to an isolated temp file (patch module globals, no env vars)
_tmpdir = tempfile.mkdtemp()
botmod.DB_PATH = os.path.join(_tmpdir, "test.db")
try:
    botmod.init_db()
except Exception as e:
    print(f"init_db warning: {e}")

conn = sqlite3.connect(botmod.DB_PATH)
c = conn.cursor()
c.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, assigned_number, balance) VALUES (111,'alice','Alice','',0)")
c.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, assigned_number, balance) VALUES (222,'bob','Bob','',0)")
c.execute("INSERT OR REPLACE INTO combos (country_code, app_name, combo_index, numbers, price_per_otp) VALUES ('NG','1xBet',1,?, 0.01)",
          (json.dumps(['2348011111101', '2348011111102', '2348011111103', '2348011111104']),))
conn.commit()
conn.close()

failures = []

def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)

print("[1] Multi-assign appends instead of overwriting")
r1 = botmod.assign_number_to_user(111, '2348011111101')
r2 = botmod.assign_number_to_user(111, '2348011111102')
r3 = botmod.assign_number_to_user(111, '2348011111103')
u = botmod.get_user(111)
check("all three assigned", r1 and r2 and r3)
check("cell holds all 3", u[5] == '2348011111101,2348011111102,2348011111103', f"got '{u[5]}'")

print("[2] OTP on ANY assigned number matches the user (the reported bug)")
check("num1 -> alice", botmod.get_user_by_number('2348011111101') == 111)
check("num2 -> alice", botmod.get_user_by_number('2348011111102') == 111)
check("num3 -> alice", botmod.get_user_by_number('2348011111103') == 111)
check("num4 (unassigned) -> nobody", botmod.get_user_by_number('2348011111104') is None)

print("[3] Partial release removes only the released number")
botmod.release_number('2348011111102')
u = botmod.get_user(111)
check("cell keeps 1 and 3", u[5] == '2348011111101,2348011111103', f"got '{u[5]}'")
check("released num matches nobody", botmod.get_user_by_number('2348011111102') is None)

print("[4] Availability check treats every CSV member as used")
avail = botmod.get_available_numbers('NG', 1, None)
check("assigned nums excluded", '2348011111101' not in avail and '2348011111103' not in avail, str(avail))
check("free num still available", '2348011111104' in avail, str(avail))

print("[5] Conflict guard still works across users")
check("bob cannot take alice's num", botmod.assign_number_to_user(222, '2348011111101') == False)

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL MULTI-NUMBER TESTS PASSED")
