"""
FastAPI backend for MLB Market Tracker.

Run with:
    uvicorn server:app --reload --port 8000
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from typing import Optional

import threading
import subprocess
import logging
import time

try:
    import schedule as _schedule
    _HAS_SCHEDULE = True
except ImportError:
    _HAS_SCHEDULE = False

import db as _db
from db import get_conn
from config.settings import quicksell_value, flip_profit, flip_profit_pct

# Track background fetch state so /api/status can report progress
_fetch_state = {"status": "idle", "message": ""}


_logger = logging.getLogger("server")


def _scheduler_loop():
    """Background thread: re-fetch listings + recompute index every 15 minutes."""
    if not _HAS_SCHEDULE:
        _logger.warning("'schedule' package not installed — recurring fetches disabled")
        return

    def _job():
        _logger.info("Scheduled fetch starting…")
        try:
            subprocess.run([sys.executable, "scripts/fetch_listings.py"], check=True)
            subprocess.run([sys.executable, "scripts/compute_index.py"], check=True)
            _logger.info("Scheduled fetch complete.")
        except Exception as e:
            _logger.error("Scheduled fetch failed: %s", e, exc_info=True)

    _schedule.every(5).minutes.do(_job)
    while True:
        _schedule.run_pending()
        time.sleep(30)


def _background_fetch():
    """Runs fetch_items then fetch_listings in a background thread on first boot."""
    global _fetch_state
    try:
        _fetch_state = {"status": "running", "message": "Fetching card metadata…"}
        subprocess.run([sys.executable, "scripts/fetch_items.py"], check=True)

        _fetch_state = {"status": "running", "message": "Fetching market prices…"}
        subprocess.run([sys.executable, "scripts/fetch_listings.py"], check=True)

        # Build the initial market index from the fresh data
        subprocess.run([sys.executable, "scripts/compute_index.py"], check=True)

        _fetch_state = {"status": "done", "message": "Initial data load complete."}
    except Exception as e:
        _fetch_state = {"status": "error", "message": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _db.init_db()
    # On first deploy the DB will be empty — kick off a background fetch so the
    # server starts immediately (health check passes) while data loads in parallel.
    if _db.card_count() == 0:
        _fetch_state["status"]  = "pending"
        _fetch_state["message"] = "Empty database detected — starting initial data fetch…"
        threading.Thread(target=_background_fetch, daemon=True).start()
    # Always start the recurring 15-minute scheduler regardless of DB state
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    yield

app = FastAPI(title="MLB Market Tracker", lifespan=lifespan)

# Segment metadata helpers
_RARITY_ORDER = {"Diamond": 0, "Gold": 1, "Silver": 2, "Bronze": 3, "Common": 4}
_POS_ORDER    = {p: i for i, p in enumerate(
    ["C", "1B", "2B", "SS", "3B", "LF", "CF", "RF", "OF", "DH", "SP", "RP", "CP"]
)}


def _enrich_segment(row: dict) -> dict:
    seg = row["segment"]
    if seg == "all":
        row["type"] = "overall";  row["label"] = "All Cards";  row["sort_key"] = 0
    elif seg.startswith("rarity:"):
        val = seg[7:]
        row["type"] = "rarity";   row["label"] = val
        row["sort_key"] = _RARITY_ORDER.get(val, 99)
    elif seg.startswith("ovr:"):
        val = int(seg[4:])
        row["type"] = "ovr";      row["label"] = f"OVR {val}"
        row["sort_key"] = 100 - val     # 99 OVR → sort_key 1
    elif seg.startswith("pos:"):
        val = seg[4:]
        row["type"] = "position"; row["label"] = val
        row["sort_key"] = _POS_ORDER.get(val, 99)
    else:
        row["type"] = "other";    row["label"] = seg;  row["sort_key"] = 99
    return row


def _enrich(row: dict) -> dict:
    """Add quicksell_value, flip_profit, flip_profit_pct to a row dict."""
    qs = quicksell_value(row.get("ovr"))
    sell = row.get("best_sell_price")
    buy  = row.get("best_buy_price")
    fp   = flip_profit(sell, buy)
    row["quicksell_value"]  = qs
    row["flip_profit"]      = fp
    row["flip_profit_pct"]  = flip_profit_pct(fp, buy)
    return row


# ---------------------------------------------------------------------------
# API routes  (must be defined before the static-file catch-all mount)
# ---------------------------------------------------------------------------


@app.get("/api/status")
def status():
    """Health + data readiness check."""
    return {
        "cards":     _db.card_count(),
        "snapshots": _db.snapshot_count(),
        "fetch":     _fetch_state,
    }


@app.get("/api/search")
def search_cards(q: str = ""):
    """Search cards by name. Returns up to 30 matches with latest prices."""
    if len(q) < 2:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT uuid, best_sell_price, best_buy_price, spread, spread_pct,
                       ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at DESC) AS rn
                FROM price_history
            )
            SELECT c.uuid, c.name, c.display_position, c.team, c.ovr, c.rarity, c.img,
                   l.best_sell_price, l.best_buy_price, l.spread, l.spread_pct
            FROM cards c
            LEFT JOIN latest l ON l.uuid = c.uuid AND l.rn = 1
            WHERE c.name LIKE ?
            ORDER BY c.ovr DESC
            LIMIT 30
            """,
            (f"%{q}%",),
        ).fetchall()
    return [_enrich(dict(r)) for r in rows]


