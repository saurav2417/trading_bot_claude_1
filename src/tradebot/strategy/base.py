"""Trade-plan datamodel and payoff math shared by all strategies."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..constants import BUY, CE, SELL


@dataclass
class OptionLeg:
    underlying: str
    expiry: str               # YYYY-MM-DD
    strike: float
    option_type: str          # CE | PE
    action: str               # BUY | SELL
    lots: int
    lot_size: int
    price: float              # reference premium per unit at plan time
    security_id: int | None = None
    trading_symbol: str | None = None

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def signed_premium(self) -> float:
        """Cash flow at entry: negative = paid (debit), positive = received."""
        sign = -1.0 if self.action == BUY else 1.0
        return sign * self.price * self.quantity

    def payoff_at(self, spot: float) -> float:
        """P&L of this leg if held to expiry with underlying at `spot`."""
        if self.option_type == CE:
            intrinsic = max(0.0, spot - self.strike)
        else:
            intrinsic = max(0.0, self.strike - spot)
        if self.action == BUY:
            return (intrinsic - self.price) * self.quantity
        return (self.price - intrinsic) * self.quantity

    def describe(self) -> str:
        return (f"{self.action} {self.lots}x{self.lot_size} {self.underlying} "
                f"{self.expiry} {self.strike:.0f}{self.option_type} @ ~{self.price:.2f}")


@dataclass
class TradePlan:
    strategy: str
    underlying: str
    spot: float
    expiry: str
    legs: list[OptionLeg]
    rationale: str
    view_summary: str = ""
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # ----------------------------------------------------------- economics
    @property
    def net_premium(self) -> float:
        """Entry cash flow: negative = net debit, positive = net credit."""
        return sum(leg.signed_premium for leg in self.legs)

    @property
    def is_credit(self) -> bool:
        return self.net_premium > 0

    def payoff_at(self, spot: float) -> float:
        return sum(leg.payoff_at(spot) for leg in self.legs)

    def _grid(self) -> list[float]:
        strikes = sorted({leg.strike for leg in self.legs})
        lo, hi = strikes[0] * 0.85, strikes[-1] * 1.15
        pts = [lo, hi] + strikes
        for s in strikes:  # probe just inside/outside each kink
            pts += [s - 0.01, s + 0.01]
        return pts

    @property
    def max_loss(self) -> float:
        """Max loss at expiry (positive number). Naked short legs make this
        effectively unbounded; we return a large sentinel so risk checks fail."""
        if self._has_naked_short():
            return float("inf")
        return max(0.0, -min(self.payoff_at(p) for p in self._grid()))

    @property
    def max_profit(self) -> float:
        if self._has_naked_long_upside():
            return float("inf")
        return max(self.payoff_at(p) for p in self._grid())

    def _net_qty(self, option_type: str) -> int:
        return sum(
            (leg.quantity if leg.action == BUY else -leg.quantity)
            for leg in self.legs if leg.option_type == option_type
        )

    def _has_naked_short(self) -> bool:
        return self._net_qty(CE) < 0 or self._net_qty("PE") < 0

    def _has_naked_long_upside(self) -> bool:
        return self._net_qty(CE) > 0  # net long calls -> unbounded upside

    @property
    def breakevens(self) -> list[float]:
        """Expiry breakeven points found by sign changes on a fine grid."""
        strikes = sorted({leg.strike for leg in self.legs})
        lo, hi = strikes[0] * 0.9, strikes[-1] * 1.1
        steps = 2000
        bes = []
        prev_spot, prev_pnl = lo, self.payoff_at(lo)
        for i in range(1, steps + 1):
            spot = lo + (hi - lo) * i / steps
            pnl = self.payoff_at(spot)
            if prev_pnl == 0 or (prev_pnl < 0) != (pnl < 0):
                # linear interpolation for the crossing point
                if pnl != prev_pnl:
                    frac = -prev_pnl / (pnl - prev_pnl)
                    bes.append(round(prev_spot + frac * (spot - prev_spot), 1))
            prev_spot, prev_pnl = spot, pnl
        # dedupe nearby points
        out: list[float] = []
        for b in bes:
            if not out or abs(b - out[-1]) > 1.0:
                out.append(b)
        return out

    @property
    def margin_estimate(self) -> float:
        """Conservative capital requirement.

        Debit structures: premium paid. Credit spreads/condors: max loss plus
        a 25% buffer approximates exchange margin for fully hedged index
        spreads. Live mode additionally verifies against the broker fund limit.
        """
        debit = max(0.0, -self.net_premium)
        if not any(leg.action == SELL for leg in self.legs):
            return debit
        ml = self.max_loss
        if ml == float("inf"):
            return float("inf")
        return debit + ml * 1.25

    def describe(self) -> str:
        lines = [f"[{self.plan_id}] {self.strategy} on {self.underlying} "
                 f"(spot {self.spot:.1f}, expiry {self.expiry})"]
        lines += [f"  - {leg.describe()}" for leg in self.legs]
        net = self.net_premium
        lines.append(f"  net {'credit' if net > 0 else 'debit'}: ₹{abs(net):,.0f}")
        ml, mp = self.max_loss, self.max_profit
        lines.append(f"  max loss: {'∞' if ml == float('inf') else f'₹{ml:,.0f}'}"
                     f" | max profit: {'∞' if mp == float('inf') else f'₹{mp:,.0f}'}"
                     f" | breakevens: {self.breakevens}")
        lines.append(f"  est. capital: ₹{self.margin_estimate:,.0f}")
        lines.append(f"  rationale: {self.rationale}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["net_premium"] = self.net_premium
        d["max_loss"] = None if self.max_loss == float("inf") else self.max_loss
        d["max_profit"] = None if self.max_profit == float("inf") else self.max_profit
        d["breakevens"] = self.breakevens
        d["margin_estimate"] = (None if self.margin_estimate == float("inf")
                                else self.margin_estimate)
        return d
