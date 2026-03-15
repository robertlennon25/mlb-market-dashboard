# MLB The Show Market Tracker

Track Diamond Dynasty community market data, identify buy/sell price gaps, and surface arbitrage opportunities.

## Project Structure

```
mlb_show_market/
├── config/
│   └── settings.py         # API base URLs, constants, config
├── data/
│   ├── db/                 # SQLite database files
│   └── raw/                # Raw JSON snapshots (optional archiving)
├── scripts/
│   ├── fetch_listings.py   # Paginate + fetch all market listings
│   ├── fetch_items.py      # Populate/update the player card database
│   ├── analyze_gaps.py     # Find cards with large buy/sell spreads
│   └── scheduler.py        # Run fetches on a schedule (cron wrapper)
├── logs/                   # Rotating log files
├── db.py                   # Database models + helpers (SQLite via sqlite3)
├── api.py                  # Thin wrapper around theshow.com API
└── README.md
```

## APIs Used (mlb25.theshow.com)

| Endpoint | Purpose |
|----------|---------|
| `/apis/listings.json` | Paginated market listings with buy/sell prices |
| `/apis/items.json` | Card metadata (ovr, rarity, position, team) |
| `/apis/listing.json?uuid=` | Single card listing detail |

## Key Data Fields

From `/apis/listings.json`:
- `listing_name` — display name
- `best_sell_price` — lowest ask (you buy at this)
- `best_buy_price` — highest bid (you sell at this)
- `item.uuid` — unique card ID
- `item.ovr`, `item.rarity`, `item.team`, `item.display_position`

**Spread = best_sell_price - best_buy_price**
High spread = potential flip opportunity.

## Quickstart

```bash
pip install requests rich schedule
python scripts/fetch_items.py      # Build card DB (run once / on roster updates)
python scripts/fetch_listings.py   # Snapshot current market prices
python scripts/analyze_gaps.py     # Print top spread opportunities
```

## Run frontend
  uvicorn server:app --reload --port 8000

## Todos
- Add quicksell value
- Add profit with tax taken into account
- More market data
- macro market trends, external shocks (stubs discount, new cards released, gmae releases to non pre-orders)

