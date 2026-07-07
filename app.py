"""Asset Tracker Web - multi-user crypto / PSE / global stocks tracker.

Local dev:   set DATABASE_URL + SECRET_KEY, then  python app.py  (port 8951)
Production:  gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT app:app
             (exactly ONE worker: it hosts the shared data-collector thread)
"""

import os
import secrets
import threading
import time
import traceback
from datetime import datetime
from functools import wraps

import requests
from flask import (Flask, jsonify, redirect, request, send_from_directory,
                   session)
from werkzeug.security import check_password_hash, generate_password_hash

import advisor as adv
import coingecko
import coinmarketcap
import config
import db
import global_data
import news
import pse_data
import signals as sig

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-" + secrets.token_hex(8))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

_advisor_lock = threading.Lock()
ADVISOR_CACHE_SECONDS = 180


def now_ms():
    return int(time.time() * 1000)


# ------------------------------------------------------------------- auth

PUBLIC_PATHS = ("/login", "/register", "/api/login", "/api/register",
                "/static/", "/healthz", "/favicon.ico")


@app.before_request
def _require_login():
    p = request.path
    if any(p == x or p.startswith(x) for x in PUBLIC_PATHS):
        return None
    if session.get("uid"):
        return None
    if p.startswith("/api/"):
        return jsonify({"error": "not signed in"}), 401
    return redirect("/login")


def uid():
    return session["uid"]


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return jsonify({"error": "admin only"}), 403
        return fn(*a, **kw)
    return wrapper


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/login")
def login_page():
    return send_from_directory("static", "login.html")


@app.get("/register")
def register_page():
    return send_from_directory("static", "register.html")


@app.post("/api/login")
def api_login():
    d = request.get_json(force=True)
    email = (d.get("email") or "").strip().lower()
    row = db.conn().execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], d.get("password") or ""):
        return jsonify({"error": "Wrong email or password."}), 401
    session.permanent = True
    session["uid"] = row["id"]
    session["email"] = row["email"]
    session["name"] = row["name"]
    session["admin"] = bool(row["is_admin"])
    return jsonify({"ok": True})


@app.post("/api/register")
def api_register():
    d = request.get_json(force=True)
    email = (d.get("email") or "").strip().lower()
    name = (d.get("name") or "").strip()[:60]
    password = d.get("password") or ""
    invite = (d.get("invite") or "").strip()
    if "@" not in email or "." not in email:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password needs at least 8 characters."}), 400
    if not d.get("agree"):
        return jsonify({"error": "Please tick the box confirming you understand "
                                 "tracked values are estimates before continuing."}), 400
    c = db.conn()
    if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
        return jsonify({"error": "That email is already registered."}), 400
    n_users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    is_admin = n_users == 0  # first account becomes the admin
    if not is_admin:
        inv = c.execute(
            "SELECT * FROM invites WHERE code=%s AND used_by IS NULL", (invite,)).fetchone()
        if not inv:
            return jsonify({"error": "A valid invite code is required - ask "
                                     "whoever shared this site with you."}), 403
    c.execute("INSERT INTO users (email, name, password_hash, is_admin, created, agreed_terms)"
              " VALUES (%s,%s,%s,%s,%s,TRUE)",
              (email, name or email.split("@")[0], generate_password_hash(password),
               is_admin, db.now_iso()))
    row = c.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    if not is_admin:
        c.execute("UPDATE invites SET used_by=%s, used_at=%s WHERE code=%s",
                  (row["id"], db.now_iso(), invite))
    # seed the starter watchlists for the new user
    for cid, sym, nm in config.CRYPTO_WATCHLIST:
        c.execute("INSERT INTO watchlist VALUES (%s,'crypto',%s,%s,%s,%s)"
                  " ON CONFLICT DO NOTHING", (row["id"], cid, sym, nm, db.now_iso()))
    for sym, nm in config.GLOBAL_WATCHLIST:
        c.execute("INSERT INTO watchlist VALUES (%s,'global',%s,%s,%s,%s)"
                  " ON CONFLICT DO NOTHING", (row["id"], sym, sym, nm, db.now_iso()))
    session.permanent = True
    session["uid"] = row["id"]
    session["email"] = row["email"]
    session["name"] = row["name"]
    session["admin"] = is_admin
    return jsonify({"ok": True, "admin": is_admin})


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/api/me")
def api_me():
    row = db.conn().execute(
        "SELECT trading_style FROM users WHERE id=%s", (uid(),)).fetchone()
    style = (row or {}).get("trading_style") or "swing"
    return jsonify({"email": session.get("email"), "name": session.get("name"),
                    "admin": bool(session.get("admin")), "trading_style": style})


@app.post("/api/change_password")
def api_change_password():
    d = request.get_json(force=True)
    current = d.get("current") or ""
    new = d.get("new") or ""
    if len(new) < 8:
        return jsonify({"error": "New password needs at least 8 characters."}), 400
    row = db.conn().execute("SELECT password_hash FROM users WHERE id=%s", (uid(),)).fetchone()
    if not row or not check_password_hash(row["password_hash"], current):
        return jsonify({"error": "Your current password isn't right."}), 403
    db.conn().execute("UPDATE users SET password_hash=%s WHERE id=%s",
                      (generate_password_hash(new), uid()))
    return jsonify({"ok": True})


@app.post("/api/settings")
def api_settings():
    d = request.get_json(force=True)
    style = (d.get("trading_style") or "").strip().lower()
    if style not in adv.STYLE_PARAMS:
        return jsonify({"error": "unknown trading style"}), 400
    db.conn().execute("UPDATE users SET trading_style=%s WHERE id=%s", (style, uid()))
    for market in config.MARKETS:  # style changes every market's advice
        _invalidate_advisor(market, uid())
    return jsonify({"ok": True, "trading_style": style})


@app.post("/api/invites")
@admin_required
def api_create_invite():
    code = secrets.token_urlsafe(6)
    db.conn().execute("INSERT INTO invites (code, created_by, created) VALUES (%s,%s,%s)",
                      (code, uid(), db.now_iso()))
    return jsonify({"ok": True, "code": code})


@app.get("/api/members")
@admin_required
def api_members():
    users = [dict(r) for r in db.conn().execute(
        "SELECT id, name, email, created, is_admin FROM users ORDER BY id").fetchall()]
    invites = [dict(r) for r in db.conn().execute(
        "SELECT i.code, i.created, i.used_at, u.email AS used_by_email"
        " FROM invites i LEFT JOIN users u ON u.id = i.used_by"
        " ORDER BY i.created DESC LIMIT 50").fetchall()]
    return jsonify({"users": users, "invites": invites})


