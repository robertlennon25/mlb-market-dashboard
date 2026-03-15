#!/usr/bin/env python3
# scripts/analyze_gaps.py
"""
Analyze stored price history to surface cards with large buy/sell spreads.
These are potential flip / arbitrage opportunities.

The Show charges a 10% tax on completed sales, so effective profit is:
    profit = best_buy_price - (best_sell_price * 0.10)
    …but you BUY at best_sell_price and SELL at best_buy_price if flipping.

Wait — clarifying the direction:
  best_sell_price = the price you pay to "Buy Now"  (lowest ask)
  best_buy_price  = the price you receive if "Sell Now" (highest bid)

So raw spread = best_sell_price - best_buy_price
  (you'd lose money if you buy then immediately sell — spread is the market maker's cut)

A large spread means:
  - The market is illiquid / inefficient for that card
  - Someone might buy at a lower price and list higher to capture part of the spread

Usage:
    python scripts/analyze_gaps.py
    python scripts/analyze_gaps.py --rarity diamond --top 20
    python scripts/analyze_gaps.py --min-sell 1000 --top 100 --no-color
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

# from log_setup import setup_logging
import db
from config.settings import quicksell_value, flip_profit, flip_profit_pct

# logger = logging.getLogger(__name__)

# Rarity display colors (ANSI)
RARITY_COLOR = {
    "Diamond": "\033[96m",   # cyan
    "Gold":    "\033[93m",   # yellow
    "Silver":  "\033[37m",   # white
    "Bronze":  "\033[33m",   # orange-ish
    "Common":  "\033[90m",   # grey
}
RESET = "\033[0m"
BOLD  = "\033[1m"
RED   = "\033[91m"
GREEN = "\033[92m"


def format_stubs(n: int) -> str:
    return f"{n:,}"


def print_table(rows: list[dict], use_color: bool = True):
    if not rows:
        print("No data found. Run fetch_listings.py first.")
        return

    col_widths = {
        "rank":       4,
        "name":      28,
        "pos":        4,
        "team":       5,
        "ovr":        4,
        "rarity":     8,
        "sell":      10,
        "buy":       10,
        "spread":    10,
        "spread%":    8,
        "qs":         8,
        "flip":      10,
        "flip%":      8,
    }

    header = (
        f"{'#':>{col_widths['rank']}}  "
        f"{'Name':<{col_widths['name']}}  "
        f"{'Pos':<{col_widths['pos']}}  "
        f"{'Team':<{col_widths['team']}}  "
        f"{'OVR':>{col_widths['ovr']}}  "
        f"{'Rarity':<{col_widths['rarity']}}  "
        f"{'Buy Now':>{col_widths['sell']}}  "
        f"{'Sell Now':>{col_widths['buy']}}  "
        f"{'Spread':>{col_widths['spread']}}  "
        f"{'Spread%':>{col_widths['spread%']}}  "
        f"{'QS Val':>{col_widths['qs']}}  "
        f"{'Flip Profit':>{col_widths['flip']}}  "
        f"{'Flip%':>{col_widths['flip%']}}"
    )

    sep = "─" * len(header)

    if use_color:
        print(f"\n{BOLD}{header}{RESET}")
    else:
        print(f"\n{header}")
    print(sep)

    for i, row in enumerate(rows, 1):
        rarity = row.get("rarity") or ""
        color = RARITY_COLOR.get(rarity, "") if use_color else ""

        spread_pct = row.get("spread_pct") or 0
        pct_color = RED if spread_pct > 50 else (GREEN if spread_pct > 20 else "")
        pct_color = pct_color if use_color else ""

        sell = row.get("best_sell_price") or 0
        buy  = row.get("best_buy_price") or 0
        qs   = quicksell_value(row.get("ovr"))
        fp   = flip_profit(sell, buy)
        fpp  = flip_profit_pct(fp, buy)

        flip_color = (GREEN if fp is not None and fp > 0 else RED) if use_color else ""
        fp_str  = format_stubs(fp) if fp is not None else "—"
        fpp_str = f"{fpp:.1f}%" if fpp is not None else "—"

        line = (
            f"{i:>{col_widths['rank']}}  "
            f"{color}{row.get('name','')[:col_widths['name']]:<{col_widths['name']}}{RESET if use_color else ''}  "
            f"{row.get('display_position',''):<{col_widths['pos']}}  "
            f"{row.get('team','')[:5]:<{col_widths['team']}}  "
            f"{row.get('ovr',0):>{col_widths['ovr']}}  "
            f"{rarity:<{col_widths['rarity']}}  "
            f"{format_stubs(sell):>{col_widths['sell']}}  "
            f"{format_stubs(buy):>{col_widths['buy']}}  "
            f"{pct_color}{format_stubs(row.get('spread',0)):>{col_widths['spread']}}  "
            f"{(row.get('spread_pct') or 0):.1f}%{RESET if use_color else ''}  "
            f"{format_stubs(qs):>{col_widths['qs']}}  "
            f"{flip_color}{fp_str:>{col_widths['flip']}}  "
            f"{fpp_str:>{col_widths['flip%']}}{RESET if use_color else ''}"
        )
        print(line)

    print(sep)
    print(f"\n  Showing {len(rows)} cards  |  "
          f"Buy Now = lowest ask  |  Sell Now = highest bid  |  "
          f"QS Val = quicksell to game  |  "
          f"Flip Profit = floor(Buy Now × 0.9) − Sell Now\n")


def run(top: int = 50, rarity: str | None = None, min_sell: int = 100, use_color: bool = True):
    # setup_logging("analyze_gaps")
    db.init_db()

    cards_total = db.card_count()
    snaps_total = db.snapshot_count()

    if snaps_total == 0:
        print("\n⚠️  No price data yet. Run: python scripts/fetch_listings.py\n")
        return

    print(f"\n{'═'*60}")
    print(f"  MLB The Show 25 — Market Gap Analysis")
    print(f"  {cards_total:,} cards tracked  |  {snaps_total:,} price snapshots")
    if rarity:
        print(f"  Filter: {rarity.title()} cards only")
    print(f"{'═'*60}")

    rows = db.get_top_spreads(limit=top, rarity=rarity, min_sell=min_sell)
    print_table(rows, use_color=use_color)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show cards with largest buy/sell spreads")
    parser.add_argument("--top", type=int, default=50, help="Number of results to show")
    parser.add_argument("--rarity", default=None,
                        choices=["Diamond", "Gold", "Silver", "Bronze", "Common"])
    parser.add_argument("--min-sell", type=int, default=100,
                        help="Minimum buy-now price to include")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    run(
        top=args.top,
        rarity=args.rarity,
        min_sell=args.min_sell,
        use_color=not args.no_color,
    )
