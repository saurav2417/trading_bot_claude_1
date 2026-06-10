import math

from tradebot.analysis.indicators import (adx, atr, bollinger, ema, macd, rsi,
                                          sma, supertrend)


def make_candles(closes, spread=5.0):
    return [
        {"open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1000}
        for c in closes
    ]


def test_sma_basic():
    out = sma([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0 and out[4] == 4.0


def test_ema_converges_to_constant():
    out = ema([10.0] * 50, 10)
    assert out[9] == 10.0
    assert math.isclose(out[-1], 10.0)


def test_ema_rises_with_uptrend():
    values = list(range(1, 101))
    out = ema([float(v) for v in values], 20)
    assert out[-1] > out[-10] > out[-20]
    assert out[-1] < values[-1]  # EMA lags price in a steady uptrend


def test_rsi_bounds_and_direction():
    up = [float(i) for i in range(1, 40)]
    down = [float(40 - i) for i in range(1, 40)]
    assert rsi(up, 14)[-1] == 100.0
    assert rsi(down, 14)[-1] == 0.0
    flat_then_up = [100.0] * 20 + [100 + i for i in range(20)]
    r = rsi(flat_then_up, 14)[-1]
    assert 50 < r <= 100


def test_macd_sign_in_trend():
    up = [100 + i * 0.5 for i in range(80)]
    macd_line, signal_line, hist = macd(up)
    assert macd_line[-1] > 0
    down = [100 - i * 0.5 for i in range(80)]
    macd_line, _, _ = macd(down)
    assert macd_line[-1] < 0


def test_atr_positive_and_scales():
    calm = make_candles([100.0] * 30, spread=1.0)
    wild = make_candles([100.0] * 30, spread=10.0)
    assert atr(wild, 14)[-1] > atr(calm, 14)[-1] > 0


def test_adx_strong_trend_high():
    trending = make_candles([100 + i * 2.0 for i in range(60)])
    choppy = make_candles([100 + (3 if i % 2 else -3) for i in range(60)])
    assert adx(trending, 14)[-1] > 25
    assert adx(trending, 14)[-1] > adx(choppy, 14)[-1]


def test_supertrend_direction():
    up = make_candles([100 + i * 2.0 for i in range(60)])
    down = make_candles([300 - i * 2.0 for i in range(60)])
    assert supertrend(up)[-1] == 1
    assert supertrend(down)[-1] == -1


def test_bollinger_contains_price_mostly():
    closes = [100 + math.sin(i / 3) * 2 for i in range(60)]
    mid, upper, lower = bollinger(closes, 20)
    assert lower[-1] < mid[-1] < upper[-1]
