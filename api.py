# api.py
"""
Thin wrapper around the MLB The Show 25 public API.
Handles retries, rate limiting, and response parsing.
"""

import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config.settings import (
    LISTINGS_ENDPOINT, ITEMS_ENDPOINT, LISTING_ENDPOINT, ITEM_ENDPOINT,
    HEADERS, REQUEST_DELAY, PAGE_SIZE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session with retry logic
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _build_session()


def _get(url: str, params: dict = None, timeout: int = 15) -> dict:
    """Make a GET request and return parsed JSON. Raises on non-200."""
    resp = _session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Listings (market prices) — paginated
# ---------------------------------------------------------------------------

def fetch_listings_page(
    page: int = 1,
    card_type: str = "mlb_card",
    rarity: str | None = None,
    sort: str = "rank",
    order: str = "desc",
    **extra,
) -> dict:
    """Fetch one page of listings. Returns raw API response dict."""
    params = {
        "type": card_type,
        "page": page,
        "sort": sort,
        "order": order,
    }
    if rarity:
        params["rarity"] = rarity
    params.update(extra)

    data = _get(LISTINGS_ENDPOINT, params=params)
    logger.debug("Listings page %d: got %d items (total_pages=%s)",
                 page, len(data.get("listings", [])), data.get("total_pages"))
    return data


def fetch_all_listings(
    card_type: str = "mlb_card",
    rarity: str | None = None,
    delay: float = REQUEST_DELAY,
    max_pages: int | None = None,
    progress_cb=None,
) -> list[dict]:
    """
    Paginate through all listings and return a flat list of listing dicts.
    Each listing dict contains:
        listing_name, best_sell_price, best_buy_price, item (nested card data)
    """
    all_listings = []
    page = 1

    first = fetch_listings_page(page=1, card_type=card_type, rarity=rarity)
    total_pages = first.get("total_pages", 1)
    all_listings.extend(first.get("listings", []))

    if max_pages:
        total_pages = min(total_pages, max_pages)

    logger.info("Fetching %d pages of %s listings (rarity=%s)…",
                total_pages, card_type, rarity or "all")

    for page in range(2, total_pages + 1):
        if progress_cb:
            progress_cb(page, total_pages)
        time.sleep(delay)
        data = fetch_listings_page(page=page, card_type=card_type, rarity=rarity)
        listings = data.get("listings", [])
        if not listings:
            break
        all_listings.extend(listings)

    logger.info("Fetched %d total listings", len(all_listings))
    return all_listings


# ---------------------------------------------------------------------------
# Items (card metadata) — paginated
# ---------------------------------------------------------------------------

def fetch_items_page(page: int = 1, card_type: str = "mlb_card") -> dict:
    params = {"type": card_type, "page": page}
    return _get(ITEMS_ENDPOINT, params=params)


def fetch_all_items(
    card_type: str = "mlb_card",
    delay: float = REQUEST_DELAY,
    max_pages: int | None = None,
) -> list[dict]:
    """Paginate through all items and return flat list of item dicts."""
    all_items = []
    first = fetch_items_page(page=1, card_type=card_type)
    total_pages = first.get("total_pages", 1)
    all_items.extend(first.get("items", []))

    if max_pages:
        total_pages = min(total_pages, max_pages)

    logger.info("Fetching %d pages of items (type=%s)…", total_pages, card_type)

    for page in range(2, total_pages + 1):
        time.sleep(delay)
        data = fetch_items_page(page=page, card_type=card_type)
        items = data.get("items", [])
        if not items:
            break
        all_items.extend(items)

    logger.info("Fetched %d total items", len(all_items))
    return all_items


# ---------------------------------------------------------------------------
# Single-card lookups
# ---------------------------------------------------------------------------

def fetch_listing(uuid: str) -> dict:
    """Fetch a single card's listing detail."""
    return _get(LISTING_ENDPOINT, params={"uuid": uuid})


def fetch_item(uuid: str) -> dict:
    """Fetch a single card's item detail."""
    return _get(ITEM_ENDPOINT, params={"uuid": uuid})
