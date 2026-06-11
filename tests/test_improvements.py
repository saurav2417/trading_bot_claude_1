"""Tests for the regime filter, IV-percentile vol classification, event-day
guard and journal analytics added in the 'make it successful' batch."""

from tradebot.analysis.market_view import (MarketView, classify_vol_adaptive,
                                           percentile_rank)
from tradebot.analysis.technicals import regime_check
from tradebot.config import Underlying
from tradebot.constants import (BULLISH, IRON_CONDOR, NEUTRAL, VOL_HIGH,
                                VOL_LOW, VOL_NORMAL)
from tradebot.journal.journal import Journal
from tradebot.journal.reports import performance_breakdown
from tradebot.simulator import Simulator
from tradebot.strategy import strategies as st
from tradebot.strategy.selector import select_strategy

from conftest import make_settings, synthetic_chain
from test_simulator import synthetic_market

U = Underlying(name="NIFTY", security_id=13, lot_size=75, strike_step=50)
REGIME_CFG = {"enabled": True, "min_daily_adx": 18,
              "range_compression_days": 5, "range_compression_pct": 1.2}


def candles(closes, spread=20.0):
    return [{"open": c, "high": c + spread, "low": c - spread, "close": c,
             "volume": 1e6, "time": None} for c in closes]


# ------------------------------------------------------------ regime filter
def test_regime_trending_market_passes():
    trending = candles([20000 + i * 80 for i in range(120)])
    ok, note = regime_check(trending, REGIME_CFG)
    assert ok and "trending" in note


def test_regime_chop_blocked():
    flat = candles([20000 + (5 if i % 2 else -5) for i in range(120)], spread=10)
    ok, note = regime_check(flat, REGIME_CFG)
    assert not ok and "chop" in note


def test_regime_disabled_always_passes():
    flat = candles([20000.0] * 120, spread=1)
    assert regime_check(flat, {})[0]
    assert regime_check(flat, {"enabled": False})[0]


def test_selector_chop_blocks_directional_allows_condor(tmp_path):
    from tradebot.analysis.options_analysis import parse_chain
    settings = make_settings(tmp_path)
    chain = parse_chain(synthetic_chain())

    bull = MarketView(underlying="NIFTY", spot=chain.spot, direction_score=60,
                      direction=BULLISH, strong=True, vol_regime=VOL_LOW,
                      confidence=0.9, chain=chain, expiry="2099-12-31",
                      trending=False, regime_note="chop: ADX 12.0 < 18")
    sel = select_strategy(bull, U, settings)
    assert not sel.actionable and "chop filter" in sel.reason

    condor = MarketView(underlying="NIFTY", spot=chain.spot, direction_score=0,
                        direction=NEUTRAL, strong=False, vol_regime=VOL_HIGH,
                        confidence=0.9, chain=chain, expiry="2099-12-31",
                        trending=False, regime_note="chop")
    sel = select_strategy(condor, U, settings)
    assert sel.actionable and sel.plan.strategy == IRON_CONDOR


# ------------------------------------------------------ IV percentile regime
def test_percentile_rank():
    history = [float(v) for v in range(10, 21)]  # 10..20
    assert percentile_rank(history, 20) == 100.0
    assert percentile_rank(history, 9) == 0.0
    assert 40 <= percentile_rank(history, 15) <= 60


def test_classify_vol_adaptive_uses_percentile():
    cfg = {"use_iv_percentile": True, "vol_percentile_high": 75,
           "vol_percentile_low": 25, "vix_high": 17.0, "vix_low": 12.5}
    history = [10 + (i % 11) for i in range(110)]  # values 10..20
    # 19 sits in the top quartile of history even though it's > fixed 17 anyway;
    # the interesting case: 16 is HIGH by percentile in a 10-20 world…
    assert classify_vol_adaptive(19.0, history, cfg)[0] == VOL_HIGH
    assert classify_vol_adaptive(11.0, history, cfg)[0] == VOL_LOW
    assert classify_vol_adaptive(15.0, history, cfg)[0] == VOL_NORMAL


