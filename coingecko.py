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

# Exposed for /api/status
last_ok = None      # epoch seconds of last successful call
last_error = None   # string of last failure, cleared on success


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
    global _last_call, last_ok, last_error
    with _lock:
        for attempt in range(3):
            wait = MIN_INTERVAL - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.monotonic()
            headers = {"accept": "application/json"}
            key = _api_key()
            if key:
                headers["x-cg-demo-api-key"] = key
            try:
                r = requests.get(BASE + path, params=params, headers=headers, timeout=25)
                if r.status_code == 429:
                    last_error = "rate limited by CoinGecko, backing off"
                    time.sleep(40)
                    continue
                r.raise_for_status()
                last_ok = time.time()
                last_error = None
                return r.json()
            except requests.RequestException as e:
                last_error = str(e)
                if attempt == 2:
                    raise
                time.sleep(5)
    raise RuntimeError("CoinGecko request failed after retries")
