import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradebot.simulator import (Simulator, bs_delta, bs_price, render_report,
                                strike_by_delta)

from conftest import make_settings

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------- pricing sanity
def test_put_call_parity():
    s, k, t, iv, r = 25000.0, 25100.0, 0.02, 0.14, 0.065
    call = bs_price(s, k, t, iv, "CE", r)
    put = bs_price(s, k, t, iv, "PE", r)
    assert math.isclose(call - put, s - k * math.exp(-r * t), abs_tol=0.5)


def test_bs_intrinsic_at_expiry():
    assert bs_price(25000, 24800, 0.0, 0.14, "CE") == 200.0
    assert bs_price(25000, 25200, 0.0, 0.14, "PE") == 200.0
    assert bs_price(25000, 26000, 0.0, 0.14, "CE") == 0.05  # floor


def test_bs_monotonic_in_vol_and_time():
    base = bs_price(25000, 25000, 0.02, 0.12, "CE")
    assert bs_price(25000, 25000, 0.02, 0.20, "CE") > base
    assert bs_price(25000, 25000, 0.05, 0.12, "CE") > base


def test_delta_behaviour():
    assert 0.45 < bs_delta(25000, 25000, 0.02, 0.14, "CE") < 0.60
    assert -0.60 < bs_delta(25000, 25000, 0.02, 0.14, "PE") < -0.40
    assert bs_delta(25000, 26500, 0.02, 0.14, "CE") < 0.05


def test_strike_by_delta_is_otm():
    k = strike_by_delta(25000, 0.02, 0.14, "PE", 0.28, 50)
    assert k < 25000
    assert abs(abs(bs_delta(25000, k, 0.02, 0.14, "PE")) - 0.28) < 0.08


# --------------------------------------------------------- engine end-to-end
def _trading_days(end: date, n: int) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def synthetic_market(trend_per_day: float = -40.0, n_daily: int = 320,
                     n_intraday_days: int = 15):
    end = date(2026, 6, 5)  # a Friday
    days = _trading_days(end, n_daily)
    px = 26000.0
    daily = []
    for d in days:
        px += trend_per_day
        daily.append({"open": px - 10, "high": px + 30, "low": px - 30,
                      "close": px, "volume": 1e6,
                      "time": datetime.combine(d, time(15, 30), tzinfo=IST)})
    intraday = []
    intraday_days = days[-n_intraday_days:]
    base = px - trend_per_day * n_intraday_days
    for d in intraday_days:
        base += trend_per_day
        for i, minutes in enumerate(range(0, 365, 15)):
            ts = datetime.combine(d, time(9, 15), tzinfo=IST) + timedelta(minutes=minutes)
            p = base + trend_per_day * (i / 25.0)
            intraday.append({"open": p, "high": p + 8, "low": p - 8,
                             "close": p, "volume": 1e5, "time": ts})
    vix = {d.isoformat(): 14.0 for d in intraday_days}
    return daily, intraday, vix


def test_simulation_runs_and_trades(tmp_path):
    settings = make_settings(tmp_path)
    daily, intraday, vix = synthetic_market()
    sim = Simulator(settings, daily, intraday, vix, weeks=2)
    result = sim.run()

    assert result.days_tested == 10
    assert result.scans > 0
    assert len(result.closed) > 0, "persistent downtrend should produce trades"
    assert not [t for t in result.trades if t.status == "OPEN"]
    # intraday product: every trade closed the day it was opened
    for t in result.closed:
        if t.exit_time is not None:
            assert t.exit_time.date() == t.entry_time.date()
    # downtrend + NORMAL vol => bearish debit strategies only
    assert {t.strategy for t in result.closed} <= {"BEAR_PUT_SPREAD", "LONG_PUT"}
    # accounting consistency
    assert math.isclose(result.end_capital - result.start_capital,
                        sum(t.pnl for t in result.closed), abs_tol=0.05)
    assert all(t.charges > 0 for t in result.closed)


def test_simulation_respects_risk_caps(tmp_path):
    settings = make_settings(tmp_path)
    daily, intraday, vix = synthetic_market()
    sim = Simulator(settings, daily, intraday, vix, weeks=2)
    result = sim.run()
    per_day: dict[str, int] = {}
    for t in result.closed:
        key = t.entry_time.date().isoformat()
        per_day[key] = per_day.get(key, 0) + 1
        assert t.planned_risk <= settings.capital * 0.03 * 1.6  # cap vs evolving capital
    assert max(per_day.values()) <= 3


def test_report_renders(tmp_path):
    settings = make_settings(tmp_path)
    daily, intraday, vix = synthetic_market()
    result = Simulator(settings, daily, intraday, vix, weeks=2).run()
    report = render_report(result, 2)
    assert "Historical simulation" in report
    assert "Caveats" in report
    assert "profit factor" in report
