"""CoinMarketCap client - a crypto price fallback for when CoinGecko is
unavailable, so live prices keep flowing. CoinGecko stays the primary source
(it provides sparklines, images, 1h/7d/30d changes that CMC's basic quote does
not). Needs a free key in env COINMARKETCAP_API_KEY or data/settings.json
{"coinmarketcap_api_key": "..."}.
"""

import json
import os
import threading
import time

import requests

BASE = "https://pro-api.coinmarketcap.com"
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")
MIN_INTERVAL = 2.5

_lock = threading.Lock()
_last_call = 0.0
last_ok = None
last_error = None


def _api_key():
    v = os.environ.get("COINMARKETCAP_API_KEY")
    if v:
        return v
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f).get("coinmarketcap_api_key") or None
    except (OSError, json.JSONDecodeError):
        return None


def quotes_by_symbol(symbols):
    """{SYMBOL: {price, pct_24h, market_cap, volume, name}} for the given
    tickers. Returns {} if no key configured or on failure (caller decides)."""
    global _last_call, last_ok, last_error
    key = _api_key()
    syms = sorted({(s or "").upper() for s in symbols if s})
    if not key or not syms:
        return {}
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    try:
        r = requests.get(
            BASE + "/v1/cryptocurrency/quotes/latest",
            params={"symbol": ",".join(syms), "convert": "USD"},
            headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"},
            timeout=20)
        r.raise_for_status()
        data = r.json().get("data") or {}
        out = {}
        for sym, entry in data.items():
            # a symbol can map to several coins; take the first (highest rank)
            e = entry[0] if isinstance(entry, list) else entry
            q = (e.get("quote") or {}).get("USD") or {}
            if q.get("price") is not None:
                out[sym.upper()] = {
                    "price": q.get("price"),
                    "pct_24h": q.get("percent_change_24h"),
                    "market_cap": q.get("market_cap"),
                    "volume": q.get("volume_24h"),
                    "name": e.get("name"),
                }
        last_ok = time.time()
        last_error = None
        return out
    except requests.RequestException as e:
        last_error = str(e)
        return {}
