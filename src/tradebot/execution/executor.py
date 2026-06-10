"""Order execution for paper and live modes.

Paper mode simulates fills at the live chain price plus slippage so paper
results stay honest. Live mode places real LIMIT orders via DhanHQ with
leg ordering chosen for safety: protective BUY legs first on entry,
short-leg buy-backs first on exit.
"""

from __future__ import annotations

import logging
import time

from ..broker.dhan_client import DhanClient, DhanError
from ..config import Settings
from ..constants import BUY, NSE_FNO, SELL
from ..journal.journal import Journal
from ..strategy.base import OptionLeg, TradePlan

log = logging.getLogger(__name__)

PAPER_SLIPPAGE_PCT = 0.25   # adverse slippage applied to every simulated fill
FILL_POLL_SECONDS = 25      # how long to wait for a live LIMIT order to fill


class ExecutionError(RuntimeError):
    pass


class Executor:
    def __init__(self, settings: Settings, client: DhanClient, journal: Journal):
        self.settings = settings
        self.client = client
        self.journal = journal

    # ------------------------------------------------------------- entry
    def open_trade(self, plan: TradePlan, planned_risk: float) -> bool:
        self._resolve_legs(plan)
        if self.settings.is_live:
            return self._open_live(plan, planned_risk)
        return self._open_paper(plan, planned_risk)

    def _resolve_legs(self, plan: TradePlan) -> None:
        for leg in plan.legs:
            info = self.client.resolve_option(
                leg.underlying, leg.expiry, leg.strike, leg.option_type)
            leg.security_id = info["security_id"]
            leg.trading_symbol = info.get("trading_symbol")
            master_lot = info.get("lot_size")
            if master_lot and master_lot != leg.lot_size:
                log.warning("lot size mismatch for %s: config %d vs scrip master %d "
                            "— using scrip master", leg.trading_symbol,
                            leg.lot_size, master_lot)
                leg.lots = max(1, leg.quantity // master_lot)
                leg.lot_size = master_lot

    def _open_paper(self, plan: TradePlan, planned_risk: float) -> bool:
        fills = {}
        for i, leg in enumerate(plan.legs):
            slip = leg.price * PAPER_SLIPPAGE_PCT / 100.0
            fills[i] = round(leg.price + slip if leg.action == BUY else leg.price - slip, 2)
        self.journal.record_open(plan, "paper", planned_risk, fills)
        self.journal.log_event("ENTRY", f"[paper] opened {plan.plan_id} {plan.strategy}")
        log.info("[paper] opened %s", plan.describe())
        return True

    def _open_live(self, plan: TradePlan, planned_risk: float) -> bool:
        # margin sanity against the real fund limit
        try:
            funds = self.client.fund_limit()
            available = float(funds.get("availabelBalance")
                              or funds.get("availableBalance") or 0)
            if available and plan.margin_estimate > available:
                raise ExecutionError(
                    f"insufficient funds: need ~₹{plan.margin_estimate:,.0f}, "
                    f"available ₹{available:,.0f}")
        except DhanError as exc:
            log.warning("fund limit check failed, proceeding cautiously: %s", exc)

        ordered = sorted(plan.legs, key=lambda l: 0 if l.action == BUY else 1)
        fills: dict[int, float] = {}
        filled_legs: list[OptionLeg] = []
        try:
            for leg in ordered:
                px = self._fill_leg(leg, leg.action)
                fills[plan.legs.index(leg)] = px
                filled_legs.append(leg)
        except Exception as exc:  # noqa: BLE001
            log.error("entry failed mid-way (%s); unwinding %d filled legs",
                      exc, len(filled_legs))
            self._unwind(filled_legs)
            self.journal.log_event("ERROR", f"entry failed for {plan.plan_id}: {exc}")
            return False

        self.journal.record_open(plan, "live", planned_risk, fills)
        self.journal.log_event("ENTRY", f"[live] opened {plan.plan_id} {plan.strategy}")
        log.info("[live] opened %s", plan.describe())
        return True

    # -------------------------------------------------------------- exit
    def close_trade(self, trade: dict, reason: str,
                    quotes: dict[int, float] | None = None) -> float | None:
        """trade: journal dict with legs. Returns realized pnl or None on failure."""
        legs = trade["legs"]
        sids = [l["security_id"] for l in legs if l["security_id"]]
        quotes = quotes or {}
        missing = [s for s in sids if s not in quotes]
        if missing:
            try:
                quotes.update(self.client.option_ltp(missing))
            except DhanError as exc:
                log.error("cannot fetch exit quotes for %s: %s", trade["plan_id"], exc)
                if trade["mode"] == "paper":
                    return None

        exit_prices: dict[int, float] = {}
        pnl = 0.0
        # buy back shorts first, then sell longs (safety in live mode)
        ordered = sorted(legs, key=lambda l: 0 if l["action"] == SELL else 1)
        for leg in ordered:
            close_action = BUY if leg["action"] == SELL else SELL
            ref = quotes.get(leg["security_id"], leg["entry_price"])
            if trade["mode"] == "live":
                try:
                    px = self._fill_leg_raw(leg["security_id"], close_action,
                                            leg["quantity"], ref)
                except Exception as exc:  # noqa: BLE001
                    log.error("exit order failed for leg %s: %s — manual check needed",
                              leg.get("trading_symbol"), exc)
                    self.journal.log_event(
                        "ERROR", f"exit leg failed {trade['plan_id']}: {exc}")
                    px = ref
            else:
                slip = ref * PAPER_SLIPPAGE_PCT / 100.0
                px = round(ref + slip if close_action == BUY else ref - slip, 2)
            exit_prices[leg["id"]] = px
            direction = 1.0 if leg["action"] == BUY else -1.0
            pnl += direction * (px - leg["entry_price"]) * leg["quantity"]

        self.journal.record_close(trade["plan_id"], exit_prices, round(pnl, 2), reason)
        self.journal.log_event(
            "EXIT", f"closed {trade['plan_id']} ({reason}) pnl ₹{pnl:,.0f}")
        log.info("closed %s (%s) pnl ₹%.0f", trade["plan_id"], reason, pnl)
        return pnl

    # ----------------------------------------------------------- plumbing
    def _fill_leg(self, leg: OptionLeg, action: str) -> float:
        return self._fill_leg_raw(leg.security_id, action, leg.quantity, leg.price)

    def _fill_leg_raw(self, security_id: int, action: str, quantity: int,
                      ref_price: float) -> float:
        """Place a LIMIT order crossed by limit_buffer_pct; poll for fill."""
        buffer = float(self.settings.execution.get("limit_buffer_pct", 0.5)) / 100.0
        limit = ref_price * (1 + buffer) if action == BUY else ref_price * (1 - buffer)
        limit = max(0.05, round(limit, 2))
        resp = self.client.place_order(
            security_id=security_id,
            transaction_type=action,
            quantity=quantity,
            order_type=self.settings.execution.get("order_type", "LIMIT"),
            price=limit,
            product_type=self.settings.execution.get("product_type", "INTRADAY"),
            exchange_segment=NSE_FNO,
            tag="tradebot",
        )
        order_id = (resp or {}).get("orderId") or (resp or {}).get("data", {}).get("orderId")
        if not order_id:
            raise ExecutionError(f"no orderId in response: {resp}")

        deadline = time.monotonic() + FILL_POLL_SECONDS
        while time.monotonic() < deadline:
            status = self.client.order_status(str(order_id))
            data = status.get("data", status)
            state = (data.get("orderStatus") or "").upper()
            if state == "TRADED":
                return float(data.get("averageTradedPrice") or limit)
            if state in ("REJECTED", "CANCELLED", "EXPIRED"):
                raise ExecutionError(f"order {order_id} {state}: "
                                     f"{data.get('omsErrorDescription', '')}")
            time.sleep(2)
        # not filled in time: cancel and fail loudly
        try:
            self.client.cancel_order(str(order_id))
        except DhanError:
            pass
        raise ExecutionError(f"order {order_id} not filled within {FILL_POLL_SECONDS}s")

    def _unwind(self, filled: list[OptionLeg]) -> None:
        for leg in reversed(filled):
            try:
                reverse = SELL if leg.action == BUY else BUY
                self._fill_leg_raw(leg.security_id, reverse, leg.quantity, leg.price)
            except Exception as exc:  # noqa: BLE001
                log.critical("UNWIND FAILED for %s — manual intervention required: %s",
                             leg.describe(), exc)
                self.journal.log_event("CRITICAL", f"unwind failed: {leg.describe()}")
