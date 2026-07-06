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


def _round_amt(v, floor=10):
    return max(floor, int(round(v / 5.0) * 5))


def build(assets, signals, portfolio, news_items, market, now_ms,
          currency="$", fundamentals=None, max_ideas=None):
    """Main entry. Returns {market_sentiment, briefing, recommendations}."""
    fundamentals = fundamentals or {}
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
            if alloc > MAX_ALLOC_PCT and n_holdings >= 3:
                action = "TRIM"
                t = TARGET_TRIM_PCT / 100.0
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
                    f"it around) brings it down to about {TARGET_TRIM_PCT}%.")
                if tech is not None and tech <= -2:
                    reasons.append("Technicals are weak too, which strengthens the case.")
            elif tech is not None and (tech <= -4 or
                                       (tech <= -2 and (news_score <= -1 or value_votes <= -1))):
                action = "SELL PART"
                amt = h["value"] * 0.5
                reasons.append("Multiple technical indicators point down at once.")
                if news_score <= -1:
                    reasons.append("Recent news coverage is negative as well.")
                if plpct is not None and plpct < 0:
                    reasons.append(
                        f"You're down {abs(plpct):.0f}% on this position - reducing "
                        "now limits further damage if the slide continues.")
            elif plpct is not None and plpct >= 25 and tech is not None and tech <= -1:
                action = "TAKE PROFIT"
                amt = h["value"] * 0.3
                reasons.append(
                    f"You're up {plpct:.0f}% and momentum is cooling - selling ~30% "
                    "locks in profit while keeping most of the upside.")
            elif ((tech is not None and tech >= 3) or (tech is None and value_votes >= 3)) \
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
            if alloc > MAX_ALLOC_PCT and n_holdings < 3:
                reasons.append(
                    f"Heads up: this is {alloc:.0f}% of the portfolio. With only "
                    f"{n_holdings} position(s) that's expected, but consider spreading "
                    "new money across more assets over time.")
        else:  # ---------- watchlist assets you don't own
            base = max(0.05 * capital, 25)
            good_setup = (tech is not None and ((tech >= 4 and news_score >= 0) or
                                                (tech >= 3 and news_score >= 1))) \
                or (value_votes >= 3 and news_score >= 0 and (tech is None or tech >= 0)) \
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

        recs.append({
            "asset_id": aid,
            "name": a.get("name") or aid,
            "symbol": a.get("symbol") or "",
            "image": a.get("image"),
            "price": price,
            "action": action,
            "usd": amt,
            "qty": (amt / price) if amt and price else None,
            "conviction": round(conviction, 1),
            "confidence": confidence,
            "news_score": round(news_score, 2),
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

    # big universes (PSE = 283 companies): keep every holding, cap the ideas
    if max_ideas is not None:
        held = [r for r in recs if r["holding"]]
        ideas = [r for r in recs if not r["holding"] and r["action"] != "HOLD"][:max_ideas]
        recs = sorted(held + ideas,
                      key=lambda r: (-ACTION_RANK.get(r["action"], 0), -abs(r["conviction"])))

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
    if actionable:
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
    }
