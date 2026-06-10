import math

from tradebot.config import Underlying
from tradebot.journal.journal import Journal
from tradebot.risk.risk_manager import RiskManager, planned_risk
from tradebot.strategy import strategies as st
from tradebot.strategy.base import OptionLeg, TradePlan

from conftest import make_settings, synthetic_chain

U = Underlying(name="NIFTY", security_id=13, lot_size=75, strike_step=50)
EXPIRY = "2099-12-31"


def setup(tmp_path, **over):
    settings = make_settings(tmp_path, **over)
    journal = Journal(settings.db_path)
    return settings, journal, RiskManager(settings, journal)


def parsed_chain():
    from tradebot.analysis.options_analysis import parse_chain
    return parse_chain(synthetic_chain())


def test_planned_risk_debit(tmp_path):
    settings, _, _ = setup(tmp_path)
    plan = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    debit = -plan.net_premium
    assert math.isclose(planned_risk(plan, settings), debit * 0.30, rel_tol=1e-6)


def test_planned_risk_credit_capped_by_max_loss(tmp_path):
    settings, _, _ = setup(tmp_path)
    plan = st.bull_put_spread(U, EXPIRY, parsed_chain(), lots=1)
    credit = plan.net_premium
    expected = min(credit * 1.5, plan.max_loss)
    assert math.isclose(planned_risk(plan, settings), expected, rel_tol=1e-6)


def test_unbounded_plan_rejected(tmp_path):
    _, _, rm = setup(tmp_path)
    naked = TradePlan(
        strategy="X", underlying="NIFTY", spot=25000, expiry=EXPIRY,
        legs=[OptionLeg("NIFTY", EXPIRY, 25200, "CE", "SELL", 1, 75, 100.0)],
        rationale="")
    verdict = rm.evaluate(naked)
    assert not verdict and "unbounded" in verdict.reason


def test_risk_cap_rejects_oversized_trade(tmp_path):
    # 1% cap on 50k = ₹500; an ATM long call risks ~30% of ~₹12k premium
    _, _, rm = setup(tmp_path, risk={"max_risk_per_trade_pct": 1.0})
    plan = st.long_call(U, EXPIRY, parsed_chain(), lots=1)
    verdict = rm.evaluate(plan)
    assert not verdict and "exceeds per-trade cap" in verdict.reason


def test_daily_loss_kill_switch(tmp_path):
    settings, journal, rm = setup(tmp_path)
    plan = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    journal.record_open(plan, "paper", 1000.0)
    journal.record_close(plan.plan_id, {}, -3000.0, "stop loss")  # > 5% of 50k... (2500)
    assert rm.daily_loss_breached()
    plan2 = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    verdict = rm.evaluate(plan2)
    assert not verdict and "kill switch" in verdict.reason


def test_max_open_positions(tmp_path):
    settings, journal, rm = setup(tmp_path, risk={"max_open_positions": 1})
    p1 = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    journal.record_open(p1, "paper", 1000.0)
    p2 = st.bear_put_spread(U, EXPIRY, parsed_chain(), lots=1)
    verdict = rm.evaluate(p2)
    assert not verdict and "max open positions" in verdict.reason


def test_capital_tracks_realized_pnl(tmp_path):
    settings, journal, rm = setup(tmp_path)
    assert rm.capital_now() == 50000
    p = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    journal.record_open(p, "paper", 1000.0)
    journal.record_close(p.plan_id, {}, 1500.0, "target")
    assert rm.capital_now() == 51500


def test_size_lots_returns_largest_passing(tmp_path):
    settings, journal, rm = setup(
        tmp_path, risk={"max_risk_per_trade_pct": 100.0},
        max_capital_per_trade=10_000_000, capital=10_000_000.0)
    chain = parsed_chain()

    def build(lots):
        return st.bull_call_spread(U, EXPIRY, chain, lots=lots)

    plan = rm.size_lots(build, max_lots=2)
    assert plan is not None and plan.legs[0].lots == 2


def test_entry_cooldown_blocks_back_to_back_trades(tmp_path):
    _, journal, rm = setup(tmp_path, risk={"entry_cooldown_minutes": 45})
    p1 = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    journal.record_open(p1, "paper", 1000.0)  # opened_at = now
    p2 = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    verdict = rm.evaluate(p2)
    assert not verdict and "cooldown" in verdict.reason


def test_no_cooldown_when_disabled(tmp_path):
    _, journal, rm = setup(tmp_path, risk={"entry_cooldown_minutes": 0})
    p1 = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    journal.record_open(p1, "paper", 1000.0)
    p2 = st.bear_put_spread(U, EXPIRY, parsed_chain(), lots=1)
    assert rm.evaluate(p2)


def test_size_lots_none_when_nothing_fits(tmp_path):
    _, _, rm = setup(tmp_path, risk={"max_risk_per_trade_pct": 0.01})
    chain = parsed_chain()
    plan = rm.size_lots(lambda lots: st.long_call(U, EXPIRY, chain, lots=lots))
    assert plan is None
