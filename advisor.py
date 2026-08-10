"""Portfolio-aware recommendation engine (all markets).

Combines up to four inputs into concrete, sized suggestions:
  1. Technical signals  (signals.py score from stored price history)
  2. News sentiment     (keyword scoring of recent headlines, matched per asset)
  3. Fundamentals       (stocks only: P/E, dividend yield, 52-week position)
  4. Your holdings      (allocation %, unrealized P/L, concentration risk)

Output is a ranked list of actions - TRIM / SELL PART / TAKE PROFIT /
BUY MORE / BUY / WATCH / HOLD - each with a currency-sized amount and the
reasoning spelled out. Automated heuristics, not financial advice.
"""

import datetime
import math
import re
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- sentiment

POSITIVE = {
    "all-time high": 3, "all time high": 3, "record high": 3, "record profit": 3,
    "etf approval": 3, "approves etf": 3, "greenlight": 2, "approval": 2,
    "drops lawsuit": 3, "dismisses lawsuit": 3, "lawsuit dismissed": 3,
    "case dismissed": 2, "settles lawsuit": 2,
    "beats estimates": 3, "beats expectations": 3, "raises guidance": 3,
    "raises dividend": 3, "dividend increase": 3, "special dividend": 2,
    "buyback": 2, "share repurchase": 2, "upgraded": 2, "price target raised": 2,
    "breakout": 2, "bullish": 2, "adoption": 2, "adopts": 2,
    "partnership": 2, "partners with": 2, "inflow": 2, "inflows": 2,
    "institutional demand": 2, "accumulation": 2,
    "rally": 2, "rallies": 2, "rallying": 2, "rallied": 2,
    "surge": 2, "surges": 2, "surged": 2, "surging": 2,
    "soar": 2, "soars": 2, "soared": 2, "soaring": 2,
    "jump": 1, "jumps": 1, "jumped": 1, "climb": 1, "climbs": 1, "climbed": 1,
    "gain": 1, "gains": 1, "rise": 1, "rises": 1, "rebound": 1, "rebounds": 1,
    "recovery": 1, "recovers": 1, "upgrade": 1, "upgrades": 1,
    "launch": 1, "launches": 1, "mainnet": 1, "integration": 1, "integrates": 1,
    "milestone": 1, "outperform": 1, "outperforms": 1, "expansion": 1,
    "record revenue": 2, "profit up": 2, "income rose": 2, "net income up": 2,
}

NEGATIVE = {
    "hack": 3, "hacked": 3, "exploit": 3, "exploited": 3, "stolen": 3,
    "theft": 3, "scam": 3, "rug pull": 3, "fraud": 3,
    "bankrupt": 3, "bankruptcy": 3, "insolvent": 3, "collapse": 3,
    "crash": 3, "crashes": 3, "crashed": 3,
    "misses estimates": 3, "misses expectations": 3, "cuts guidance": 3,
    "profit warning": 3, "cuts dividend": 3, "dividend cut": 3,
    "downgraded": 2, "price target cut": 2, "layoffs": 2, "recall": 2,
    "hacker": 2, "breach": 2, "vulnerability": 2,
    "lawsuit": 2, "sues": 2, "sued": 2,
    "crackdown": 2, "ban": 2, "bans": 2, "banned": 2,
    "plunge": 2, "plunges": 2, "plunged": 2, "plummet": 2, "plummets": 2,
    "tumble": 2, "tumbles": 2, "slump": 2, "slumps": 2,
    "dump": 2, "selloff": 2, "sell-off": 2, "bearish": 2,
    "liquidation": 2, "liquidations": 2, "outflow": 2, "outflows": 2,
    "delist": 2, "delisted": 2, "halt": 2, "halted": 2, "outage": 2,
    "downturn": 2, "loss widens": 2, "net loss": 2, "profit down": 2,
    "investigation": 1, "fear": 1, "fears": 1,
}
# Deliberately absent: ambiguous words like "charges", "drop(s)", "fall(s)",
# "sink(s)", "probe", "correction" - they invert meaning too often in
# headlines ("Bitcoin charges toward $110K", "launching this fall").

_LEX = None


def _lexicon():
    global _LEX
    if _LEX is None:
        _LEX = [(re.compile(r"\b" + re.escape(t) + r"\b"), w)
                for t, w in POSITIVE.items()]
        _LEX += [(re.compile(r"\b" + re.escape(t) + r"\b"), -w)
                 for t, w in NEGATIVE.items()]
    return _LEX


def article_sentiment(title, summary):
    """Signed score, clamped to [-6, +6]. Title hits count double."""
    t = (title or "").lower()
    s = (summary or "").lower()
    score = 0
    for rx, w in _lexicon():
        if rx.search(t):
            score += 2 * w
        elif rx.search(s):
            score += w
    return max(-6, min(6, score))


# ------------------------------------------------------------ asset matching

ALIASES = {
    "ripple": ["ripple"],
    "dogecoin": ["doge"],
    "hedera-hashgraph": ["hedera hashgraph"],
    "ethereum": ["ether"],  # \b keeps this from matching "tether"
}

_NAME_SUFFIX = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|plc|ltd|the)\b\.?", re.I)


