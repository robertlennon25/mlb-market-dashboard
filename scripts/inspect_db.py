#!/usr/bin/env python3
# scripts/inspect_db.py
# Quick look at what's in market.db

import sys, os, sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

for table in ["cards", "price_history"]:
    rows = conn.execute(f"SELECT * FROM {table} LIMIT 5").fetchall()
    if not rows:
        print(f"\n[{table}] — empty")
        continue
    headers = rows[0].keys()
    print(f"\n[{table}] — {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:,} total rows")
    print("  " + " | ".join(f"{h:>15}" for h in headers))
    print("  " + "-" * (18 * len(headers)))
    for row in rows:
        print("  " + " | ".join(f"{str(row[h])[:15]:>15}" for h in headers))

conn.close()