@app.get("/api/invites")
@admin_required
def api_list_invites():
    rows = db.conn().execute(
        "SELECT i.code, i.created, i.used_at, u.email AS used_by_email"
        " FROM invites i LEFT JOIN users u ON u.id = i.used_by"
        " ORDER BY i.created DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------- helpers

def watch_ids(market, user):
    owner = 0 if market == "pse" else user
    rows = db.conn().execute(
        "SELECT asset_id FROM watchlist WHERE market=%s AND user_id=%s ORDER BY asset_id",
        (market, owner)).fetchall()
    return [r["asset_id"] for r in rows]


def tracked_ids_all_users(market):
    """Everything the collector must keep fresh: every user's watchlist plus
    every asset anyone holds."""
    if market == "pse":
        rows = db.conn().execute("SELECT symbol AS a FROM pse_companies").fetchall()
        return [r["a"] for r in rows]
    rows = db.conn().execute(
        "SELECT DISTINCT asset_id AS a FROM watchlist WHERE market=%s"
        " UNION SELECT DISTINCT asset_id FROM transactions WHERE market=%s",
        (market, market)).fetchall()
    return [r["a"] for r in rows]


def price_map(market):
    out = {}
    if market == "crypto":
        snap = db.kv_get("crypto:watch_markets", {})
        for m in snap.get("data", []):
            out[m["id"]] = {"price": m.get("current_price"),
                            "chg_24h": m.get("price_change_percentage_24h_in_currency"),
                            "name": m.get("name"),
                            "symbol": (m.get("symbol") or "").upper(),
                            "image": m.get("image"), "_raw": m}
        return out, snap.get("updated")
    if market == "pse":
        snap = db.kv_get("pse:quotes", {})
        names = {r["symbol"]: r["name"] for r in db.conn().execute(
            "SELECT symbol, name FROM pse_companies").fetchall()}
        for symb, q in snap.get("data", {}).items():
            out[symb] = {"price": q.get("price"), "chg_24h": q.get("chg_pct"),
                         "name": names.get(symb) or q.get("name") or symb,
                         "symbol": symb, "image": None,
                         "volume": q.get("volume"), "value_traded": q.get("value")}
        return out, snap.get("updated")
    snap = db.kv_get("global:quotes", {})
    profiles = db.kv_get("global:profiles", {})
    for symb, q in snap.get("data", {}).items():
        prof = profiles.get(symb, {})
        out[symb] = {"price": q.get("price"), "chg_24h": q.get("chg_pct"),
                     "name": prof.get("name") or symb, "symbol": symb,
                     "image": prof.get("image")}
    return out, snap.get("updated")


# ---------------------------------------------------- shared data collectors

def crypto_fetch_markets():
    ids = tracked_ids_all_users("crypto")
    if not ids:
        return
    try:
        data = coingecko.get("/coins/markets", {
            "vs_currency": "usd", "ids": ",".join(ids[:250]), "per_page": 250,
            "price_change_percentage": "1h,24h,7d,30d", "sparkline": "true"})
        db.kv_set("crypto:watch_markets", {"updated": now_ms(), "data": data})
    except Exception:
        # CoinGecko unavailable: keep prices alive from CoinMarketCap
        fallback = _cmc_markets_fallback(ids)
        if not fallback:
            raise
        db.kv_set("crypto:watch_markets",
                  {"updated": now_ms(), "data": fallback, "degraded": "coinmarketcap"})
        print(f"[crypto] CoinGecko down - served {len(fallback)} prices from CoinMarketCap")


def _cmc_markets_fallback(ids):
    """Build a CoinGecko-markets-shaped snapshot from CoinMarketCap so live
    prices survive a CoinGecko outage. Richer fields (sparkline, 1h/7d/30d,
    image) are left empty until CoinGecko recovers."""
    rows = db.conn().execute(
        "SELECT DISTINCT asset_id, symbol, name FROM watchlist WHERE market='crypto'").fetchall()
    id_meta = {r["asset_id"]: (r["symbol"], r["name"]) for r in rows}
    symbols = [id_meta[i][0] for i in ids if i in id_meta and id_meta[i][0]]
    q = coinmarketcap.quotes_by_symbol(symbols)
    if not q:
        return None
    out = []
    for i in ids:
        sym, nm = id_meta.get(i, (None, None))
        c = q.get((sym or "").upper())
        if not c:
            continue
        out.append({
            "id": i, "symbol": (sym or "").lower(), "name": c.get("name") or nm or i,
            "image": None, "market_cap_rank": None,
            "current_price": c["price"], "market_cap": c.get("market_cap"),
            "total_volume": c.get("volume"),
            "price_change_percentage_24h_in_currency": c.get("pct_24h"),
            "price_change_percentage_1h_in_currency": None,
            "price_change_percentage_7d_in_currency": None,
            "price_change_percentage_30d_in_currency": None,
            "high_24h": None, "low_24h": None,
            "sparkline_in_7d": {"price": []},
        })
    return out or None


def crypto_fetch_top100():
    data = coingecko.get("/coins/markets", {
        "vs_currency": "usd", "order": "market_cap_desc", "per_page": 100,
        "page": 1, "price_change_percentage": "1h,24h,7d"})
    slim = [{"id": m["id"], "symbol": m["symbol"], "name": m["name"],
             "image": m.get("image"), "market_cap_rank": m.get("market_cap_rank"),
             "current_price": m.get("current_price"), "market_cap": m.get("market_cap"),
             "total_volume": m.get("total_volume"),
             "chg_1h": m.get("price_change_percentage_1h_in_currency"),
             "chg_24h": m.get("price_change_percentage_24h_in_currency"),
             "chg_7d": m.get("price_change_percentage_7d_in_currency")} for m in data]
    db.kv_set("crypto:top100", {"updated": now_ms(), "data": slim})


def crypto_fetch_global():
    data = coingecko.get("/global").get("data", {})
    db.kv_set("crypto:global", {"updated": now_ms(), "data": data})


def crypto_fetch_fng():
    r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=20,
                     headers={"User-Agent": "Mozilla/5.0 asset-tracker/1.0"})
    r.raise_for_status()
    data = r.json().get("data") or []
    if data:
        db.kv_set("crypto:fng", {
            "updated": now_ms(), "value": int(data[0]["value"]),
            "label": data[0]["value_classification"],
            "yesterday": int(data[1]["value"]) if len(data) > 1 else None})


def fetch_fx():
    """USD -> PHP rate for the display-currency switch (two free sources)."""
    rate = None
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=20)
        rate = (r.json().get("rates") or {}).get("PHP")
    except Exception:
        pass
    if not rate:
        try:
            r = requests.get("https://api.frankfurter.app/latest?from=USD&to=PHP", timeout=20)
            rate = (r.json().get("rates") or {}).get("PHP")
        except Exception:
            pass
    if rate:
        db.kv_set("fx:usdphp", {"rate": float(rate), "updated": now_ms()})


