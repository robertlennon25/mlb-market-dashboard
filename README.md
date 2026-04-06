# MLB The Show Market Tracker

A live market tracker for MLB The Show 26's Diamond Dynasty community market. Monitors buy/sell prices across all cards, surfaces flip opportunities, and tracks market-wide price trends over time.

**Stubs** = the in-game currency used in Diamond Dynasty.

---

## What It Does

- **Polls the market every 15 minutes** via the public `mlb26.theshow.com` API
- **Tracks buy/sell prices** for every card and stores a timestamped history
- **Surfaces flip opportunities** — cards where buying at the bid and selling at the ask yields profit after the 10% marketplace tax
- **Market browser** — filter and sort all cards by rarity, position, team, price range, and more
- **Price trends** — market-wide index charts by segment (all cards, by rarity, by OVR, by position)
- **Card detail** — per-card price history chart with 24h / 7d / all-time views

---

## Current State (as of 2026-04-05)

| Component | Status |
|---|---|
| Market data polling | Live on Railway, every 15 min |
| Price history | ~1M rows post-purge (7 days full resolution + twice-daily landmarks going back to 3/15) |
| Dashboard loading | Pre-computed after every fetch, served instantly from memory |
| Web UI | Deployed and serving at Railway URL |
| DB | SQLite on Railway persistent volume |

---

## Running Locally

```bash
source .venv/bin/activate
uvicorn server:app --reload --port 8000
# Open http://localhost:8000
```

On first boot with an empty DB, the server automatically runs `fetch_items.py` then `fetch_listings.py` in the background. The frontend polls `/api/status` and shows a loading state until data is ready.

---

## Project Structure

```
mlb-market/
├── config/
│   └── settings.py          # API endpoints, pricing functions, constants
├── scripts/
│   ├── fetch_items.py        # Populate card metadata (run once on first boot)
│   ├── fetch_listings.py     # Snapshot market prices (runs every 15 min)
│   ├── compute_index.py      # Aggregate prices into market_index table
│   ├── analyze_gaps.py       # CLI: print top spread opportunities
│   ├── inspect_db.py         # CLI: quick DB row count check
│   ├── backfill_index.py     # One-time: build market_index from existing history
│   └── purge_history.py      # Standalone purge script (prefer admin endpoints instead)
├── static/
│   └── index.html            # Single-page frontend (vanilla JS + Chart.js)
├── api.py                    # HTTP wrapper for mlb26.theshow.com (rate limiting, retries)
├── db.py                     # SQLite schema, connection management, query helpers
├── server.py                 # FastAPI backend + background scheduler
├── Dockerfile                # Container config for Railway
├── railway.toml              # Railway deployment config
└── requirements.txt
```

---

## Key Commands

```bash
# Populate card metadata (first time setup or after roster updates)
python scripts/fetch_items.py

# Snapshot current market prices
python scripts/fetch_listings.py

# Analyze top spread/flip opportunities in the terminal
python scripts/analyze_gaps.py --top 50 --rarity diamond

# Smoke test (limits API pages)
python scripts/fetch_items.py --max-pages 1
python scripts/fetch_listings.py --max-pages 5

# Check DB row counts
python scripts/inspect_db.py
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/status` | Card count, snapshot count, fetch state |
| `GET /api/dashboard` | Top flip profit, top flip %, movers up/down |
| `GET /api/search?q=` | Card search by name (top 30, with prices) |
| `GET /api/card/{uuid}` | Full card metadata + latest price |
| `GET /api/card/{uuid}/history?timerange=` | Price history: `24h`, `7d`, `all` |
| `GET /api/market` | Full market browser with filters and sorting |
| `GET /api/filters` | Distinct values for filter dropdowns |
| `GET /api/index/segments` | Market index segments with 1h/24h deltas |
| `GET /api/index/history?segment=&hours=` | Time-series for one segment |
| `GET /admin/db-info` | DB path + row counts |
| `GET /admin/download-db` | Download full SQLite file |

---

## Pricing Logic

- **best_sell_price** — lowest ask (what you pay to buy a card instantly)
- **best_buy_price** — highest bid (what you receive selling a card instantly)
- **spread** — sell − buy (large spread = illiquid = potential flip)
- **flip_profit** — `floor(sell × 0.9) − buy` (profit after 10% marketplace tax)

All enrichment logic lives in `config/settings.py`.

---

## Deployment

Hosted on **Railway** with a persistent volume for the SQLite DB.

- Build: Docker (`Dockerfile`)
- Health check: `GET /api/filters`
- DB path: `/data/market.db` on the volume (set via `DATABASE_PATH` env var)
- Restart policy: on failure, max 3 retries

See `CLAUDE.md` for full operational details including the purge process.