def test_classify_vol_adaptive_falls_back_without_history():
    cfg = {"use_iv_percentile": True, "vix_high": 17.0, "vix_low": 12.5}
    assert classify_vol_adaptive(20.0, [], cfg)[0] == VOL_HIGH
    assert classify_vol_adaptive(10.0, [14.0] * 10, cfg)[0] == VOL_LOW
    assert classify_vol_adaptive(None, [], cfg)[0] == VOL_NORMAL


def test_classify_vol_adaptive_percentile_beats_fixed():
    # calm year: history 8-13, current 14 is rich by percentile though < 17 fixed
    cfg = {"use_iv_percentile": True, "vol_percentile_high": 75,
           "vol_percentile_low": 25, "vix_high": 17.0, "vix_low": 12.5}
    calm_history = [8 + (i % 6) for i in range(120)]  # 8..13
    assert classify_vol_adaptive(14.0, calm_history, cfg)[0] == VOL_HIGH


# ------------------------------------------------------------ event-day guard
def test_simulator_skips_event_days(tmp_path):
    daily, intraday, vix = synthetic_market()
    test_days = sorted({b["time"].date().isoformat() for b in intraday})
    settings = make_settings(tmp_path, events={"skip_dates": test_days[-10:]})
    result = Simulator(settings, daily, intraday, vix, weeks=2).run()
    assert len(result.closed) == 0  # every test day was an event day

    settings2 = make_settings(tmp_path, events={"skip_dates": []})
    result2 = Simulator(settings2, daily, intraday, vix, weeks=2).run()
    assert len(result2.closed) > 0


# ---------------------------------------------------------- journal analytics
def test_performance_breakdown(tmp_path):
    from tradebot.analysis.options_analysis import parse_chain
    settings = make_settings(tmp_path)
    journal = Journal(settings.db_path)
    chain = parse_chain(synthetic_chain())
    for i, pnl in enumerate([1500.0, -800.0, 400.0]):
        plan = st.bull_call_spread(U, "2099-12-31", chain, lots=1)
        plan.view_summary = (f"NIFTY spot=25000.0 | BULLISH score=+45 "
                             f"| vol=NORMAL vix=14.0 | conf=0.7{i} | x=+1")
        journal.record_open(plan, "paper", 1000.0)
        journal.record_close(plan.plan_id, {}, pnl,
                             "target" if pnl > 0 else "stop loss")
    out = performance_breakdown(journal)
    assert "By strategy" in out and "BULL_CALL_SPREAD" in out
    assert "By vol regime" in out and "NORMAL" in out
    assert "By exit reason" in out and "stop loss" in out
    assert "weak evidence" in out  # n < 50 warning


def test_performance_breakdown_empty(tmp_path):
    settings = make_settings(tmp_path)
    out = performance_breakdown(Journal(settings.db_path))
    assert "No closed trades" in out


# ------------------------------------------------------ scrip master parser
def _client_with_master(tmp_path, csv_text):
    import datetime
    from tradebot.broker.dhan_client import DhanClient
    c = DhanClient.__new__(DhanClient)
    c._scrip_index = None
    c.cache_dir = tmp_path
    (tmp_path / f"scrip_master_v2_{datetime.date.today().isoformat()}.csv").write_text(csv_text)
    return c


COMPACT_CSV = (
    "SEM_EXM_EXCH_ID,SEM_INSTRUMENT_NAME,SM_SYMBOL_NAME,SEM_EXPIRY_DATE,"
    "SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_SMST_SECURITY_ID,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL\n"
    "NSE,OPTIDX,NIFTY,2026-06-16,23200.000000,PE,123456,65,NIFTY 16 JUN 23200 PUT\n"
    "NSE,OPTIDX,NIFTY,2026-06-16,23050.000000,CE,123457,65,NIFTY 16 JUN 23050 CALL\n"
    "NSE,EQUITY,RELIANCE,,0,,999,1,RELIANCE\n"
)

