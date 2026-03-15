#!/usr/bin/env python3
# scripts/fetch_listings.py
"""
Snapshot current market buy/sell prices for all (or filtered) cards.
Stores each snapshot in price_history so we can track trends over time.

Also upserts any card metadata from the listing response in case
fetch_items.py hasn't been run yet (listings embed item data).

Usage:
    python scripts/fetch_listings.py                      # all mlb_card listings
    python scripts/fetch_listings.py --rarity diamond     # diamonds only
    python scripts/fetch_listings.py --max-pages 10       # smoke test
    python scripts/fetch_listings.py --archive            # also save raw JSON
"""

import argparse
import json

import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

# from log_setup import setup_logging
import api
import db
import compute_index
from config.settings import RAW_DIR

# logger = logging.getLogger(__name__)


def parse_listing(raw: dict) -> dict | None:
    """
    Extract the fields we care about from a raw listing dict.

    API shape:
    {
      "listing_name": "Mike Trout",
      "best_sell_price": 45000,
      "best_buy_price":  42000,
      "item": { "uuid": "...", "ovr": 99, "rarity": "Diamond", ... }
    }
    """
    item = raw.get("item", {})
    uuid = item.get("uuid")
    if not uuid:
        return None

    sell = raw.get("best_sell_price") or 0
    buy  = raw.get("best_buy_price")  or 0

    return {
        # Price data
        "uuid":            uuid,
        "listing_name":    raw.get("listing_name"),
        "best_sell_price": sell,
        "best_buy_price":  buy,
        # Card metadata (for upsert)
        "name":             item.get("name") or raw.get("listing_name"),
        "display_position": item.get("display_position"),
        "team":             item.get("team"),
        "ovr":              item.get("ovr"),
        "rarity":           item.get("rarity"),
        "series":           item.get("series"),
        "series_id":        item.get("series_id"),
        "is_hitter":        item.get("is_hitter"),
        "bat_hand":         item.get("bat_hand"),
        "throw_hand":       item.get("throw_hand"),
        "age":              item.get("age"),
        "img":              item.get("img"),
    }


def archive_raw(listings: list, rarity: str | None):
    """Optionally dump raw JSON snapshot to data/raw/."""
    os.makedirs(RAW_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{rarity}" if rarity else "_all"
    path = os.path.join(RAW_DIR, f"listings{suffix}_{ts}.json")
    with open(path, "w") as f:
        json.dump(listings, f)
    # logger.info("Archived raw JSON → %s", path)


def run(
    card_type: str = "mlb_card",
    rarity: str | None = None,
    max_pages: int | None = None,
    archive: bool = False,
):
    # setup_logging("fetch_listings")
    db.init_db()

    start = time.time()
    # logger.info("=== Listings snapshot START (type=%s rarity=%s) ===",
                # card_type, rarity or "all")

    # def progress(page, total):
        # logger.info("  fetching page %d / %d …", page, total)

    raw_listings = api.fetch_all_listings(
        card_type=card_type,
        rarity=rarity,
        max_pages=max_pages,
    )

    if archive:
        archive_raw(raw_listings, rarity)

    # Parse + split into card metadata and price rows
    parsed = [parse_listing(r) for r in raw_listings]
    parsed = [p for p in parsed if p]  # drop None

    # logger.info("Parsed %d valid listings", len(parsed))

    # Upsert card metadata (in case new cards appeared)
    db.bulk_upsert_cards(parsed)

    # Record price snapshots
    saved = db.bulk_insert_snapshots(parsed)

    # Update market index with this snapshot
    snapshot_rows = compute_index.compute_snapshot(parsed)
    if snapshot_rows:
        db.insert_index_snapshot(snapshot_rows)

    elapsed = time.time() - start
    # logger.info("=== Snapshot DONE: %d prices saved | %.1fs elapsed ===",
    #             saved, elapsed)
    # logger.info("DB totals: %d cards, %d price records",
    #             db.card_count(), db.snapshot_count())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snapshot MLB The Show market prices")
    parser.add_argument("--type", default="mlb_card",
                        choices=["mlb_card", "equipment", "sponsorship", "stadium", "unlockable"],
                        dest="card_type")
    parser.add_argument("--rarity", default=None,
                        choices=["diamond", "gold", "silver", "bronze", "common"])
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--archive", action="store_true",
                        help="Save raw JSON snapshot to data/raw/")
    args = parser.parse_args()

    run(
        card_type=args.card_type,
        rarity=args.rarity,
        max_pages=args.max_pages,
        archive=args.archive,
    )