def _clean_name(name):
    """'Ayala Land, Inc.' -> 'ayala land' (matches how headlines are written)."""
    n = _NAME_SUFFIX.sub(" ", (name or "").lower())
    n = re.sub(r"[.,()'\"]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _asset_patterns(assets):
    """Per asset: (id, [name regexes], symbol regex, [longer names to mask])."""
    cleaned = [( _clean_name(a.get("name")), a["asset_id"]) for a in assets]
    out = []
    for a in assets:
        name = _clean_name(a.get("name"))
        terms = ([name] if len(name) >= 4 else []) + ALIASES.get(a["asset_id"], [])
        name_rx = [re.compile(r"\b" + re.escape(t) + r"\b") for t in terms]
        sym = (a.get("symbol") or "").upper()
        # case-sensitive, >=3 chars, so tickers like NEAR/ALL don't match prose
        sym_rx = re.compile(r"\b" + re.escape(sym) + r"\b") if len(sym) >= 3 else None
        mask = [n for n, aid in cleaned
                if aid != a["asset_id"] and name and len(name) >= 4
                and name in n and n != name]
        out.append((a["asset_id"], name_rx, sym_rx, mask))
    return out


def _match_news(assets, news_items, now_ms):
    pats = _asset_patterns(assets)
    per_asset = {a["asset_id"]: {"raw": 0.0, "articles": []} for a in assets}
    total_sent = 0.0
    total_w = 0.0
    for it in news_items:
        published = it.get("published") or now_ms
        age_h = max(0.0, (now_ms - published) / 3600000.0)
        if age_h > 72:
            continue
        sent = article_sentiment(it.get("title"), it.get("summary"))
        w = math.exp(-age_h / 24.0)
        total_sent += sent * w
        total_w += w
        raw_text = (it.get("title") or "") + " " + (it.get("summary") or "")
        lower = raw_text.lower()
        for aid, name_rx, sym_rx, mask in pats:
            masked = lower
            for m in mask:
                masked = masked.replace(m, " ")
            hit = any(rx.search(masked) for rx in name_rx) or \
                  (sym_rx is not None and sym_rx.search(raw_text))
            if hit:
                bucket = per_asset[aid]
                bucket["raw"] += sent * w
                if len(bucket["articles"]) < 40:
                    bucket["articles"].append({
                        "title": it.get("title"), "link": it.get("link"),
                        "source": it.get("source"), "published": published,
                        "sentiment": sent,
                    })
    market_sent = (total_sent / total_w) if total_w else 0.0
    return per_asset, market_sent


# ---------------------------------------------------------- industry news
# News that names no company can still move a whole sector ("BSP cuts rates"
# lifts every bank). Assets map to a canonical sector via their stored sector
# tag (PSE board name / Finnhub industry); headlines map to sectors by
# keyword. The resulting nudge is deliberately small (capped at ±0.5 of the
# ±3 direct-news scale): sector reads are context, not headlines about YOU.

_SECTOR_MATCH = [  # ordered: first match wins ("Mining and Oil" is mining)
    ("mining", ("mining", "metals")),
    ("banks", ("financial", "bank", "insurance")),
    ("property", ("property", "real estate")),
    ("energy", ("energy", "oil", "gas", "utilit", "power")),
    ("tech", ("technology", "semiconductor", "software", "internet",
              "communication", "media", "telecom")),
    ("healthcare", ("health", "pharma", "biotech")),
    ("consumer", ("retail", "consumer", "beverage", "food")),
    ("autos", ("automobile", "auto")),
    ("industrial", ("industrial", "aerospace", "machinery", "construction")),
    ("conglomerates", ("holding",)),
    ("services", ("services",)),
]

_SECTOR_NEWS = {
    "banks": ("bank ", "banks", "banking", "lender", "bsp ", "interest rate",
              "rate hike", "rate cut", "monetary policy", "fed rate"),
    "property": ("property", "real estate", "reit", "housing", "condo"),
    "mining": ("mining", "nickel", "copper", "gold price", "ore ", "commodity"),
    "energy": ("oil price", "crude", "opec", "fuel price", "gasoline",
               "power plant", "electricity", "coal", "renewable energy", "lng"),
    "tech": ("semiconductor", "chip ", "chips", " ai ", "artificial intelligence",
             "software", "cloud computing", "data center", "5g", "broadband"),
    "healthcare": ("pharma", "hospital", "drugmaker", "biotech", "vaccine"),
    "consumer": ("retail sales", "consumer spending", "inflation",
                 "supermarket", "fast food", "food prices"),
    "autos": ("automaker", "electric vehicle", " ev ", "car sales"),
    "industrial": ("manufacturing", "infrastructure", "construction",
                   "cement", "factory output"),
    "conglomerates": ("conglomerate",),
    "services": ("tourism", "casino", "gaming revenue", "airline",
                 "air travel", "shipping", "logistics"),
}


def _sector_key(sector):
    if not sector:
        return None
    s = sector.lower()
    for key, terms in _SECTOR_MATCH:
        if any(t in s for t in terms):
            return key
    return None


# keywords match on WORD BOUNDARIES: a plain substring scan would tag "ore"
# inside "more"/"before" and hit the mining sector on half the feed
_SECTOR_RX = {key: [re.compile(r"\b" + re.escape(k.strip()) + r"\b")
                    for k in kws]
              for key, kws in _SECTOR_NEWS.items()}


def sector_tags(text):
    """Sector keys a piece of text touches (lower-cased input)."""
    return [key for key, rxs in _SECTOR_RX.items()
            if any(rx.search(text) for rx in rxs)]


def _industry_news(assets, fundamentals, news_items, now_ms, per_asset_news):
    """Per-asset sector-news nudge: {aid: {score, sector, headline, link}}.
    Articles already credited to the asset directly are skipped, so a story
    naming both the company and its industry never counts twice."""
    sector_hits = {}
    seen_titles = set()
    for it in news_items:
        published = it.get("published") or now_ms
        age_h = max(0.0, (now_ms - published) / 3600000.0)
        if age_h > 72:
            continue
        sent = article_sentiment(it.get("title"), it.get("summary"))
        if not sent:
            continue
        # syndicated copies of one story arrive under different links -
        # dedupe on the normalized title so one event counts once
        tkey = re.sub(r"\W+", " ", (it.get("title") or "").lower()).strip()
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        text = ((it.get("title") or "") + " " + (it.get("summary") or "")).lower()
        w = math.exp(-age_h / 24.0)
        for key in sector_tags(text):
            sector_hits.setdefault(key, []).append(
                (sent * w, it.get("title"), it.get("link")))
    out = {}
    for a in assets:
        f = fundamentals.get(a["asset_id"]) or {}
        key = _sector_key(f.get("sector"))
        hits = sector_hits.get(key)
        if not hits:
            continue
        own = {x["link"] for x in
               (per_asset_news.get(a["asset_id"]) or {}).get("articles", [])}
        rel = [hh for hh in hits if hh[2] not in own]
        if not rel:
            continue
        score = max(-0.5, min(0.5, sum(hh[0] for hh in rel) * 0.15))
        if abs(score) < 0.05:
            continue
        # the example headline must argue the same direction as the net score
        same = [hh for hh in rel if hh[0] * score > 0]
        top = max(same or rel, key=lambda hh: abs(hh[0]))
        out[a["asset_id"]] = {"score": round(score, 2), "sector": key,
                              "headline": top[1], "link": top[2]}
    return out


# ------------------------------------------------------- fundamentals voting

def _value_votes(f, price):
    """Valuation-based votes for stocks. Returns (votes, reasons)."""
    votes = 0.0
    reasons = []
    if not f:
        return votes, reasons
    pe = f.get("pe")
    if pe is not None and pe > 0:
        if pe <= 10:
            votes += 2
            reasons.append(f"P/E {pe:.1f} - cheap; you pay little for each peso/dollar of profit")
        elif pe <= 18:
            votes += 1
            reasons.append(f"P/E {pe:.1f} - reasonably valued")
        elif pe > 30:
            votes -= 1
            reasons.append(f"P/E {pe:.1f} - expensive; a lot of growth already priced in")
        spe = f.get("sector_pe")
        if spe and pe < 0.8 * spe:
            votes += 1
            reasons.append(f"Cheaper than its sector average (P/E {spe:.1f})")
    dy = f.get("div_yield")
    if dy:
        if dy >= 5:
            votes += 2
            reasons.append(f"Dividend yield {dy:.1f}% - strong income while you hold")
        elif dy >= 3:
            votes += 1
            reasons.append(f"Dividend yield {dy:.1f}% - decent income")
    hi, lo = f.get("wk52_high"), f.get("wk52_low")
    if hi and lo and price and hi > lo:
        pos = (price - lo) / (hi - lo)
        if pos < 0.2:
            votes += 1
            reasons.append("Trading near its 52-week low - potential value entry "
                           "(worth checking why it fell)")
        elif pos > 0.95:
            reasons.append("Trading at the top of its 52-week range")
    ex = f.get("div_ex_date")
    if ex:
        reasons.append(f"Upcoming dividend: buy before the ex-date ({ex}) to receive it")
        votes += 0.5
    # growth & quality (rides on data the metric calls already return)
    eg, rg = f.get("eps_growth"), f.get("rev_growth")
    roe, de, pb = f.get("roe"), f.get("debt_equity"), f.get("pb")
    if eg is not None:
        if eg >= 15 and (rg is None or rg > 0):
            votes += 1
            if rg is not None and rg > 0:
                reasons.append(f"Profits growing {eg:.0f}% year-on-year on rising revenue - "
                               "the business itself is expanding, not just the chart")
            else:
                reasons.append(f"Profits growing {eg:.0f}% year-on-year - "
                               "the business is earning more, not just charting higher")
        elif eg <= -15:
            if pe is not None and 0 < pe <= 10:
                votes -= 2  # cancels the cheap-P/E bonus: cheap + shrinking = trap risk
                reasons.append(f"But profits shrank {abs(eg):.0f}% year-on-year - a low P/E "
                               "with falling profits can be a value trap")
            else:
                votes -= 1
                reasons.append(f"Profits shrank {abs(eg):.0f}% year-on-year - "
                               "the price may be weak for a reason")
    if roe is not None and roe >= 15 and (de is None or de <= 1.5):
        votes += 1
        reasons.append(f"Earns {roe:.0f}% on shareholders' money without heavy debt - "
                       "a quality business")
    if de is not None and de >= 2.0:
        votes -= 1
        reasons.append(f"Carries {de:.1f}x more debt than equity - lenders get paid "
                       "before shareholders if things go wrong")
    if (pe is None or pe <= 0) and pb is not None and 0 < pb < 1.0 and (roe or 0) > 5:
        votes += 1
        reasons.append(f"Trades below book value (P/B {pb:.2f}) while still profitable - "
                       "quietly cheap")
    return max(-4.0, min(4.0, votes)), reasons


# ----------------------------------------------------------- recommendations

ACTION_RANK = {"SELL PART": 6, "TRIM": 5, "TAKE PROFIT": 4,
               "BUY": 3, "BUY MORE": 3, "WATCH": 1, "HOLD": 0}

MAX_ALLOC_PCT = 35
TARGET_TRIM_PCT = 30
BUY_CAP_PCT = 30

# How boldly to act, independent of trading style: shifts the technical bar a
# fresh buy must clear and scales suggested buy sizes. Sell-side logic is
# deliberately untouched - risk appetite should change how you enter, not
# whether you protect what you hold.
AGGRESSIVENESS = {
    "cautious": {"label": "Cautious", "buy_shift": 1, "size_mult": 0.5},
    "balanced": {"label": "Balanced", "buy_shift": 0, "size_mult": 1.0},
    "aggressive": {"label": "Aggressive", "buy_shift": -1, "size_mult": 1.5},
}

# How spread-out the advisor pushes the portfolio to be: shifts the
# concentration cap (and with it the trim trigger and the wallet-level
# take-profit guard) around the style's baseline.
DIVERSITY = {
    "focused": {"label": "Focused", "cap_shift": 10},
    "balanced": {"label": "Balanced", "cap_shift": 0},
    "spread": {"label": "Spread out", "cap_shift": -10},
}

# Trading-style presets tune how eager vs. patient the advisor is. "swing" is
# the balanced default and reproduces the original thresholds exactly.
#   buy_tech    - minimum technical score to act on a buy
#   sell_hard   - technical score that triggers a sell on its own
#   sell_soft   - technical score that triggers a sell if news/value also weak
#   tp_pct      - profit % at which "take profit" kicks in
#   tp_tech     - momentum-cooling threshold for take profit
#   value_buy   - fundamentals score needed to buy on value alone (99 = ignore
#                 fundamentals; lower = more willing to buy a cheap stock)
#   alloc_cap   - position size (% of wallet) considered "too concentrated"
#   port_tp     - wallet-level profit target: take profit also fires (cooling
#                 still required) when this one position's unrealized gain has
#                 added this % to the whole wallet, even below tp_pct. Only
#                 applies while alloc <= alloc_cap (beyond the cap TRIM owns
#                 the call, and a small portfolio's single big position must
#                 still earn its full per-position target). Set at ~75% of the
#                 wallet gain a cap-sized position shows at its full target:
#                 alloc_cap * tp_pct / (100 + tp_pct) - the denominator matters
#                 because gain is measured against cost, not current value.
STYLE_PARAMS = {
    "scalper": {"label": "Scalper", "buy_tech": 2, "sell_hard": -2, "sell_soft": -1,
                "tp_pct": 2, "tp_tech": 1, "value_buy": 99, "alloc_cap": 40,
                "port_tp": 0.6},
    "day": {"label": "Day Trader", "buy_tech": 2, "sell_hard": -3, "sell_soft": -2,
            "tp_pct": 4, "tp_tech": 0, "value_buy": 99, "alloc_cap": 38,
            "port_tp": 1.1},
    "swing": {"label": "Swing Trader", "buy_tech": 3, "sell_hard": -4, "sell_soft": -2,
              "tp_pct": 10, "tp_tech": -1, "value_buy": 3, "alloc_cap": 35,
              "port_tp": 2.4},
    "long": {"label": "Long-Term Investor", "buy_tech": 4, "sell_hard": -5, "sell_soft": -4,
             "tp_pct": 40, "tp_tech": -1, "value_buy": 2, "alloc_cap": 35,
             "port_tp": 7.5},
}
DEFAULT_STYLE = "swing"

# "Hot & cold" awareness flags - surfaced as information, NOT trade instructions.
# Based on raw price movement, so a big drop can't be masked by an oversold RSI.
MOVER_24H_PCT = 8     # flag a 24h price move beyond +/- this %
MOVER_7D_PCT = 15     # flag a 7d move beyond +/- this % (where 7d data exists)
DRAWDOWN_PCT = 15     # flag a held position down more than this % from your avg buy

# Entry-timing guard (anti-chasing): a fresh BUY on something already up this
# much over ~30 days AND near its highs is chasing, not a setup. Style-scaled
# (longer horizons are pickier about entries); scalpers are exempt entirely.
EXT30_STOCKS = {"long": 20, "swing": 25, "day": 35}
EXT30_CRYPTO = {"long": 30, "swing": 40, "day": 50}
EXTREME_30D = {"stocks": 60, "crypto": 80}   # run-up that trips the gate on its own
EARNINGS_GATE_DAYS = 3    # no fresh buys this close to an earnings report
EARNINGS_FLAG_DAYS = 7    # awareness flag inside this window

# Basing / coiled-quiet detection (calibrated on live data 2026-07-26 so each
# flags a handful of names, not half the market). coil_ratio = recent span vs
# what the asset's own volatility predicts (~1 normal, well below 1 = quiet).
BASE_CHG30 = -25          # fell at least this much over ~30d
BASE_RANGE_POS = 0.20     # ...and sits in the bottom fifth of its range
BASE_COIL = 0.50          # ...and recent action has gone quiet
QUIET_CHG30 = 8           # went nowhere over ~30d (abs)
QUIET_COIL = 0.12         # extremely tight recent action
QUIET_MIN_VOL = 1.5       # only meaningful for assets that normally move
BASE_MIN_VOL = 1.0


def _round_amt(v, floor=10):
    return max(floor, int(round(v / 5.0) * 5))


def _fmt_price(v):
    """Human price formatting that never goes scientific: $0.00001234 stays
    readable instead of 1.234e-05, and big prices keep their commas."""
    if v >= 1:
        return f"{v:,.2f}"
    s = f"{v:.10f}".rstrip("0")
    return s if s[-1] != "." else s + "0"


# ------------------------------------------------- suggested TP/SL engine
# Levels are DEDUCED per asset instead of flat style percentages:
#   1. Volatility base: the asset's own typical daily move, scaled to the
#      style's holding horizon (sqrt-of-time), sets the stop distance; the
#      target starts at 2x that (risk:reward 1:2).
#   2. Structure snapping: if a real swing-low support sits near the stop,
#      tuck the stop just below it (stops belong behind support, not in the
#      middle of nowhere); likewise the target snaps to a nearby swing-high
#      resistance or the 52-week high (stocks).
#   3. Style guardrails clamp the result so no suggestion is ever absurd.
# Every suggestion carries a plain-language "why".
PLAN_STYLE = {
    #        horizon(d)  sl%   min-max     tp% min-max
    "scalper": {"h": 0.5,  "sl": (0.8, 3.0),  "tp": (1.6, 6.0)},
    "day":     {"h": 1.5,  "sl": (1.5, 6.0),  "tp": (3.0, 12.0)},
    "swing":   {"h": 10.0, "sl": (3.0, 10.0), "tp": (6.0, 20.0)},
    "long":    {"h": 45.0, "sl": (7.5, 25.0), "tp": (15.0, 50.0)},
}
_SL_Z = 1.4          # stop sits ~1.4 typical horizon-moves away
_SNAP_GAP = 0.25     # snapped levels sit this fraction of a daily move beyond the structure


def suggest_plan(price, style, prim=None, wk52_high=None, style_label=None):
    """Data-deduced TP/SL suggestion. Returns
    {tp, sl, tp_pct, sl_pct, rr, why} or None (no price)."""
    if not price or price <= 0:
        return None
    ps = PLAN_STYLE.get(style) or PLAN_STYLE[DEFAULT_STYLE]
    sp = STYLE_PARAMS.get(style) or STYLE_PARAMS[DEFAULT_STYLE]
    label = style_label or sp["label"]
    vol = (prim or {}).get("vol_day")
    why = []

    if vol and vol > 0.05:
        sl_pct = _SL_Z * vol * (ps["h"] ** 0.5)
        base = f"sized to this asset's own volatility (typical day: ±{vol:.1f}%)"
    elif vol is not None:
        # history exists and was measured - the asset just barely moves
        # (stablecoins, ultra-thin names): tightest stop for the style
        sl_pct = ps["sl"][0]
        base = (f"this asset barely moves (typical day: ±{vol:.2f}%) - "
                "using your style's tightest levels")
    else:
        sl_pct = sp["tp_pct"] / 2.0
        base = "style default - not enough price history yet to measure this asset"
    # clamp the volatility base into the style band BEFORE structure snapping,
    # so "near the stop" is judged from a sane distance and a snap that the
    # guardrails would move can never be accepted (the why must stay true)
    sl_pct = min(max(sl_pct, ps["sl"][0]), ps["sl"][1])
    tp_pct = min(max(2.0 * sl_pct, ps["tp"][0]), ps["tp"][1])

    # structure snapping - accepted only when the snapped level itself lies
    # inside the style band, so later clamps can never un-snap it
    support = (prim or {}).get("support")
    if support and vol and 0 < price - support < price * sl_pct / 100 * 1.8:
        cand = support * (1 - _SNAP_GAP * vol / 100)
        cand_pct = (1 - cand / price) * 100
        if cand < price * 0.995 and ps["sl"][0] <= cand_pct <= ps["sl"][1]:
            sl_pct = cand_pct
            why.append("stop tucked below the nearest support level")

    res_cands = [r for r in [(prim or {}).get("resistance"), wk52_high]
                 if r and r > price * 1.01]
    tp_snapped = False
    if res_cands and vol:
        res = min(res_cands)
        if price * (1 + tp_pct / 100 * 0.4) < res < price * (1 + tp_pct / 100 * 2.0):
            cand = res * (1 - _SNAP_GAP * vol / 100)
            cand_pct = (cand / price - 1) * 100
            if cand > price * 1.01 and ps["tp"][0] <= cand_pct <= ps["tp"][1]:
                tp_pct = cand_pct
                tp_snapped = True
                which = ("the 52-week high" if wk52_high is not None and res == wk52_high
                         else "the nearest resistance level")
                why.append(f"target set just under {which}")

    # keep risk:reward honest (>= 1.3); if this widens a snapped target, the
    # snap rationale no longer holds - drop it rather than mislead
    if tp_pct / sl_pct < 1.3:
        tp_pct = min(1.5 * sl_pct, ps["tp"][1])
        if tp_snapped:
            why = [w for w in why if not w.startswith("target set just under")]
        why.append("target widened to keep the reward worth the risk")
    rr = tp_pct / sl_pct
    why.insert(0, f"{label} horizon, {base}")
    return {
        "tp": price * (1 + tp_pct / 100),
        "sl": price * (1 - sl_pct / 100),
        "tp_pct": round(tp_pct, 1),
        "sl_pct": round(sl_pct, 1),
        "rr": round(rr, 1),
        "why": "; ".join(why),
    }


def build(assets, signals, portfolio, news_items, market, now_ms,
          currency="$", fundamentals=None, max_ideas=None, style=DEFAULT_STYLE,
          targets=None, earnings=None, aggressiveness="balanced",
          diversity="balanced"):
    """Main entry. Returns {market_sentiment, briefing, recommendations}."""
    fundamentals = fundamentals or {}
    targets = targets or {}
    earnings = earnings or {}
    is_crypto = market.get("name") == "crypto"
    regime = market.get("regime") or {}
    caution = regime.get("state") == "caution"
    # earnings dates are US-market dates: compare in the market's own timezone,
    # or the gate would lift at Manila midnight = noon ET, hours before an
    # after-close report (the exact window it exists to protect)
    tz = ZoneInfo("America/New_York" if market.get("name") == "global" else "Asia/Manila")
    today = datetime.datetime.fromtimestamp(now_ms / 1000, tz).date()
    sp = STYLE_PARAMS.get(style) or STYLE_PARAMS[DEFAULT_STYLE]
    ag = AGGRESSIVENESS.get(aggressiveness) or AGGRESSIVENESS["balanced"]
    dv = DIVERSITY.get(diversity) or DIVERSITY["balanced"]
    # the buy bar never drops below 1: even "aggressive" requires the
    # technicals to actually point up before the advisor suggests entering
    buy_bar = max(1, sp["buy_tech"] + ag["buy_shift"])
    max_alloc = max(15, sp["alloc_cap"] + dv["cap_shift"])
    target_trim = max_alloc - 5
    # buys must never build a position the same engine would immediately trim:
    # the buy ceiling tracks the (possibly diversity-lowered) concentration cap
    buy_cap = min(BUY_CAP_PCT, max_alloc)
    per_asset_news, market_sent = _match_news(assets, news_items, now_ms)
    industry_news = (_industry_news(assets, fundamentals, news_items, now_ms,
                                    per_asset_news)
                     if not is_crypto and fundamentals else {})

    summary = portfolio.get("summary", {})
    total = summary.get("value") or 0.0
    cash = summary.get("cash")  # None when no budget is set
    # size buys against the full bankroll (positions + cash) when known
    capital = (total + max(cash, 0)) if cash is not None else total
    hold_by_id = {h["asset_id"]: h for h in portfolio.get("holdings", [])}
    n_holdings = len(portfolio.get("holdings", []))

    recs = []
    for a in assets:
        aid = a["asset_id"]
        sig = signals.get(aid) or {}
        ind = sig.get("indicators") or {}
        tech = sig.get("score") if sig.get("action") not in (None, "WAIT") else None
        nb = per_asset_news.get(aid, {"raw": 0.0, "articles": []})
        news_score = max(-3.0, min(3.0, nb["raw"] / 3.0))
        if len(nb["articles"]) == 1:
            news_score *= 0.5  # a single headline shouldn't swing a trade call
        articles = sorted(nb["articles"], key=lambda x: -abs(x["sentiment"]))[:3]
        h = hold_by_id.get(aid)
        price = a.get("price") or (h or {}).get("price")
        f = fundamentals.get(aid)
        value_votes, value_reasons = _value_votes(f, price)
        has_value = h is not None and h.get("value") is not None
        # with a budget set, concentration is judged against the whole wallet
        # (positions + cash); without one, against invested positions only
        alloc_base = capital if cash is not None else total
        # with a budget the base includes tracked cash ("wallet"); without one
        # it is invested positions only - every string below must say which
        wallet_word = "wallet" if cash is not None else "portfolio"
        alloc = (h["value"] / alloc_base * 100) if has_value and alloc_base > 0 else 0.0
        plpct = (h or {}).get("unrealized_pct")
        # what this position's unrealized gain adds to that base - the number
        # that actually compounds (gain = value - cost, cost backed out of the
        # position's own unrealized %)
        gain_val = (h["value"] * plpct / (100.0 + plpct)
                    if has_value and plpct is not None and plpct > -100 else None)
        wallet_gain = (gain_val / alloc_base * 100
                       if gain_val is not None and alloc_base > 0 else None)

        # basing / coiled-quiet detection (user-suggested reads, calibrated):
        # a fall that has STOPPED falling, or an active name gone dead quiet
        prim0 = sig.get("plan") or {}
        cr0 = prim0.get("coil_ratio")
        vol0 = prim0.get("vol_day")
        chg30_0 = a.get("chg_30d") if is_crypto else (sig.get("indicators") or {}).get("chg_30d")
        rl0, rh0 = prim0.get("range_low"), prim0.get("range_high")
        rpos0 = ((price - rl0) / (rh0 - rl0)) if price and rl0 and rh0 and rh0 > rl0 else None
        basing = (chg30_0 is not None and chg30_0 <= BASE_CHG30
                  and rpos0 is not None and rpos0 <= BASE_RANGE_POS
                  and cr0 is not None and 0 < cr0 <= BASE_COIL
                  and vol0 is not None and vol0 >= BASE_MIN_VOL)
        coiled = (not basing and chg30_0 is not None and abs(chg30_0) < QUIET_CHG30
                  and cr0 is not None and 0 < cr0 <= QUIET_COIL
                  and vol0 is not None and vol0 >= QUIET_MIN_VOL
                  and prim0.get("bars", 0) >= 40)
        # basing earns a modest vote only while RSI is still below 50 (before
        # the technical score itself starts crediting the recovery, which
        # would double-count it) and the news isn't negative - bases do fail
        rsi0 = ind.get("rsi")
        base_vote = 1.0 if (basing and rsi0 is not None and rsi0 < 50
                            and news_score >= 0) else 0.0
        ind_n = industry_news.get(aid)
        ind_score = ind_n["score"] if ind_n else 0.0
        conviction = (tech or 0) + news_score + value_votes + base_vote + ind_score

        reasons = []
        gate_notes = []  # interventions recorded for the breakdown ledger
        action, amt = "HOLD", None
        sale_reasons_n = 0  # how many leading reasons argue for a sell action
        pullback = False  # set by the watchlist buy path; read by the chase gate

        if h and not has_value:
            reasons.append(
                "No live price available right now, so this position can't be "
                "assessed - review it manually.")
        elif h:  # ---------- assets you own
            headroom = (buy_cap / 100.0) * alloc_base - h["value"]
            if alloc > max_alloc and n_holdings >= 3:
                action = "TRIM"
                t = target_trim / 100.0
                if cash is not None:
                    # sale proceeds become tracked cash, so the wallet total
                    # stays the same and the sizing is direct
                    amt = h["value"] - t * capital
                else:
                    # no cash tracking: the sale shrinks the tracked total,
                    # so size it to land at ~TARGET of what remains
                    amt = (h["value"] - t * total) / (1 - t)
                reasons.append(
                    f"{a['name']} is {alloc:.0f}% of this {wallet_word} - a lot riding "
                    f"on one position. Selling this much (keep it as cash or spread "
                    f"it around) brings it down to about {target_trim}%.")
                if tech is not None and tech <= -2:
                    reasons.append("Technicals are weak too, which strengthens the case.")
            elif tech is not None and (tech <= sp["sell_hard"] or
                                       (tech <= sp["sell_soft"] and (news_score <= -1 or value_votes <= -1))):
                action = "SELL PART"
                amt = h["value"] * 0.5
                reasons.append("Multiple technical indicators point down at once.")
                if news_score <= -1:
                    reasons.append("Recent news coverage is negative as well.")
                if plpct is not None and plpct < 0:
                    reasons.append(
                        f"You're down {abs(plpct):.0f}% on this position - reducing "
                        "now limits further damage if the slide continues.")
            elif plpct is not None and plpct > 0 and tech is not None and tech <= sp["tp_tech"] \
                    and (plpct >= sp["tp_pct"]
                         or (wallet_gain is not None and wallet_gain >= sp["port_tp"]
                             and alloc <= max_alloc)):
                # the wallet-level arm requires alloc <= alloc_cap: beyond the
                # cap TRIM owns the call, and a small portfolio's single big
                # position must still earn its full per-position target
                action = "TAKE PROFIT"
                amt = h["value"] * 0.3
                if plpct >= sp["tp_pct"]:
                    reasons.append(
                        f"You're up {plpct:.0f}% and momentum is cooling - selling ~30% "
                        "locks in profit while keeping most of the upside.")
                else:
                    reasons.append(
                        f"Up {plpct:.1f}% on the position, but it's large enough that "
                        f"this gain alone has added ~{wallet_gain:.1f}% to your whole "
                        f"{wallet_word} - with momentum cooling, banking part of that "
                        "counts as much as a full target on a smaller position.")
                    gate_notes.append(
                        f"{wallet_word.capitalize()}-level profit target: this gain = "
                        f"{wallet_gain:.1f}% of the whole {wallet_word} (style threshold "
                        f"{sp['port_tp']}%), triggered below the per-position "
                        f"{sp['tp_pct']}% target")
            elif ((tech is not None and tech >= buy_bar) or (tech is None and value_votes >= sp["value_buy"])) \
                    and news_score >= -0.5 and alloc < buy_cap and headroom >= 10 \
                    and (cash is None or cash >= 15):
                action = "BUY MORE"
                amt = min(0.10 * capital, headroom)
                reasons.append(("Strong setup on a position you already own."
                                if tech is None or tech >= sp["buy_tech"] else
                                "Early setup on a position you already own - your "
                                "aggressive setting acts on signals this style "
                                "normally waits out."))
                if news_score >= 1:
                    reasons.append("News flow around it is clearly positive.")
            else:
                action = "HOLD"
                if tech is None and not f:
                    reasons.append("Not enough price history yet for a confident call.")
                else:
                    reasons.append("Signals don't line up strongly enough either "
                                   "way - no edge; sit tight.")
            # everything appended so far argues for THIS action; remembered so
            # a later demotion can retract the argument along with the action
            sale_reasons_n = len(reasons)
            if alloc > max_alloc and n_holdings < 3:
                reasons.append(
                    f"Heads up: this is {alloc:.0f}% of the portfolio. With only "
                    f"{n_holdings} position(s) that's expected, but consider spreading "
                    "new money across more assets over time.")
        else:  # ---------- watchlist assets you don't own
            base = max(0.05 * capital, 25)
            # in a caution regime (market weather), fresh entries need one
            # extra technical notch - the bar rises, it never drops
            bt = buy_bar + (1 if caution else 0)
            good_setup = (tech is not None and ((tech >= bt + 1 and news_score >= 0) or
                                                (tech >= bt and news_score >= 1))) \
                or (value_votes >= sp["value_buy"] and news_score >= 0 and (tech is None or tech >= 0)) \
                or (value_votes >= 2 and tech is not None and tech >= 2)
            # pullback-in-uptrend: the entry the short-horizon votes wrongly
            # skip - a solid month-long trend resting at its recent average.
            # Buying the dip in strength beats buying the breakout.
            if (not good_setup and style in ("swing", "long") and price
                    and tech is not None and tech >= 0
                    and news_score >= (0.5 if caution else 0)):
                chg30p = a.get("chg_30d") if is_crypto else ind.get("chg_30d")
                anchor7 = ind.get("anchor7")
                rsi_v = ind.get("rsi")
                prim_pb = sig.get("plan") or {}
                rl_pb, rh_pb = prim_pb.get("range_low"), prim_pb.get("range_high")
                rpos = ((price - rl_pb) / (rh_pb - rl_pb)) if rl_pb and rh_pb and rh_pb > rl_pb else None
                # "resting AT its average" means near it - a price far BELOW
                # the anchor is a decline, not a rest (two-sided band)
                if (chg30p is not None and anchor7 and rsi_v is not None
                        and anchor7 * 0.98 <= price <= anchor7 * 1.005 and rsi_v < 55):
                    if is_crypto:
                        # chg_7d floor = the medium-trend check crypto's short
                        # window can't provide via a 20d SMA: a coin two weeks
                        # into a collapse is not "resting", it's falling
                        pullback = (chg30p >= 15
                                    and (a.get("chg_7d") or 0) >= -5
                                    and rpos is not None and 0.40 <= rpos <= 0.70)
                    else:
                        sma20 = ind.get("sma20d")
                        pullback = (chg30p >= 10 and sma20 and price > sma20
                                    and value_votes >= -1
                                    and rpos is not None and 0.40 <= rpos <= 0.85)
            good_setup = good_setup or pullback
            if good_setup and cash is not None and cash < 25:
                action = "WATCH"
                reasons.append(
                    f"Good setup, but your available cash ({currency}{max(cash, 0):,.0f}) "
                    "is too low for a meaningful buy - raise the budget on the "
                    "Portfolio tab or free up funds first.")
            elif good_setup:
                action = "BUY"
                amt = base
                if pullback:
                    reasons.append("In a solid uptrend but resting at its recent average - "
                                   "buying the dip in strength usually beats buying the breakout.")
                if value_votes >= 2:
                    reasons.append("Attractive valuation - a candidate for a starter position.")
                if tech is not None and tech >= 3:
                    reasons.append("Strong technical setup backs the entry.")
                if news_score >= 1:
                    reasons.append("Positive news flow backs it up.")
                if not reasons:
                    reasons.append("Several signals line up - could be a good entry.")
            elif (tech is not None and tech >= 2) or news_score >= 1.5 or value_votes >= 2:
                action = "WATCH"
                reasons.append("Improving setup - not a clear entry yet, but keep an eye on it.")
            else:
                action = "HOLD"
                reasons.append("Nothing actionable here right now.")

        # ---- entry-timing guard: don't chase extended moves (FRESH buys only;
        # held positions and pullback entries - already timing-checked - exempt)
        conf_cap = False
        if action == "BUY" and not pullback and style != "scalper" and price:
            chg30 = a.get("chg_30d") if is_crypto else ind.get("chg_30d")
            prim_x = sig.get("plan") or {}
            rl_x, rh_x = prim_x.get("range_low"), prim_x.get("range_high")
            range_pos = ((price - rl_x) / (rh_x - rl_x)) if rl_x and rh_x and rh_x > rl_x else None
            wk52_pos = None
            if f and f.get("wk52_high") and f.get("wk52_low") and f["wk52_high"] > f["wk52_low"]:
                wk52_pos = (price - f["wk52_low"]) / (f["wk52_high"] - f["wk52_low"])
            thr = (EXT30_CRYPTO if is_crypto else EXT30_STOCKS).get(style)
            extreme = EXTREME_30D["crypto" if is_crypto else "stocks"]
            if is_crypto:
                near_high = (a.get("chg_7d") or 0) > 0
            else:
                near_high = ((range_pos is not None and range_pos >= 0.85) or
                             (wk52_pos is not None and wk52_pos >= 0.90))
            if chg30 is not None and thr is not None and \
                    ((chg30 >= thr and near_high) or chg30 >= extreme):
                anchor = ind.get("anchor7")
                # the "calmer entry" price is only honest when it IS calmer
                anch_txt = (f" near ~{currency}{_fmt_price(anchor)} (its recent average)"
                            if anchor and anchor < price * 0.995 else "")
                # phrase from what actually tripped - never claim an unchecked fact
                if is_crypto:
                    pos_txt = ("still climbing" if (a.get("chg_7d") or 0) > 0
                               else "after an outsized run")
                elif range_pos is not None and range_pos >= 0.85:
                    pos_txt = "near the top of its recent range"
                elif wk52_pos is not None and wk52_pos >= 0.90:
                    pos_txt = "near its 52-week high"
                else:
                    pos_txt = "an outsized run in that time"
                growth_backed = (f or {}).get("eps_growth") is not None and f["eps_growth"] >= 15
                if value_votes >= 3 and growth_backed:
                    reasons.insert(0, "Near its highs after a strong run, but profits are "
                                      "genuinely growing underneath - this looks like "
                                      "growth, not froth.")
                elif style == "day":
                    conf_cap = True
                    if amt is not None:
                        amt = amt / 2.0  # "keep it small" must actually be smaller
                    gate_notes.append(f"Chase caution: +{chg30:.0f}% month - size halved, confidence capped")
                    reasons.insert(0, f"Up {chg30:.0f}% in a month - fine for a quick trade, but "
                                      "this is a chase, not a fresh setup; suggested size is "
                                      "halved - stay nimble.")
                elif is_crypto:
                    action, amt = "WATCH", None
                    gate_notes.append(f"Entry-timing gate: +{chg30:.0f}% month - BUY held back as WATCH")
                    reasons.insert(0, f"Already up {chg30:.0f}% in the past month and {pos_txt} - "
                                      "most of that move is behind it. Watching for "
                                      f"a cooler entry{anch_txt}.")
                else:
                    action, amt = "WATCH", None
                    gate_notes.append(f"Entry-timing gate: +{chg30:.0f}% month - BUY held back as WATCH")
                    reasons.insert(0, f"Already up {chg30:.0f}% in the past month, {pos_txt} - "
                                      "buying now is chasing someone else's rally. Watching "
                                      f"instead; a rest{anch_txt} would be a calmer entry.")

        # ---- earnings-event gate: a report date is a coin flip, not a setup ----
        earn = earnings.get(aid)
        earn_days = earn_date = None
        if earn and earn.get("date"):
            try:
                earn_date = earn["date"]
                earn_days = (datetime.date.fromisoformat(earn_date) - today).days
            except (ValueError, TypeError):
                earn_days = earn_date = None
        if earn_days is not None and 0 <= earn_days <= EARNINGS_GATE_DAYS \
                and style != "long" and action == "BUY":
            action, amt = "WATCH", None
            gate_notes.append(f"Earnings gate: report {earn_date} - BUY held back as WATCH")
            reasons.insert(0, f"Earnings report due {earn_date} ({earn_days} day(s) away) - "
                              "results can gap the price sharply either way. This guide would "
                              "rather react to real numbers than guess them; check back after "
                              "the report.")
        if earn_days is not None and 0 <= earn_days <= EARNINGS_FLAG_DAYS \
                and action in ("BUY", "WATCH"):
            conf_cap = True  # never dampen sell-side decisiveness over event risk

        # ---- market weather: in a caution regime, half-size any fresh buys ----
        if caution and action in ("BUY", "BUY MORE") and amt is not None:
            amt = amt / 2.0
            gate_notes.append("Market weather: caution regime - buy size halved")

        if amt is not None:
            if action in ("TRIM", "SELL PART", "TAKE PROFIT"):
                amt = min(amt, h["value"])
                if amt < 5 or h["value"] < 20:
                    # retract the sale argument along with the action, or the
                    # card would urge a sell right under "not worth selling"
                    gate_notes.append(f"Size gate: {action} signal, but the position "
                                      "is too small for the sale to beat fees - held instead")
                    del reasons[:sale_reasons_n]
                    action, amt = "HOLD", None
                    reasons.insert(0, "This position's signals argued for selling, but "
                                      "the amount involved is too small to be worth it - "
                                      "fees and spreads would eat the benefit.")
                else:
                    amt = min(int(round(amt / 5.0) * 5), int(h["value"]))
            else:
                # buys: never suggest more than the cash on hand; round DOWN
                # in $5 steps so the number always stays affordable
                if ag["size_mult"] != 1.0:
                    pre_mult = amt
                    amt = amt * ag["size_mult"]
                    if action == "BUY MORE":
                        # scaling must not push the position past the buy cap
                        amt = min(amt, headroom)
                    if abs(amt - pre_mult) > 1e-9:
                        gate_notes.append(f"Sizing x{ag['size_mult']} "
                                          f"({ag['label']} aggressiveness setting)")
                if ag["buy_shift"] < 0 and tech is not None and tech < sp["buy_tech"]:
                    gate_notes.append("Aggressive setting: acting on a weaker setup "
                                      "than this style normally waits for")
                if cash is not None:
                    amt = min(amt, cash)
                amt = max(10, int(amt // 5) * 5)
                if cash is not None and amt > cash:
                    action, amt = "WATCH", None
                    gate_notes.append("Cash gate: buy setup kept as WATCH - not enough "
                                      "available cash for a meaningful buy")
                    reasons.insert(0, "Good setup, but not enough available cash "
                                      "for a meaningful buy right now.")

        # what banking this specific sale locks in, as a % of the whole wallet -
        # the number that compounds across many small trades
        wallet_impact = None
        if action in ("TRIM", "SELL PART", "TAKE PROFIT") and amt and gain_val \
                and gain_val > 0 and h.get("value") and alloc_base > 0:
            wallet_impact = round(gain_val * (amt / h["value"]) / alloc_base * 100, 2)

        reasons.extend(value_reasons)
        for r in (sig.get("reasons") or [])[:3]:
            reasons.append(r)
        if articles and abs(news_score) >= 0.5:
            mood = "positive" if news_score > 0 else "negative"
            reasons.append(f"News sentiment is {mood} "
                           f"({news_score:+.1f} on a -3..+3 scale).")
        if ind_n and abs(ind_score) >= 0.15:
            reasons.append(
                f"{ind_n['sector'].capitalize()}-sector news is "
                f"{'a tailwind' if ind_score > 0 else 'a headwind'} for this one "
                f"({ind_score:+.2f}) - e.g. \"{(ind_n['headline'] or '')[:90]}\"")

        if tech is None and not f:
            confidence = "Low"
        elif abs(conviction) >= 4 and (news_score == 0 or news_score * (tech or value_votes or 0) >= 0):
            confidence = "High"
        else:
            confidence = "Medium"
        if conf_cap and confidence == "High":
            confidence = "Medium"  # chase-caution / imminent earnings caps certainty
            gate_notes.append("Confidence capped at Medium - extended run-up or "
                              "earnings within a week makes certainty cheap")

        # movement flags: awareness of big moves, independent of the trade call
        chg24 = a.get("chg_24h")
        chg7 = a.get("chg_7d")
        flags = []
        if chg24 is not None and abs(chg24) >= MOVER_24H_PCT:
            if chg24 < 0:
                flags.append({"kind": "cold", "text": f"Down {abs(chg24):.0f}% in 24h - cooling fast"})
            else:
                flags.append({"kind": "hot", "text": f"Up {chg24:.0f}% in 24h - heating up"})
        elif chg7 is not None and abs(chg7) >= MOVER_7D_PCT:
            if chg7 < 0:
                flags.append({"kind": "cold", "text": f"Down {abs(chg7):.0f}% this week"})
            else:
                flags.append({"kind": "hot", "text": f"Up {chg7:.0f}% this week"})
        if has_value and plpct is not None and plpct <= -DRAWDOWN_PCT:
            flags.append({"kind": "cold",
                          "text": f"You're down {abs(plpct):.0f}% since you bought - worth reviewing"})
        # the user's own take-profit / stop-loss plan: flag when a level is
        # crossed. This is THEIR plan being triggered, not our advice - the
        # strongest kind of heads-up a paper trader can get.
        t = targets.get(aid)
        if t and h and price:
            tp, sl = t.get("tp_price"), t.get("sl_price")
            # only call the stop "trailing" when it IS the trailing floor - a
            # higher manual stop can coexist and must not borrow the label
            trailing = bool(t.get("trail_pct") and t.get("peak_price") and sl
                            and abs(sl - t["peak_price"] * (1 - t["trail_pct"] / 100.0))
                            <= sl * 1e-6)
            if tp and price >= tp:
                flags.append({"kind": "tp",
                              "text": f"Hit your take-profit ({currency}{_fmt_price(tp)})"
                                      + (f" - up {plpct:.0f}%" if plpct is not None and plpct > 0 else "")
                                      + " - your plan says consider selling"})
            elif sl and price <= sl:
                flags.append({"kind": "sl",
                              "text": (f"Fell through your trailing stop ({currency}{_fmt_price(sl)}, "
                                       f"trailing {t['trail_pct']:.0f}% below its "
                                       f"{currency}{_fmt_price(t.get('peak_price') or sl)} peak)"
                                       if trailing else
                                       f"Fell through your stop-loss ({currency}{_fmt_price(sl)})")
                                      + (f" - down {abs(plpct):.0f}%" if plpct is not None and plpct < 0 else "")
                                      + " - your plan says cut the loss"})
        # trailing-BUY alert: fires held or not (it mainly matters AFTER you
        # sold and want back in off the bottom) - awareness, not an order
        if t and price and t.get("trail_buy_pct") and t.get("trough_price"):
            tbp, trough = t["trail_buy_pct"], t["trough_price"]
            if trough > 0 and price >= trough * (1 + tbp / 100.0):
                flags.append({"kind": "rebound",
                              "text": f"Up {tbp:.0f}%+ off its {currency}{_fmt_price(trough)} low "
                                      "- your trailing-buy alert says take a look"})
        if basing:
            flags.append({"kind": "base",
                          "text": f"Down {abs(chg30_0):.0f}% over the month but the fall has gone "
                                  "quiet in the bottom of its recent range - sellers may be "
                                  "tiring; one to watch"})
        elif coiled:
            flags.append({"kind": "quiet",
                          "text": "Unusually quiet for its normal pace - coiled; big moves often "
                                  "follow quiet spells, in either direction"})
        if earn_days is not None and 0 <= earn_days <= EARNINGS_FLAG_DAYS:
            flags.append({"kind": "event",
                          "text": f"Earnings {earn_date} - expect a bigger-than-usual move around it"})
        # the user's own triggered plan outranks a fresh buy suggestion on the
        # same asset - never show "BUY MORE" under a tripped stop or target
        if action in ("BUY", "BUY MORE") and any(f["kind"] in ("tp", "sl") for f in flags):
            action, amt = "HOLD", None  # suggested_plan is derived below from the demoted action
            gate_notes.append("Plan gate: your own tripped stop/target outranks a "
                              "fresh buy - demoted to HOLD")
            reasons.insert(0, "Your own stop/target has triggered on this position - "
                              "resolve your plan first before adding more.")

        # a data-deduced starting plan for buy ideas: the asset's own
        # volatility and structure, scaled to the user's style horizon.
        # Shown as "our suggested starting point" - the user edits or ignores it.
        suggested_plan = None
        if action in ("BUY", "BUY MORE") and price:
            suggested_plan = suggest_plan(
                price, style, prim=sig.get("plan"),
                wk52_high=(f or {}).get("wk52_high"), style_label=sp["label"])

        recs.append({
            "asset_id": aid,
            "name": a.get("name") or aid,
            "symbol": a.get("symbol") or "",
            "image": a.get("image"),
            "price": price,
            "action": action,
            "suggested_plan": suggested_plan,
            "usd": amt,
            "qty": (amt / price) if amt and price else None,
            "wallet_impact": wallet_impact,
            "wallet_word": wallet_word,
            "conviction": round(conviction, 1),
            "confidence": confidence,
            "news_score": round(news_score, 2),
            "chg_24h": chg24,
            "flags": flags,
            "breakdown": {
                "tech": {"score": tech, "points": list(sig.get("reasons") or [])},
                "news": {"score": round(news_score, 2),
                         "points": [("+" if x["sentiment"] > 0 else "-" if x["sentiment"] < 0 else "=")
                                    + " " + (x.get("title") or "") for x in articles]},
                "value": {"score": round(value_votes, 2), "points": list(value_reasons)},
                "extras": (([{"label": "Basing pattern (fall gone quiet)", "score": base_vote}]
                            if base_vote else [])
                           + ([{"label": f"Industry news ({ind_n['sector']})",
                                "score": ind_score}] if ind_n else [])),
                "gates": gate_notes,
                "total": round(conviction, 1),
            },
            "reasons": reasons,
            "articles": articles,
            "fundamentals": ({k: f.get(k) for k in
                              ("eps", "pe", "div_ps", "div_yield", "div_ex_date",
                               "eps_growth", "rev_growth", "roe", "debt_equity", "pb")}
                             if f else None),
            "holding": ({
                "value": h.get("value"), "alloc_pct": round(alloc, 1),
                "unrealized_pct": plpct, "qty": h.get("qty"),
                "avg_buy": h.get("avg_buy"),
            } if h else None),
        })

    recs.sort(key=lambda r: (-ACTION_RANK.get(r["action"], 0), -abs(r["conviction"])))

    # big universes (PSE = 283 companies): keep every holding, cap the ideas,
    # but also keep the biggest hot/cold movers so they stay visible
    if max_ideas is not None:
        held = [r for r in recs if r["holding"]]
        ideas = [r for r in recs if not r["holding"] and r["action"] != "HOLD"][:max_ideas]
        kept_ids = {r["asset_id"] for r in held + ideas}
        movers = sorted([r for r in recs if r["flags"] and r["asset_id"] not in kept_ids],
                        # the user's own plan alerts (stops, targets, rebound
                        # watches) must never lose their slot to a mere mover
                        key=lambda r: (not any(f["kind"] in ("tp", "sl", "rebound")
                                               for f in r["flags"]),
                                       -abs(r.get("chg_24h") or 0)))[:10]
        recs = sorted(held + ideas + movers,
                      key=lambda r: (-ACTION_RANK.get(r["action"], 0), -abs(r["conviction"])))

    # when the exchange is closed there is nothing to act on: suppress
    # buy/sell suggestions entirely (crypto never closes) - but keep any rec
    # carrying awareness flags (hot/cold moves, tripped stops/targets): a stop
    # hit at Friday's close must not vanish for the whole weekend
    market_open = market.get("open", True)
    if not market_open:
        recs = [r if r["action"] in ("HOLD", "WATCH")
                else {**r, "action": "HOLD", "usd": None, "qty": None,
                      "wallet_impact": None,
                      "breakdown": {**r["breakdown"],
                                    "gates": r["breakdown"]["gates"]
                                    + [f"Market closed: {r['action']} shown as HOLD "
                                       "until the exchange reopens"]}}
                for r in recs if r["action"] in ("HOLD", "WATCH") or r["flags"]]

    # fast styles recycle banked profit: point each take-profit card at the
    # strongest current buy-side ideas from this same pass, so small wins go
    # back to work and build up - context, not an instruction. Candidates only;
    # the API layer words the hint after filtering out ideas the user already
    # dismissed today (dismissals live outside this cached snapshot).
    if style in ("scalper", "day"):
        buy_ideas = [r for r in recs if r["action"] in ("BUY", "BUY MORE")]
        for r in recs:
            if r["action"] != "TAKE PROFIT":
                continue
            cands = [b for b in buy_ideas if b["asset_id"] != r["asset_id"]][:2]
            if cands:
                r["rotation"] = [{"asset_id": b["asset_id"], "symbol": b["symbol"],
                                  "name": b["name"], "action": b["action"]}
                                 for b in cands]

    # ---------------------------------------------------------- briefing
    if market_sent > 0.4:
        news_mood = "leaning positive"
    elif market_sent < -0.4:
        news_mood = "leaning negative"
    else:
        news_mood = "neutral"

    bits = []
    if market.get("line"):
        bits.append(market["line"])
    elif market.get("mcap_chg") is not None:
        d = "up" if market["mcap_chg"] >= 0 else "down"
        bits.append(f"the overall market is {d} {abs(market['mcap_chg']):.1f}% in the last 24h")
    bits.append(f"news flow is {news_mood}")
    chg = summary.get("change_24h_pct")
    if chg is not None and total > 0:
        word = "up" if chg >= 0 else "down"
        bits.append(f"your portfolio is {word} {abs(chg):.1f}% today")
    briefing = ". ".join(b[0].upper() + b[1:] for b in bits) + "."
    if caution and regime.get("why"):
        briefing += " " + regime["why"]
    tweaks = []
    if ag is not AGGRESSIVENESS["balanced"]:
        tweaks.append(f"{ag['label'].lower()} sizing (x{ag['size_mult']} buys)")
    if dv is not DIVERSITY["balanced"]:
        tweaks.append(f"{dv['label'].lower()} portfolio (trim above ~{max_alloc}%)")
    if tweaks:
        briefing += " Your settings: " + " and ".join(tweaks) + "."

    actionable = [r for r in recs if r["action"] not in ("HOLD", "WATCH")]
    if not market_open:
        nxt = market.get("next_open")
        briefing += (" The market is closed right now - buy/sell suggestions "
                     "resume when it reopens" + (f" ({nxt})." if nxt else "."))
    elif actionable:
        top = actionable[0]
        verb = "buying" if top["action"] in ("BUY", "BUY MORE") else "selling"
        amt_txt = f" ~{currency}{top['usd']}" if top["usd"] else ""
        briefing += (f" Strongest suggestion: {top['action']} {top['name']}"
                     f" ({verb}{amt_txt}) - see below for the reasoning.")
    else:
        briefing += (" No strong buy or sell setups right now - "
                     "sometimes the best move is no move.")

    return {
        "market_sentiment": {"score": round(market_sent, 2), "label": news_mood},
        "briefing": briefing,
        "recommendations": recs,
        "style": style,
        "style_label": sp["label"],
        "aggressiveness": aggressiveness if aggressiveness in AGGRESSIVENESS else "balanced",
        "diversity": diversity if diversity in DIVERSITY else "balanced",
    }
