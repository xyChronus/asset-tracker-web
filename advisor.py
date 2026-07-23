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

import math
import re

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
    return votes, reasons


# ----------------------------------------------------------- recommendations

ACTION_RANK = {"SELL PART": 6, "TRIM": 5, "TAKE PROFIT": 4,
               "BUY": 3, "BUY MORE": 3, "WATCH": 1, "HOLD": 0}

MAX_ALLOC_PCT = 35
TARGET_TRIM_PCT = 30
BUY_CAP_PCT = 30

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
STYLE_PARAMS = {
    "scalper": {"label": "Scalper", "buy_tech": 2, "sell_hard": -2, "sell_soft": -1,
                "tp_pct": 4, "tp_tech": 1, "value_buy": 99, "alloc_cap": 40},
    "day": {"label": "Day Trader", "buy_tech": 2, "sell_hard": -3, "sell_soft": -2,
            "tp_pct": 6, "tp_tech": 0, "value_buy": 99, "alloc_cap": 38},
    "swing": {"label": "Swing Trader", "buy_tech": 3, "sell_hard": -4, "sell_soft": -2,
              "tp_pct": 25, "tp_tech": -1, "value_buy": 3, "alloc_cap": 35},
    "long": {"label": "Long-Term Investor", "buy_tech": 4, "sell_hard": -5, "sell_soft": -4,
             "tp_pct": 60, "tp_tech": -1, "value_buy": 2, "alloc_cap": 35},
}
DEFAULT_STYLE = "swing"

