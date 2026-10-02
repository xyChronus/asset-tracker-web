"""Thin CoinGecko client with a global rate limiter.

The free public API allows roughly 10-30 requests/minute. All requests go
through get(), which enforces a minimum gap between calls and backs off when
the API says "too many requests" (HTTP 429).

Optional: put a free demo API key in data/settings.json as
{"coingecko_api_key": "CG-..."} to get more generous limits.
"""

import json
import os
import threading
import time

import requests

BASE = "https://api.coingecko.com/api/v3"
MIN_INTERVAL = 7.0  # seconds between requests (~8/min)
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")

_lock = threading.Lock()
_last_call = 0.0
_cooloff_until = 0.0  # monotonic ts; set when 429s persist (burst or monthly cap)

# Exposed for /api/status
last_ok = None      # epoch seconds of last successful call
last_error = None   # string of last failure, cleared on success
last_error_at = None  # epoch seconds of that failure
# after a connection failure or timeout, every call fails at once for this
# long instead of each one sitting through its own retries (3 x 25 s): the
# collector thread is shared by every market, and one unreachable source
# must not freeze the others' prices for the duration
_skip_until = 0.0
SKIP_S = 60.0
_NET_ERRORS = (requests.ConnectionError, requests.Timeout)


class RateLimited(RuntimeError):
    """CoinGecko said 429 and retries didn't clear it (burst storm or the
    monthly quota). Typed so callers can back off without string-sniffing."""


def _api_key():
    key = os.environ.get("COINGECKO_API_KEY")
    if key:
        return key
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f).get("coingecko_api_key") or None
    except (OSError, json.JSONDecodeError):
        return None


def get(path, params=None):
    global _last_call, _cooloff_until, _skip_until, last_ok, last_error, last_error_at
    with _lock:
        # while cooling off after persistent 429s, fail instantly instead of
        # sleeping the caller (the scheduler is single-threaded) - callers'
        # fallbacks (CoinMarketCap prices, backfill retry-later) take over
        if time.monotonic() < _cooloff_until:
            raise RateLimited("CoinGecko 429 cool-off active")
        if time.monotonic() < _skip_until:
            raise RuntimeError("CoinGecko unreachable a moment ago - skipped until the next retry window")
        got_429 = False
        net_fail = False
        for attempt in range(3):
            key = _api_key()
            interval = 2.2 if key else MIN_INTERVAL  # a demo key allows ~30/min
            wait = interval - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.monotonic()
            headers = {"accept": "application/json"}
            if key:
                headers["x-cg-demo-api-key"] = key
            try:
                r = requests.get(BASE + path, params=params, headers=headers, timeout=25)
                if r.status_code == 429:
                    got_429 = True
                    last_error = "rate limited by CoinGecko, backing off"
                    last_error_at = time.time()
                    time.sleep(15)
                    continue
                r.raise_for_status()
                last_ok = time.time()
                last_error = None
                _cooloff_until = 0.0
                _skip_until = 0.0
                return r.json()
            except requests.RequestException as e:
                last_error = str(e)
                last_error_at = time.time()
                net_fail = isinstance(e, _NET_ERRORS)
                if attempt == 2:
                    if net_fail:
                        _skip_until = time.monotonic() + SKIP_S
                    raise
                time.sleep(5)
    if got_429:
        # a burst storm clears within the retry loop; reaching here means the
        # limit is sustained (likely the monthly cap) - stop calling a while
        _cooloff_until = time.monotonic() + 900
        raise RateLimited("CoinGecko 429 persisted after retries")
    raise RuntimeError("CoinGecko request failed after retries")
