#!/usr/bin/env python3
"""Regression test: admin Upload / Restore Database must actually restore.

The handler used to fail in two places before touching the file:

1. clear_state() was called with bare chat/user ids, but it expects the
   message object (it pops message.chat.id / message.from_user.id), so the
   very first line raised AttributeError — the handler died, no download,
   no restore, no reply.
2. The download used telebot.apihelper.download_file(token, file_id, path),
   but that helper's real signature is download_file(token, file_path) —
   it takes a Telegram server file path, not a file_id + destination, so
   it raised TypeError and no bytes were ever written.

This exercises the REAL handler end-to-end with only the network stubbed.

Run:  python3 tests/test_db_restore.py
"""
import os
import sys
import sqlite3
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bot  # noqa: E402

fails = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


class Obj:
    pass


OWNER = bot.ADMIN_IDS[0]
tmpdir = tempfile.mkdtemp(prefix="dbrestore_")

SCHEMA = [
    "CREATE TABLE users (user_id INTEGER PRIMARY KEY, balance REAL)",
    "CREATE TABLE admins (user_id INTEGER PRIMARY KEY)",
    "CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)",
]

# ---- the file "the admin sends in" ----
upload_path = os.path.join(tmpdir, "old_backup.db")
conn = sqlite3.connect(upload_path)
for stmt in SCHEMA:
    conn.execute(stmt)
conn.execute("INSERT INTO bot_settings (key, value) VALUES ('watermark', 'RESTORED_MARKER_XYZ')")
conn.commit()
conn.close()

# ---- the live DB the bot currently runs with ----
live_db = os.path.join(tmpdir, "live.db")
conn = sqlite3.connect(live_db)
for stmt in SCHEMA:
    conn.execute(stmt)
conn.execute("INSERT INTO bot_settings (key, value) VALUES ('watermark', 'OLD_LIVE_DATA')")
conn.commit()
conn.close()

backup_dir = os.path.join(tmpdir, "backups")
os.makedirs(backup_dir, exist_ok=True)

# Redirect the module under test to the sandboxed paths
bot.DB_PATH = live_db
bot.BACKUP_DIR = backup_dir

replies = []
downloads = []
payload = {"bytes": open(upload_path, "rb").read()}


def fake_get_file(file_id):
    o = Obj()
    o.file_path = f"documents/{file_id}"
    return o


def fake_download_file(file_path):
    downloads.append(file_path)
    return payload["bytes"]


def fake_reply_to(message, text, *a, **k):
    replies.append(text)
    return None


bot.bot.get_file = fake_get_file
bot.bot.download_file = fake_download_file
bot.bot.reply_to = fake_reply_to


def make_message(name, size=None):
    m = Obj()
    m.chat = Obj()
    m.chat.id = OWNER
    m.from_user = Obj()
    m.from_user.id = OWNER
    m.content_type = "document"
    m.document = Obj()
    m.document.file_name = name
    m.document.file_id = "FAKEFILEID"
    m.document.file_size = size if size is not None else len(payload["bytes"])
    return m


def read_marker():
    conn = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM bot_settings WHERE key='watermark'").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ------------------------------------------------ 1) happy path
msg = make_message("backup.db")
bot.set_state(OWNER, "waiting_db_file")
check("state set before send", bot.get_state(msg) == "waiting_db_file")

raised = None
try:
    bot.handle_db_restore_file(msg)
except Exception as e:  # noqa: BLE001
    raised = e

check("handler runs without raising", raised is None, f"raised: {raised!r}")
check("file downloaded exactly once", len(downloads) == 1, f"downloads={downloads}")
check("live DB replaced by the upload",
      read_marker() == "RESTORED_MARKER_XYZ", f"marker={read_marker()!r}")
check("state cleared after handling", bot.get_state(msg) is None)
check("success reply sent", any("Database restored" in r for r in replies),
      f"replies={replies!r}")

backups = sorted(os.listdir(backup_dir))
check("rollback backup created before overwrite",
      any(b.startswith("bot_pre_restore_") for b in backups), f"files={backups}")
check("temp upload file cleaned up",
      not any(f.startswith("upload_") for f in backups), f"files={backups}")

# ------------------------------------------------ 2) wrong file type rejected
replies.clear()
msg2 = make_message("notes.txt")
bot.set_state(OWNER, "waiting_db_file")
bot.handle_db_restore_file(msg2)
check("non-.db file rejected", any("Send a" in r and ".db" in r for r in replies),
      f"replies={replies!r}")
check("state cleared on reject", bot.get_state(msg2) is None)
check("live DB untouched by rejected file",
      read_marker() == "RESTORED_MARKER_XYZ", f"marker={read_marker()!r}")

# ------------------------------------------------ 3) invalid sqlite rejected
payload["bytes"] = b"definitely not a sqlite database " * 100  # > 512 bytes
replies.clear()
msg3 = make_message("garbage.db", size=len(payload["bytes"]))
bot.set_state(OWNER, "waiting_db_file")
bot.handle_db_restore_file(msg3)
check("invalid DB rejected with explanation",
      any("Invalid database file" in r for r in replies), f"replies={replies!r}")
check("state cleared on invalid file", bot.get_state(msg3) is None)
check("live DB untouched by invalid file",
      read_marker() == "RESTORED_MARKER_XYZ", f"marker={read_marker()!r}")

# ------------------------------------------------ 4) dispatch: state filter matches
# is_admin() reads the live DB, so make the owner an admin there first.
conn = sqlite3.connect(live_db)
conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER,))
conn.commit()
conn.close()

handler_entry = next(
    (h for h in bot.bot.message_handlers
     if h["function"] is bot.handle_db_restore_file), None)
check("restore handler registered for documents", handler_entry is not None)
if handler_entry is not None:
    # exact same evaluation telebot uses when a message arrives
    test = bot.bot._test_message_handler
    bot.set_state(OWNER, "waiting_db_file")
    check("filter matches owner + state + document", bool(test(handler_entry, msg)))
    bot.user_states.pop(OWNER, None)
    check("filter rejects once state is gone", not test(handler_entry, msg))

# ------------------------------------------------ summary
print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL DB RESTORE TESTS PASSED")
