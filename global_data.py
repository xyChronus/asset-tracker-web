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
TWELVE = "https://api.twelvedata.com"
ALPHA = "https://www.alphavantage.co/query"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) portfolio-tracker/1.0"}
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")

_lock = threading.Lock()
_last_fh_call = 0.0
FH_MIN_INTERVAL = 1.1

last_ok = None
last_error = None


def _setting(env_name, settings_key):
    """Read a key from an env var (production) or data/settings.json (local)."""
    v = os.environ.get(env_name)
    if v:
        return v
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f).get(settings_key) or None
    except (OSError, json.JSONDecodeError):
        return None


def _api_key():
    return _setting("FINNHUB_API_KEY", "finnhub_api_key")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
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
    """Real-time-ish quote, trying sources in order of quality until one has a
    price: Finnhub -> Yahoo -> Twelve Data -> Alpha Vantage."""
    try:
        q = fh_get("/quote", {"symbol": symbol})
        if q.get("c"):
            return {"price": q["c"], "chg_pct": q.get("dp"), "chg": q.get("d"),
                    "high": q.get("h"), "low": q.get("l"), "open": q.get("o"),
                    "prev_close": q.get("pc"), "src": "finnhub"}
    except Exception:
        pass
    for fn in (yahoo_quote, twelvedata_quote, alphavantage_quote):
        try:
            q = fn(symbol)
            if q and q.get("price"):
                return q
        except Exception:
            pass
    return {"price": None, "chg_pct": None, "src": "none"}


def twelvedata_quote(symbol):
    key = _setting("TWELVEDATA_API_KEY", "twelvedata_api_key")
    if not key:
        raise RuntimeError("no Twelve Data key")
    r = requests.get(f"{TWELVE}/quote", params={"symbol": symbol, "apikey": key},
                     headers=UA, timeout=15)
    r.raise_for_status()
    d = r.json()
    price = d.get("close") or d.get("price")
    if not price:
        raise RuntimeError(d.get("message") or "twelvedata: no price")
    return {"price": _f(price), "chg_pct": _f(d.get("percent_change")),
            "chg": _f(d.get("change")), "high": _f(d.get("high")), "low": _f(d.get("low")),
            "open": _f(d.get("open")), "prev_close": _f(d.get("previous_close")),
            "src": "twelvedata"}


def alphavantage_quote(symbol):
    key = _setting("ALPHAVANTAGE_API_KEY", "alphavantage_api_key")
    if not key:
        raise RuntimeError("no Alpha Vantage key")
    r = requests.get(ALPHA, params={"function": "GLOBAL_QUOTE", "symbol": symbol,
                                    "apikey": key}, headers=UA, timeout=15)
    r.raise_for_status()
    g = r.json().get("Global Quote") or {}
    price = g.get("05. price")
    if not price:
        raise RuntimeError("alphavantage: no price (daily limit?)")
    pct = (g.get("10. change percent") or "").replace("%", "")
    return {"price": _f(price), "chg_pct": _f(pct), "chg": _f(g.get("09. change")),
            "high": _f(g.get("03. high")), "low": _f(g.get("04. low")),
            "open": _f(g.get("02. open")), "prev_close": _f(g.get("08. previous close")),
            "src": "alphavantage"}


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


# ------------------------------------------------- Philippine stocks (Finnhub)
# Finnhub lists PSE names with a ".PM" suffix (e.g. BDO.PM, SM.PM). It returns
# clean quotes and fundamentals for them on the free tier - a far steadier
# source than the phisix mirrors and the PSE Edge scrape.

def pse_quote(symbol):
    """Single PSE quote from Finnhub. {price, chg_pct, prev_close} or None."""
    try:
        q = fh_get("/quote", {"symbol": symbol + ".PM"})
    except Exception:
        return None
    if q.get("c"):
        return {"price": q["c"], "chg_pct": q.get("dp"), "prev_close": q.get("pc")}
    return None


def pse_fundamentals(symbol):
    """PSE fundamentals from Finnhub: {pe, wk52_high, wk52_low, book_value, eps}.
    Returns {} if nothing usable. No sector P/E - Finnhub doesn't expose it, so
    the caller keeps the Edge scrape as a fallback for that one field."""
    try:
        m = fh_get("/stock/metric", {"symbol": symbol + ".PM",
                                     "metric": "all"}).get("metric", {})
    except Exception:
        return {}
    out = {
        "pe": _pick(m, ["peTTM", "peBasicExclExtraTTM", "peExclExtraTTM", "peInclExtraTTM"]),
        "wk52_high": m.get("52WeekHigh"),
        "wk52_low": m.get("52WeekLow"),
        "book_value": _pick(m, ["bookValuePerShareAnnual", "bookValuePerShareQuarterly"]),
        "eps": _pick(m, ["epsTTM", "epsBasicExclExtraItemsTTM", "epsInclExtraItemsTTM"]),
    }
    return out if any(v is not None for v in out.values()) else {}


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