def crypto_history_tick():
    ids = tracked_ids_all_users("crypto")
    if not ids:
        return
    fetched = db.kv_get("crypto:history_fetched", {})
    stalest = min(ids, key=lambda i: fetched.get(i, 0))
    if time.time() - fetched.get(stalest, 0) < config.HISTORY_REFRESH_MINUTES["crypto"] * 60:
        return
    data = coingecko.get(f"/coins/{stalest}/market_chart",
                         {"vs_currency": "usd", "days": config.HISTORY_DAYS})
    rows = [("crypto", stalest, int(ts // 3600000 * 3600000), float(p))
            for ts, p in data.get("prices", []) if p is not None]
    c = db.conn()
    c.executemany("INSERT INTO price_history VALUES (%s,%s,%s,%s)"
                  " ON CONFLICT (market, asset_id, ts) DO UPDATE SET price=EXCLUDED.price",
                  rows)
    c.execute("DELETE FROM price_history WHERE ts < %s",
              (now_ms() - config.HISTORY_KEEP_DAYS * 86400000,))
    fetched[stalest] = time.time()
    db.kv_set("crypto:history_fetched", fetched)
    recompute_signals("crypto")


def _pse_open():
    n = datetime.now()  # server clock is Asia/Manila (TZ env var on Render)
    return n.weekday() < 5 and (9, 0) <= (n.hour, n.minute) <= (15, 30)


def pse_sync_directory_if_needed():
    n = db.conn().execute("SELECT COUNT(*) n FROM pse_companies").fetchone()["n"]
    last = db.kv_get("pse:directory_synced", 0)
    if n > 0 and now_ms() - last < config.INTERVALS["pse"]["directory"] * 1000:
        return
    companies = pse_data.fetch_directory()
    if not companies:
        return
    c = db.conn()
    for co in companies:
        c.execute("""INSERT INTO pse_companies VALUES (%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (symbol) DO UPDATE SET cmpy_id=EXCLUDED.cmpy_id,
                     security_id=EXCLUDED.security_id, name=EXCLUDED.name,
                     sector=EXCLUDED.sector, updated=EXCLUDED.updated""",
                  (co["symbol"], co["cmpy_id"], co["security_id"], co["name"],
                   co.get("sector"), now_ms()))
        c.execute("INSERT INTO watchlist VALUES (0,'pse',%s,%s,%s,%s)"
                  " ON CONFLICT DO NOTHING",
                  (co["symbol"], co["symbol"], co["name"], db.now_iso()))
    db.kv_set("pse:directory_synced", now_ms())
    print(f"[pse] directory synced: {len(companies)} companies")


def pse_fetch_quotes():
    quotes, as_of = pse_data.fetch_quotes()
    db.kv_set("pse:quotes", {"updated": now_ms(), "data": quotes, "as_of": as_of})
    if _pse_open():
        hour = now_ms() // 3600000 * 3600000
        c = db.conn()
        known = {r["symbol"] for r in c.execute("SELECT symbol FROM pse_companies").fetchall()}
        c.executemany("INSERT INTO price_history VALUES ('pse',%s,%s,%s)"
                      " ON CONFLICT (market, asset_id, ts) DO UPDATE SET price=EXCLUDED.price",
                      [(s, hour, q["price"]) for s, q in quotes.items()
                       if s in known and q.get("price")])


def pse_fundamentals_tick():
    row = db.conn().execute("""
        SELECT p.symbol, p.cmpy_id, COALESCE(f.updated, 0) AS upd
        FROM pse_companies p LEFT JOIN fundamentals f
          ON f.market='pse' AND f.asset_id = p.symbol
        ORDER BY upd ASC LIMIT 1""").fetchone()
    if not row or now_ms() - row["upd"] < config.FUNDAMENTALS_REFRESH_DAYS * 86400000:
        return
    sd = pse_data.fetch_stock_data(row["cmpy_id"])
    eps = sd["price"] / sd["pe"] if sd.get("pe") and sd.get("price") and sd["pe"] > 0 else None
    db.set_fundamentals("pse", row["symbol"], pe=sd.get("pe"),
                        sector_pe=sd.get("sector_pe"), wk52_high=sd.get("wk52_high"),
                        wk52_low=sd.get("wk52_low"), book_value=sd.get("book_value"),
                        eps=eps, updated=now_ms())


def pse_backfill_tick():
    done = db.kv_get("pse:backfilled", {})
    rows = db.conn().execute(
        "SELECT symbol, cmpy_id, security_id FROM pse_companies ORDER BY symbol").fetchall()
    todo = [r for r in rows if r["symbol"] not in done]
    if not todo:
        return
    held = {r["asset_id"] for r in db.conn().execute(
        "SELECT DISTINCT asset_id FROM transactions WHERE market='pse'").fetchall()}
    todo.sort(key=lambda r: (r["symbol"] not in held, r["symbol"]))
    r = todo[0]
    try:
        pts = pse_data.fetch_chart(r["cmpy_id"], r["security_id"]) if r["security_id"] else []
    except Exception as e:
        print(f"[pse] backfill {r['symbol']}: {e}")
        pts = []
    if pts:
        db.conn().executemany(
            "INSERT INTO price_history VALUES ('pse',%s,%s,%s)"
            " ON CONFLICT (market, asset_id, ts) DO UPDATE SET price=EXCLUDED.price",
            [(r["symbol"], ts, p) for ts, p in pts])
    done[r["symbol"]] = len(pts)
    db.kv_set("pse:backfilled", done)


def pse_fetch_dividends():
    decls = pse_data.fetch_dividends(pages=5)
    if not decls:
        return
    by_norm = {pse_data.norm_name(r["name"]): r["symbol"] for r in db.conn().execute(
        "SELECT symbol, name FROM pse_companies").fetchall()}
    quotes = db.kv_get("pse:quotes", {}).get("data", {})
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = {}
    seen = set()
    for d in decls:
        if "preferred" in (d.get("security") or "").lower():
            continue
        symb = by_norm.get(pse_data.norm_name(d["company"]))
        if not symb or (d["ex_date"] is not None and d["ex_date"] < today):
            continue
        key = (symb, d.get("security"), d["rate_raw"], d["ex_date"])
        if key in seen:
            continue
        seen.add(key)
        u = upcoming.setdefault(symb, {"cash": 0.0, "rates": [], "ex": None,
                                       "rec": None, "pay": None})
        if "cash" in (d["div_type"] or "").lower() and d["rate"]:
            u["cash"] += d["rate"]
        u["rates"].append(d["rate_raw"] + (" (" + d["div_type"] + ")" if d["div_type"] else ""))
        for k, v in (("ex", d["ex_date"]), ("rec", d["record_date"]), ("pay", d["pay_date"])):
            if v and (u[k] is None or v < u[k]):
                u[k] = v
    c = db.conn()
    c.execute("""UPDATE fundamentals SET div_ps=NULL, div_yield=NULL, div_rate=NULL,
                 div_ex_date=NULL, div_record_date=NULL, div_pay_date=NULL
                 WHERE market='pse'""")
    for symb, u in upcoming.items():
        price = (quotes.get(symb) or {}).get("price")
        div_ps = u["cash"] or None
        div_yield = (div_ps / price * 100) if div_ps and price else None
        if div_yield is not None and div_yield > 50:
            div_ps, div_yield = None, None
        db.set_fundamentals("pse", symb, div_ps=div_ps, div_yield=div_yield,
                            div_rate="; ".join(u["rates"])[:200],
                            div_ex_date=u["ex"] or "TBA",
                            div_record_date=u["rec"], div_pay_date=u["pay"])
    db.kv_set("pse:dividends_updated", now_ms())


def global_fetch_quotes():
    data = {}
    for symb in tracked_ids_all_users("global"):
        try:
            data[symb] = global_data.quote(symb)
        except Exception as e:
            print(f"[global] quote {symb}: {e}")
    if not data:
        return
    db.kv_set("global:quotes", {"updated": now_ms(), "data": data})
    hour = now_ms() // 3600000 * 3600000
    db.conn().executemany(
        "INSERT INTO price_history VALUES ('global',%s,%s,%s)"
        " ON CONFLICT (market, asset_id, ts) DO UPDATE SET price=EXCLUDED.price",
        [(s, hour, q["price"]) for s, q in data.items() if q.get("price")])
    profiles = db.kv_get("global:profiles", {})
    missing = [s for s in data if s not in profiles]
    for symb in missing[:3]:
        profiles[symb] = global_data.profile(symb)
    if missing:
        db.kv_set("global:profiles", profiles)


def global_history_tick():
    ids = tracked_ids_all_users("global")
    if not ids:
        return
    fetched = db.kv_get("global:history_fetched", {})
    stalest = min(ids, key=lambda i: fetched.get(i, 0))
    if time.time() - fetched.get(stalest, 0) < config.HISTORY_REFRESH_MINUTES["global"] * 60:
        return
    try:
        pts = global_data.yahoo_history(stalest, "1h", "60d")
    except Exception as e:
        print(f"[global] history {stalest}: {e}")
        pts = []
    if pts:
        db.conn().executemany(
            "INSERT INTO price_history VALUES ('global',%s,%s,%s)"
            " ON CONFLICT (market, asset_id, ts) DO UPDATE SET price=EXCLUDED.price",
            [(stalest, ts, p) for ts, p in pts])
    fetched[stalest] = time.time()
    db.kv_set("global:history_fetched", fetched)
    recompute_signals("global")


def global_metrics_tick():
    ids = tracked_ids_all_users("global")
    if not ids:
        return
    fund = db.get_fundamentals("global")
    stalest = min(ids, key=lambda i: (fund.get(i) or {}).get("updated") or 0)
    upd = (fund.get(stalest) or {}).get("updated") or 0
    if now_ms() - upd < config.METRICS_REFRESH_HOURS * 3600000:
        return
    try:
        m = global_data.metrics(stalest)
    except Exception as e:
        print(f"[global] metrics {stalest}: {e}")
        db.set_fundamentals("global", stalest,
                            updated=now_ms() - (config.METRICS_REFRESH_HOURS - 1) * 3600000)
        return
    db.set_fundamentals("global", stalest, updated=now_ms(), **m)


def global_fetch_indices():
    out = {}
    for symb, label in (("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones")):
        try:
            q = global_data.index_quote(symb)
            out[label] = {"price": q.get("price"), "chg_pct": q.get("chg_pct")}
        except Exception as e:
            print(f"[global] index {symb}: {e}")
    if out:
        db.kv_set("global:indices", {"updated": now_ms(), "data": out})


def fetch_news(market):
    items = news.fetch_all(config.NEWS_FEEDS[market])
    if not items:
        return
    c = db.conn()
    c.executemany(
        f"INSERT INTO news VALUES ('{market}',%(link)s,%(source)s,%(title)s,"
        f"%(published)s,%(summary)s) ON CONFLICT (market, link) DO NOTHING", items)
    c.execute("""DELETE FROM news WHERE market=%s AND link NOT IN
                 (SELECT link FROM news WHERE market=%s ORDER BY published DESC LIMIT 400)""",
              (market, market))
    db.kv_set(f"{market}:news_updated", now_ms())


def recompute_signals(market):
    pm, _ = price_map(market)
    out = {}
    for aid in tracked_ids_all_users(market):
        rows = db.conn().execute(
            "SELECT price FROM price_history WHERE market=%s AND asset_id=%s ORDER BY ts",
            (market, aid)).fetchall()
        closes = [r["price"] for r in rows]
        out[aid] = sig.compute(closes, (pm.get(aid) or {}).get("chg_24h"))
    db.kv_set(f"{market}:signals", {"updated": now_ms(), "data": out})


# ------------------------------------------------------------------ scheduler

def scheduler():
    iv = config.INTERVALS
    jobs = [
        [lambda: iv["crypto"]["quotes"], 0, crypto_fetch_markets],
        [lambda: iv["crypto"]["top100"], 0, crypto_fetch_top100],
        [lambda: iv["crypto"]["global"], 0, crypto_fetch_global],
        [lambda: 4 * 3600, 0, crypto_fetch_fng],
        [lambda: 6 * 3600, 0, fetch_fx],
        [lambda: iv["crypto"]["history"], 0, crypto_history_tick],
        [lambda: iv["crypto"]["news"], 0, lambda: fetch_news("crypto")],
        [lambda: iv["crypto"]["signals"], 0, lambda: recompute_signals("crypto")],
        [lambda: iv["pse"]["directory"], 0, pse_sync_directory_if_needed],
        [lambda: iv["pse"]["quotes"] if _pse_open() else 1800, 0, pse_fetch_quotes],
        [lambda: iv["pse"]["fundamentals"], 0, pse_fundamentals_tick],
        [lambda: 30, 0, pse_backfill_tick],
        [lambda: iv["pse"]["dividends"], 0, pse_fetch_dividends],
        [lambda: iv["pse"]["news"], 0, lambda: fetch_news("pse")],
        [lambda: iv["pse"]["signals"], 0, lambda: recompute_signals("pse")],
        [lambda: iv["global"]["quotes"], 0, global_fetch_quotes],
        [lambda: iv["global"]["history"], 0, global_history_tick],
        [lambda: iv["global"]["metrics"], 0, global_metrics_tick],
        [lambda: iv["global"]["indices"], 0, global_fetch_indices],
        [lambda: iv["global"]["news"], 0, lambda: fetch_news("global")],
    ]
    # stagger the first runs: on 0.1-CPU free instances a boot-time stampede
    # of collectors starves the web server and the router marks it down
    for i, job in enumerate(jobs):
        job[1] = time.time() + 20 + i * 12
    while True:
        for job in jobs:
            interval_fn, next_run, fn = job
            if time.time() >= next_run:
                try:
                    fn()
                except Exception:
                    print(f"[scheduler] {getattr(fn, '__name__', 'job')} failed:")
                    traceback.print_exc()
                job[1] = time.time() + interval_fn()
                time.sleep(1)  # always yield to request threads between jobs
        time.sleep(2)


_scheduler_started = False
_scheduler_guard = threading.Lock()


def ensure_scheduler():
    global _scheduler_started
    if os.environ.get("RUN_SCHEDULER", "1") != "1":
        return
    with _scheduler_guard:
        if not _scheduler_started:
            _scheduler_started = True
            threading.Thread(target=scheduler, daemon=True).start()
            print("[scheduler] shared data collector started")


# --------------------------------------------------------------- portfolio

def portfolio_state(market, user):
    txs = db.conn().execute(
        "SELECT * FROM transactions WHERE market=%s AND user_id=%s ORDER BY ts, id",
        (market, user)).fetchall()
    pm, updated = price_map(market)
    w = db.conn().execute("SELECT budget FROM wallets WHERE user_id=%s AND market=%s",
                          (user, market)).fetchone()
    budget = w["budget"] if w else None
    # money currently tied up = trade values + every fee paid (fees are cash out)
    net_flow = sum((t["value"] or 0) + (t["fee"] or 0) for t in txs)
    tot_fees = sum((t["fee"] or 0) for t in txs)
    pos = {}
    for t in txs:
        p = pos.setdefault(t["asset_id"], {
            "asset_id": t["asset_id"], "name": t["name"] or t["asset_id"],
            "qty": 0.0, "cost": 0.0, "realized": 0.0,
            "bought_usd": 0.0, "sold_usd": 0.0})
        q = t["quantity"]
        fee = t["fee"] or 0
        val = abs(t["value"] if t["value"] else q * t["price"])
        if q >= 0:
            p["qty"] += q
            p["cost"] += val + fee          # buy fees fold into the cost basis
            p["bought_usd"] += val + fee
        else:
            sell_qty = -q
            avg = p["cost"] / p["qty"] if p["qty"] > 1e-12 else t["price"]
            proceeds = val - fee            # sell fees reduce what you receive
            p["realized"] += proceeds - avg * sell_qty
            p["cost"] -= avg * sell_qty
            p["qty"] -= sell_qty
            p["sold_usd"] += proceeds
            if p["qty"] <= 1e-9:
                p["qty"], p["cost"] = 0.0, 0.0
    holdings, closed = [], []
    tot_value = tot_cost = tot_realized = tot_change24 = 0.0
    for aid, p in pos.items():
        m = pm.get(aid) or {}
        tot_realized += p["realized"]
        if p["qty"] <= 1e-9:
            if abs(p["realized"]) > 1e-9:
                closed.append({**p, "symbol": m.get("symbol", "")})
            continue
        price = m.get("price")
        chg24 = m.get("chg_24h")
        value = price * p["qty"] if price is not None else None
        holdings.append({**p, "symbol": m.get("symbol", ""), "image": m.get("image"),
                         "price": price, "avg_buy": p["cost"] / p["qty"], "value": value,
                         "chg_24h": chg24,
                         "unrealized": (value - p["cost"]) if value is not None else None,
                         "unrealized_pct": ((value - p["cost"]) / p["cost"] * 100)
                                           if value is not None and p["cost"] > 0 else None})
        if value is not None:
            tot_value += value
            tot_cost += p["cost"]
            if chg24 is not None:
                tot_change24 += value - value / (1 + chg24 / 100)
    holdings.sort(key=lambda h: -(h["value"] or 0))
    closed.sort(key=lambda h: -abs(h["realized"]))
    cash = (budget - net_flow) if budget is not None else None
    return {
        "updated": updated, "holdings": holdings, "closed": closed,
        "summary": {
            "budget": budget, "cash": cash,
            "total_worth": (tot_value + cash) if cash is not None else None,
            "budget_return_pct": ((tot_value + cash - budget) / budget * 100)
                                 if cash is not None and budget else None,
            "value": tot_value, "cost": tot_cost,
            "unrealized": tot_value - tot_cost,
            "unrealized_pct": ((tot_value - tot_cost) / tot_cost * 100) if tot_cost > 0 else 0,
            "realized": tot_realized,
            "fees": tot_fees,
            "change_24h_usd": tot_change24,
            "change_24h_pct": (tot_change24 / (tot_value - tot_change24) * 100)
                              if tot_value - tot_change24 > 0 else 0,
        },
    }


def portfolio_history(market, user, hours):
    txs = db.conn().execute(
        "SELECT * FROM transactions WHERE market=%s AND user_id=%s ORDER BY ts, id",
        (market, user)).fetchall()
    if not txs:
        return []
    tx_list = [(db.parse_tx_ts(t["ts"]), t["asset_id"], t["quantity"],
                t["value"] if t["value"] else t["quantity"] * t["price"]) for t in txs]
    assets = sorted({t[1] for t in tx_list})
    end = now_ms() // 3600000 * 3600000
    start = end - hours * 3600000
    prices = {}
    for aid in assets:
        rows = db.conn().execute(
            "SELECT ts, price FROM price_history WHERE market=%s AND asset_id=%s"
            " AND ts>=%s ORDER BY ts", (market, aid, start - 96 * 3600000)).fetchall()
        prices[aid] = [(r["ts"], r["price"]) for r in rows]
    points = []
    idx = {aid: 0 for aid in assets}
    last_price = {aid: None for aid in assets}
    for hpoint in range(start, end + 1, 3600000):
        qty = {aid: 0.0 for aid in assets}
        invested = 0.0
        for ts, aid, q, val in tx_list:
            if ts <= hpoint:
                qty[aid] += q
                invested += val
        total = 0.0
        have_any = False
        for aid in assets:
            series = prices[aid]
            i = idx[aid]
            while i < len(series) and series[i][0] <= hpoint:
                last_price[aid] = series[i][1]
                i += 1
            idx[aid] = i
            if qty[aid] > 1e-9 and last_price[aid] is not None:
                total += qty[aid] * last_price[aid]
                have_any = True
        if have_any:
            points.append([hpoint, round(total, 2), round(invested, 2)])
    return points


# ----------------------------------------------------------- per-user advisor

BUY_ACTIONS = ("BUY", "BUY MORE")
SELL_ACTIONS = ("TRIM", "SELL PART", "TAKE PROFIT")
DISMISS_HOURS = 24


def _direction(action):
    if action in BUY_ACTIONS:
        return "buy"
    if action in SELL_ACTIONS:
        return "sell"
    return None


def dismiss_suggestion(user, market, asset_id, action):
    c = db.conn()
    c.execute("INSERT INTO advisor_dismissed VALUES (%s,%s,%s,%s,%s)"
              " ON CONFLICT (user_id, market, asset_id) DO UPDATE SET"
              " action=EXCLUDED.action, ts=EXCLUDED.ts",
              (user, market, asset_id, action, now_ms()))
    c.execute("DELETE FROM advisor_dismissed WHERE ts < %s",
              (now_ms() - 2 * DISMISS_HOURS * 3600000,))


def dismissals(user, market):
    cutoff = now_ms() - DISMISS_HOURS * 3600000
    return {r["asset_id"]: r["action"] for r in db.conn().execute(
        "SELECT asset_id, action FROM advisor_dismissed"
        " WHERE user_id=%s AND market=%s AND ts>=%s", (user, market, cutoff)).fetchall()}


def market_session(market):
    """(is_open, human 'reopens at' text). Crypto never closes.
    PSE: 9:30-12:00 & 13:00-15:00 Manila, Mon-Fri (holidays not modeled).
    Global: US session 9:30-16:00 Eastern, shown in Manila time."""
    from datetime import timedelta, timezone as _tz
    if market == "crypto":
        return True, None
    now = datetime.now()  # Manila clock (TZ=Asia/Manila)
    if market == "pse":
        wd, t = now.weekday(), (now.hour, now.minute)
        if wd < 5 and ((9, 30) <= t < (12, 0) or (13, 0) <= t < (15, 0)):
            return True, None
        if wd < 5 and t < (9, 30):
            return False, "today at 9:30 AM"
        if wd < 5 and (12, 0) <= t < (13, 0):
            return False, "at 1:00 PM, after the lunch break"
        nxt = now + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        label = "tomorrow" if (nxt.date() - now.date()).days == 1 else nxt.strftime("%A")
        return False, f"{label} at 9:30 AM"
    # global: US-listed names, NYSE/Nasdaq hours
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
        have_tz = True
    except Exception:
        off = -4 if 3 <= now.month <= 10 else -5  # rough EDT/EST
        et = datetime.now(_tz.utc) + timedelta(hours=off)
        have_tz = False
    wd, t = et.weekday(), (et.hour, et.minute)
    if wd < 5 and (9, 30) <= t < (16, 0):
        return True, None
    nxt = et
    if wd >= 5 or t >= (16, 0):
        nxt = et + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    open_et = nxt.replace(hour=9, minute=30, second=0, microsecond=0)
    if have_tz:
        try:
            from zoneinfo import ZoneInfo
            manila = open_et.astimezone(ZoneInfo("Asia/Manila"))
            return False, manila.strftime("%A %I:%M %p").replace(" 0", " ") + " Manila time"
        except Exception:
            pass
    return False, "around 9:30-10:30 PM Manila time"


def _market_line(market):
    if market == "crypto":
        g = db.kv_get("crypto:global", {}).get("data", {})
        chg = g.get("market_cap_change_percentage_24h_usd")
        if chg is None:
            return None
        d = "up" if chg >= 0 else "down"
        line = f"the crypto market is {d} {abs(chg):.1f}% in the last 24h"
        fng = db.kv_get("crypto:fng")
        if fng:
            line += f", with Fear & Greed at {fng['value']} ({fng['label'].lower()})"
        return line
    if market == "pse":
        quotes = db.kv_get("pse:quotes", {}).get("data", {})
        traded = [q for q in quotes.values() if (q.get("volume") or 0) > 0]
        up = sum(1 for q in traded if (q.get("chg_pct") or 0) > 0)
        down = sum(1 for q in traded if (q.get("chg_pct") or 0) < 0)
        if not traded:
            return None
        mood = "positive" if up > down * 1.3 else "negative" if down > up * 1.3 else "mixed"
        return f"the PSE is {mood} today ({up} advancers vs {down} decliners)"
    idx = db.kv_get("global:indices", {}).get("data", {})
    sp = idx.get("S&P 500")
    if not sp or sp.get("chg_pct") is None:
        return None
    d = "up" if sp["chg_pct"] >= 0 else "down"
    return f"the S&P 500 is {d} {abs(sp['chg_pct']):.1f}%"


def get_advisor(market, user, force=False):
    """Per-user advisor, cached a few minutes."""
    key = f"advisor:{market}:{user}"
    cached = db.kv_get(key)
    if cached and not force and now_ms() - cached.get("updated", 0) < ADVISOR_CACHE_SECONDS * 1000:
        return cached
    with _advisor_lock:
        pm, _ = price_map(market)
        assets = []
        seen = set()
        owner = 0 if market == "pse" else user
        for r in db.conn().execute(
                "SELECT * FROM watchlist WHERE market=%s AND user_id=%s ORDER BY asset_id",
                (market, owner)).fetchall():
            m = pm.get(r["asset_id"], {})
            seen.add(r["asset_id"])
            assets.append({"asset_id": r["asset_id"],
                           "symbol": (m.get("symbol") or r["symbol"] or "").upper(),
                           "name": m.get("name") or r["name"] or r["asset_id"],
                           "image": m.get("image"), "price": m.get("price"),
                           "chg_24h": m.get("chg_24h"),
                           "chg_7d": (m.get("_raw") or {}).get("price_change_percentage_7d_in_currency")})
        for r in db.conn().execute(
                "SELECT DISTINCT asset_id, name FROM transactions"
                " WHERE market=%s AND user_id=%s", (market, user)).fetchall():
            if r["asset_id"] in seen:
                continue
            m = pm.get(r["asset_id"], {})
            assets.append({"asset_id": r["asset_id"],
                           "symbol": (m.get("symbol") or r["asset_id"]).upper(),
                           "name": m.get("name") or r["name"] or r["asset_id"],
                           "image": m.get("image"), "price": m.get("price"),
                           "chg_24h": m.get("chg_24h"),
                           "chg_7d": (m.get("_raw") or {}).get("price_change_percentage_7d_in_currency")})
        signals_data = db.kv_get(f"{market}:signals", {}).get("data", {})
        port = portfolio_state(market, user)
        since = now_ms() - 72 * 3600000
        news_rows = [dict(r) for r in db.conn().execute(
            "SELECT * FROM news WHERE market=%s AND published>=%s", (market, since)).fetchall()]
        fund = db.get_fundamentals(market) if market != "crypto" else None
        is_open, next_open = market_session(market)
        srow = db.conn().execute(
            "SELECT trading_style FROM users WHERE id=%s", (user,)).fetchone()
        style = (srow or {}).get("trading_style") or "swing"
        result = adv.build(assets, signals_data, port, news_rows,
                           {"line": _market_line(market), "open": is_open,
                            "next_open": next_open}, now_ms(),
                           currency=config.CURRENCY[market], fundamentals=fund,
                           max_ideas=config.ADVISOR_MAX_IDEAS[market], style=style)
        result["updated"] = now_ms()
        result["market_open"] = is_open
        result["next_open"] = next_open
        db.kv_set(key, result)
        return result


def _invalidate_advisor(market, user):
    db.conn().execute("DELETE FROM kv WHERE key=%s", (f"advisor:{market}:{user}",))


# --------------------------------------------------------------------- routes

VALID = set(config.MARKETS)


def _check(market):
    if market not in VALID:
        from flask import abort
        abort(404)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/<market>/portfolio")
def api_portfolio(market):
    _check(market)
    return jsonify(portfolio_state(market, uid()))


@app.get("/api/<market>/portfolio_history")
def api_portfolio_history(market):
    _check(market)
    hours = min(int(request.args.get("hours", 168)), 24 * config.HISTORY_KEEP_DAYS)
    return jsonify({"points": portfolio_history(market, uid(), hours)})


@app.get("/api/<market>/transactions")
def api_transactions(market):
    _check(market)
    rows = db.conn().execute(
        "SELECT * FROM transactions WHERE market=%s AND user_id=%s"
        " ORDER BY ts DESC, id DESC", (market, uid())).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/<market>/transactions")
def api_add_transaction(market):
    _check(market)
    d = request.get_json(force=True)
    asset_id = (d.get("asset_id") or "").strip()
    asset_id = asset_id.lower() if market == "crypto" else asset_id.upper()
    side = d.get("side", "buy").lower()
    price = float(d.get("price") or 0)
    qty = float(d.get("quantity") or 0)
    value = float(d.get("value") or 0)
    fee = max(0.0, float(d.get("fee") or 0))
    ts = (d.get("ts") or db.now_iso()).replace("T", " ")[:16]
    if not asset_id or price <= 0:
        return jsonify({"error": "asset and a positive price are required"}), 400
    if qty <= 0 and value > 0:
        qty = value / price
    if qty <= 0:
        return jsonify({"error": "enter a quantity or a total amount"}), 400
    pm, _ = price_map(market)
    owner = 0 if market == "pse" else uid()
    wrow = db.conn().execute(
        "SELECT name FROM watchlist WHERE market=%s AND asset_id=%s AND user_id=%s",
        (market, asset_id, owner)).fetchone()
    name = (pm.get(asset_id) or {}).get("name") or \
           (wrow["name"] if wrow and wrow["name"] else asset_id)
    signed_qty = qty if side == "buy" else -qty
    c = db.conn()
    c.execute(
        "INSERT INTO transactions (user_id, market, ts, asset_id, quantity, price, value, type, name, fee)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (uid(), market, ts, asset_id, signed_qty, price, signed_qty * price,
         "Buy" if side == "buy" else "Sell", name, fee))
    if not wrow and market != "pse":
        m = pm.get(asset_id, {})
        c.execute("INSERT INTO watchlist VALUES (%s,%s,%s,%s,%s,%s)"
                  " ON CONFLICT DO NOTHING",
                  (uid(), market, asset_id, (m.get("symbol") or asset_id).upper(),
                   m.get("name") or name, db.now_iso()))
    adv_snap = db.kv_get(f"advisor:{market}:{uid()}", {})
    for r in adv_snap.get("recommendations", []):
        if r.get("asset_id") == asset_id and _direction(r.get("action")) == side:
            dismiss_suggestion(uid(), market, asset_id, r["action"])
            break
    _invalidate_advisor(market, uid())
    return jsonify({"ok": True})


@app.put("/api/<market>/transactions/<int:tx_id>")
def api_edit_transaction(market, tx_id):
    _check(market)
    row = db.conn().execute(
        "SELECT * FROM transactions WHERE market=%s AND id=%s AND user_id=%s",
        (market, tx_id, uid())).fetchone()
    if not row:
        return jsonify({"error": "transaction not found"}), 404
    d = request.get_json(force=True)
    price = float(d.get("price") or 0)
    qty = float(d.get("quantity") or 0)
    value = float(d.get("value") or 0)
    fee = max(0.0, float(d.get("fee") or 0))
    ts = (d.get("ts") or row["ts"]).replace("T", " ")[:16]
    if price <= 0:
        return jsonify({"error": "a positive price is required"}), 400
    if qty <= 0 and value > 0:
        qty = value / price
    if qty <= 0:
        return jsonify({"error": "enter a quantity or a total amount"}), 400
    sign = 1 if row["quantity"] >= 0 else -1
    db.conn().execute(
        "UPDATE transactions SET ts=%s, quantity=%s, price=%s, value=%s, fee=%s"
        " WHERE id=%s AND user_id=%s",
        (ts, sign * qty, price, sign * qty * price, fee, tx_id, uid()))
    _invalidate_advisor(market, uid())
    return jsonify({"ok": True})


@app.delete("/api/<market>/transactions/<int:tx_id>")
def api_delete_transaction(market, tx_id):
    _check(market)
    db.conn().execute("DELETE FROM transactions WHERE market=%s AND id=%s AND user_id=%s",
                      (market, tx_id, uid()))
    _invalidate_advisor(market, uid())
    return jsonify({"ok": True})


@app.post("/api/<market>/wallet")
def api_wallet(market):
    _check(market)
    d = request.get_json(force=True)
    raw = d.get("budget")
    if raw in (None, ""):
        budget = None
    else:
        try:
            budget = float(raw)
        except (TypeError, ValueError):
            return jsonify({"error": "enter a plain number, e.g. 5000"}), 400
        if budget < 0:
            return jsonify({"error": "the budget can't be negative"}), 400
    db.conn().execute("INSERT INTO wallets VALUES (%s,%s,%s)"
                      " ON CONFLICT (user_id, market) DO UPDATE SET budget=EXCLUDED.budget",
                      (uid(), market, budget))
    _invalidate_advisor(market, uid())
    return jsonify({"ok": True})


@app.get("/api/<market>/watchlist")
def api_watchlist(market):
    _check(market)
    pm, updated = price_map(market)
    signals_data = db.kv_get(f"{market}:signals", {}).get("data", {})
    fund = db.get_fundamentals(market) if market != "crypto" else {}
    sparks = {}
    if market != "crypto":
        since = now_ms() - 7 * 86400000
        for r in db.conn().execute(
                "SELECT asset_id, price FROM price_history WHERE market=%s AND ts>=%s"
                " ORDER BY asset_id, ts", (market, since)).fetchall():
            sparks.setdefault(r["asset_id"], []).append(r["price"])
    owner = 0 if market == "pse" else uid()
    out = []
    for r in db.conn().execute(
            "SELECT * FROM watchlist WHERE market=%s AND user_id=%s ORDER BY asset_id",
            (market, owner)).fetchall():
        aid = r["asset_id"]
        m = pm.get(aid, {})
        raw = m.get("_raw", {})
        f = fund.get(aid) or {}
        spark = ((raw.get("sparkline_in_7d") or {}).get("price") or [])[::4] \
            if market == "crypto" else sparks.get(aid, [])
        if len(spark) > 45:
            spark = spark[::max(1, len(spark) // 45)]
        out.append({
            "asset_id": aid,
            "symbol": (m.get("symbol") or r["symbol"] or "").upper(),
            "name": m.get("name") or r["name"] or aid,
            "image": m.get("image"), "price": m.get("price"),
            "chg_24h": m.get("chg_24h"),
            "chg_1h": raw.get("price_change_percentage_1h_in_currency"),
            "chg_7d": raw.get("price_change_percentage_7d_in_currency"),
            "chg_30d": raw.get("price_change_percentage_30d_in_currency"),
            "market_cap": raw.get("market_cap"),
            "high_24h": raw.get("high_24h"), "low_24h": raw.get("low_24h"),
            "volume": m.get("volume"), "value_traded": m.get("value_traded"),
            "eps": f.get("eps"), "pe": f.get("pe"),
            "div_ps": f.get("div_ps"), "div_yield": f.get("div_yield"),
            "div_ex_date": f.get("div_ex_date"), "div_rate": f.get("div_rate"),
            "sector": f.get("sector"),
            "sparkline": spark,
            "signal": signals_data.get(aid),
        })
    return jsonify({"updated": updated, "assets": out})


@app.post("/api/<market>/watchlist")
def api_watchlist_add(market):
    _check(market)
    if market == "pse":
        return jsonify({"error": "The PSE watchlist tracks all listed companies automatically."}), 400
    q = (request.get_json(force=True).get("query") or "").strip()
    if not q:
        return jsonify({"error": "empty search"}), 400
    c = db.conn()
    if market == "crypto":
        try:
            res = coingecko.get("/search", {"query": q})
        except Exception as e:
            return jsonify({"error": f"search failed: {e}"}), 502
        coins = res.get("coins") or []
        if not coins:
            return jsonify({"error": f'no coin found for "{q}"'}), 404
        best = coins[0]
        c.execute("INSERT INTO watchlist VALUES (%s,'crypto',%s,%s,%s,%s)"
                  " ON CONFLICT DO NOTHING",
                  (uid(), best["id"], best.get("symbol", "").upper(),
                   best.get("name", best["id"]), db.now_iso()))
        added = {"asset_id": best["id"], "name": best.get("name"),
                 "symbol": best.get("symbol", "").upper()}
    else:
        symb = q.upper()
        try:
            quote = global_data.quote(symb)
            if not quote.get("price"):
                raise RuntimeError("no price")
        except Exception:
            return jsonify({"error": f'"{symb}" not found - use the exchange ticker, e.g. AAPL'}), 404
        prof = global_data.profile(symb)
        c.execute("INSERT INTO watchlist VALUES (%s,'global',%s,%s,%s,%s)"
                  " ON CONFLICT DO NOTHING",
                  (uid(), symb, symb, prof.get("name") or symb, db.now_iso()))
        added = {"asset_id": symb, "name": prof.get("name") or symb, "symbol": symb}
    _invalidate_advisor(market, uid())
    return jsonify({"ok": True, "added": added})


@app.delete("/api/<market>/watchlist/<path:asset_id>")
def api_watchlist_remove(market, asset_id):
    _check(market)
    if market == "pse":
        return jsonify({"error": "PSE companies can't be removed - the list mirrors the exchange."}), 400
    db.conn().execute("DELETE FROM watchlist WHERE market=%s AND asset_id=%s AND user_id=%s",
                      (market, asset_id, uid()))
    _invalidate_advisor(market, uid())
    return jsonify({"ok": True})


@app.get("/api/<market>/market")
def api_market(market):
    _check(market)
    if market == "crypto":
        g = db.kv_get("crypto:global", {})
        top = db.kv_get("crypto:top100", {})
        data = top.get("data", [])
        by24 = sorted((m for m in data if m.get("chg_24h") is not None),
                      key=lambda m: m["chg_24h"])
        gd = g.get("data", {})
        mcap = (gd.get("total_market_cap") or {}).get("usd")
        mcap_chg = gd.get("market_cap_change_percentage_24h_usd")
        btc_dom = (gd.get("market_cap_percentage") or {}).get("btc")
        up = sum(1 for m in data if (m.get("chg_24h") or 0) > 0)
        summary = ""
        if mcap and mcap_chg is not None:
            mood = ("strongly rallying" if mcap_chg > 3 else "moving up" if mcap_chg > 0.5
                    else "flat" if mcap_chg > -0.5 else "pulling back" if mcap_chg > -3
                    else "selling off sharply")
            summary = (f"The crypto market is {mood}: total market cap is "
                       f"${mcap / 1e12:.2f}T ({mcap_chg:+.1f}% in 24h). "
                       f"Bitcoin dominance is {btc_dom:.1f}%. "
                       f"{up} of the top 100 coins are up over the last 24 hours.")
        return jsonify({"kind": "crypto", "global": gd, "top100": data,
                        "gainers": list(reversed(by24[-6:])), "losers": by24[:6],
                        "summary": summary, "updated": top.get("updated"),
                        "fng": db.kv_get("crypto:fng")})
    if market == "pse":
        snap = db.kv_get("pse:quotes", {})
        quotes = snap.get("data", {})
        names = {r["symbol"]: r["name"] for r in db.conn().execute(
            "SELECT symbol, name FROM pse_companies").fetchall()}
        traded = [{"symbol": s, "name": names.get(s, q.get("name")), **q}
                  for s, q in quotes.items() if s in names]
        active = [t for t in traded if (t.get("volume") or 0) > 0]
        up = sum(1 for t in active if (t.get("chg_pct") or 0) > 0)
        down = sum(1 for t in active if (t.get("chg_pct") or 0) < 0)
        flat = len(active) - up - down
        by_chg = sorted((t for t in active if t.get("chg_pct") is not None),
                        key=lambda t: t["chg_pct"])
        by_val = sorted(active, key=lambda t: -(t.get("value") or 0))
        mood = ("broadly positive" if up > down * 1.3 else
                "broadly negative" if down > up * 1.3 else "mixed")
        summary = (f"The Philippine market is {mood} today: {up} advancers, "
                   f"{down} decliners, {flat} unchanged among traded stocks."
                   if active else "Waiting for the first quote update from the PSE.")
        return jsonify({"kind": "pse", "advancers": up, "decliners": down,
                        "unchanged": flat,
                        "gainers": list(reversed(by_chg[-10:])), "losers": by_chg[:10],
                        "most_active": by_val[:10], "summary": summary,
                        "as_of": snap.get("as_of"), "updated": snap.get("updated"),
                        "companies": len(names)})
    idx = db.kv_get("global:indices", {})
    pm, updated = price_map("global")
    mine = set(watch_ids("global", uid()))
    rows = [v for k, v in pm.items() if v.get("chg_24h") is not None and k in mine]
    by_chg = sorted(rows, key=lambda r: r["chg_24h"])
    sp = (idx.get("data") or {}).get("S&P 500") or {}
    summary = ""
    if sp.get("chg_pct") is not None:
        mood = ("rallying" if sp["chg_pct"] > 1 else "up" if sp["chg_pct"] > 0.1
                else "flat" if sp["chg_pct"] > -0.1 else "down" if sp["chg_pct"] > -1
                else "selling off")
        summary = f"US markets are {mood}: S&P 500 {sp['chg_pct']:+.1f}% today."
    return jsonify({"kind": "global", "indices": idx.get("data", {}),
                    "gainers": list(reversed(by_chg[-6:])), "losers": by_chg[:6],
                    "summary": summary, "updated": updated})


@app.get("/api/fx")
def api_fx():
    return jsonify(db.kv_get("fx:usdphp", {}))


@app.get("/api/changelog")
def api_changelog():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CHANGELOG.md")
    try:
        with open(path, encoding="utf-8") as f:
            return jsonify({"markdown": f.read()})
    except OSError:
        return jsonify({"markdown": ""})


@app.get("/api/<market>/advisor")
def api_advisor(market):
    _check(market)
    snap = dict(get_advisor(market, uid()))
    dis = dismissals(uid(), market)
    recs = []
    for r in snap.get("recommendations", []):
        r = dict(r)
        d = _direction(r.get("action"))
        r["dismissed"] = (r.get("asset_id") in dis and d is not None
                          and _direction(dis[r["asset_id"]]) == d)
        recs.append(r)
    snap["recommendations"] = recs
    return jsonify(snap)


@app.post("/api/<market>/advisor/dismiss")
def api_advisor_dismiss(market):
    _check(market)
    d = request.get_json(force=True)
    asset_id = (d.get("asset_id") or "").strip()
    action = (d.get("action") or "").strip()
    if not asset_id or not action:
        return jsonify({"error": "asset_id and action are required"}), 400
    dismiss_suggestion(uid(), market, asset_id, action)
    return jsonify({"ok": True})


@app.get("/api/<market>/signals")
def api_signals(market):
    _check(market)
    return jsonify(db.kv_get(f"{market}:signals", {}))


@app.get("/api/<market>/history/<path:asset_id>")
def api_history(market, asset_id):
    _check(market)
    hours = min(int(request.args.get("hours", 168)), 24 * config.HISTORY_KEEP_DAYS)
    since = now_ms() - hours * 3600000
    rows = db.conn().execute(
        "SELECT ts, price FROM price_history WHERE market=%s AND asset_id=%s AND ts>=%s"
        " ORDER BY ts", (market, asset_id, since)).fetchall()
    return jsonify({"asset_id": asset_id, "points": [[r["ts"], r["price"]] for r in rows]})


@app.get("/api/<market>/news")
def api_news(market):
    _check(market)
    limit = min(int(request.args.get("limit", 120)), 400)
    source = request.args.get("source")
    if source:
        rows = db.conn().execute(
            "SELECT * FROM news WHERE market=%s AND source=%s ORDER BY published DESC LIMIT %s",
            (market, source, limit)).fetchall()
    else:
        rows = db.conn().execute(
            "SELECT * FROM news WHERE market=%s ORDER BY published DESC LIMIT %s",
            (market, limit)).fetchall()
    sources = [r["source"] for r in db.conn().execute(
        "SELECT DISTINCT source FROM news WHERE market=%s ORDER BY source", (market,)).fetchall()]
    return jsonify({"updated": db.kv_get(f"{market}:news_updated"),
                    "sources": sources, "items": [dict(r) for r in rows]})


@app.get("/api/<market>/status")
def api_status(market):
    _check(market)
    c = db.conn()
    if market == "pse":
        quotes_updated = db.kv_get("pse:quotes", {}).get("updated")
        err = pse_data.last_error
    elif market == "global":
        quotes_updated = db.kv_get("global:quotes", {}).get("updated")
        err = global_data.last_error
    else:
        quotes_updated = db.kv_get("crypto:watch_markets", {}).get("updated")
        err = coingecko.last_error
    counts = {"transactions": c.execute(
        "SELECT COUNT(*) n FROM transactions WHERE market=%s AND user_id=%s",
        (market, uid())).fetchone()["n"]}
    return jsonify({"quotes_updated": quotes_updated,
                    "signals_updated": db.kv_get(f"{market}:signals", {}).get("updated"),
                    "news_updated": db.kv_get(f"{market}:news_updated"),
                    "counts": counts, "source_error": err})


# ----------------------------------------------------------------------- boot

db.init()
ensure_scheduler()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8951)), threaded=True)
