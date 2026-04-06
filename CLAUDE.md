# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MLB The Show market tracker that monitors the Diamond Dynasty community market, tracks buy/sell price spreads, surfaces arbitrage/flip opportunities, and shows market-wide price trends. "Stubs" = in-game currency.

## Running Locally

```bash
source .venv/bin/activate
uvicorn server:app --reload --port 8000
# Open http://localhost:8000
```

## Common Commands

```bash
# Initial setup: populate card metadata, then snapshot prices
python scripts/fetch_items.py
python scripts/fetch_listings.py

# Analyze current spreads (CLI output)
python scripts/analyze_gaps.py --top 50 --rarity diamond
python scripts/analyze_gaps.py --min-sell 5000 --no-color

# Compute market index snapshot (run after fetch_listings)
python scripts/compute_index.py
python scripts/compute_index.py --dry-run   # preview without saving

# Quick smoke tests (limit pages to avoid full API crawl)
python scripts/fetch_items.py --max-pages 1
python scripts/fetch_listings.py --max-pages 5

# Inspect DB state
python scripts/inspect_db.py
```

---

## Data Pipeline

```
mlb26.theshow.com public API
        │
        ▼
    api.py                  ← all HTTP calls go here (rate limiting, retries)
        │
        ├── fetch_items.py  ← card metadata only (run once on first boot)
        └── fetch_listings.py ← prices + metadata upsert (runs every 15 min)
                │
                ▼
            db.py / market.db (SQLite on Railway volume)
                │
                ├── compute_index.py  ← aggregates prices into market_index table
                └── server.py         ← FastAPI serves everything to the frontend
                        │
                        ▼
                static/index.html     ← single-page app (vanilla JS + Chart.js)
```

**Key timing note:** `fetch_listings.py` + `compute_index.py` run every **15 minutes** via the server's background scheduler (changed from 5 min on 2026-03-22 to reduce volume usage). `fetch_items.py` runs only once on first boot when the DB is empty.

---

## Hosting & Storage

**Platform:** Railway (`railway.toml`, `Dockerfile`)
- Container runs `uvicorn server:app --host 0.0.0.0 --port $PORT`
- Health check: `GET /api/filters`
- Restart policy: on failure, max 3 retries

**Database:** SQLite file at `/data/market.db` on a Railway persistent volume
- Path controlled by `DATABASE_PATH` env var (defaults to `data/db/market.db` locally)
- `db.get_conn()` auto-creates the directory if missing
- WAL mode enabled on every connection

**Static frontend:** `static/index.html` — served by FastAPI's `StaticFiles` mount. This mount **must be last** in `server.py` or it shadows API routes.

**Local fallback paths:**
- DB: `data/db/market.db`
- Raw JSON archive: `data/raw/` (only written when `--archive` flag passed to `fetch_listings.py`)

---

## Database Schema

Three tables in `db.py`:

### `cards`
Static card metadata. UUID is the primary key from the MLB The Show API.
Key columns: `uuid`, `name`, `display_position`, `team`, `ovr`, `rarity`, `series`, `is_hitter`, `bat_hand`, `throw_hand`, `img`

### `price_history`
One row per card per fetch cycle (~15-min snapshots). Grows continuously.
Key columns: `uuid`, `fetched_at` (UTC), `best_sell_price`, `best_buy_price`, `spread`, `spread_pct`
- `spread` and `spread_pct` are stored (not computed at query time)
- All timestamp queries use `ORDER BY fetched_at DESC` + `MAX(fetched_at)` CTEs to get latest prices

### `market_index`
Aggregate stats per segment per fetch cycle. Segments: `all`, `rarity:Diamond`, `ovr:99`, `pos:SP`, etc.
Key columns: `segment`, `computed_at` (UTC), `card_count`, `mean_sell`, `mean_buy`, `median_sell`, `median_buy`

**Indexes:** `idx_ph_uuid_time (uuid, fetched_at DESC)` is the most-used index — all "latest price" queries rely on it.

---

## Key Business Logic (`config/settings.py`)

All pricing constants and pure functions live here:

