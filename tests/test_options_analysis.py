from tradebot.analysis.options_analysis import parse_chain
from tradebot.backtest import backtest_daily_signal

from conftest import synthetic_chain


def test_parse_chain_basics():
    a = parse_chain(synthetic_chain(spot=25000))
    assert a.spot == 25000
    assert a.atm_strike == 25000
    assert a.atm_iv and 13 < a.atm_iv < 16
    assert a.pcr is not None and a.pcr > 0
    assert a.max_pain is not None
    assert a.oi_support is not None and a.oi_support < 25000  # put OI below spot
    assert a.oi_resistance is not None and a.oi_resistance > 25000


def test_pcr_shapes_direction():
    bull = parse_chain(synthetic_chain(pcr_shape="bullish"))
    bear = parse_chain(synthetic_chain(pcr_shape="bearish"))
    assert bull.pcr > bear.pcr
    assert bull.direction_score > bear.direction_score


def test_empty_chain_safe():
    a = parse_chain({"last_price": 0, "oc": {}})
    assert a.direction_score == 0.0 and a.pcr is None


def test_backtest_runs_on_synthetic_trend():
    import math
    candles = [
        {"open": c, "high": c + 5, "low": c - 5, "close": c, "volume": 1}
        for c in (20000 + i * 12 + 60 * math.sin(i / 5) for i in range(250))
    ]
    result = backtest_daily_signal(candles)
    assert result.signal_days > 0
    assert result.hit_rate > 50  # persistent uptrend should be caught
    assert result.long_days > result.short_days
