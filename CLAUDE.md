# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MLB The Show market tracker that monitors the Diamond Dynasty community market, tracks buy/sell price spreads, and surfaces arbitrage opportunities ("stubs" = in-game currency).

## Running the Web UI

```bash
uvicorn server:app --reload --port 8000
# Then open http://localhost:8000
```

## Setup & Common Commands

```bash
# Activate virtualenv
source .venv/bin/activate

# Initial setup: populate card metadata, then snapshot prices
python scripts/fetch_items.py
python scripts/fetch_listings.py

# Analyze current spreads
python scripts/analyze_gaps.py --top 50 --rarity diamond
python scripts/analyze_gaps.py --min-sell 5000 --no-color

# Quick smoke tests (limit pages)
python scripts/fetch_items.py --max-pages 1
python scripts/fetch_listings.py --max-pages 5

# Background scheduled snapshots
python scripts/scheduler.py --interval 30 --rarity diamond

# Inspect DB state
python scripts/inspect_db.py
```

## Architecture

**Data flow**: `api.py` → `fetch_items.py` / `fetch_listings.py` → `db.py` (SQLite) → `analyze_gaps.py`

**`api.py`** — HTTP wrapper around `mlb26.theshow.com` public API. Handles pagination, rate limiting (0.3s delay), and retry logic (exponential backoff on 429/5xx). All API calls go through here.

**`db.py`** — SQLite layer with two tables:
- `cards` — Static card metadata (uuid PK, name, position, team, ovr, rarity, etc.)
- `price_history` — Timestamped price snapshots (best_sell_price, best_buy_price, spread, spread_pct)

Uses WAL mode and `get_conn()` context manager. Spread is stored (not computed at query time). Upsert pattern handles new/updated cards.

**`config/settings.py`** — All constants: API base URL, endpoints, page size, card types, rarities, rate limit delay, min spread threshold, DB path.

**Scripts** are standalone and can be run independently. `fetch_listings.py` upserts card metadata as a side effect (handles new cards appearing mid-season).

## Key Concepts

- **best_sell_price** = lowest ask (what you pay to buy a card now)
- **best_buy_price** = highest bid (what you receive selling now)
- **spread** = sell_price − buy_price; large spread = low liquidity = potential trading opportunity
- **spread_pct** = spread / sell_price × 100

## Known Issues

- `scripts/scheduler.py` imports `log_setup.setup_logging()` from a missing module — other scripts are unaffected
- FastAPI backend (`fastapi`, `uvicorn` in requirements.txt) is planned but not yet implemented
