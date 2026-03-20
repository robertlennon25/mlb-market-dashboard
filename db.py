# db.py
"""
SQLite database helpers.

Tables
------
cards          — static card metadata (uuid, name, ovr, rarity, position, team, …)
price_history  — timestamped snapshots of buy/sell prices per card
"""

import sqlite3
import logging
from datetime import datetime, timezone
from contextlib import contextmanager

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config.settings import DB_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    uuid              TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    display_position  TEXT,
    team              TEXT,
    ovr               INTEGER,
    rarity            TEXT,
    series            TEXT,
    series_id         INTEGER,
    is_hitter         INTEGER,          -- 1 = hitter, 0 = pitcher
    bat_hand          TEXT,
    throw_hand        TEXT,
    age               INTEGER,
    img               TEXT,             -- card image URL
    first_seen        TIMESTAMP NOT NULL,
    last_updated      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid             TEXT NOT NULL REFERENCES cards(uuid),
    fetched_at       TIMESTAMP NOT NULL,
    best_sell_price  INTEGER,           -- lowest ask (cost to buy now)
    best_buy_price   INTEGER,           -- highest bid (what you get selling now)
    spread           INTEGER,           -- best_sell_price - best_buy_price
    spread_pct       REAL               -- spread as % of sell price
);

CREATE INDEX IF NOT EXISTS idx_ph_uuid       ON price_history(uuid);
CREATE INDEX IF NOT EXISTS idx_ph_fetched_at ON price_history(fetched_at);
CREATE INDEX IF NOT EXISTS idx_ph_spread     ON price_history(spread DESC);
CREATE INDEX IF NOT EXISTS idx_ph_uuid_time  ON price_history(uuid, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_cards_rarity  ON cards(rarity);
CREATE INDEX IF NOT EXISTS idx_cards_ovr     ON cards(ovr DESC);

CREATE TABLE IF NOT EXISTS market_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    segment     TEXT    NOT NULL,   -- 'all' | 'rarity:Diamond' | 'ovr:99' | 'pos:SP'
    computed_at TEXT    NOT NULL,   -- UTC, 'YYYY-MM-DD HH:MM:SS'
    card_count  INTEGER,
    mean_sell   REAL,               -- mean best_sell_price across segment
    mean_buy    REAL,               -- mean best_buy_price across segment
    median_sell REAL,
    median_buy  REAL,
    total_sell  INTEGER,
    total_buy   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mi_seg_time ON market_index(segment, computed_at DESC);
"""


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Card upserts
# ---------------------------------------------------------------------------

def upsert_card(card: dict):
    """Insert or update a card's static metadata."""
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT uuid FROM cards WHERE uuid = ?", (card["uuid"],)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE cards SET
                    name=?, display_position=?, team=?, ovr=?, rarity=?,
                    series=?, series_id=?, is_hitter=?, bat_hand=?,
                    throw_hand=?, age=?, img=?, last_updated=?
                   WHERE uuid=?""",
                (
                    card.get("name"), card.get("display_position"),
                    card.get("team"), card.get("ovr"), card.get("rarity"),
                    card.get("series"), card.get("series_id"),
                    card.get("is_hitter"), card.get("bat_hand"),
                    card.get("throw_hand"), card.get("age"), card.get("img"),
                    now, card["uuid"],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO cards
                   (uuid, name, display_position, team, ovr, rarity,
                    series, series_id, is_hitter, bat_hand, throw_hand,
                    age, img, first_seen, last_updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    card["uuid"], card.get("name"), card.get("display_position"),
                    card.get("team"), card.get("ovr"), card.get("rarity"),
                    card.get("series"), card.get("series_id"),
                    card.get("is_hitter"), card.get("bat_hand"),
                    card.get("throw_hand"), card.get("age"), card.get("img"),
                    now, now,
                ),
            )


def bulk_upsert_cards(cards: list[dict]):
    for c in cards:
        upsert_card(c)


# ---------------------------------------------------------------------------
# Price snapshots
# ---------------------------------------------------------------------------

def insert_price_snapshot(uuid: str, sell: int, buy: int, fetched_at: datetime | None = None):
    """Record a single price observation."""
    ts = fetched_at or datetime.now(timezone.utc)
    spread = (sell or 0) - (buy or 0)
    spread_pct = round(spread / sell * 100, 2) if sell else None

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO price_history
               (uuid, fetched_at, best_sell_price, best_buy_price, spread, spread_pct)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid, ts, sell, buy, spread, spread_pct),
        )


def bulk_insert_snapshots(rows: list[dict]):
    """
    rows: list of dicts with keys uuid, best_sell_price, best_buy_price
    All rows share the same fetched_at timestamp (now).
    """
    ts = datetime.now(timezone.utc)
    data = []
    for r in rows:
        sell = r.get("best_sell_price") or 0
        buy  = r.get("best_buy_price")  or 0
        spread = sell - buy
        spread_pct = round(spread / sell * 100, 2) if sell else None
        data.append((r["uuid"], ts, sell, buy, spread, spread_pct))

    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO price_history
               (uuid, fetched_at, best_sell_price, best_buy_price, spread, spread_pct)
               VALUES (?, ?, ?, ?, ?, ?)""",
            data,
        )
    return len(data)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_top_spreads(limit: int = 50, rarity: str | None = None, min_sell: int = 100):
    """Return cards with the largest current spread (most recent snapshot)."""
    rarity_filter = "AND c.rarity = ?" if rarity else ""
    params = [min_sell]
    if rarity:
        params.append(rarity)
    params.append(limit)

    sql = f"""
        WITH latest AS (
            SELECT uuid,
                   best_sell_price, best_buy_price, spread, spread_pct,
                   fetched_at,
                   ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at DESC) AS rn
            FROM price_history
            WHERE best_sell_price >= ?
        )
        SELECT c.name, c.display_position, c.team, c.ovr, c.rarity, c.series,
               l.best_sell_price, l.best_buy_price, l.spread, l.spread_pct,
               l.fetched_at, c.uuid
        FROM latest l
        JOIN cards c ON c.uuid = l.uuid
        WHERE l.rn = 1
          {rarity_filter}
        ORDER BY l.spread DESC
        LIMIT ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_price_history(uuid: str, limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT fetched_at, best_sell_price, best_buy_price, spread
               FROM price_history WHERE uuid=? ORDER BY fetched_at DESC LIMIT ?""",
            (uuid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def card_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]


