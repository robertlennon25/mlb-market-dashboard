#!/usr/bin/env python3
# scripts/compute_index.py
"""
Compute a market-index snapshot across all segments and store in market_index.

Segments created per run:
  all               — entire card market
  rarity:<Rarity>   — e.g. rarity:Diamond
  ovr:<N>           — e.g. ovr:99
  pos:<Position>    — e.g. pos:SP

Run manually or hook into your scheduler:
    python scripts/compute_index.py
    python scripts/compute_index.py --dry-run
"""

import argparse
import statistics
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


def compute_snapshot(price_rows: list[dict]) -> list[dict]:
    """
    Given a list of dicts that each have at minimum:
        rarity, ovr, display_position, best_sell_price, best_buy_price
    compute index stats for every segment and return snapshot rows
    ready for db.insert_index_snapshot().
    """
    segments: dict[str, list] = {}

    def add(key: str, row: dict):
        segments.setdefault(key, []).append(row)

    for row in price_rows:
        if not (row.get("best_sell_price") or 0) > 0:
            continue
        add("all", row)
        if row.get("rarity"):
            add(f"rarity:{row['rarity']}", row)
        if row.get("ovr"):
            add(f"ovr:{row['ovr']}", row)
        if row.get("display_position"):
            add(f"pos:{row['display_position']}", row)

    snapshot_rows = []
    for seg, seg_rows in segments.items():
        sells = sorted(r["best_sell_price"] for r in seg_rows if r.get("best_sell_price"))
        buys  = sorted(r["best_buy_price"]  for r in seg_rows if r.get("best_buy_price"))
        if not sells:
            continue
        snapshot_rows.append({
            "segment":    seg,
            "card_count": len(seg_rows),
            "mean_sell":   round(statistics.mean(sells), 1),
            "mean_buy":    round(statistics.mean(buys),  1) if buys else None,
            "median_sell": float(statistics.median(sells)),
            "median_buy":  float(statistics.median(buys)) if buys else None,
            "total_sell":  sum(sells),
            "total_buy":   sum(buys) if buys else None,
        })
    return snapshot_rows


def run(dry_run: bool = False):
    db.init_db()

    rows = db.get_latest_prices_with_metadata()
    if not rows:
        print("No price data found. Run fetch_listings.py first.")
        return

    snapshot_rows = compute_snapshot(rows)

    if dry_run:
        print(f"\n{'Segment':<30}  {'Cards':>6}  {'Mean Buy Now':>14}  {'Mean Sell Now':>14}")
        print("─" * 72)
        for r in sorted(snapshot_rows, key=lambda x: x["segment"]):
            print(
                f"  {r['segment']:<28}  {r['card_count']:>6,}  "
                f"{r['mean_sell']:>14,.1f}  "
                f"{(r['mean_buy'] or 0):>14,.1f}"
            )
        print(f"\n  {len(snapshot_rows)} segments computed (dry run — nothing saved)\n")
        return

    n = db.insert_index_snapshot(snapshot_rows)
    print(f"Stored {n} index snapshots across {len(snapshot_rows)} segments.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute market-index snapshot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without saving to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
