#!/usr/bin/env python3
"""
Functional test for the change-number → stock-deletion flow.

When a user changes their number (chg_local -> fetch_number_logic -> release_number):
1. Old number(s) are deleted from combo stock and private stock entirely.
2. Multi-number CSV cells release every number (not just an exact-match single).
3. Matching is digit-normalized (+ prefix / formatting differences still hit).
4. Stock stays self-healed: numbers already assigned never linger in stock
   (purge_assigned_from_stock).
"""
import os, sys, json, sqlite3, tempfile, importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

spec = importlib.util.spec_from_file_location("botmod", "bot.py")
botmod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(botmod)
except SystemExit:
    pass

_tmp = tempfile.mkdtemp()
botmod.DB_PATH = os.path.join(_tmp, "t.db")
botmod.init_db()

conn = sqlite3.connect(botmod.DB_PATH); c = conn.cursor()
c.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, assigned_number, balance) VALUES (1,'u','U','',0)")
c.execute("INSERT INTO combos (country_code, combo_index, numbers, app_name) VALUES ('NG',1,?,'1xBet')",
          (json.dumps(['+2348011111101', '2348011111102']),))
c.execute("INSERT INTO combos (country_code, combo_index, numbers, app_name) VALUES ('NG',2,?,'1xBet')",
          (json.dumps(['2348011111103']),))
conn.commit(); conn.close()

failures = []

def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)

print("[1] Assign normalized (+ prefixed) stock number")
check("assign +234... succeeds", botmod.assign_number_to_user(1, '+2348011111101'))
u = botmod.get_user(1)
check("cell holds digits-only", u[5] == '2348011111101', f"got {u[5]!r}")

print("[2] release_number deletes from stock across formats")
botmod.release_number('+2348011111101')
check("stock row1 no longer has it",
      json.loads(sqlite3.connect(botmod.DB_PATH).execute(
          "SELECT numbers FROM combos WHERE combo_index=1").fetchone()[0]) == ['2348011111102'])
check("user assignment cleared", not botmod.get_user(1)[5])

print("[3] Multi-number change (CSV cell) deletes ALL old numbers from stock")
botmod.assign_number_to_user(1, '2348011111102')
botmod.assign_number_to_user(1, '2348011111103')
conn = sqlite3.connect(botmod.DB_PATH)
conn.execute("INSERT OR REPLACE INTO users (user_id,username,first_name,assigned_number,balance) VALUES (1,'u','U','2348011111102,2348011111103',0)")
conn.commit(); conn.close()
botmod.release_number('2348011111102,2348011111103')
conn = sqlite3.connect(botmod.DB_PATH)
rows = conn.execute("SELECT combo_index, numbers FROM combos ORDER BY combo_index").fetchall()
conn.close()
left = [n for _, js in rows for n in json.loads(js)]
check("all old numbers gone from stock", left == [], f"left={left}")

print("[4] purge_assigned_from_stock self-heal")
conn = sqlite3.connect(botmod.DB_PATH)
conn.execute("INSERT INTO combos (country_code, combo_index, numbers, app_name) VALUES ('NG',3,?,\"1xBet\")",
             (json.dumps(['2348011111102', '2349999999999']),))
conn.commit(); conn.close()
botmod.assign_number_to_user(1, '2348011111102')
botmod.purge_assigned_from_stock()
conn = sqlite3.connect(botmod.DB_PATH)
js = conn.execute("SELECT numbers FROM combos WHERE combo_index=3").fetchone()[0]
conn.close()
check("assigned num purged, free num kept", json.loads(js) == ['2349999999999'], js)

print("[5] Availability uses digit keys")
conn = sqlite3.connect(botmod.DB_PATH)
conn.execute("INSERT OR REPLACE INTO users (user_id,username,first_name,assigned_number,balance) VALUES (2,'v','V','+2349999999999',0)")
conn.commit(); conn.close()
avail = botmod.get_available_numbers('NG', 3, None)
check("+2349999999999 correctly unavailable", '2349999999999' not in avail, str(avail))
check("avail empty (all assigned)", avail == [], str(avail))

print("[6] Conflict guard across formats")
check("user1 cannot take user2's + number", botmod.assign_number_to_user(1, '+2349999999999') == False)

print("[7] Ever-assigned guard: a number once given to user A never goes to user B")
conn = sqlite3.connect(botmod.DB_PATH)
conn.execute("INSERT OR REPLACE INTO users (user_id,username,first_name,assigned_number,balance) VALUES (1,'u','U','',0)")
conn.execute("INSERT OR REPLACE INTO users (user_id,username,first_name,assigned_number,balance) VALUES (2,'v','V','',0)")
conn.execute("INSERT INTO combos (country_code, combo_index, numbers, app_name) VALUES ('NG',4,?,'1xBet')",
             (json.dumps(['2348012222201', '2348012222202']),))
conn.commit(); conn.close()
check("user1 gets 2348012222201", botmod.assign_number_to_user(1, '2348012222201'))
botmod.release_number('2348012222201')  # user1 changes number
check("user2 rejected 2348012222201 (ever-assigned)",
      botmod.assign_number_to_user(2, '2348012222201') == False)
check("user1 can still reuse own old number", botmod.assign_number_to_user(1, '2348012222201'))
botmod.release_number('2348012222201')
avail2 = botmod.get_available_numbers('NG', 4, 2)
check("ever-assigned num hidden from user2 availability", '2348012222201' not in avail2, str(avail2))

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL STOCK-CHANGE TESTS PASSED")
