"""Technical-indicator math and the buy/sell signal engine.

Signals are computed from stored hourly closing prices:
  - RSI(14)            - overbought / oversold gauge
  - SMA 24h vs SMA 7d  - short-term trend vs longer trend
  - MACD (12/26/9)     - momentum direction
  - 24h price change   - immediate momentum

Each indicator votes; the votes sum to a score which maps to
STRONG BUY / BUY / HOLD / SELL / STRONG SELL. These are informational
technical signals, not financial advice.
"""


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema_series(values, n):
    """EMA aligned to values[n-1:]. Empty list if not enough data."""
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(closes[:-1], closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd(closes):
    """Return (macd_line, signal_line, histogram) or None."""
    if len(closes) < 26 + 9:
        return None
    e12 = ema_series(closes, 12)   # aligned to closes[11:]
    e26 = ema_series(closes, 26)   # aligned to closes[25:]
    line = [a - b for a, b in zip(e12[14:], e26)]
    sig = ema_series(line, 9)
    if not sig:
        return None
    return line[-1], sig[-1], line[-1] - sig[-1]


def compute(closes, chg_24h=None):
    """closes: hourly closing prices, oldest first."""
    if len(closes) < 48:
        return {
            "action": "WAIT",
            "score": 0,
            "reasons": ["Still collecting hourly price history for this coin."],
            "indicators": {},
        }

    price = closes[-1]
    score = 0
    reasons = []
    ind = {"price": price}

    r = rsi(closes)
    if r is not None:
        ind["rsi"] = round(r, 1)
        if r < 30:
            score += 2
            reasons.append(f"RSI {r:.0f} - oversold, often a buying zone")
        elif r < 40:
            score += 1
            reasons.append(f"RSI {r:.0f} - approaching oversold")
        elif r > 70:
            score -= 2
            reasons.append(f"RSI {r:.0f} - overbought, pullback risk")
        elif r > 60:
            score -= 1
            reasons.append(f"RSI {r:.0f} - getting stretched")
        else:
            reasons.append(f"RSI {r:.0f} - neutral")

    long_n = min(168, len(closes) - 1)  # up to 7 days of hours
    s24 = sma(closes, 24)
    s_long = sma(closes, long_n)
    if s24 is not None and s_long is not None:
        ind["sma_24h"] = s24
        ind["sma_7d"] = s_long
        if price > s_long:
            score += 1
            reasons.append("Price above its 7-day average - uptrend")
        else:
            score -= 1
            reasons.append("Price below its 7-day average - downtrend")
        if s24 > s_long:
            score += 1
            reasons.append("1-day average above 7-day average - bullish momentum")
        else:
            score -= 1
            reasons.append("1-day average below 7-day average - bearish momentum")

    m = macd(closes)
    if m is not None:
        line, sig_line, hist = m
        ind["macd_hist"] = hist
        if line > sig_line:
            score += 1
            reasons.append("MACD above its signal line - momentum turning up")
        else:
            score -= 1
            reasons.append("MACD below its signal line - momentum turning down")

    if chg_24h is not None:
        ind["chg_24h"] = round(chg_24h, 2)
        if chg_24h > 2:
            score += 1
            reasons.append(f"Up {chg_24h:.1f}% in 24h")
        elif chg_24h < -2:
            score -= 1
            reasons.append(f"Down {abs(chg_24h):.1f}% in 24h")

    if score >= 4:
        action = "STRONG BUY"
    elif score >= 2:
        action = "BUY"
    elif score <= -4:
        action = "STRONG SELL"
    elif score <= -2:
        action = "SELL"
    else:
        action = "HOLD"

    return {"action": action, "score": score, "reasons": reasons, "indicators": ind}
