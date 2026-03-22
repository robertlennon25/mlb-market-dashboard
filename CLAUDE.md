# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MLB The Show market tracker that monitors the Diamond Dynasty community market, tracks buy/sell price spreads, and surfaces arbitrage opportunities ("stubs" = in-game currency).

## Running the Web UI

```bash
source .venv/bin/activate
uvicorn server:app --reload --port 8000
# Then open http://localhost:8000
```

## Common Commands

```bash
# Initial setup: populate card metadata, then snapshot prices
python scripts/fetch_items.py
python scripts/fetch_listings.py

# Analyze current spreads
python scripts/analyze_gaps.py --top 50 --rarity diamond
python scripts/analyze_gaps.py --min-sell 5000 --no-color

# Compute market index snapshot (run after fetch_listings)
python scripts/compute_index.py
python scripts/compute_index.py --dry-run   # preview without saving

# Quick smoke tests (limit pages)
python scripts/fetch_items.py --max-pages 1
python scripts/fetch_listings.py --max-pages 5

# Inspect DB state
python scripts/inspect_db.py
```

## Architecture

**Data flow**: `api.py` → `fetch_items.py` / `fetch_listings.py` → `db.py` (SQLite) → `analyze_gaps.py` / `compute_index.py` → `server.py` (FastAPI)

**`api.py`** — HTTP wrapper around `mlb26.theshow.com` public API. Handles pagination, rate limiting (0.3s delay), and retry logic (exponential backoff on 429/5xx). All API calls go through here.

**`db.py`** — SQLite layer with three tables:
- `cards` — Static card metadata (uuid PK, name, position, team, ovr, rarity, series, etc.)
- `price_history` — Timestamped price snapshots (best_sell_price, best_buy_price, spread, spread_pct)
- `market_index` — Aggregate index snapshots per segment (all, rarity:Diamond, ovr:99, pos:SP, etc.)

Uses WAL mode and `get_conn()` context manager. Spread is stored (not computed at query time). Upsert pattern handles new/updated cards.

**`config/settings.py`** — All constants plus three pure functions: `quicksell_value(ovr)`, `flip_profit(sell, buy)`, and `flip_profit_pct(profit, buy)`. `flip_profit` accounts for the 10% marketplace tax: `floor(sell * 0.9) - buy`.

**`scripts/compute_index.py`** — Reads latest prices from DB, computes mean/median/total sell and buy prices per segment, inserts into `market_index`. Run after each `fetch_listings.py`.

**`server.py`** — FastAPI app. On startup (`lifespan`): initialises DB, auto-fetches on empty DB (background thread), and launches a background scheduler (every 5 minutes: `fetch_listings.py` + `compute_index.py`). Dashboard results are cached for 5 minutes. API routes must be registered before the static-file mount or they'll be shadowed.

**Scripts** are standalone and can be run independently. `fetch_listings.py` upserts card metadata as a side effect (handles new cards appearing mid-season).

## Key Concepts

- **best_sell_price** = lowest ask (what you pay to buy a card now)
- **best_buy_price** = highest bid (what you receive selling now)
- **spread** = sell_price − buy_price; large spread = low liquidity = potential trading opportunity
- **spread_pct** = spread / sell_price × 100
- **flip_profit** = floor(sell × 0.9) − buy (bid-flip profit after 10% tax)
- **quicksell_value** = fixed in-game stub value by OVR (lookup table in `config/settings.py`)

## Deployment

Deployed on Railway via `Dockerfile`. Key env vars:
- `DATABASE_PATH` — override DB location (Railway persistent volume uses `/data/market.db`; defaults to `data/db/market.db` locally)
- `RAW_DIR` — directory for raw JSON archive (default: `data/raw`)

Health check hits `/api/filters`. The server intentionally starts up immediately (health check passes) even while the initial data fetch runs in the background.

## Known Issues

- `scripts/scheduler.py` imports `log_setup.setup_logging()` from a missing module — use the server's built-in scheduler instead
