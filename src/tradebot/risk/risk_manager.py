"""Risk management: the layer that keeps the account alive.

Rules enforced (all configurable in settings.yaml):
  * planned risk per trade capped at max_risk_per_trade_pct of capital
  * hard rejection of any structure with unbounded max loss
  * capital/margin per trade capped at max_capital_per_trade
  * max open positions and max trades per day
  * daily-loss kill switch: once breached, no new trades until tomorrow
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import Settings
from ..constants import CREDIT_STRATEGIES, DEBIT_STRATEGIES
from ..strategy.base import TradePlan

log = logging.getLogger(__name__)


@dataclass
class RiskVerdict:
    approved: bool
    reason: str
    planned_risk: float = 0.0

    def __bool__(self) -> bool:
        return self.approved


def planned_risk(plan: TradePlan, settings: Settings) -> float:
    """Expected loss if the stop-loss rule fires (tighter than max loss).

    Debit structures exit at -stop_loss_premium_pct% of premium paid;
    credit structures exit when loss reaches credit x credit_stop_multiple.
    Falls back to expiry max-loss if the rule-implied risk exceeds it
    (e.g. gap moves), because that is the true worst case.
    """
    risk_cfg = settings.risk
    ml = plan.max_loss
    if plan.strategy in DEBIT_STRATEGIES:
        debit = max(0.0, -plan.net_premium)
        rule_risk = debit * float(risk_cfg.get("stop_loss_premium_pct", 30)) / 100.0
    elif plan.strategy in CREDIT_STRATEGIES:
        credit = max(0.0, plan.net_premium)
        rule_risk = credit * float(risk_cfg.get("credit_stop_multiple", 1.5))
    else:
        rule_risk = ml
    return min(rule_risk, ml) if ml != float("inf") else float("inf")


class RiskManager:
    def __init__(self, settings: Settings, journal):
        self.settings = settings
        self.journal = journal

    # ------------------------------------------------------------- queries
    def capital_now(self) -> float:
        """Initial capital adjusted by cumulative realized P&L."""
        return self.settings.capital + self.journal.total_realized_pnl()

    def max_risk_per_trade(self) -> float:
        return self.capital_now() * float(
            self.settings.risk.get("max_risk_per_trade_pct", 3.0)) / 100.0

    def max_daily_loss(self) -> float:
        return self.capital_now() * float(
            self.settings.risk.get("max_daily_loss_pct", 5.0)) / 100.0

    def daily_loss_breached(self) -> bool:
        return self.journal.realized_pnl_today() <= -self.max_daily_loss()

    # ----------------------------------------------------------- decisions
    def evaluate(self, plan: TradePlan) -> RiskVerdict:
        r = self.settings.risk
        if self.daily_loss_breached():
            return RiskVerdict(False, "daily loss limit hit — kill switch active, "
                                      "no new trades today")

        open_count = self.journal.open_trade_count()
        if open_count >= int(r.get("max_open_positions", 2)):
            return RiskVerdict(False, f"max open positions reached ({open_count})")

        trades_today = self.journal.trades_opened_today()
        if trades_today >= int(r.get("max_trades_per_day", 3)):
            return RiskVerdict(False, f"max trades/day reached ({trades_today})")

        cooldown = int(r.get("entry_cooldown_minutes", 0))
        if cooldown > 0:
            last_open = self.journal.last_trade_opened_at()
            if last_open:
                from datetime import datetime, timedelta
                elapsed = datetime.now() - datetime.fromisoformat(last_open)
                if elapsed < timedelta(minutes=cooldown):
                    remaining = cooldown - elapsed.total_seconds() / 60
                    return RiskVerdict(
                        False, f"entry cooldown active ({remaining:.0f} min left) — "
                               "avoids duplicate entries and churn")

        if plan.max_loss == float("inf"):
            return RiskVerdict(False, "plan has unbounded max loss — rejected")

        risk = planned_risk(plan, self.settings)
        cap = self.max_risk_per_trade()
        if risk > cap:
            return RiskVerdict(False, f"planned risk ₹{risk:,.0f} exceeds per-trade "
                                      f"cap ₹{cap:,.0f}", risk)

        margin = plan.margin_estimate
        budget = min(self.settings.max_capital_per_trade, self.capital_now())
        if margin > budget:
            return RiskVerdict(False, f"capital needed ₹{margin:,.0f} exceeds budget "
                                      f"₹{budget:,.0f}", risk)

        # width sanity for spreads
        strikes = sorted({leg.strike for leg in plan.legs})
        if len(strikes) > 1:
            width = strikes[-1] - strikes[0]
            if width > float(r.get("max_spread_width", 300)) * 2:
                return RiskVerdict(False, f"structure too wide ({width:.0f} pts)", risk)

        return RiskVerdict(True, "approved", risk)

    def size_lots(self, build_plan, max_lots: int = 2) -> TradePlan | None:
        """Find the largest lot count (>=1) that passes risk checks.
        `build_plan(lots)` constructs a fresh plan for the given size."""
        best = None
        for lots in range(1, max_lots + 1):
            try:
                plan = build_plan(lots)
            except Exception as exc:  # noqa: BLE001
                log.warning("plan build failed at %d lots: %s", lots, exc)
                break
            if self.evaluate(plan):
                best = plan
            else:
                break
        return best
