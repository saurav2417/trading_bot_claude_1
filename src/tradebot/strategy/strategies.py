"""Strategy builders — the Zerodha Varsity options playbook, coded.

Strike-selection rules follow Varsity's module 6 guidance:
  * long options: ATM (avoid deep OTM 'lottery tickets', avoid deep ITM
    liquidity problems)
  * debit spreads: buy ATM, sell 2-4 strike-steps OTM
  * credit spreads: sell around the 0.25-0.30 delta strike (or ~1.5% OTM
    when greeks are missing), buy a wing further out to define risk
  * iron condor: short strangle near 0.20 delta with protective wings

Every builder returns a TradePlan (with reference prices from the live
chain) or raises StrategyError when the chain can't support the structure.
"""

from __future__ import annotations

from ..analysis.options_analysis import ChainAnalysis, leg_delta, leg_price
from ..config import Underlying
from ..constants import (BEAR_CALL_SPREAD, BEAR_PUT_SPREAD, BULL_CALL_SPREAD,
                         BULL_PUT_SPREAD, BUY, CE, IRON_CONDOR, LONG_CALL,
                         LONG_PUT, PE, SELL)
from .base import OptionLeg, TradePlan


class StrategyError(ValueError):
    pass


def _leg(u: Underlying, expiry: str, chain: ChainAnalysis, strike: float,
         opt: str, action: str, lots: int) -> OptionLeg:
    price = leg_price(chain, strike, opt)
    if price is None or price <= 0:
        raise StrategyError(f"no tradeable price for {strike:.0f}{opt}")
    return OptionLeg(
        underlying=u.name, expiry=expiry, strike=strike, option_type=opt,
        action=action, lots=lots, lot_size=u.lot_size, price=price,
    )


def _atm(chain: ChainAnalysis, step: int) -> float:
    if not chain.strikes:
        raise StrategyError("empty chain")
    return min(chain.strikes, key=lambda s: abs(s - chain.spot))


def _nearest_listed(chain: ChainAnalysis, target: float) -> float:
    return min(chain.strikes, key=lambda s: abs(s - target))


def _strike_by_delta(chain: ChainAnalysis, opt: str, target_delta: float,
                     fallback_offset_pct: float) -> float:
    """Find the strike whose |delta| is closest to target. If the chain has
    no greeks, fall back to a %-OTM offset from spot."""
    candidates = []
    for strike in chain.strikes:
        d = leg_delta(chain, strike, opt)
        if d is None:
            continue
        candidates.append((abs(abs(d) - target_delta), strike))
    if candidates:
        return min(candidates)[1]
    direction = 1.0 if opt == CE else -1.0
    return _nearest_listed(chain, chain.spot * (1 + direction * fallback_offset_pct))


# ------------------------------------------------------------------ builders

def long_call(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
              rationale: str = "") -> TradePlan:
    atm = _atm(chain, u.strike_step)
    return TradePlan(
        strategy=LONG_CALL, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[_leg(u, expiry, chain, atm, CE, BUY, lots)], rationale=rationale,
    )


def long_put(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
             rationale: str = "") -> TradePlan:
    atm = _atm(chain, u.strike_step)
    return TradePlan(
        strategy=LONG_PUT, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[_leg(u, expiry, chain, atm, PE, BUY, lots)], rationale=rationale,
    )


def bull_call_spread(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
                     width_steps: int = 3, rationale: str = "") -> TradePlan:
    atm = _atm(chain, u.strike_step)
    sell_strike = _nearest_listed(chain, atm + width_steps * u.strike_step)
    if sell_strike <= atm:
        raise StrategyError("cannot find OTM call for spread")
    return TradePlan(
        strategy=BULL_CALL_SPREAD, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[
            _leg(u, expiry, chain, atm, CE, BUY, lots),
            _leg(u, expiry, chain, sell_strike, CE, SELL, lots),
        ],
        rationale=rationale,
    )


def bear_put_spread(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
                    width_steps: int = 3, rationale: str = "") -> TradePlan:
    atm = _atm(chain, u.strike_step)
    sell_strike = _nearest_listed(chain, atm - width_steps * u.strike_step)
    if sell_strike >= atm:
        raise StrategyError("cannot find OTM put for spread")
    return TradePlan(
        strategy=BEAR_PUT_SPREAD, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[
            _leg(u, expiry, chain, atm, PE, BUY, lots),
            _leg(u, expiry, chain, sell_strike, PE, SELL, lots),
        ],
        rationale=rationale,
    )


def bull_put_spread(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
                    wing_steps: int = 4, rationale: str = "") -> TradePlan:
    short = _strike_by_delta(chain, PE, 0.28, 0.012)
    wing = _nearest_listed(chain, short - wing_steps * u.strike_step)
    if wing >= short:
        raise StrategyError("cannot find protective put wing")
    return TradePlan(
        strategy=BULL_PUT_SPREAD, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[
            _leg(u, expiry, chain, short, PE, SELL, lots),
            _leg(u, expiry, chain, wing, PE, BUY, lots),
        ],
        rationale=rationale,
    )


def bear_call_spread(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
                     wing_steps: int = 4, rationale: str = "") -> TradePlan:
    short = _strike_by_delta(chain, CE, 0.28, 0.012)
    wing = _nearest_listed(chain, short + wing_steps * u.strike_step)
    if wing <= short:
        raise StrategyError("cannot find protective call wing")
    return TradePlan(
        strategy=BEAR_CALL_SPREAD, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[
            _leg(u, expiry, chain, short, CE, SELL, lots),
            _leg(u, expiry, chain, wing, CE, BUY, lots),
        ],
        rationale=rationale,
    )


def iron_condor(u: Underlying, expiry: str, chain: ChainAnalysis, lots: int,
                wing_steps: int = 3, rationale: str = "") -> TradePlan:
    short_put = _strike_by_delta(chain, PE, 0.20, 0.018)
    short_call = _strike_by_delta(chain, CE, 0.20, 0.018)
    if short_put >= short_call:
        raise StrategyError("condor short strikes inverted")
    put_wing = _nearest_listed(chain, short_put - wing_steps * u.strike_step)
    call_wing = _nearest_listed(chain, short_call + wing_steps * u.strike_step)
    if put_wing >= short_put or call_wing <= short_call:
        raise StrategyError("cannot find condor wings")
    return TradePlan(
        strategy=IRON_CONDOR, underlying=u.name, spot=chain.spot, expiry=expiry,
        legs=[
            _leg(u, expiry, chain, short_put, PE, SELL, lots),
            _leg(u, expiry, chain, put_wing, PE, BUY, lots),
            _leg(u, expiry, chain, short_call, CE, SELL, lots),
            _leg(u, expiry, chain, call_wing, CE, BUY, lots),
        ],
        rationale=rationale,
    )
