#!/usr/bin/env python3
# scripts/scheduler.py
"""
Run fetch_listings on a repeating schedule using the `schedule` library.
Meant to run in the background (e.g., tmux, screen, or as a systemd service).

Default: snapshot all mlb_card listings every 30 minutes.

Usage:
    pip install schedule
    python scripts/scheduler.py
    python scripts/scheduler.py --interval 60          # every 60 minutes
    python scripts/scheduler.py --rarity diamond --interval 15
"""

import argparse
import logging
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

try:
    import schedule
except ImportError:
    print("Install schedule: pip install schedule")
    sys.exit(1)

from log_setup import setup_logging
from fetch_listings import run as fetch_run

logger = logging.getLogger(__name__)


def job(card_type: str, rarity: str | None, archive: bool):
    logger.info("⏰  Scheduled fetch starting…")
    try:
        fetch_run(card_type=card_type, rarity=rarity, archive=archive)
    except Exception as e:
        logger.error("Fetch failed: %s", e, exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="Schedule recurring market snapshots")
    parser.add_argument("--interval", type=int, default=30,
                        help="Minutes between snapshots (default: 30)")
    parser.add_argument("--type", default="mlb_card", dest="card_type")
    parser.add_argument("--rarity", default=None)
    parser.add_argument("--archive", action="store_true",
                        help="Save raw JSON each run")
    args = parser.parse_args()

    setup_logging("scheduler")
    logger.info("Scheduler starting: every %d minutes (type=%s rarity=%s)",
                args.interval, args.card_type, args.rarity or "all")

    # Run immediately on start, then on schedule
    job(args.card_type, args.rarity, args.archive)

    schedule.every(args.interval).minutes.do(
        job, card_type=args.card_type, rarity=args.rarity, archive=args.archive
    )

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
