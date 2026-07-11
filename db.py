"""Postgres storage for the web version (Neon). Multi-user schema.

Shared (global) tables:  price_history, news, fundamentals, pse_companies, kv,
                         watchlist rows with user_id = 0 (the PSE directory)
Per-user tables/rows:    users, invites, transactions, watchlist (crypto/global),
                         advisor_dismissed, wallets
"""

import os
import threading
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE,
    created TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    created_by INTEGER,
    used_by INTEGER,
    created TEXT,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    ts TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    type TEXT NOT NULL,
    name TEXT,
    fee DOUBLE PRECISION DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions (user_id, market);
CREATE TABLE IF NOT EXISTS watchlist (
    user_id INTEGER NOT NULL,          -- 0 = shared (PSE directory)
    market TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    added_ts TEXT,
    PRIMARY KEY (user_id, market, asset_id)
);
CREATE TABLE IF NOT EXISTS price_history (
    market TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    ts BIGINT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (market, asset_id, ts)
);
CREATE TABLE IF NOT EXISTS news (
    market TEXT NOT NULL,
    link TEXT NOT NULL,
    source TEXT,
    title TEXT,
    published BIGINT,
    summary TEXT,
    PRIMARY KEY (market, link)
);
CREATE TABLE IF NOT EXISTS fundamentals (
    market TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    eps DOUBLE PRECISION, pe DOUBLE PRECISION, sector_pe DOUBLE PRECISION,
    book_value DOUBLE PRECISION,
    div_ps DOUBLE PRECISION, div_yield DOUBLE PRECISION,
    div_rate TEXT, div_ex_date TEXT, div_record_date TEXT, div_pay_date TEXT,
    wk52_high DOUBLE PRECISION, wk52_low DOUBLE PRECISION,
    sector TEXT,
    updated BIGINT,
    PRIMARY KEY (market, asset_id)
);
CREATE TABLE IF NOT EXISTS pse_companies (
    symbol TEXT PRIMARY KEY,
    cmpy_id TEXT,
    security_id TEXT,
    name TEXT,
    sector TEXT,
    updated BIGINT
);
CREATE TABLE IF NOT EXISTS advisor_dismissed (
    user_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    action TEXT,
    ts BIGINT,
    PRIMARY KEY (user_id, market, asset_id)
);
CREATE TABLE IF NOT EXISTS wallets (
    user_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    budget DOUBLE PRECISION,
    PRIMARY KEY (user_id, market)
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class _Conn:
    """Thin wrapper: sqlite3-like surface + automatic reconnect (Neon closes
    idle connections). Runs in autocommit mode; commit() is a no-op kept for
    call-site compatibility."""

    def __init__(self):
        self._pg = None

    def _ensure(self):
        if self._pg is None or self._pg.closed:
            self._pg = psycopg.connect(DATABASE_URL, autocommit=True,
                                       row_factory=dict_row, connect_timeout=15)
        return self._pg

    def execute(self, sql, params=None):
        try:
            return self._ensure().execute(sql, params or ())
        except psycopg.OperationalError:
            self._pg = None  # dropped connection: reconnect once and retry
            return self._ensure().execute(sql, params or ())

    def executemany(self, sql, rows):
        rows = list(rows)
        if not rows:
            return
        try:
            with self._ensure().cursor() as cur:
                cur.executemany(sql, rows)
        except psycopg.OperationalError:
            self._pg = None
            with self._ensure().cursor() as cur:
                cur.executemany(sql, rows)

    def commit(self):
        pass  # autocommit


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = _Conn()
        _local.conn = c
    return c


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def init():
    conn().execute(SCHEMA)
    # migrations for columns added after the initial deploy (idempotent)
    conn().execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trading_style TEXT DEFAULT 'swing'")
    conn().execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS agreed_terms BOOLEAN DEFAULT FALSE")
    conn().execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS fee DOUBLE PRECISION DEFAULT 0")


# --- tiny JSON key/value store ---
import json  # noqa: E402
import time  # noqa: E402


# In-process cache for hot, snapshot-style kv keys. We run a single gunicorn
# worker (render.yaml: -w 1), so every write goes through this process's
# kv_set and the cache stays coherent. This is what protects Neon's "public
# network transfer" quota: these blobs are tens of KB and were being re-read
# from Postgres on every API call and collector tick. The TTL is a
# belt-and-braces bound; in steady state each collector's kv_set refreshes
# its key before the TTL lapses, so hot reads never touch the DB at all.
# Do NOT add advisor:* keys - _invalidate_advisor deletes rows directly,
# which this cache would not see.
_KV_HOT = {
    "crypto:watch_markets", "crypto:top100", "crypto:global", "crypto:fng",
    "crypto:signals", "crypto:history_fetched",
    "pse:quotes", "pse:signals", "pse:backfilled",
    "global:quotes", "global:signals", "global:profiles", "global:indices",
    "global:history_fetched", "fx:usdphp",
}
_KV_TTL = 900.0
_kv_cache = {}          # key -> (expires_monotonic, value)
_kv_lock = threading.Lock()


def kv_set(key, obj):
    conn().execute(
        "INSERT INTO kv (key, value) VALUES (%s,%s)"
        " ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
        (key, json.dumps(obj)))
    if key in _KV_HOT:
        with _kv_lock:
            _kv_cache[key] = (time.monotonic() + _KV_TTL, obj)


def kv_get(key, default=None):
    hit = None
    if key in _KV_HOT:
        with _kv_lock:
            hit = _kv_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    row = conn().execute("SELECT value FROM kv WHERE key=%s", (key,)).fetchone()
    if row is None:
        return default
    try:
        val = json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return default
    if key in _KV_HOT:
        with _kv_lock:
            # Only store if no concurrent kv_set/kv_get refreshed the entry while
            # our SELECT was in flight - a slow read must never clobber a newer
            # value and pin it for a full TTL.
            if _kv_cache.get(key) is hit:
                _kv_cache[key] = (time.monotonic() + _KV_TTL, val)
    return val


def parse_tx_ts(ts):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(ts.strip(), fmt).timestamp() * 1000)
        except ValueError:
            continue
    return 0


def set_fundamentals(market, asset_id, **fields):
    allowed = ("eps", "pe", "sector_pe", "book_value", "div_ps", "div_yield",
               "div_rate", "div_ex_date", "div_record_date", "div_pay_date",
               "wk52_high", "wk52_low", "sector", "updated")
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    c = conn()
    c.execute("INSERT INTO fundamentals (market, asset_id) VALUES (%s,%s)"
              " ON CONFLICT (market, asset_id) DO NOTHING", (market, asset_id))
    sets = ", ".join(f"{k}=%s" for k in fields)
    c.execute(f"UPDATE fundamentals SET {sets} WHERE market=%s AND asset_id=%s",
              (*fields.values(), market, asset_id))


def get_fundamentals(market):
    return {r["asset_id"]: dict(r) for r in conn().execute(
        "SELECT * FROM fundamentals WHERE market=%s", (market,)).fetchall()}