@app.get("/api/card/{uuid}")
def get_card(uuid: str):
    """Full card metadata plus latest price snapshot."""
    with get_conn() as conn:
        card = conn.execute(
            "SELECT * FROM cards WHERE uuid = ?", (uuid,)
        ).fetchone()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        latest = conn.execute(
            """
            SELECT best_sell_price, best_buy_price, spread, spread_pct, fetched_at
            FROM price_history WHERE uuid = ? ORDER BY fetched_at DESC LIMIT 1
            """,
            (uuid,),
        ).fetchone()
    result = dict(card)
    if latest:
        result.update(dict(latest))
    return _enrich(result)


@app.get("/api/card/{uuid}/history")
def get_card_history(uuid: str, limit: int = Query(500, le=2000)):
    """Price history for a card, oldest first (for charting)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT fetched_at, best_sell_price, best_buy_price, spread, spread_pct
            FROM price_history WHERE uuid = ?
            ORDER BY fetched_at ASC
            LIMIT ?
            """,
            (uuid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/market")
def get_market(
    q: Optional[str] = None,
    min_sell: Optional[int] = None,
    max_sell: Optional[int] = None,
    min_buy: Optional[int] = None,
    max_buy: Optional[int] = None,
    sort: str = "spread",
    order: str = "desc",
    rarity: Optional[str] = None,
    team: Optional[str] = None,
    series: Optional[str] = None,
    throw_hand: Optional[str] = None,
    bat_hand: Optional[str] = None,
    is_hitter: Optional[int] = None,
    limit: int = Query(100, le=500),
):
    """Market browser with full filtering and sorting."""
    filters = ["l.rn = 1"]
    params: list = []

    if q:
        filters.append("c.name LIKE ?")
        params.append(f"%{q}%")
    if min_sell is not None:
        filters.append("l.best_sell_price >= ?")
        params.append(min_sell)
    if max_sell is not None:
        filters.append("l.best_sell_price <= ?")
        params.append(max_sell)
    if min_buy is not None:
        filters.append("l.best_buy_price >= ?")
        params.append(min_buy)
    if max_buy is not None:
        filters.append("l.best_buy_price <= ?")
        params.append(max_buy)
    if rarity:
        filters.append("c.rarity = ?")
        params.append(rarity)
    if team:
        filters.append("c.team = ?")
        params.append(team)
    if series:
        filters.append("c.series = ?")
        params.append(series)
    if throw_hand:
        filters.append("c.throw_hand = ?")
        params.append(throw_hand)
    if bat_hand:
        filters.append("c.bat_hand = ?")
        params.append(bat_hand)
    if is_hitter is not None:
        filters.append("c.is_hitter = ?")
        params.append(is_hitter)

    sort_map = {
        "spread":     "l.spread",
        "spread_pct": "l.spread_pct",
        "ovr":        "c.ovr",
        "sell":       "l.best_sell_price",
        "buy":        "l.best_buy_price",
        "name":       "c.name",
    }
    sort_col  = sort_map.get(sort, "l.spread")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    params.append(limit)

    sql = f"""
        WITH latest AS (
            SELECT uuid, best_sell_price, best_buy_price, spread, spread_pct, fetched_at,
                   ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at DESC) AS rn
            FROM price_history
        )
        SELECT c.uuid, c.name, c.display_position, c.team, c.ovr, c.rarity, c.series,
               c.is_hitter, c.bat_hand, c.throw_hand, c.age, c.img,
               l.best_sell_price, l.best_buy_price, l.spread, l.spread_pct, l.fetched_at
        FROM latest l
        JOIN cards c ON c.uuid = l.uuid
        WHERE {" AND ".join(filters)}
        ORDER BY {sort_col} {order_dir}
        LIMIT ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_enrich(dict(r)) for r in rows]


@app.get("/api/filters")
def get_filters():
    """Distinct values for all filter dropdowns."""
    with get_conn() as conn:
        def distinct(col, table="cards"):
            return [
                r[0]
                for r in conn.execute(
                    f"SELECT DISTINCT {col} FROM {table} "
                    f"WHERE {col} IS NOT NULL ORDER BY {col}"
                ).fetchall()
            ]
        return {
            "teams":     distinct("team"),
            "series":    distinct("series"),
            "rarities":  distinct("rarity"),
            "positions": distinct("display_position"),
        }


# ---------------------------------------------------------------------------
# Dashboard endpoint
# ---------------------------------------------------------------------------

_FLIP_CTE = """
    WITH latest AS (
        SELECT uuid, best_sell_price, best_buy_price,
               ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at DESC) rn
        FROM price_history WHERE best_sell_price > 0
    )
    SELECT c.uuid, c.name, c.display_position, c.team, c.ovr, c.rarity, c.img,
           l.best_sell_price, l.best_buy_price,
           (l.best_sell_price * 9 / 10 - l.best_buy_price)           AS flip_profit,
           ROUND((l.best_sell_price * 9 / 10 - l.best_buy_price)
                 * 100.0 / l.best_buy_price, 1)                      AS flip_profit_pct
    FROM latest l
    JOIN cards c ON c.uuid = l.uuid
    WHERE l.rn = 1
      AND l.best_buy_price > 0
      AND (l.best_sell_price * 9 / 10 - l.best_buy_price) > 0
