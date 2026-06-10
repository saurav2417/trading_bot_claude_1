"""Map a MarketView to a concrete TradePlan.

Selection matrix (Varsity module 6, 'choosing the right strategy'):

    view \\ vol     LOW (buy premium)   NORMAL              HIGH (sell premium)
    --------------------------------------------------------------------------
    strong bull    LONG_CALL           BULL_CALL_SPREAD    BULL_PUT_SPREAD
    mild bull      BULL_CALL_SPREAD    BULL_CALL_SPREAD    BULL_PUT_SPREAD
    neutral        no trade            no trade            IRON_CONDOR
    mild bear      BEAR_PUT_SPREAD     BEAR_PUT_SPREAD     BEAR_CALL_SPREAD
    strong bear    LONG_PUT            BEAR_PUT_SPREAD     BEAR_CALL_SPREAD

Low-IV + no view = stay out (theta kills you both ways); high-IV favours
defined-risk credit structures; buying naked premium is reserved for strong
directional conviction in cheap-vol regimes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..analysis.market_view import MarketView
from ..config import Settings, Underlying
from ..constants import BEARISH, BULLISH, NEUTRAL, NO_TRADE, VOL_HIGH, VOL_LOW
from . import strategies as st
from .base import TradePlan
from .strategies import StrategyError

log = logging.getLogger(__name__)


@dataclass
class Selection:
    plan: TradePlan | None
    reason: str

    @property
    def actionable(self) -> bool:
        return self.plan is not None


def select_strategy(view: MarketView, underlying: Underlying,
                    settings: Settings, lots: int = 1) -> Selection:
    if view.chain is None or not view.chain.strikes or not view.expiry:
        return Selection(None, "no option chain available")

    min_conf = float(settings.signals.get("min_confidence", 0.5))
    if view.confidence < min_conf:
        return Selection(
            None, f"confidence {view.confidence:.2f} < {min_conf} (signals disagree "
                  "or data missing) — capital preservation first")

    rationale = (f"view={view.direction} score={view.direction_score:+.0f} "
                 f"vol={view.vol_regime} vix={view.vix} conf={view.confidence:.2f}")
    chain, expiry = view.chain, view.expiry

    try:
        if view.direction == BULLISH:
            if view.vol_regime == VOL_HIGH:
                plan = st.bull_put_spread(underlying, expiry, chain, lots, rationale=rationale)
            elif view.vol_regime == VOL_LOW and view.strong:
                plan = st.long_call(underlying, expiry, chain, lots, rationale=rationale)
            else:
                plan = st.bull_call_spread(underlying, expiry, chain, lots, rationale=rationale)
        elif view.direction == BEARISH:
            if view.vol_regime == VOL_HIGH:
                plan = st.bear_call_spread(underlying, expiry, chain, lots, rationale=rationale)
            elif view.vol_regime == VOL_LOW and view.strong:
                plan = st.long_put(underlying, expiry, chain, lots, rationale=rationale)
            else:
                plan = st.bear_put_spread(underlying, expiry, chain, lots, rationale=rationale)
        else:  # NEUTRAL
            if view.vol_regime == VOL_HIGH:
                plan = st.iron_condor(underlying, expiry, chain, lots, rationale=rationale)
            else:
                return Selection(
                    None, "neutral view in non-high-vol regime — no edge, no trade")
    except StrategyError as exc:
        return Selection(None, f"strategy construction failed: {exc}")

    plan.view_summary = view.summary()
    return Selection(plan, f"selected {plan.strategy}")
