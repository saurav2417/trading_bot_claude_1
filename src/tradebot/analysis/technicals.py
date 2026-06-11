"""Convert raw candles into directional scores.

Two horizons, mirroring how Varsity frames a 'view':
  - daily trend (EMA structure, supertrend, ADX-gated)
  - intraday momentum (15-min RSI + MACD)
Each returns a score in [-1, +1].
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .indicators import adx, ema, macd, rsi, supertrend


@dataclass
class TechnicalRead:
    score: float                       # [-1, 1]
    detail: dict[str, float | str] = field(default_factory=dict)


def daily_trend_score(daily_candles: list[dict]) -> TechnicalRead:
    closes = [c["close"] for c in daily_candles]
    if len(closes) < 60:
        return TechnicalRead(0.0, {"note": "insufficient daily history"})

    e20, e50 = ema(closes, 20), ema(closes, 50)
    st = supertrend(daily_candles, 10, 3.0)
    ax = adx(daily_candles, 14)
    last = closes[-1]

    score = 0.0
    detail: dict[str, float | str] = {}

    # EMA structure: price vs EMA20 vs EMA50 (max +/-0.5)
    if e20[-1] is not None and e50[-1] is not None:
        ema_score = 0.0
        ema_score += 0.25 if last > e20[-1] else -0.25
        ema_score += 0.25 if e20[-1] > e50[-1] else -0.25
        score += ema_score
        detail["ema20"] = round(e20[-1], 2)
        detail["ema50"] = round(e50[-1], 2)
        detail["ema_score"] = ema_score

    # Supertrend direction (max +/-0.5)
    if st[-1] is not None:
        score += 0.5 * st[-1]
        detail["supertrend"] = "UP" if st[-1] == 1 else "DOWN"

    # ADX gate: weak trend (<20) halves the score; strong (>25) keeps it
    if ax[-1] is not None:
        detail["adx"] = round(ax[-1], 1)
        if ax[-1] < 20:
            score *= 0.5
            detail["adx_gate"] = "weak trend, score halved"

    return TechnicalRead(max(-1.0, min(1.0, score)), detail)


def regime_check(daily_candles: list[dict], cfg: dict) -> tuple[bool, str]:
    """Is the market trending enough to justify directional trades?

    Returns (trending, note). Chop = weak ADX or a compressed recent range;
    trend systems give back their edge in chop via stop-out bleed, so the
    selector refuses directional structures when this returns False
    (range-bound structures like iron condors remain allowed).
    """
    if not cfg or not cfg.get("enabled", False):
        return True, "regime filter off"
    if len(daily_candles) < 40:
        return True, "regime filter: insufficient history, not applied"

    min_adx = float(cfg.get("min_daily_adx", 18))
    days = int(cfg.get("range_compression_days", 5))
    min_range_pct = float(cfg.get("range_compression_pct", 1.2))

    ax = adx(daily_candles, 14)[-1]
    recent = daily_candles[-days:]
    close = daily_candles[-1]["close"]
    range_pct = ((max(c["high"] for c in recent) - min(c["low"] for c in recent))
                 / close * 100.0) if close else 0.0

    if ax is not None and ax < min_adx:
        return False, f"chop: ADX {ax:.1f} < {min_adx}"
    if range_pct < min_range_pct:
        return False, f"chop: {days}-day range {range_pct:.2f}% < {min_range_pct}%"
    return True, f"trending: ADX {ax:.1f}, {days}-day range {range_pct:.2f}%"


def intraday_momentum_score(intraday_candles: list[dict]) -> TechnicalRead:
    closes = [c["close"] for c in intraday_candles]
    if len(closes) < 40:
        return TechnicalRead(0.0, {"note": "insufficient intraday history"})

    r = rsi(closes, 14)
    macd_line, signal_line, hist = macd(closes)
    score = 0.0
    detail: dict[str, float | str] = {}

    if r[-1] is not None:
        detail["rsi14"] = round(r[-1], 1)
        # RSI mapped linearly: 50 -> 0, 70 -> +0.5, 30 -> -0.5 (capped)
        score += max(-0.5, min(0.5, (r[-1] - 50.0) / 40.0))

    if hist[-1] is not None and macd_line[-1] is not None and signal_line[-1] is not None:
        detail["macd_hist"] = round(hist[-1], 2)
        score += 0.3 if macd_line[-1] > signal_line[-1] else -0.3
        # histogram expanding in the direction of the signal adds conviction
        if len(hist) >= 2 and hist[-2] is not None:
            if hist[-1] > hist[-2] > 0 or hist[-1] < hist[-2] < 0:
                score += 0.2 if hist[-1] > 0 else -0.2

    return TechnicalRead(max(-1.0, min(1.0, score)), detail)
