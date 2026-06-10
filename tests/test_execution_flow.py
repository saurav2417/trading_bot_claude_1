"""End-to-end paper-trade lifecycle: open -> monitor -> exit -> journal."""

import math

from tradebot.config import Underlying
from tradebot.execution.executor import Executor
from tradebot.execution.position_monitor import PositionMonitor
from tradebot.journal.journal import Journal
from tradebot.strategy import strategies as st

from conftest import make_settings, synthetic_chain

U = Underlying(name="NIFTY", security_id=13, lot_size=75, strike_step=50)
EXPIRY = "2099-12-31"


class FakeClient:
    """Stands in for DhanClient: scrip-master lookups and LTP quotes."""

    def __init__(self):
        self.quotes: dict[int, float] = {}
        self._next_id = 1000

    def resolve_option(self, underlying, expiry, strike, option_type):
        self._next_id += 1
        return {"security_id": self._next_id, "lot_size": 75,
                "trading_symbol": f"{underlying}{strike:.0f}{option_type}"}

    def option_ltp(self, security_ids):
        return {sid: self.quotes[sid] for sid in security_ids if sid in self.quotes}


def setup(tmp_path):
    settings = make_settings(tmp_path, mode="paper")
    journal = Journal(settings.db_path)
    client = FakeClient()
    executor = Executor(settings, client, journal)
    monitor = PositionMonitor(settings, executor, journal)
    return settings, journal, client, executor, monitor


def parsed_chain():
    from tradebot.analysis.options_analysis import parse_chain
    return parse_chain(synthetic_chain())


def open_spread(executor, journal):
    plan = st.bull_call_spread(U, EXPIRY, parsed_chain(), lots=1)
    assert executor.open_trade(plan, planned_risk=1500.0)
    trades = journal.open_trades()
    assert len(trades) == 1
    return plan, trades[0]


def set_quotes(client, trade, move: float):
    """Move every leg premium by `move` points (long leg gains when +)."""
    for leg in trade["legs"]:
        delta = move if leg["action"] == "BUY" else -move * 0.4
        client.quotes[leg["security_id"]] = max(0.05, leg["entry_price"] + delta)


def test_paper_open_records_slippage(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    plan, trade = open_spread(executor, journal)
    buy_leg = next(l for l in trade["legs"] if l["action"] == "BUY")
    plan_buy = next(l for l in plan.legs if l.action == "BUY")
    assert buy_leg["entry_price"] > plan_buy.price  # adverse slippage on buys


def test_monitor_holds_within_limits(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    _, trade = open_spread(executor, journal)
    set_quotes(client, trade, move=0.0)
    statuses = monitor.check_all()
    assert statuses[0].action == "HOLD"
    assert journal.open_trade_count() == 1


def test_stop_loss_exit(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    _, trade = open_spread(executor, journal)
    debit = -trade["entry_net"]
    # drop long-leg premium enough to lose > 30% of debit
    set_quotes(client, trade, move=-(debit * 0.5) / 75)
    statuses = monitor.check_all()
    assert statuses[0].action == "EXIT" and "stop loss" in statuses[0].reason
    assert journal.open_trade_count() == 0
    closed = journal.all_closed_trades()
    assert closed[0]["realized_pnl"] < 0


def test_target_exit_books_profit(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    _, trade = open_spread(executor, journal)
    debit = -trade["entry_net"]
    set_quotes(client, trade, move=(debit * 1.2) / 75)
    statuses = monitor.check_all()
    assert statuses[0].action == "EXIT" and "target" in statuses[0].reason
    assert journal.all_closed_trades()[0]["realized_pnl"] > 0
    assert journal.total_realized_pnl() > 0


def test_forced_squareoff(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    _, trade = open_spread(executor, journal)
    set_quotes(client, trade, move=0.0)
    statuses = monitor.check_all(force_squareoff=True)
    assert statuses[0].action == "EXIT" and "square-off" in statuses[0].reason
    assert journal.open_trade_count() == 0


def test_credit_spread_profit_take(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    plan = st.bull_put_spread(U, EXPIRY, parsed_chain(), lots=1)
    assert executor.open_trade(plan, planned_risk=2000.0)
    trade = journal.open_trades()[0]
    credit = trade["entry_net"]
    assert credit > 0
    # premiums collapse -> short leg profits exceed 50% of credit
    for leg in trade["legs"]:
        client.quotes[leg["security_id"]] = max(0.05, leg["entry_price"] * 0.1)
    statuses = monitor.check_all()
    assert statuses[0].action == "EXIT" and "profit take" in statuses[0].reason


def test_pnl_math_matches_quotes(tmp_path):
    settings, journal, client, executor, monitor = setup(tmp_path)
    _, trade = open_spread(executor, journal)
    for leg in trade["legs"]:
        client.quotes[leg["security_id"]] = leg["entry_price"] + 10.0
    pnl = monitor.mark_to_market(trade, client.quotes)
    qty_buy = sum(l["quantity"] for l in trade["legs"] if l["action"] == "BUY")
    qty_sell = sum(l["quantity"] for l in trade["legs"] if l["action"] == "SELL")
    assert math.isclose(pnl, 10.0 * (qty_buy - qty_sell), abs_tol=0.01)
