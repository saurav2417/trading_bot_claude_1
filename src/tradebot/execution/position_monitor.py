"""Continuous position monitoring: stop-loss, target, trailing and time exits.

Exit rules (Varsity-aligned, configurable):
  Debit trades   - SL at -stop_loss_premium_pct% of premium paid
                 - target at +target_premium_pct%
                 - trail once profit >= trail_after_r x planned risk,
                   locking peak - trail_lock_r x planned risk
  Credit trades  - book at credit_profit_take_pct% of max profit
                 - stop at credit x credit_stop_multiple loss
  All trades     - intraday square-off / expiry-day square-off
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from ..broker.dhan_client import DhanError
from ..config import Settings
from ..constants import CREDIT_STRATEGIES
from ..execution.executor import Executor
from ..journal.journal import Journal

log = logging.getLogger(__name__)


@dataclass
class PositionStatus:
    plan_id: str
    strategy: str
    pnl: float
    action: str        # HOLD | EXIT
    reason: str


class PositionMonitor:
    def __init__(self, settings: Settings, executor: Executor, journal: Journal):
        self.settings = settings
        self.executor = executor
        self.journal = journal

    def check_all(self, force_squareoff: bool = False) -> list[PositionStatus]:
        trades = self.journal.open_trades()
        if not trades:
            return []
        sids = [l["security_id"] for t in trades for l in t["legs"] if l["security_id"]]
        try:
            quotes = self.executor.client.option_ltp(sids)
        except DhanError as exc:
            log.warning("monitor: quote fetch failed, skipping cycle: %s", exc)
            return []

        results = []
        for trade in trades:
            status = self._evaluate(trade, quotes, force_squareoff)
            results.append(status)
            if status.action == "EXIT":
                self.executor.close_trade(trade, status.reason, quotes)
        return results

    def mark_to_market(self, trade: dict, quotes: dict[int, float]) -> float | None:
        pnl = 0.0
        for leg in trade["legs"]:
            px = quotes.get(leg["security_id"])
            if px is None:
                return None
            direction = 1.0 if leg["action"] == "BUY" else -1.0
            pnl += direction * (px - leg["entry_price"]) * leg["quantity"]
        return round(pnl, 2)

    def _evaluate(self, trade: dict, quotes: dict[int, float],
                  force_squareoff: bool) -> PositionStatus:
        pnl = self.mark_to_market(trade, quotes)
        pid, strat = trade["plan_id"], trade["strategy"]
        if pnl is None:
            return PositionStatus(pid, strat, 0.0, "HOLD", "quotes incomplete")

        if force_squareoff:
            return PositionStatus(pid, strat, pnl, "EXIT", "scheduled square-off")
        if trade["expiry"] <= date.today().isoformat():
            return PositionStatus(pid, strat, pnl, "EXIT", "expiry day square-off")

        r = self.settings.risk
        risk = float(trade["planned_risk"]) or 1.0
        peak = max(float(trade["peak_pnl"] or 0.0), pnl)
        if peak > float(trade["peak_pnl"] or 0.0):
            self.journal.update_peak(pid, peak)

        if strat in CREDIT_STRATEGIES:
            credit = max(0.0, float(trade["entry_net"]))
            take = credit * float(r.get("credit_profit_take_pct", 50)) / 100.0
            stop = credit * float(r.get("credit_stop_multiple", 1.5))
            if pnl >= take:
                return PositionStatus(pid, strat, pnl, "EXIT",
                                      f"profit take {pnl:.0f} >= {take:.0f}")
            if pnl <= -stop:
                return PositionStatus(pid, strat, pnl, "EXIT",
                                      f"credit stop {pnl:.0f} <= {-stop:.0f}")
        else:
            debit = max(0.0, -float(trade["entry_net"]))
            sl = debit * float(r.get("stop_loss_premium_pct", 30)) / 100.0
            target = debit * float(r.get("target_premium_pct", 60)) / 100.0
            if pnl <= -sl:
                return PositionStatus(pid, strat, pnl, "EXIT",
                                      f"stop loss {pnl:.0f} <= {-sl:.0f}")
            if pnl >= target:
                return PositionStatus(pid, strat, pnl, "EXIT",
                                      f"target hit {pnl:.0f} >= {target:.0f}")

        # trailing lock once sufficiently in profit (applies to all strategies)
        trail_after = float(r.get("trail_after_r", 1.0)) * risk
        if peak >= trail_after:
            floor = peak - float(r.get("trail_lock_r", 0.5)) * risk
            if pnl <= floor:
                return PositionStatus(pid, strat, pnl, "EXIT",
                                      f"trail stop: pnl {pnl:.0f} fell below "
                                      f"locked {floor:.0f} (peak {peak:.0f})")

        return PositionStatus(pid, strat, pnl, "HOLD", "within limits")
