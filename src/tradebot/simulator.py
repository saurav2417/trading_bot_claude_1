"""Walk-forward historical simulation of the deterministic strategy.

What's real: NIFTY daily + 15-min candles and India VIX from DhanHQ, the
exact signal code (daily trend + intraday momentum), the selection matrix,
risk caps, exit rules, slippage and per-order charges. At each 15-min bar
the system sees only data up to that bar — no lookahead.

What's synthetic: option premiums. Dhan does not serve chains for expired
contracts, so legs are priced with Black-Scholes using India VIX as ATM IV.
That means no skew/smile, no microstructure, and the chain/FII/news signal
components are absent (the composite renormalises over what's available).
Treat results as a test of the TECHNICAL CORE under honest frictions —
a go/no-go gauge, not a P&L promise.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .analysis.market_view import classify_vol_adaptive
from .analysis.technicals import (daily_trend_score, intraday_momentum_score,
                                  regime_check)
from .constants import (BEAR_CALL_SPREAD, BEAR_PUT_SPREAD, BEARISH,
                        BULL_CALL_SPREAD, BULL_PUT_SPREAD, BULLISH, BUY, CE,
                        IRON_CONDOR, LONG_CALL, LONG_PUT, NEUTRAL, PE, SELL,
                        VOL_HIGH, VOL_LOW, VOL_NORMAL)

log = logging.getLogger(__name__)

RISK_FREE = 0.065
SLIPPAGE_PCT = 0.25          # adverse, both sides (matches paper broker)
CHARGES_PER_ORDER = 25.0     # brokerage + STT + txn charges, approx per leg-order
EXPIRY_WEEKDAY = 1           # NIFTY weekly expiry: Tuesday (verify if NSE changes it)


# --------------------------------------------------------- Black-Scholes
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, iv: float,
             option_type: str, r: float = RISK_FREE) -> float:
    if t_years <= 0 or iv <= 0:
        intrinsic = max(0.0, spot - strike) if option_type == CE else max(0.0, strike - spot)
        return max(0.05, intrinsic)
    sq = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + iv * iv / 2.0) * t_years) / sq
    d2 = d1 - sq
    call = spot * _ncdf(d1) - strike * math.exp(-r * t_years) * _ncdf(d2)
    if option_type == CE:
        return max(0.05, call)
    return max(0.05, call - spot + strike * math.exp(-r * t_years))  # put-call parity


def bs_delta(spot: float, strike: float, t_years: float, iv: float,
             option_type: str, r: float = RISK_FREE) -> float:
    if t_years <= 0 or iv <= 0:
        itm = spot > strike if option_type == CE else spot < strike
        return (1.0 if option_type == CE else -1.0) if itm else 0.0
    sq = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + iv * iv / 2.0) * t_years) / sq
    return _ncdf(d1) if option_type == CE else _ncdf(d1) - 1.0


def strike_by_delta(spot: float, t_years: float, iv: float, option_type: str,
                    target: float, step: int) -> float:
    atm = round(spot / step) * step
    candidates = [atm + i * step * (1 if option_type == CE else -1) for i in range(0, 25)]
    return min(candidates,
               key=lambda k: abs(abs(bs_delta(spot, k, t_years, iv, option_type)) - target))


# ------------------------------------------------------------- datamodel
@dataclass
class SimLeg:
    strike: float
    option_type: str
    action: str
    qty: int
    entry_price: float


@dataclass
class SimTrade:
    trade_id: str
    strategy: str
    entry_time: datetime
    expiry: date
    legs: list[SimLeg]
    entry_net: float           # +credit / -debit (after slippage)
    planned_risk: float
    peak_pnl: float = 0.0
    status: str = "OPEN"
    exit_time: datetime | None = None
    exit_reason: str = ""
    pnl: float = 0.0
    charges: float = 0.0


@dataclass
class SimResult:
    start_capital: float
    end_capital: float
    trades: list[SimTrade]
    equity_curve: list[tuple[str, float]]
    days_tested: int
    scans: int

    @property
    def closed(self) -> list[SimTrade]:
        return [t for t in self.trades if t.status == "CLOSED"]

    def stats(self) -> dict:
        closed = self.closed
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = sum(t.pnl for t in losses)
        peak = self.start_capital
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            max_dd = max(max_dd, peak - eq)
        by_strategy: dict[str, list[float]] = {}
        for t in closed:
            by_strategy.setdefault(t.strategy, []).append(t.pnl)
        return {
            "days": self.days_tested,
            "scans": self.scans,
            "trades": len(closed),
            "wins": len(wins),
            "win_rate": len(wins) / len(closed) * 100 if closed else 0.0,
            "total_pnl": sum(t.pnl for t in closed),
            "return_pct": (self.end_capital / self.start_capital - 1) * 100,
            "gross_win": gross_win,
            "gross_loss": gross_loss,
            "profit_factor": abs(gross_win / gross_loss) if gross_loss < 0 else float("inf"),
            "avg_win": gross_win / len(wins) if wins else 0.0,
            "avg_loss": gross_loss / len(losses) if losses else 0.0,
            "max_drawdown": max_dd,
            "charges": sum(t.charges for t in closed),
            "by_strategy": {k: (len(v), sum(v)) for k, v in by_strategy.items()},
        }


# ------------------------------------------------------------ the engine
class Simulator:
    def __init__(self, settings, daily_candles: list[dict],
                 intraday_candles: list[dict], vix_daily: dict[str, float],
                 weeks: int = 6,
                 vix_series: list[tuple[str, float]] | None = None):
        self.s = settings
        self.daily = daily_candles
        self.weeks = weeks
        self.vix_daily = vix_daily          # date iso -> prior-day VIX close
        # full (date iso, close) series for trailing IV-percentile classification
        self.vix_series = sorted(vix_series or [])
        self.u = settings.underlyings[0]
        self.bars_by_day: dict[str, list[dict]] = {}
        for bar in intraday_candles:
            if bar["time"] is None:
                continue
            self.bars_by_day.setdefault(bar["time"].date().isoformat(), []).append(bar)
        self.capital = settings.capital
        self.trades: list[SimTrade] = []
        self.equity: list[tuple[str, float]] = []
        self.scans = 0

    # ------------------------------------------------------------- helpers
    def _daily_prefix(self, day: str) -> list[dict]:
        return [c for c in self.daily
                if c["time"] is not None and c["time"].date().isoformat() < day]

    def _intraday_window(self, day: str, idx: int) -> list[dict]:
        days = sorted(d for d in self.bars_by_day if d <= day)
        bars: list[dict] = []
        for d in days[-4:-1]:
            bars.extend(self.bars_by_day[d])
        bars.extend(self.bars_by_day[day][: idx + 1])
        return bars

    def _vix(self, day: str) -> float:
        return self.vix_daily.get(day, 14.0)

    @staticmethod
    def _expiry_for(d: date) -> date:
        offset = (EXPIRY_WEEKDAY - d.weekday()) % 7
        return d + timedelta(days=offset)

    @staticmethod
    def _t_years(now: datetime, expiry: date) -> float:
        exp_dt = datetime.combine(expiry, time(15, 30), tzinfo=now.tzinfo)
        return max(0.0, (exp_dt - now).total_seconds() / (365.0 * 86400))

    # ------------------------------------------------------------ main loop
    def run(self) -> SimResult:
        all_days = sorted(self.bars_by_day)
        test_days = all_days[-(self.weeks * 5):]
        thr = float(self.s.signals.get("direction_threshold", 30))
        strong_thr = float(self.s.signals.get("strong_direction_threshold", 55))
        start_capital = self.capital

        skip_dates = set(self.s.events.get("skip_dates") or [])
        for day in test_days:
            daily_prefix = self._daily_prefix(day)
            if len(daily_prefix) < 80:
                continue
            d_score = daily_trend_score(daily_prefix).score
            trending, _ = regime_check(daily_prefix, self.s.regime)
            vix_history = [c for d, c in self.vix_series if d < day]
            event_day = day in skip_dates
            day_realized = 0.0
            trades_today = 0
            last_scan: datetime | None = None
            last_entry: datetime | None = None
            cooldown = timedelta(minutes=int(self.s.risk.get("entry_cooldown_minutes", 0)))
            kill = False

            for idx, bar in enumerate(self.bars_by_day[day]):
                now: datetime = bar["time"]
                hm = now.strftime("%H:%M")
                spot = bar["close"]
                vix = self._vix(day)
                iv = vix / 100.0

                # 1) manage open positions on every bar
                day_realized += self._monitor(now, spot, iv, force=hm >= "15:12")

                if day_realized <= -0.05 * self.capital:
                    kill = True

                # 2) entry scan every 15 minutes inside the window
                if kill or event_day or hm < "09:30" or hm > "14:30":
                    continue
                if last_scan and (now - last_scan) < timedelta(minutes=15):
                    continue
                last_scan = now
                self.scans += 1
                if trades_today >= int(self.s.risk.get("max_trades_per_day", 3)):
                    continue
                if len(self._open()) >= int(self.s.risk.get("max_open_positions", 2)):
                    continue
                if last_entry is not None and (now - last_entry) < cooldown:
                    continue

                i_score = intraday_momentum_score(self._intraday_window(day, idx)).score
                # renormalised composite over available components
                w_d, w_i = 0.30, 0.25
                raw = (w_d * d_score + w_i * i_score) / (w_d + w_i)
                score = max(-100.0, min(100.0, raw * 100.0))
                sided = [v for v in (d_score, i_score) if abs(v) >= 0.1]
                agree = (max(sum(1 for v in sided if v > 0),
                             sum(1 for v in sided if v < 0)) / len(sided)) if sided else 0.5
                if agree < float(self.s.signals.get("min_confidence", 0.5)):
                    continue

                direction = BULLISH if score >= thr else BEARISH if score <= -thr else NEUTRAL
                if direction != NEUTRAL and not trending:
                    continue  # chop filter, as in the live selector
                strong = abs(score) >= strong_thr
                vol, _ = classify_vol_adaptive(vix, vix_history, self.s.signals)
                strategy = _select(direction, vol, strong)
                if self.s.signals.get("use_vol_premium_filter"):
                    rv = realized_vol_pct([c["close"] for c in daily_prefix[-7:]])
                    vrp = (vix - rv) if rv is not None else None
                    strategy = apply_vol_premium_filter(
                        strategy, vrp,
                        float(self.s.signals.get("vol_premium_threshold", 2.0)))
                if strategy is None:
                    continue

                trade = self._enter(strategy, now, spot, iv)
                if trade is not None:
                    self.trades.append(trade)
                    trades_today += 1
                    last_entry = now

            self.equity.append((day, self.capital))

        # safety: nothing should remain open (intraday square-off), but be sure
        for t in self._open():
            t.status = "CLOSED"
            t.exit_reason = "end of simulation"
        return SimResult(start_capital, self.capital, self.trades,
                         self.equity, len(test_days), self.scans)

    def _open(self) -> list[SimTrade]:
        return [t for t in self.trades if t.status == "OPEN"]

    # -------------------------------------------------------------- entries
    def _enter(self, strategy: str, now: datetime, spot: float,
               iv: float) -> SimTrade | None:
        expiry = self._expiry_for(now.date())
        if expiry == now.date() and now.strftime("%H:%M") >= "13:30":
            return None  # expiry-day late-entry guard, as in live
        t_years = self._t_years(now, expiry)
        legs = _build_legs(strategy, spot, t_years, iv, self.u.lot_size,
                           self.u.strike_step)
        if not legs:
            return None
        # slippage-adjusted entries
        entry_net = 0.0
        for leg in legs:
            slip = leg.entry_price * SLIPPAGE_PCT / 100.0
            leg.entry_price = round(
                leg.entry_price + slip if leg.action == BUY else leg.entry_price - slip, 2)
            entry_net += (leg.entry_price if leg.action == SELL
                          else -leg.entry_price) * leg.qty

        risk_cfg = self.s.risk
        debit = max(0.0, -entry_net)
        credit = max(0.0, entry_net)
        if debit > 0:
            planned = debit * float(risk_cfg.get("stop_loss_premium_pct", 30)) / 100.0
            margin = debit
        else:
            planned = credit * float(risk_cfg.get("credit_stop_multiple", 1.5))
            width = (max(l.strike for l in legs) - min(l.strike for l in legs))
            margin = width * legs[0].qty * 1.25
        if planned > self.capital * float(risk_cfg.get("max_risk_per_trade_pct", 3.0)) / 100.0:
            return None
        if margin > min(self.s.max_capital_per_trade, self.capital):
            return None

        return SimTrade(
            trade_id=uuid.uuid4().hex[:8], strategy=strategy, entry_time=now,
            expiry=expiry, legs=legs, entry_net=entry_net, planned_risk=planned,
        )

    # ---------------------------------------------------------- monitoring
    def _monitor(self, now: datetime, spot: float, iv: float,
                 force: bool) -> float:
        realized = 0.0
        r = self.s.risk
        for trade in self._open():
            t_years = self._t_years(now, trade.expiry)
            pnl = 0.0
            for leg in trade.legs:
                px = bs_price(spot, leg.strike, t_years, iv, leg.option_type)
                direction = 1.0 if leg.action == BUY else -1.0
                pnl += direction * (px - leg.entry_price) * leg.qty
            trade.peak_pnl = max(trade.peak_pnl, pnl)

            reason = None
            if force:
                reason = "square-off"
            elif trade.entry_net < 0:  # debit
                debit = -trade.entry_net
                if pnl <= -debit * float(r.get("stop_loss_premium_pct", 30)) / 100.0:
                    reason = "stop loss"
                elif pnl >= debit * float(r.get("target_premium_pct", 60)) / 100.0:
                    reason = "target"
            else:  # credit
                credit = trade.entry_net
                if pnl >= credit * float(r.get("credit_profit_take_pct", 50)) / 100.0:
                    reason = "profit take"
                elif pnl <= -credit * float(r.get("credit_stop_multiple", 1.5)):
                    reason = "credit stop"
            if reason is None:
                trail_after = float(r.get("trail_after_r", 1.0)) * trade.planned_risk
                if trade.peak_pnl >= trail_after:
                    floor = trade.peak_pnl - float(r.get("trail_lock_r", 0.5)) * trade.planned_risk
                    if pnl <= floor:
                        reason = "trail stop"
            if reason is None:
                continue

            # exit with slippage + charges (entry orders + exit orders)
            exit_pnl = 0.0
            for leg in trade.legs:
                px = bs_price(spot, leg.strike, t_years, iv, leg.option_type)
                slip = px * SLIPPAGE_PCT / 100.0
                px = max(0.05, px - slip if leg.action == BUY else px + slip)
                direction = 1.0 if leg.action == BUY else -1.0
                exit_pnl += direction * (px - leg.entry_price) * leg.qty
            charges = CHARGES_PER_ORDER * len(trade.legs) * 2
            trade.status = "CLOSED"
            trade.exit_time = now
            trade.exit_reason = reason
            trade.charges = charges
            trade.pnl = round(exit_pnl - charges, 2)
            self.capital += trade.pnl
            realized += trade.pnl
        return realized


def realized_vol_pct(closes: list[float]) -> float | None:
    """Annualised realized volatility (%) from daily closes (log returns)."""
    if len(closes) < 4:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0]
    if len(rets) < 3:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252.0) * 100.0


def apply_vol_premium_filter(strategy: str | None, vrp: float | None,
                             threshold: float = 2.0) -> str | None:
    """Gamma-economics filter: VRP = implied (VIX) − realized vol.

    Rich premium (vrp >= +t): being short gamma is paid for — prefer credit
    structures. Cheap premium (vrp <= −t): realized moves exceed what options
    price — prefer long-gamma debit structures, and refuse to sell condors.
    """
    if strategy is None or vrp is None:
        return strategy
    if vrp >= threshold:
        return {LONG_CALL: BULL_PUT_SPREAD, BULL_CALL_SPREAD: BULL_PUT_SPREAD,
                LONG_PUT: BEAR_CALL_SPREAD, BEAR_PUT_SPREAD: BEAR_CALL_SPREAD,
                }.get(strategy, strategy)
    if vrp <= -threshold:
        return {BULL_PUT_SPREAD: BULL_CALL_SPREAD,
                BEAR_CALL_SPREAD: BEAR_PUT_SPREAD,
                IRON_CONDOR: None}.get(strategy, strategy)
    return strategy


# -------------------------------------------------- strategy construction
def _select(direction: str, vol: str, strong: bool) -> str | None:
    if direction == BULLISH:
        if vol == VOL_HIGH:
            return BULL_PUT_SPREAD
        return LONG_CALL if (vol == VOL_LOW and strong) else BULL_CALL_SPREAD
    if direction == BEARISH:
        if vol == VOL_HIGH:
            return BEAR_CALL_SPREAD
        return LONG_PUT if (vol == VOL_LOW and strong) else BEAR_PUT_SPREAD
    return IRON_CONDOR if vol == VOL_HIGH else None


def _build_legs(strategy: str, spot: float, t_years: float, iv: float,
                lot: int, step: int) -> list[SimLeg]:
    atm = round(spot / step) * step

    def leg(strike: float, opt: str, action: str) -> SimLeg:
        return SimLeg(strike, opt, action, lot,
                      round(bs_price(spot, strike, t_years, iv, opt), 2))

    if strategy == LONG_CALL:
        return [leg(atm, CE, BUY)]
    if strategy == LONG_PUT:
        return [leg(atm, PE, BUY)]
    if strategy == BULL_CALL_SPREAD:
        return [leg(atm, CE, BUY), leg(atm + 3 * step, CE, SELL)]
    if strategy == BEAR_PUT_SPREAD:
        return [leg(atm, PE, BUY), leg(atm - 3 * step, PE, SELL)]
    if strategy == BULL_PUT_SPREAD:
        short = strike_by_delta(spot, t_years, iv, PE, 0.28, step)
        return [leg(short, PE, SELL), leg(short - 4 * step, PE, BUY)]
    if strategy == BEAR_CALL_SPREAD:
        short = strike_by_delta(spot, t_years, iv, CE, 0.28, step)
        return [leg(short, CE, SELL), leg(short + 4 * step, CE, BUY)]
    if strategy == IRON_CONDOR:
        sp = strike_by_delta(spot, t_years, iv, PE, 0.20, step)
        sc = strike_by_delta(spot, t_years, iv, CE, 0.20, step)
        if sp >= sc:
            return []
        return [leg(sp, PE, SELL), leg(sp - 3 * step, PE, BUY),
                leg(sc, CE, SELL), leg(sc + 3 * step, CE, BUY)]
    return []


# --------------------------------------------------------------- reporting
def render_report(result: SimResult, weeks: int) -> str:
    s = result.stats()
    lines = [
        f"# Historical simulation — deterministic strategy, last {weeks} weeks",
        "",
        f"- Trading days: {s['days']} | entry scans: {s['scans']}",
        f"- Capital: ₹{result.start_capital:,.0f} → **₹{result.end_capital:,.0f}** "
        f"({s['return_pct']:+.1f}%)",
        f"- Trades: {s['trades']} | win rate: {s['win_rate']:.0f}% "
        f"| profit factor: {s['profit_factor']:.2f}",
        f"- Avg win: ₹{s['avg_win']:,.0f} | avg loss: ₹{s['avg_loss']:,.0f}",
        f"- Max drawdown: ₹{s['max_drawdown']:,.0f} "
        f"({s['max_drawdown'] / result.start_capital * 100:.1f}% of capital)",
        f"- Total charges paid: ₹{s['charges']:,.0f}",
        "",
        "## By strategy",
        "| Strategy | Trades | P&L |",
        "|---|---|---|",
    ]
    for name, (n, pnl) in sorted(s["by_strategy"].items()):
        lines.append(f"| {name} | {n} | ₹{pnl:,.0f} |")
    lines += ["", "## Trades", "| Date | Strategy | Entry | Exit | Reason | P&L |",
              "|---|---|---|---|---|---|"]
    for t in result.closed:
        lines.append(
            f"| {t.entry_time.date()} | {t.strategy} "
            f"| {t.entry_time.strftime('%H:%M')} "
            f"| {t.exit_time.strftime('%H:%M') if t.exit_time else '—'} "
            f"| {t.exit_reason} | ₹{t.pnl:,.0f} |")
    lines += [
        "",
        "## Caveats (read before acting on this)",
        "- Option premiums are Black-Scholes-synthesised from real NIFTY/VIX data; "
        "real premiums carry skew, smile and microstructure this cannot capture.",
        "- Signals tested: daily trend + intraday momentum (the technical core). "
        "Option-chain positioning, FII/DII and news components are not "
        "reconstructable historically and are absent here.",
        "- Slippage 0.25%/side and ₹25/order charges are estimates.",
        f"- Weekly expiry assumed on weekday {EXPIRY_WEEKDAY} (Tuesday).",
        "- A few weeks is a small sample; treat this as a sanity gauge, "
        "not a guarantee.",
    ]
    return "\n".join(lines) + "\n"
