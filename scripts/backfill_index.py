#!/usr/bin/env python3
# scripts/backfill_index.py
"""
One-time script: build market_index history from all existing price_history rows.

For each distinct fetched_at timestamp in price_history, computes a full market
index snapshot and inserts it into market_index with computed_at = fetched_at.
Already-processed timestamps are skipped, so the script is safe to re-run.

Usage:
    python scripts/backfill_index.py
    python scripts/backfill_index.py --dry-run
"""

import argparse
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import db
from compute_index import compute_snapshot
from config.settings import DB_PATH


def _raw_conn():
    """Plain connection — no PARSE_DECLTYPES — so timestamps stay as raw strings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def run(dry_run: bool = False):
    db.init_db()

    conn = _raw_conn()
    try:
        # All distinct fetch timestamps as raw strings, oldest first
        all_ts = [
            r["fetched_at"]
            for r in conn.execute(
                "SELECT DISTINCT fetched_at FROM price_history ORDER BY fetched_at ASC"
            ).fetchall()
        ]

        # Timestamps already indexed (segment='all' = one per run)
        done_set = {
            r["computed_at"]
            for r in conn.execute(
                "SELECT DISTINCT computed_at FROM market_index WHERE segment = 'all'"
            ).fetchall()
        }
    finally:
        conn.close()

    print(f"Found {len(all_ts)} fetch run(s) in price_history")
    print(f"Already indexed: {len(done_set)}")

    # A stored raw_ts looks like '2026-03-15 18:33:27.523449+00:00'
    # market_index stores computed_at as 'YYYY-MM-DD HH:MM:SS' — compare on the prefix
    def to_index_ts(raw_ts: str) -> str:
        return raw_ts[:19]   # 'YYYY-MM-DD HH:MM:SS'

    to_process = [ts for ts in all_ts if to_index_ts(ts) not in done_set]

    if not to_process:
        print("Nothing to backfill — all timestamps already indexed.")
        return

    print(f"Backfilling {len(to_process)} run(s)…\n")

    total_segments = 0
    conn = _raw_conn()
    try:
        for raw_ts in to_process:
            index_ts = to_index_ts(raw_ts)

            price_rows = conn.execute(
                """SELECT c.rarity, c.ovr, c.display_position,
                          ph.best_sell_price, ph.best_buy_price
                   FROM price_history ph
                   JOIN cards c ON c.uuid = ph.uuid
                   WHERE ph.fetched_at = ?
                     AND ph.best_sell_price > 0""",
                (raw_ts,),
            ).fetchall()

            if not price_rows:
                print(f"  {index_ts}  — no usable rows, skipping")
                continue

            snapshot_rows = compute_snapshot([dict(r) for r in price_rows])
            seg_all = next((r for r in snapshot_rows if r["segment"] == "all"), {})

            if dry_run:
                print(
                    f"  {index_ts}  {len(price_rows):>5,} cards  "
                    f"{len(snapshot_rows):>3} segments  "
                    f"mean_sell={seg_all.get('mean_sell', 0):>10,.1f}"
                )
            else:
                db.insert_index_snapshot(snapshot_rows, computed_at=index_ts)
                print(
                    f"  {index_ts}  {len(price_rows):>5,} cards  "
                    f"{len(snapshot_rows):>3} segments stored  "
                    f"mean_sell={seg_all.get('mean_sell', 0):>10,.1f}"
                )

            total_segments += len(snapshot_rows)
    finally:
        conn.close()

    suffix = "(nothing saved)" if dry_run else "stored"
    print(f"\nBackfill complete — {total_segments:,} total segment rows {suffix}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill market_index from existing price_history data"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be stored without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