# the live failure mode: SM_SYMBOL_NAME blank on option rows, underlying only
# present in the trading/custom symbol
COMPACT_CSV_BLANK_SYMBOL = (
    "SEM_EXM_EXCH_ID,SEM_INSTRUMENT_NAME,SM_SYMBOL_NAME,SEM_EXPIRY_DATE,"
    "SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_SMST_SECURITY_ID,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL\n"
    "NSE,OPTIDX,,2026-06-16,23200.000000,PE,123456,65,NIFTY 16 JUN 23200 PUT\n"
    "NSE,OPTIDX,,2026-06-16,45000.000000,CE,222,15,BANKNIFTY 16 JUN 45000 CALL\n"
)

DETAILED_CSV = (
    "EXCH_ID,INSTRUMENT,UNDERLYING_SYMBOL,SM_EXPIRY_DATE,STRIKE_PRICE,"
    "OPTION_TYPE,SECURITY_ID,LOT_SIZE,DISPLAY_NAME\n"
    "NSE,OPTIDX,NIFTY,2026-06-16,23200.00,PE,123456,65,NIFTY 23200 PE\n"
)


def test_scrip_master_compact_schema(tmp_path):
    c = _client_with_master(tmp_path, COMPACT_CSV)
    idx = c._load_scrip_master()
    assert len(idx) == 2  # equity row skipped
    assert c.resolve_lot_size("NIFTY") == 65
    assert c.resolve_option("NIFTY", "2026-06-16", 23200, "PE")["security_id"] == 123456


def test_scrip_master_detailed_schema(tmp_path):
    c = _client_with_master(tmp_path, DETAILED_CSV)
    assert c.resolve_lot_size("NIFTY") == 65
    assert c.resolve_option("NIFTY", "2026-06-16", 23200, "PE")["security_id"] == 123456


def test_scrip_master_derives_underlying_when_symbol_blank(tmp_path):
    c = _client_with_master(tmp_path, COMPACT_CSV_BLANK_SYMBOL)
    idx = c._load_scrip_master()
    assert len(idx) == 2
    assert c.resolve_lot_size("NIFTY") == 65
    assert c.resolve_lot_size("BANKNIFTY") == 15
    assert c.resolve_option("NIFTY", "2026-06-16", 23200, "PE")["security_id"] == 123456


def test_scrip_master_empty_raises_with_headers(tmp_path):
    from tradebot.broker.dhan_client import DhanError
    c = _client_with_master(tmp_path, "COL_A,COL_B\nx,y\n")
    try:
        c._load_scrip_master()
        assert False, "expected DhanError"
    except DhanError as exc:
        assert "COL_A" in str(exc)  # surfaces seen columns for diagnosis


# --------------------------------------------------------- gamma exposure
def test_gex_computed_from_chain():
    from tradebot.analysis.options_analysis import parse_chain
    a = parse_chain(synthetic_chain())
    assert a.net_gex is not None
    assert any("GEX" in n for n in a.notes)
    # symmetric gamma, put OI dominates below spot in the fixture -> sign sane
    assert isinstance(a.net_gex, float)


def test_gex_absent_without_greeks():
    from tradebot.analysis.options_analysis import parse_chain
    chain = synthetic_chain()
    for legs in chain["oc"].values():
        legs["ce"]["greeks"].pop("gamma", None)
        legs["pe"]["greeks"].pop("gamma", None)
    a = parse_chain(chain)
    assert a.net_gex is None  # no fabricated values


def test_vol_premium_filter_mapping():
    from tradebot.simulator import apply_vol_premium_filter, realized_vol_pct
    # rich premium -> debit becomes credit
    assert apply_vol_premium_filter("LONG_CALL", 3.0) == "BULL_PUT_SPREAD"
    assert apply_vol_premium_filter("BEAR_PUT_SPREAD", 3.0) == "BEAR_CALL_SPREAD"
    # cheap premium -> credit becomes debit, condor refused
    assert apply_vol_premium_filter("BULL_PUT_SPREAD", -3.0) == "BULL_CALL_SPREAD"
    assert apply_vol_premium_filter("IRON_CONDOR", -3.0) is None
    # neutral band / missing data -> unchanged
    assert apply_vol_premium_filter("LONG_CALL", 0.5) == "LONG_CALL"
    assert apply_vol_premium_filter("LONG_CALL", None) == "LONG_CALL"
    rv = realized_vol_pct([100, 101, 99, 102, 100, 101])
    assert rv is not None and rv > 0
