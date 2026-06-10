from tradebot.analysis.llm_analyst import LLMAnalyst, LLMView, build_dossier
from tradebot.analysis.market_view import apply_llm_view
from tradebot.analysis.options_analysis import parse_chain

from conftest import synthetic_chain


def llm_view(score=60, conviction=0.8, direction="BULLISH"):
    return LLMView(
        direction=direction, direction_score=score, conviction=conviction,
        volatility_view="NORMAL", suggested_strategy="BULL_CALL_SPREAD",
        key_factors=["uptrend intact"], risks=["global selloff"],
        summary="Bullish bias with writers supporting below spot.",
    )


def test_primary_mode_llm_drives_view():
    score, conf, notes = apply_llm_view(10.0, 0.4, llm_view(60, 0.8),
                                        mode="primary", weight=0.35)
    assert score == 60.0 and conf == 0.8
    assert notes == []


def test_primary_mode_disagreement_haircut():
    score, conf, notes = apply_llm_view(-45.0, 0.7, llm_view(60, 0.8),
                                        mode="primary", weight=0.35)
    assert score == 60.0
    assert conf == 0.65  # 0.8 - 0.15
    assert any("disagrees" in n for n in notes)


def test_component_mode_blends():
    score, conf, _ = apply_llm_view(0.0, 0.5, llm_view(100, 1.0),
                                    mode="component", weight=0.5)
    # (0 + 100*0.5) / 1.5 = 33.3
    assert 33.0 <= score <= 34.0
    assert 0.5 < conf < 1.0


def test_analyst_disabled_without_key():
    analyst = LLMAnalyst({"enabled": True}, api_key="")
    assert not analyst.enabled
    assert analyst.analyze("anything") is None


def test_analyst_disabled_by_config():
    analyst = LLMAnalyst({"enabled": False}, api_key="sk-test")
    assert not analyst.enabled


def test_dossier_contains_key_data():
    chain = parse_chain(synthetic_chain())
    from types import SimpleNamespace
    flows = SimpleNamespace(date="2026-06-10", fii_net=1200.0, dii_net=-300.0)
    dossier = build_dossier(
        underlying="NIFTY", spot=25000.0,
        daily_detail={"ema20": 24900, "supertrend": "UP", "adx": 28},
        intraday_detail={"rsi14": 61.2, "macd_hist": 4.1},
        recent_closes=[24800.0, 24900.0, 25000.0],
        chain=chain, vix=14.2, flows=flows,
        headlines=["Nifty hits record high"],
        quant_components={"daily_trend": 0.75},
    )
    for fragment in ("NIFTY", "25000", "PCR", "India VIX: 14.20",
                     "FII net: +1200", "record high", "daily_trend",
                     "supertrend"):
        assert fragment in dossier, f"missing {fragment!r}"


def test_clamping():
    from tradebot.analysis.llm_analyst import _clamp
    v = llm_view(score=100, conviction=1.0)
    v.direction_score = 250
    v.conviction = 3.0
    v = _clamp(v)
    assert v.direction_score == 100 and v.conviction == 1.0
