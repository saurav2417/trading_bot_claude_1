import math

import pytest

from tradebot.config import Underlying
from tradebot.strategy import strategies as st

U = Underlying(name="NIFTY", security_id=13, lot_size=75, strike_step=50)
EXPIRY = "2099-12-31"


def test_long_call_economics(chain):
    plan = st.long_call(U, EXPIRY, chain, lots=1)
    leg = plan.legs[0]
    assert leg.strike == 25000 and leg.option_type == "CE" and leg.action == "BUY"
    debit = leg.price * 75
    assert math.isclose(plan.net_premium, -debit)
    assert math.isclose(plan.max_loss, debit)
    assert plan.max_profit == float("inf")
    # breakeven = strike + premium
    assert any(abs(b - (25000 + leg.price)) < 2 for b in plan.breakevens)


def test_long_put_economics(chain):
    plan = st.long_put(U, EXPIRY, chain, lots=1)
    leg = plan.legs[0]
    assert leg.option_type == "PE" and leg.action == "BUY"
    assert math.isclose(plan.max_loss, leg.price * 75)
    assert plan.max_profit < float("inf")  # put upside bounded by strike


def test_bull_call_spread_payoff(chain):
    plan = st.bull_call_spread(U, EXPIRY, chain, lots=1, width_steps=3)
    buy, sell = plan.legs
    assert buy.strike == 25000 and sell.strike == 25150
    debit = -plan.net_premium
    assert debit > 0
    width_value = (sell.strike - buy.strike) * 75
    assert math.isclose(plan.max_loss, debit, rel_tol=1e-6)
    assert math.isclose(plan.max_profit, width_value - debit, rel_tol=1e-6)
    # deep ITM payoff equals max profit
    assert math.isclose(plan.payoff_at(27000), plan.max_profit, rel_tol=1e-6)
    assert math.isclose(plan.payoff_at(23000), -plan.max_loss, rel_tol=1e-6)


def test_bear_put_spread_payoff(chain):
    plan = st.bear_put_spread(U, EXPIRY, chain, lots=1, width_steps=3)
    buy, sell = plan.legs
    assert buy.strike > sell.strike
    assert plan.payoff_at(23000) > 0 > plan.payoff_at(26000)


def test_bull_put_spread_credit_and_risk(chain):
    plan = st.bull_put_spread(U, EXPIRY, chain, lots=1, wing_steps=4)
    short = next(l for l in plan.legs if l.action == "SELL")
    wing = next(l for l in plan.legs if l.action == "BUY")
    assert short.strike > wing.strike
    assert short.strike < chain.spot  # OTM put sold
    credit = plan.net_premium
    assert credit > 0
    width_value = (short.strike - wing.strike) * 75
    assert math.isclose(plan.max_loss, width_value - credit, rel_tol=1e-6)
    assert math.isclose(plan.max_profit, credit, rel_tol=1e-6)


def test_bear_call_spread_credit(chain):
    plan = st.bear_call_spread(U, EXPIRY, chain, lots=1)
    short = next(l for l in plan.legs if l.action == "SELL")
    assert short.option_type == "CE" and short.strike > chain.spot
    assert plan.net_premium > 0 and plan.max_loss < float("inf")


def test_iron_condor_structure(chain):
    plan = st.iron_condor(U, EXPIRY, chain, lots=1)
    assert len(plan.legs) == 4
    assert plan.net_premium > 0
    assert plan.max_loss < float("inf")
    # profitable in the middle, losing at the edges
    assert plan.payoff_at(chain.spot) > 0
    assert plan.payoff_at(chain.spot * 1.06) < 0
    assert plan.payoff_at(chain.spot * 0.94) < 0
    assert len(plan.breakevens) == 2


def test_delta_based_short_strike_selection(chain):
    plan = st.bull_put_spread(U, EXPIRY, chain, lots=1)
    short = next(l for l in plan.legs if l.action == "SELL")
    from tradebot.analysis.options_analysis import leg_delta
    d = abs(leg_delta(chain, short.strike, "PE"))
    assert 0.15 <= d <= 0.40  # near the 0.28 target


def test_naked_short_flagged_unbounded(chain):
    from tradebot.strategy.base import OptionLeg, TradePlan
    naked = TradePlan(
        strategy="X", underlying="NIFTY", spot=25000, expiry=EXPIRY,
        legs=[OptionLeg("NIFTY", EXPIRY, 25200, "CE", "SELL", 1, 75, 100.0)],
        rationale="",
    )
    assert naked.max_loss == float("inf")