# "Hot & cold" awareness flags - surfaced as information, NOT trade instructions.
# Based on raw price movement, so a big drop can't be masked by an oversold RSI.
MOVER_24H_PCT = 8     # flag a 24h price move beyond +/- this %
MOVER_7D_PCT = 15     # flag a 7d move beyond +/- this % (where 7d data exists)
DRAWDOWN_PCT = 15     # flag a held position down more than this % from your avg buy


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
    "scalper": {"h": 0.5,  "sl": (1.5, 6.0),  "tp": (3.0, 12.0)},
    "day":     {"h": 1.5,  "sl": (2.0, 9.0),  "tp": (4.0, 18.0)},
    "swing":   {"h": 10.0, "sl": (5.0, 18.0), "tp": (10.0, 36.0)},
    "long":    {"h": 45.0, "sl": (10.0, 32.0), "tp": (20.0, 70.0)},
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
          targets=None):
    """Main entry. Returns {market_sentiment, briefing, recommendations}."""
    fundamentals = fundamentals or {}
    targets = targets or {}
    sp = STYLE_PARAMS.get(style) or STYLE_PARAMS[DEFAULT_STYLE]
    max_alloc = sp["alloc_cap"]
    target_trim = sp["alloc_cap"] - 5
    per_asset_news, market_sent = _match_news(assets, news_items, now_ms)

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
        alloc = (h["value"] / alloc_base * 100) if has_value and alloc_base > 0 else 0.0
        plpct = (h or {}).get("unrealized_pct")
        conviction = (tech or 0) + news_score + value_votes

        reasons = []
        action, amt = "HOLD", None

        if h and not has_value:
            reasons.append(
                "No live price available right now, so this position can't be "
                "assessed - review it manually.")
        elif h:  # ---------- assets you own
            headroom = (BUY_CAP_PCT / 100.0) * alloc_base - h["value"]
            if alloc > max_alloc and n_holdings >= 3:
                action = "TRIM"
                t = target_trim / 100.0
                if cash is not None:
                    # sale proceeds become tracked cash, so the wallet total
                    # stays the same and the sizing is direct
                    amt = h["value"] - t * capital
                    wallet_word = "wallet"
                else:
                    # no cash tracking: the sale shrinks the tracked total,
                    # so size it to land at ~TARGET of what remains
                    amt = (h["value"] - t * total) / (1 - t)
                    wallet_word = "portfolio"
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
            elif plpct is not None and plpct >= sp["tp_pct"] and tech is not None and tech <= sp["tp_tech"]:
                action = "TAKE PROFIT"
                amt = h["value"] * 0.3
                reasons.append(
                    f"You're up {plpct:.0f}% and momentum is cooling - selling ~30% "
                    "locks in profit while keeping most of the upside.")
            elif ((tech is not None and tech >= sp["buy_tech"]) or (tech is None and value_votes >= sp["value_buy"])) \
                    and news_score >= -0.5 and alloc < BUY_CAP_PCT and headroom >= 10 \
                    and (cash is None or cash >= 15):
                action = "BUY MORE"
                amt = min(0.10 * capital, headroom)
                reasons.append("Strong setup on a position you already own.")
                if news_score >= 1:
                    reasons.append("News flow around it is clearly positive.")
            else:
                action = "HOLD"
                if tech is None and not f:
                    reasons.append("Not enough price history yet for a confident call.")
                else:
                    reasons.append("Signals don't line up strongly enough either "
                                   "way - no edge; sit tight.")
            if alloc > max_alloc and n_holdings < 3:
                reasons.append(
                    f"Heads up: this is {alloc:.0f}% of the portfolio. With only "
                    f"{n_holdings} position(s) that's expected, but consider spreading "
                    "new money across more assets over time.")
        else:  # ---------- watchlist assets you don't own
            base = max(0.05 * capital, 25)
            good_setup = (tech is not None and ((tech >= sp["buy_tech"] + 1 and news_score >= 0) or
                                                (tech >= sp["buy_tech"] and news_score >= 1))) \
                or (value_votes >= sp["value_buy"] and news_score >= 0 and (tech is None or tech >= 0)) \
                or (value_votes >= 2 and tech is not None and tech >= 2)
            if good_setup and cash is not None and cash < 25:
                action = "WATCH"
                reasons.append(
                    f"Good setup, but your available cash ({currency}{max(cash, 0):,.0f}) "
                    "is too low for a meaningful buy - raise the budget on the "
                    "Portfolio tab or free up funds first.")
            elif good_setup:
                action = "BUY"
                amt = base
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

        if amt is not None:
            if action in ("TRIM", "SELL PART", "TAKE PROFIT"):
                amt = min(amt, h["value"])
                if amt < 5 or h["value"] < 20:
                    action, amt = "HOLD", None
                    reasons.insert(0, "The amount involved is too small to be worth "
                                      "selling - fees and spreads would eat the benefit.")
                else:
                    amt = min(int(round(amt / 5.0) * 5), int(h["value"]))
            else:
                # buys: never suggest more than the cash on hand; round DOWN
                # in $5 steps so the number always stays affordable
                if cash is not None:
                    amt = min(amt, cash)
                amt = max(10, int(amt // 5) * 5)
                if cash is not None and amt > cash:
                    action, amt = "WATCH", None
                    reasons.insert(0, "Good setup, but not enough available cash "
                                      "for a meaningful buy right now.")

        reasons.extend(value_reasons)
        for r in (sig.get("reasons") or [])[:3]:
            reasons.append(r)
        if articles and abs(news_score) >= 0.5:
            mood = "positive" if news_score > 0 else "negative"
            reasons.append(f"News sentiment is {mood} "
                           f"({news_score:+.1f} on a -3..+3 scale).")

        if tech is None and not f:
            confidence = "Low"
        elif abs(conviction) >= 4 and (news_score == 0 or news_score * (tech or value_votes or 0) >= 0):
            confidence = "High"
        else:
            confidence = "Medium"

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
            if tp and price >= tp:
                flags.append({"kind": "tp",
                              "text": f"Hit your take-profit ({currency}{_fmt_price(tp)})"
                                      + (f" - up {plpct:.0f}%" if plpct is not None and plpct > 0 else "")
                                      + " - your plan says consider selling"})
            elif sl and price <= sl:
                flags.append({"kind": "sl",
                              "text": f"Fell through your stop-loss ({currency}{_fmt_price(sl)})"
                                      + (f" - down {abs(plpct):.0f}%" if plpct is not None and plpct < 0 else "")
                                      + " - your plan says cut the loss"})
        # the user's own triggered plan outranks a fresh buy suggestion on the
        # same asset - never show "BUY MORE" under a tripped stop or target
        if action in ("BUY", "BUY MORE") and any(f["kind"] in ("tp", "sl") for f in flags):
            action, amt = "HOLD", None  # suggested_plan is derived below from the demoted action
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
            "conviction": round(conviction, 1),
            "confidence": confidence,
            "news_score": round(news_score, 2),
            "chg_24h": chg24,
            "flags": flags,
            "reasons": reasons,
            "articles": articles,
            "fundamentals": ({k: f.get(k) for k in
                              ("eps", "pe", "div_ps", "div_yield", "div_ex_date")}
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
                        key=lambda r: -abs(r.get("chg_24h") or 0))[:10]
        recs = sorted(held + ideas + movers,
                      key=lambda r: (-ACTION_RANK.get(r["action"], 0), -abs(r["conviction"])))

    # when the exchange is closed there is nothing to act on: suppress
    # buy/sell suggestions entirely (crypto never closes) - but keep any rec
    # carrying awareness flags (hot/cold moves, tripped stops/targets): a stop
    # hit at Friday's close must not vanish for the whole weekend
    market_open = market.get("open", True)
    if not market_open:
        recs = [r if r["action"] in ("HOLD", "WATCH")
                else {**r, "action": "HOLD", "usd": None, "qty": None}
                for r in recs if r["action"] in ("HOLD", "WATCH") or r["flags"]]

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
    }
