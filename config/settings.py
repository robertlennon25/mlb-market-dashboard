# config/settings.py

BASE_URL = "https://mlb26.theshow.com"

LISTINGS_ENDPOINT = f"{BASE_URL}/apis/listings.json"
ITEMS_ENDPOINT    = f"{BASE_URL}/apis/items.json"
LISTING_ENDPOINT  = f"{BASE_URL}/apis/listing.json"   # ?uuid=<uuid>
ITEM_ENDPOINT     = f"{BASE_URL}/apis/item.json"       # ?uuid=<uuid>

# How many results per page (API max is 25)
PAGE_SIZE = 25

# Card types
CARD_TYPES = ["mlb_card", "equipment", "sponsorship", "stadium", "unlockable"]

# Rarities (descending value)
RARITIES = ["diamond", "gold", "silver", "bronze", "common"]

# Request headers — mimic a browser to avoid 403s
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Seconds to wait between paginated requests (be a good citizen)
REQUEST_DELAY = 0.3

# Minimum spread (stubs) to flag as interesting
MIN_SPREAD_THRESHOLD = 500

# Database path
# Reads DATABASE_PATH env var if set (Railway volume: /data/market.db).
# Falls back to data/db/market.db next to the project root.
# db.get_conn() calls os.makedirs so the directory is created automatically.
import os
_default_db = os.path.join(os.path.dirname(__file__), "..", "data", "db", "market.db")
DB_PATH = os.environ.get("DATABASE_PATH", os.path.normpath(_default_db))

# Raw JSON archive dir (set to None to disable archiving)
_default_raw = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
RAW_DIR = os.environ.get("RAW_DIR", os.path.normpath(_default_raw))

# ---------------------------------------------------------------------------
# Quicksell values by overall rating (fixed in-game stub values, MLB TS 25)
# ---------------------------------------------------------------------------
QUICKSELL_BY_OVR: dict[int, int] = {
    99: 5_000,
    98: 4_500,
    97: 4_000,
    96: 3_500,
    95: 3_000,
    94: 2_500,
    93: 2_000,
    92: 1_750,
    91: 1_500,
    90: 1_250,
    89: 1_000,
    88:   875,
    87:   750,
    86:   625,
    85:   500,
    84:   400,
    83:   350,
    82:   300,
    81:   250,
    80:   200,
    79:   125,
    78:   100,
    77:    75,
    76:    65,
    75:    50,
    74:    40,
    73:    35,
    72:    30,
    71:    25,
    70:    20,
}
QUICKSELL_DEFAULT = 5  # anything below 70 OVR


def quicksell_value(ovr: int | None) -> int:
    """Return the fixed in-game quicksell stub value for a given overall."""
    if ovr is None:
        return QUICKSELL_DEFAULT
    return QUICKSELL_BY_OVR.get(ovr, QUICKSELL_DEFAULT)


def flip_profit(best_sell_price: int | None, best_buy_price: int | None) -> int | None:
    """
    Profit from a bid-flip:
      - Buy at best_buy_price (place a buy order, wait for fill)
      - List at best_sell_price; after 10% tax receive floor(best_sell_price * 0.9)
      - Flip profit = floor(best_sell_price * 0.9) - best_buy_price
    """
    if not best_sell_price or not best_buy_price:
        return None
    return int(best_sell_price * 0.9) - best_buy_price


def flip_profit_pct(profit: int | None, best_buy_price: int | None) -> float | None:
    """Flip profit as a % of the buy-order cost."""
    if profit is None or not best_buy_price:
        return None
    return round(profit / best_buy_price * 100, 1)