- `quicksell_value(ovr)` — fixed in-game stub value by overall rating (lookup table)
- `flip_profit(sell, buy)` — `floor(sell × 0.9) − buy` — profit from buying at bid, selling at ask after **10% marketplace tax**
- `flip_profit_pct(profit, buy)` — flip profit as % of buy-order cost

Every API response row is passed through `_enrich()` in `server.py`, which adds `quicksell_value`, `flip_profit`, and `flip_profit_pct` to the dict.

**Pricing terms:**
- `best_sell_price` = lowest ask (cost to buy a card instantly)
- `best_buy_price` = highest bid (amount received selling instantly)
- `spread` = sell − buy (large = illiquid = possible trading opportunity)

---

## API Routes (`server.py`)

| Endpoint | Description |
|---|---|
| `GET /api/status` | Card count, snapshot count, background fetch state |
| `GET /api/dashboard` | Four ranked lists: top flip profit, top flip %, movers up/down (5-min TTL cache) |
| `GET /api/search?q=` | Card search by name, latest prices, top 30 |
| `GET /api/card/{uuid}` | Full card metadata + latest price snapshot |
| `GET /api/card/{uuid}/history?timerange=` | Price history: `24h`, `7d`, or `all` (downsampled to 12h buckets) |
| `GET /api/market` | Full market browser with filtering/sorting (rarity, team, series, hand, price range) |
| `GET /api/filters` | Distinct values for all filter dropdowns |
| `GET /api/index/segments` | All market index segments with 1h and 24h deltas |
| `GET /api/index/history?segment=&hours=` | Time-series for one segment |
| `GET /admin/db-info` | DB path + row counts (debug) |
| `GET /admin/download-db` | Download full SQLite file (WAL checkpointed first) |

**Dashboard cache:** results cached for 300 seconds in `_dashboard_cache`. Invalidated by the background scheduler after each fetch. Call `_dashboard_cache["expires"] = 0.0` to force refresh.

---

## Frontend (`static/index.html`)

Single HTML file, vanilla JS, Chart.js for charts. Four pages toggled by nav buttons:

| Page | JS entry point | API calls |
|---|---|---|
| Dashboard | `loadDashboard()` | `/api/dashboard` |
| Search | `fetchSearch(q)`, `loadCard(uuid)` | `/api/search`, `/api/card/{uuid}`, `/api/card/{uuid}/history` |
| Market Browser | `loadMarket()`, `loadFilters()` | `/api/market`, `/api/filters` |
| Trends | `loadTrends()`, `selectTrendsSegment()` | `/api/index/segments`, `/api/index/history` |

**Timestamp rendering:** all timestamps from the API are UTC strings like `"2026-03-22 18:37:00"`. Always parse as `new Date(ts.replace(' ', 'T') + 'Z')` to get correct local time display. The `fmtTime()` helper already does this — use it everywhere.

---

## Server Startup Behavior (`server.py` `lifespan`)

1. `db.init_db()` — creates tables if missing
2. If `card_count() == 0` → spawns background thread running `fetch_items.py` then `fetch_listings.py` then `compute_index.py`
3. Always spawns background scheduler thread: every 15 min runs `fetch_listings.py` + `compute_index.py`

Server returns 200 on health check immediately, even while initial data loads in the background. Frontend polls `/api/status` to show loading state.

---

## Volume Management

`price_history` grows by ~1 row per card per 15-min fetch indefinitely. To thin history if volume fills up again, see the commented-out purge endpoints in `server.py` (search for `"Purge endpoints"`).

**Purge strategy (as of 2026-04-05):** Delete all rows older than 7 days, except rows whose UTC time falls within ±7 min of **12:00 UTC (8am EDT)** or **00:00 UTC (8pm EDT)**. Those landmark rows are kept indefinitely for all-time price charts. Last 7 days are kept at full 15-min resolution. Last purge: **2026-04-05**.

---

## Known Issues / Gotchas

- `scripts/scheduler.py` imports a missing `log_setup` module — use the server's built-in scheduler instead, don't run this script
- `railway shell` spawns an ephemeral container **without** the Railway volume mounted — to run commands against the live DB, add a temporary admin endpoint to the server instead
- API rate limit: 0.3s delay between paginated requests (`REQUEST_DELAY` in `config/settings.py`). Don't remove this.
