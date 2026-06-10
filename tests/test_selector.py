import pytest

from tradebot.analysis.market_view import MarketView, classify_vol
from tradebot.config import Underlying
from tradebot.constants import (BEAR_CALL_SPREAD, BEAR_PUT_SPREAD, BEARISH,
                                BULL_CALL_SPREAD, BULL_PUT_SPREAD, BULLISH,
                                IRON_CONDOR, LONG_CALL, LONG_PUT, NEUTRAL,
                                VOL_HIGH, VOL_LOW, VOL_NORMAL)
from tradebot.strategy.selector import select_strategy

U = Underlying(name="NIFTY", security_id=13, lot_size=75, strike_step=50)


def view(chain, direction, score, vol, strong=False, confidence=0.8):
    return MarketView(
        underlying="NIFTY", spot=chain.spot, direction_score=score,
        direction=direction, strong=strong, vol_regime=vol,
        confidence=confidence, vix=15.0, chain=chain, expiry="2099-12-31",
    )


@pytest.mark.parametrize("direction,vol,strong,expected", [
    (BULLISH, VOL_LOW, True, LONG_CALL),
    (BULLISH, VOL_LOW, False, BULL_CALL_SPREAD),
    (BULLISH, VOL_NORMAL, True, BULL_CALL_SPREAD),
    (BULLISH, VOL_HIGH, False, BULL_PUT_SPREAD),
    (BEARISH, VOL_LOW, True, LONG_PUT),
    (BEARISH, VOL_NORMAL, False, BEAR_PUT_SPREAD),
    (BEARISH, VOL_HIGH, True, BEAR_CALL_SPREAD),
    (NEUTRAL, VOL_HIGH, False, IRON_CONDOR),
])
def test_selection_matrix(chain, settings, direction, vol, strong, expected):
    v = view(chain, direction, 60 if strong else 40, vol, strong)
    sel = select_strategy(v, U, settings)
    assert sel.actionable, sel.reason
    assert sel.plan.strategy == expected


def test_neutral_low_vol_no_trade(chain, settings):
    sel = select_strategy(view(chain, NEUTRAL, 0, VOL_LOW), U, settings)
    assert not sel.actionable
    assert "no edge" in sel.reason


def test_low_confidence_rejected(chain, settings):
    v = view(chain, BULLISH, 60, VOL_LOW, strong=True, confidence=0.3)
    sel = select_strategy(v, U, settings)
    assert not sel.actionable
    assert "confidence" in sel.reason


def test_no_chain_rejected(settings):
    v = MarketView(underlying="NIFTY", spot=0, direction_score=60,
                   direction=BULLISH, strong=True, vol_regime=VOL_LOW,
                   confidence=0.9, chain=None, expiry=None)
    assert not select_strategy(v, U, settings).actionable


def test_classify_vol():
    assert classify_vol(20.0, None, 17.0, 12.5)[0] == VOL_HIGH
    assert classify_vol(10.0, None, 17.0, 12.5)[0] == VOL_LOW
    assert classify_vol(15.0, None, 17.0, 12.5)[0] == VOL_NORMAL
    assert classify_vol(None, 18.0, 17.0, 12.5)[0] == VOL_HIGH
    assert classify_vol(None, None, 17.0, 12.5)[0] == VOL_NORMAL