def snapshot_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]


# ---------------------------------------------------------------------------
# Market index
# ---------------------------------------------------------------------------

def get_latest_prices_with_metadata() -> list[dict]:
    """Most-recent price snapshot per card, joined with card metadata."""
    with get_conn() as conn:
        rows = conn.execute("""
            WITH latest_times AS (
                SELECT uuid, MAX(fetched_at) AS max_at
                FROM price_history
                GROUP BY uuid
            )
            SELECT c.rarity, c.ovr, c.display_position,
                   ph.best_sell_price, ph.best_buy_price
            FROM price_history ph
            JOIN latest_times lt ON ph.uuid = lt.uuid AND ph.fetched_at = lt.max_at
            JOIN cards c ON c.uuid = ph.uuid
            WHERE ph.best_sell_price > 0
        """).fetchall()
    return [dict(r) for r in rows]


def insert_index_snapshot(rows: list[dict], computed_at=None) -> int:
    """Bulk-insert one round of market-index snapshots (one row per segment).
    computed_at may be a datetime object or a pre-formatted 'YYYY-MM-DD HH:MM:SS' string.
    """
    if computed_at is None:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(computed_at, str):
        ts = computed_at[:19]   # accept raw DB strings like '2026-03-15 18:33:27.523449+00:00'
    else:
        ts = computed_at.strftime('%Y-%m-%d %H:%M:%S')
    data = [
        (
            r['segment'], ts, r['card_count'],
            r.get('mean_sell'), r.get('mean_buy'),
            r.get('median_sell'), r.get('median_buy'),
            r.get('total_sell'), r.get('total_buy'),
        )
        for r in rows
    ]
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO market_index
               (segment, computed_at, card_count, mean_sell, mean_buy,
                median_sell, median_buy, total_sell, total_buy)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            data,
        )
    return len(data)


def get_index_history(segment: str, hours: int = 168) -> list[dict]:
    """Time-series snapshots for one segment, oldest-first, within the last N hours."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT computed_at, card_count, mean_sell, mean_buy,
                      median_sell, median_buy
               FROM market_index
               WHERE segment = ?
                 AND computed_at >= datetime('now', ?)
               ORDER BY computed_at ASC""",
            (segment, f'-{hours} hours'),
        ).fetchall()
    return [dict(r) for r in rows]


def get_index_summary() -> list[dict]:
    """
    Latest snapshot per segment plus deltas vs ~1 h and ~24 h ago.
    Delta is on mean_sell (Buy-Now side, most useful for traders).
    """
    with get_conn() as conn:
        latest_rows = conn.execute("""
            WITH ranked AS (
                SELECT segment, computed_at, card_count, mean_sell, mean_buy,
                       ROW_NUMBER() OVER (PARTITION BY segment ORDER BY computed_at DESC) rn
                FROM market_index
            )
            SELECT segment, computed_at, card_count, mean_sell, mean_buy
            FROM ranked WHERE rn = 1
        """).fetchall()

        if not latest_rows:
            return []

        def past_by_offset(hours: int) -> dict:
            rows = conn.execute(
                """WITH ranked AS (
                       SELECT segment, mean_sell, mean_buy,
                              ROW_NUMBER() OVER (PARTITION BY segment ORDER BY computed_at DESC) rn
                       FROM market_index
                       WHERE computed_at <= datetime('now', ?)
                   )
                   SELECT segment, mean_sell, mean_buy FROM ranked WHERE rn = 1""",
                (f'-{hours} hours',),
            ).fetchall()
            return {r['segment']: dict(r) for r in rows}

        past_1h  = past_by_offset(1)
        past_24h = past_by_offset(24)

    result = []
    for r in latest_rows:
        row = dict(r)
        seg       = row['segment']
        curr_sell = row.get('mean_sell')

        def _delta(curr_val, past_dict):
            past_val = past_dict.get(seg, {}).get('mean_sell')
            if curr_val is None or past_val is None:
                return None, None
            d = round(curr_val - past_val, 1)
            pct = round(d / past_val * 100, 2) if past_val else None
            return d, pct

        row['delta_1h'],  row['delta_1h_pct']  = _delta(curr_sell, past_1h)
        row['delta_24h'], row['delta_24h_pct'] = _delta(curr_sell, past_24h)
        result.append(row)
    return result
