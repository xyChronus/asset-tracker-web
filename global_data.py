"""International stock data: Finnhub (primary) with Yahoo Finance backup.

Finnhub free tier: 60 calls/min - we stay near 1 call/second.
Yahoo's public chart endpoint needs no key and supplies hourly history
(Finnhub keeps candles behind a paywall) plus a full quote fallback.
"""

import json
import os
import threading
import time

import requests

FINNHUB = "https://finnhub.io/api/v1"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) portfolio-tracker/1.0"}
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")

_lock = threading.Lock()
_last_fh_call = 0.0
FH_MIN_INTERVAL = 1.1

last_ok = None
last_error = None


def _api_key():
    key = os.environ.get("FINNHUB_API_KEY")
    if key:
        return key
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f).get("finnhub_api_key") or None
    except (OSError, json.JSONDecodeError):
        return None


def fh_get(path, params=None):
    """Rate-limited Finnhub GET. Raises if no key or on failure."""
    global _last_fh_call, last_ok, last_error
    key = _api_key()
    if not key:
        raise RuntimeError("no Finnhub API key configured")
    with _lock:
        wait = FH_MIN_INTERVAL - (time.monotonic() - _last_fh_call)
        if wait > 0:
            time.sleep(wait)
        _last_fh_call = time.monotonic()
    p = dict(params or {})
    p["token"] = key
    try:
        r = requests.get(FINNHUB + path, params=p, headers=UA, timeout=20)
        if r.status_code == 429:
            time.sleep(30)
            r = requests.get(FINNHUB + path, params=p, headers=UA, timeout=20)
        r.raise_for_status()
        last_ok = time.time()
        last_error = None
        return r.json()
    except requests.RequestException as e:
        last_error = str(e)
        raise


def quote(symbol):
    """{price, chg_pct, chg, high, low, open, prev_close} via Finnhub,
    falling back to Yahoo if Finnhub fails or has no data."""
    try:
        q = fh_get("/quote", {"symbol": symbol})
        if q.get("c"):
            return {"price": q["c"], "chg_pct": q.get("dp"), "chg": q.get("d"),
                    "high": q.get("h"), "low": q.get("l"), "open": q.get("o"),
                    "prev_close": q.get("pc"), "src": "finnhub"}
    except Exception:
        pass
    return yahoo_quote(symbol)


def _pick(metric, keys):
    for k in keys:
        v = metric.get(k)
        if v is not None:
            return v
    return None


def metrics(symbol):
    """EPS / P/E / dividend per share / dividend yield / 52-week range."""
    m = fh_get("/stock/metric", {"symbol": symbol, "metric": "all"}).get("metric", {})
    return {
        "eps": _pick(m, ["epsTTM", "epsBasicExclExtraItemsTTM", "epsInclExtraItemsTTM"]),
        "pe": _pick(m, ["peTTM", "peBasicExclExtraTTM", "peExclExtraTTM", "peInclExtraTTM"]),
        "div_ps": _pick(m, ["dividendPerShareAnnual", "dividendPerShareTTM"]),
        "div_yield": _pick(m, ["dividendYieldIndicatedAnnual", "currentDividendYieldTTM"]),
        "wk52_high": m.get("52WeekHigh"),
        "wk52_low": m.get("52WeekLow"),
    }


def profile(symbol):
    """Company name + logo (best effort)."""
    try:
        p = fh_get("/stock/profile2", {"symbol": symbol})
        return {"name": p.get("name"), "image": p.get("logo")}
    except Exception:
        return {}


# ------------------------------------------------------------------- yahoo

def _yahoo_chart(symbol, interval, rng):
    r = requests.get(f"{YAHOO}/{symbol}",
                     params={"interval": interval, "range": rng},
                     headers=UA, timeout=20)
    r.raise_for_status()
    result = (r.json().get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"yahoo: no data for {symbol}")
    return result


def yahoo_history(symbol, interval="1h", rng="60d"):
    """[[epoch_ms, close], ...] - hour-rounded, None closes skipped."""
    global last_ok, last_error
    try:
        res = _yahoo_chart(symbol, interval, rng)
        ts = res.get("timestamp") or []
        closes = ((res.get("indicators", {}).get("quote") or [{}])[0]).get("close") or []
        out = []
        for t, cl in zip(ts, closes):
            if cl is None:
                continue
            out.append([int(t // 3600 * 3600) * 1000, float(cl)])
        last_ok = time.time()
        last_error = None
        return out
    except Exception as e:
        last_error = str(e)
        raise


def yahoo_quote(symbol):
    """Quote from Yahoo chart metadata (keyless fallback)."""
    res = _yahoo_chart(symbol, "1d", "5d")
    meta = res.get("meta", {})
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    chg_pct = ((price - prev) / prev * 100) if price is not None and prev else None
    return {"price": price, "chg_pct": chg_pct, "chg": None,
            "high": meta.get("regularMarketDayHigh"), "low": meta.get("regularMarketDayLow"),
            "open": None, "prev_close": prev, "src": "yahoo"}


def index_quote(symbol):
    """For market indices like ^GSPC / ^IXIC / ^DJI (Yahoo only)."""
    return yahoo_quote(symbol)
