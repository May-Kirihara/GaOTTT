#!/usr/bin/env python3
"""Verify that FAISS contains all non-archived SQLite nodes.

Run after `compact(rebuild_faiss=True)` with the new _rebuild_faiss_index fix.

Usage:
    .venv/bin/python scripts/verify_faiss_recovery.py [node_id_prefix ...]

Prints SQLite count vs FAISS count, and checks specific node IDs if given.
"""

import sys
import sqlite3

DB_PATH = "/home/misaki_maihara/.local/share/gaottt/gaottt.db"
FAISS_IDS_PATH = "/home/misaki_maihara/.local/share/gaottt/gaottt.faiss.ids"

con = sqlite3.connect(DB_PATH)
sqlite_count = con.execute(
    "SELECT COUNT(*) FROM documents d JOIN nodes n ON d.id=n.id WHERE n.is_archived=0"
).fetchone()[0]

with open(FAISS_IDS_PATH) as f:
    faiss_ids = {line.strip() for line in f if line.strip()}

faiss_count = len(faiss_ids)
gap = sqlite_count - faiss_count

print(f"SQLite non-archived: {sqlite_count}")
print(f"FAISS ids:           {faiss_count}")
print(f"Gap:                 {gap}  {'✅ OK' if gap == 0 else '❌ MISSING'}")

# Check specific IDs if provided
check_ids = sys.argv[1:] if len(sys.argv) > 1 else [
    "0185c463", "c8878b4c", "f2083964", "540c05dd", "6de9ee7a", "60e1b3c6", "b051203a"
]
print()
for short in check_ids:
    matches = [fid for fid in faiss_ids if fid.startswith(short)]
    status = "✅ IN FAISS" if matches else "❌ MISSING"
    print(f"  {short}  {status}")

con.close()
