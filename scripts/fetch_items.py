#!/usr/bin/env python3
# scripts/fetch_items.py
"""
Populate / refresh the cards table with metadata from the Items API.

Run this:
  - Once on first setup
  - After each roster update (new cards are added mid-season)

Usage:
    python scripts/fetch_items.py
    python scripts/fetch_items.py --max-pages 5      # quick smoke test
    python scripts/fetch_items.py --type equipment   # non-player cards
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import argparse


import api
import db

# logger = logging.getLogger(__name__)


def parse_item(raw: dict) -> dict:
    """Normalise a raw API item into our DB schema."""
    return {
        "uuid":             raw.get("uuid"),
        "name":             raw.get("name"),
        "display_position": raw.get("display_position"),
        "team":             raw.get("team"),
        "ovr":              raw.get("ovr"),
        "rarity":           raw.get("rarity"),
        "series":           raw.get("series"),
        "series_id":        raw.get("series_id"),
        "is_hitter":        raw.get("is_hitter"),
        "bat_hand":         raw.get("bat_hand"),
        "throw_hand":       raw.get("throw_hand"),
        "age":              raw.get("age"),
        "img":              raw.get("img"),
    }


def run(card_type: str = "mlb_card", max_pages: int | None = None):
    # setup_logging("fetch_items")
    db.init_db()

    before = db.card_count()
    # logger.info("Starting item fetch (type=%s, max_pages=%s). DB has %d cards.",
    #             card_type, max_pages or "all", before)

    raw_items = api.fetch_all_items(card_type=card_type, max_pages=max_pages)

    cards = [parse_item(r) for r in raw_items if r.get("uuid")]
    # logger.info("Parsed %d cards, upserting into DB…", len(cards))

    db.bulk_upsert_cards(cards)

    after = db.card_count()
    # logger.info("Done. Cards: %d → %d (+%d)", before, after, after - before)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch MLB The Show card metadata")
    parser.add_argument("--type", default="mlb_card",
                        choices=["mlb_card", "equipment", "sponsorship", "stadium", "unlockable"],
                        dest="card_type")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Limit pages fetched (for testing)")
    args = parser.parse_args()

    run(card_type=args.card_type, max_pages=args.max_pages)
