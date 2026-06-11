import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.config import Settings, Underlying  # noqa: E402


def make_settings(tmp_path: Path, mode: str = "paper", **overrides) -> Settings:
    risk = {
        "max_risk_per_trade_pct": 3.0,
        "max_daily_loss_pct": 5.0,
        "max_open_positions": 2,
        "max_trades_per_day": 3,
        "entry_cooldown_minutes": 0,  # off by default in tests; covered explicitly
        "stop_loss_premium_pct": 30,
        "target_premium_pct": 60,
        "trail_after_r": 1.0,
        "trail_lock_r": 0.5,
        "credit_profit_take_pct": 50,
        "credit_stop_multiple": 1.5,
        "max_spread_width": 300,
    }
    risk.update(overrides.pop("risk", {}))
    signals = {
        "direction_threshold": 30,
        "strong_direction_threshold": 55,
        "min_confidence": 0.5,
        "vix_high": 17.0,
        "vix_low": 12.5,
    }
    signals.update(overrides.pop("signals", {}))
    return Settings(
        raw={},
        mode=mode,
        capital=overrides.pop("capital", 50000.0),
        max_capital_per_trade=overrides.pop("max_capital_per_trade", 40000.0),
        underlyings=[Underlying(name="NIFTY", security_id=13, lot_size=75,
                                strike_step=50)],
        risk=risk,
        schedule={"timezone": "Asia/Kolkata"},
        signals=signals,
        execution={"product_type": "INTRADAY", "order_type": "LIMIT",
                   "limit_buffer_pct": 0.5},
        notifications={},
        llm=overrides.pop("llm", {}),
        db_path=tmp_path / "test.db",
        cache_dir=tmp_path / "cache",
        reports_dir=tmp_path / "reports",
        regime=overrides.pop("regime", {}),
        events=overrides.pop("events", {}),
    )


def synthetic_chain(spot: float = 25000.0, step: int = 50,
                    span: int = 1000, pcr_shape: str = "neutral") -> dict:
    """Dhan-format option chain with sane premiums, deltas and OI."""
    oc = {}
    lo = int(spot - span)
    hi = int(spot + span)
    for strike in range(lo, hi + step, step):
        dist = strike - spot
        tv = max(5.0, 160.0 - abs(dist) * 0.22)
        ce_price = max(0.0, -dist) + tv
        pe_price = max(0.0, dist) + tv
        ce_delta = min(0.98, max(0.02, 0.5 - dist / 1200.0))
        pe_delta = ce_delta - 1.0

        ce_oi = 500_000 + max(0, dist) * 800          # call writers above spot
        pe_oi = 500_000 + max(0, -dist) * 800         # put writers below spot
        if pcr_shape == "bullish":
            pe_oi *= 1.8
        elif pcr_shape == "bearish":
            ce_oi *= 1.8

        oc[f"{strike:.6f}"] = {
            "ce": {"last_price": round(ce_price, 2), "oi": ce_oi,
                   "implied_volatility": 14.0, "volume": 10000,
                   "greeks": {"delta": round(ce_delta, 3)}},
            "pe": {"last_price": round(pe_price, 2), "oi": pe_oi,
                   "implied_volatility": 14.5, "volume": 10000,
                   "greeks": {"delta": round(pe_delta, 3)}},
        }
    return {"last_price": spot, "oc": oc}


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def chain():
    from tradebot.analysis.options_analysis import parse_chain
    return parse_chain(synthetic_chain())
