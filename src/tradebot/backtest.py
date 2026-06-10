"""Walk-forward sanity check of the directional signal.

This backtests ONLY the daily-trend component against next-day index
returns — it does not model option pricing, IV, slippage or theta. Treat
it as a signal-quality gauge, not a P&L forecast; the paper-trading mode
is the real validation environment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis.technicals import daily_trend_score


@dataclass
class BacktestResult:
    days_tested: int
    signal_days: int
    hit_rate: float          # % of signal days where next-day move agreed
    avg_next_day_move_pct: float  # signed move in signal direction
    long_days: int
    short_days: int

    def summary(self) -> str:
        return (
            f"days tested: {self.days_tested} | signal days: {self.signal_days} "
            f"({self.long_days} long / {self.short_days} short)\n"
            f"hit rate: {self.hit_rate:.1f}% | avg next-day move in signal "
            f"direction: {self.avg_next_day_move_pct:+.3f}%\n"
            "note: directional-signal test only — option P&L (theta/IV/slippage) "
            "not modelled; validate with paper mode."
        )


def backtest_daily_signal(candles: list[dict], threshold: float = 0.3,
                          warmup: int = 80) -> BacktestResult:
    closes = [c["close"] for c in candles]
    hits = misses = long_days = short_days = 0
    moves: list[float] = []
    for i in range(warmup, len(candles) - 1):
        window = candles[: i + 1]
        score = daily_trend_score(window).score
        if abs(score) < threshold:
            continue
        direction = 1 if score > 0 else -1
        long_days += direction > 0
        short_days += direction < 0
        ret = (closes[i + 1] - closes[i]) / closes[i] * 100.0
        signed = ret * direction
        moves.append(signed)
        if signed > 0:
            hits += 1
        else:
            misses += 1
    signal_days = hits + misses
    return BacktestResult(
        days_tested=max(0, len(candles) - warmup - 1),
        signal_days=signal_days,
        hit_rate=(hits / signal_days * 100.0) if signal_days else 0.0,
        avg_next_day_move_pct=(sum(moves) / len(moves)) if moves else 0.0,
        long_days=long_days,
        short_days=short_days,
    )
