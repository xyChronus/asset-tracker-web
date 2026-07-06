"""Philippine Stock Exchange data.

Quotes:       phisix (free JSON mirror of PSE quotes, all stocks in one call)
Directory:    PSE Edge company directory (symbol, name, ids, sector)
Fundamentals: PSE Edge per-company Stock Data page (P/E, 52-week, book value;
              EPS derived as price / P/E)
Dividends:    PSE Edge site-wide dividend declarations (ex/record/payment dates)

PSE Edge is the exchange's official disclosure site but has no official API -
we read the same endpoints its own web pages use, politely (one request every
few seconds, generous caching).
"""

import json
import re
import threading
import time
from datetime import datetime, timedelta

import requests

PHISIX_URLS = [
    "https://phisix-api3.appspot.com/stocks.json",
    "https://phisix-api4.appspot.com/stocks.json",
]
EDGE = "https://edge.pse.com.ph"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) portfolio-tracker/1.0"}

_lock = threading.Lock()
_last_edge_call = 0.0
EDGE_MIN_INTERVAL = 4.0

last_ok = None
last_error = None


def _edge_request(method, path, **kw):
    """Rate-limited request to PSE Edge."""
    global _last_edge_call, last_ok, last_error
    with _lock:
        wait = EDGE_MIN_INTERVAL - (time.monotonic() - _last_edge_call)
        if wait > 0:
            time.sleep(wait)
        _last_edge_call = time.monotonic()
        try:
            r = requests.request(method, EDGE + path, headers=UA, timeout=25, **kw)
            r.raise_for_status()
            last_ok = time.time()
            last_error = None
            return r.text
        except requests.RequestException as e:
            last_error = str(e)
            raise


def fetch_chart(cmpy_id, security_id, months=6):
    """Official daily closes from the Edge stock-data chart.
    Returns [[epoch_ms (3 PM close, hour-rounded), close], ...]."""
    end = datetime.now()
    start = end - timedelta(days=months * 30)
    body = _edge_request(
        "POST", "/common/DisclosureCht.ax",
        json={"cmpy_id": str(cmpy_id), "security_id": str(security_id),
              "startDate": start.strftime("%m-%d-%Y"),
              "endDate": end.strftime("%m-%d-%Y")})
    out = []
    for row in json.loads(body).get("chartData", []):
        close = row.get("CLOSE")
        raw = row.get("CHART_DATE")
        if close is None or not raw:
            continue
        try:
            d = datetime.strptime(raw, "%b %d, %Y %H:%M:%S")
        except ValueError:
            continue
        ts = int(datetime(d.year, d.month, d.day, 15).timestamp() * 1000)
        out.append([ts // 3600000 * 3600000, float(close)])
    return out


def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def _num(s):
    """'1,234.56' -> float; '-', '', 'n/a' -> None."""
    if s is None:
        return None
    s = s.replace(",", "").replace("&nbsp;", " ").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m or s in ("-", ""):
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# ------------------------------------------------------------------- quotes

def fetch_quotes():
    """All PSE quotes: {SYMBOL: {price, chg_pct, volume, value, name}}."""
    global last_ok, last_error
    err = None
    for url in PHISIX_URLS:
        try:
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            data = r.json()
            out = {}
            for s in data.get("stocks", []):
                price = (s.get("price") or {}).get("amount")
                if price is None:
                    continue
                sym = s.get("symbol", "").upper()
                vol = s.get("volume") or 0
                out[sym] = {
                    "price": float(price),
                    "chg_pct": s.get("percentChange"),
                    "volume": vol,
                    "value": float(price) * vol,
                    "name": s.get("name"),
                }
            if out:
                last_ok = time.time()
                last_error = None
                return out, data.get("as_of")
        except Exception as e:  # try the next mirror
            err = e
    last_error = str(err)
    raise RuntimeError(f"phisix quotes failed: {err}")


# ---------------------------------------------------------------- directory

def fetch_directory():
    """All listed companies from the PSE Edge directory.
    Returns [{symbol, name, cmpy_id, security_id, sector}]."""
    companies = []
    page = 1
    total_pages = 1
    while page <= total_pages and page <= 12:
        html = _edge_request(
            "POST", f"/companyDirectory/search.ax?pageNo={page}&sortType=common")
        m = re.search(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]", html)
        if m:
            total_pages = int(m.group(2))
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
        for row in rows:
            ids = re.search(r"cmDetail\('(\d+)','(\d+)'\)", row)
            if not ids:
                continue
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
            texts = [_strip(c) for c in cells]
            if len(texts) < 2 or not texts[1]:
                continue
            companies.append({
                "name": texts[0],
                "symbol": texts[1].upper(),
                "sector": texts[2] if len(texts) > 2 else None,
                "cmpy_id": ids.group(1),
                "security_id": ids.group(2),
            })
        page += 1
    return companies


# -------------------------------------------------------------- fundamentals

def fetch_stock_data(cmpy_id):
    """P/E, sector P/E, 52-week range, book value from the Stock Data page."""
    html = _edge_request("GET", f"/companyPage/stockData.do?cmpy_id={cmpy_id}")
    # the page lays fields out as label/value table cells; build a flat map
    cells = [_strip(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", html, flags=re.S)]
    fields = {}
    for i, cell in enumerate(cells):
        if i + 1 < len(cells):
            fields[cell.lower()] = cells[i + 1]
    return {
        "price": _num(fields.get("last traded price")),
        "pe": _num(fields.get("p/e ratio")),
        "sector_pe": _num(fields.get("sector p/e ratio")),
        "wk52_high": _num(fields.get("52-week high")),
        "wk52_low": _num(fields.get("52-week low")),
        "book_value": _num(fields.get("book value")),
    }


# ----------------------------------------------------------------- dividends

def _parse_edge_date(s):
    s = (s or "").strip()
    if not s or s.upper() in ("TBA", "-", "N/A"):
        return None
    for fmt in ("%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def fetch_dividends(pages=5):
    """Recent dividend declarations across all companies.
    Returns [{company, security, div_type, rate_raw, rate, ex_date, record_date, pay_date}]."""
    out = []
    for page in range(1, pages + 1):
        html = _edge_request(
            "POST", "/disclosureData/dividends_and_rights_info_list.ax",
            data={"pageNo": page, "DividendsOrRights": ""})
        if "Dividend Information" not in html:
            break
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
        got = 0
        for row in rows:
            cells = [_strip(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
            if len(cells) < 7:
                continue
            company, security, div_type, rate_raw = cells[0], cells[1], cells[2], cells[3]
            out.append({
                "company": company,
                "security": security,
                "div_type": div_type,
                "rate_raw": rate_raw,
                "rate": _num(rate_raw) if "%" not in rate_raw else None,
                "ex_date": _parse_edge_date(cells[4]),
                "record_date": _parse_edge_date(cells[5]),
                "pay_date": _parse_edge_date(cells[6]),
            })
            got += 1
        if not got:
            break
    return out


def norm_name(name):
    """Normalize a company name for matching the dividends table to symbols."""
    n = (name or "").lower()
    n = re.sub(r"[\"'`.,()]", " ", n)
    n = re.sub(r"\b(incorporated|inc|corporation|corp|company|co|the|and|of|phils?|philippines)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()