"""

_MOVERS_CTE = """
    WITH latest AS (
        SELECT uuid, best_sell_price, best_buy_price,
               ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at DESC) rn
        FROM price_history WHERE best_sell_price > 0
    ),
    ref AS (
        SELECT uuid, best_sell_price,
               ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at ASC) rn
        FROM price_history WHERE best_sell_price > 0
    )
    SELECT c.uuid, c.name, c.display_position, c.team, c.ovr, c.rarity, c.img,
           l.best_sell_price, l.best_buy_price,
           r.best_sell_price                                          AS ref_price,
           (l.best_sell_price - r.best_sell_price)                   AS price_change,
           ROUND((l.best_sell_price - r.best_sell_price)
                 * 100.0 / r.best_sell_price, 1)                     AS change_pct
    FROM latest l
    JOIN ref r ON r.uuid = l.uuid AND r.rn = 1
    JOIN cards c ON c.uuid = l.uuid
    WHERE l.rn = 1 AND r.best_sell_price > 0
"""


@app.get("/api/dashboard")
def dashboard(limit: int = Query(8, le=20)):
    """
    Returns four ranked card lists for the landing page:
      top_flip_profit — highest absolute flip profit (stubs) after 10% tax
      top_flip_pct    — highest % return on bid after 10% tax
      movers_up       — biggest Buy Now price increase since first recorded price
      movers_down     — biggest Buy Now price decrease since first recorded price
    """
    with get_conn() as conn:
        top_flip_profit = conn.execute(
            _FLIP_CTE + " ORDER BY flip_profit DESC LIMIT ?", (limit,)
        ).fetchall()

        top_flip_pct = conn.execute(
            _FLIP_CTE + " ORDER BY flip_profit_pct DESC LIMIT ?", (limit,)
        ).fetchall()

        movers_up = conn.execute(
            _MOVERS_CTE +
            " AND l.best_sell_price > r.best_sell_price"
            " ORDER BY price_change DESC LIMIT ?",
            (limit,),
        ).fetchall()

        movers_down = conn.execute(
            _MOVERS_CTE +
            " AND l.best_sell_price < r.best_sell_price"
            " ORDER BY price_change ASC LIMIT ?",
            (limit,),
        ).fetchall()

    def enrich(rows):
        return [_enrich(dict(r)) for r in rows]

    return {
        "top_flip_profit": enrich(top_flip_profit),
        "top_flip_pct":    enrich(top_flip_pct),
        "movers_up":       enrich(movers_up),
        "movers_down":     enrich(movers_down),
    }


# ---------------------------------------------------------------------------
# Market index endpoints
# ---------------------------------------------------------------------------


@app.get("/api/index/segments")
def index_segments():
    """
    All segments with latest values and deltas vs ~1h and ~24h ago.
    Each row includes: segment, type, label, sort_key, card_count,
    mean_sell, mean_buy, delta_1h, delta_1h_pct, delta_24h, delta_24h_pct.
    """
    rows = _db.get_index_summary()
    return [_enrich_segment(r) for r in rows]


@app.get("/api/index/history")
def index_history(
    segment: str = "all",
    hours: int = Query(168, le=720),
):
    """
    Time-series snapshots for a single segment, oldest-first.
    Each row: computed_at, card_count, mean_sell, mean_buy, median_sell, median_buy.
    """
    return _db.get_index_history(segment, hours)


# ---------------------------------------------------------------------------
# Static SPA — must come last so API routes take priority
# ---------------------------------------------------------------------------

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")
