"""Technical indicators over plain candle lists (no pandas dependency).

A candle is a dict with keys: open, high, low, close, volume.
All functions return lists aligned with the input; warm-up slots are None.
"""

from __future__ import annotations


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= period:
            acc -= values[i - period]
        if i >= period - 1:
            out[i] = acc / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period  # seed with SMA
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains += max(diff, 0.0)
        losses += max(-diff, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """-> (macd_line, signal_line, histogram), each aligned with input."""
    n = len(values)
    fast_e, slow_e = ema(values, fast), ema(values, slow)
    macd_line: list[float | None] = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(fast_e, slow_e)
    ]
    valid = [(i, m) for i, m in enumerate(macd_line) if m is not None]
    signal_line: list[float | None] = [None] * n
    if valid:
        idxs, vals = zip(*valid)
        sig_vals = ema(list(vals), signal)
        for j, i in enumerate(idxs):
            signal_line[i] = sig_vals[j]
    hist = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, hist


def true_range(candles: list[dict]) -> list[float]:
    out = []
    for i, c in enumerate(candles):
        if i == 0:
            out.append(c["high"] - c["low"])
        else:
            pc = candles[i - 1]["close"]
            out.append(max(c["high"] - c["low"], abs(c["high"] - pc), abs(c["low"] - pc)))
    return out


def atr(candles: list[dict], period: int = 14) -> list[float | None]:
    """Wilder-smoothed ATR."""
    tr = true_range(candles)
    out: list[float | None] = [None] * len(candles)
    if len(candles) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(candles)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def adx(candles: list[dict], period: int = 14) -> list[float | None]:
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < 2 * period + 1:
        return out
    plus_dm, minus_dm = [0.0], [0.0]
    for i in range(1, n):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr = true_range(candles)

    def wilder_sum(vals: list[float]) -> list[float | None]:
        res: list[float | None] = [None] * n
        s = sum(vals[1:period + 1])
        res[period] = s
        for i in range(period + 1, n):
            s = s - s / period + vals[i]
            res[i] = s
        return res

    tr_s, pdm_s, mdm_s = wilder_sum(tr), wilder_sum(plus_dm), wilder_sum(minus_dm)
    dx: list[float | None] = [None] * n
    for i in range(period, n):
        if tr_s[i]:
            pdi = 100.0 * pdm_s[i] / tr_s[i]
            mdi = 100.0 * mdm_s[i] / tr_s[i]
            denom = pdi + mdi
            dx[i] = 100.0 * abs(pdi - mdi) / denom if denom else 0.0
    first = 2 * period
    out[first] = sum(dx[period + 1: first + 1]) / period
    for i in range(first + 1, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


def supertrend(candles: list[dict], period: int = 10, multiplier: float = 3.0):
    """-> list of +1 (uptrend) / -1 (downtrend) / None per candle."""
    n = len(candles)
    a = atr(candles, period)
    trend: list[int | None] = [None] * n
    upper = lower = None
    direction = 1
    for i in range(n):
        if a[i] is None:
            continue
        mid = (candles[i]["high"] + candles[i]["low"]) / 2.0
        ub = mid + multiplier * a[i]
        lb = mid - multiplier * a[i]
        close = candles[i]["close"]
        prev_close = candles[i - 1]["close"] if i else close
        upper = ub if upper is None or ub < upper or prev_close > upper else upper
        lower = lb if lower is None or lb > lower or prev_close < lower else lower
        if direction == 1 and close < lower:
            direction = -1
            upper = ub
        elif direction == -1 and close > upper:
            direction = 1
            lower = lb
        trend[i] = direction
    return trend


def bollinger(values: list[float], period: int = 20, num_std: float = 2.0):
    """-> (middle, upper, lower) bands."""
    mid = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        m = mid[i]
        var = sum((v - m) ** 2 for v in window) / period
        sd = var ** 0.5
        upper[i] = m + num_std * sd
        lower[i] = m - num_std * sd
    return mid, upper, lower
