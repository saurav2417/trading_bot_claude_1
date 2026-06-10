"""Composite market view: fuse technicals, option chain, flows and news
into a single directional score plus a volatility regime.

This is the heart of the recommendation engine. Output drives strategy
selection exactly the way Varsity teaches it: first form a view (direction
+ conviction), then read volatility, then pick the structure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..config import Settings, Underlying
from ..constants import BEARISH, BULLISH, INDIA_VIX, NEUTRAL, VOL_HIGH, VOL_LOW, VOL_NORMAL
from ..data.fii_dii import FlowData, fetch_fii_dii
from ..data.news import NewsSentiment, fetch_news_sentiment
from .llm_analyst import LLMAnalyst, LLMView as LLMViewOutput, build_dossier
from .options_analysis import ChainAnalysis, parse_chain
from .technicals import daily_trend_score, intraday_momentum_score

log = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "daily_trend": 0.30,
    "intraday_momentum": 0.25,
    "option_chain": 0.20,
    "fii_dii": 0.15,
    "news": 0.10,
}


@dataclass
class MarketView:
    underlying: str
    spot: float
    direction_score: float          # [-100, 100]
    direction: str                  # BULLISH / BEARISH / NEUTRAL
    strong: bool
    vol_regime: str                 # HIGH / NORMAL / LOW
    confidence: float               # [0, 1] — data coverage x agreement
    vix: float | None = None
    chain: ChainAnalysis | None = None
    expiry: str | None = None
    components: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    llm: LLMViewOutput | None = None
    as_of: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def summary(self) -> str:
        comp = ", ".join(f"{k}={v:+.2f}" for k, v in self.components.items())
        return (
            f"{self.underlying} spot={self.spot:.1f} | {self.direction}"
            f"{' (strong)' if self.strong else ''} score={self.direction_score:+.0f} "
            f"| vol={self.vol_regime} vix={self.vix} | conf={self.confidence:.2f} | {comp}"
        )


class MarketViewBuilder:
    """Builds a MarketView for one underlying. External data (FII/DII, news)
    is fetched once and cached for the session day."""

    def __init__(self, settings: Settings, client):
        self.settings = settings
        self.client = client
        self.llm = LLMAnalyst(settings.llm, settings.anthropic_api_key)
        self._flows: FlowData | None | str = "unset"
        self._news: NewsSentiment | None = None

    # cached-per-run external inputs --------------------------------------
    def flows(self) -> FlowData | None:
        if self._flows == "unset":
            self._flows = fetch_fii_dii()
        return self._flows  # type: ignore[return-value]

    def news(self) -> NewsSentiment:
        if self._news is None:
            self._news = fetch_news_sentiment()
        return self._news

    # ---------------------------------------------------------------- main
    def build(self, underlying: Underlying) -> MarketView:
        s = self.settings
        weights = {**DEFAULT_WEIGHTS, **(s.weights or {})}
        components: dict[str, float] = {}
        notes: list[str] = []

        daily = self.client.daily_candles(
            underlying.security_id, underlying.segment, underlying.instrument, days=300)
        intraday = self.client.intraday_candles(
            underlying.security_id, underlying.segment, underlying.instrument,
            interval=15, days=7)

        trend = daily_trend_score(daily)
        momentum = intraday_momentum_score(intraday)
        components["daily_trend"] = trend.score
        components["intraday_momentum"] = momentum.score
        notes.append(f"daily: {trend.detail}")
        notes.append(f"intraday: {momentum.detail}")

        # option chain (nearest expiry)
        chain_analysis: ChainAnalysis | None = None
        expiry: str | None = None
        try:
            expiries = self.client.expiry_list(underlying.security_id, underlying.segment)
            expiry = pick_expiry(expiries)
            raw_chain = self.client.option_chain(
                underlying.security_id, expiry, underlying.segment)
            chain_analysis = parse_chain(raw_chain)
            components["option_chain"] = chain_analysis.direction_score
            notes.extend(chain_analysis.notes)
        except Exception as exc:  # noqa: BLE001
            log.warning("option chain unavailable: %s", exc)
            notes.append(f"option chain unavailable: {exc}")

        flows = self.flows()
        if flows is not None:
            components["fii_dii"] = flows.combined_bias
            notes.append(f"FII net {flows.fii_net:+.0f} cr, DII net {flows.dii_net:+.0f} cr"
                         f" ({flows.date})")

        sentiment = self.news()
        if sentiment.headlines:
            components["news"] = sentiment.score

        # weighted composite -> [-100, 100]
        used = {k: v for k, v in components.items() if k in weights}
        total_w = sum(weights[k] for k in used)
        raw = sum(weights[k] * v for k, v in used.items()) / total_w if total_w else 0.0
        score = max(-100.0, min(100.0, raw * 100.0))

        # confidence = data coverage x component agreement
        coverage = total_w / sum(weights.values())
        agreement = _agreement(list(used.values()))
        confidence = round(coverage * agreement, 2)

        # volatility regime from India VIX (fallback: ATM IV)
        vix = self._fetch_vix()
        vol_regime, vol_note = classify_vol(
            vix,
            chain_analysis.atm_iv if chain_analysis else None,
            float(s.signals.get("vix_high", 17.0)),
            float(s.signals.get("vix_low", 12.5)),
        )
        if vol_note:
            notes.append(vol_note)

        # LLM analyst: reasons over the full dossier; quant stays as audit/fallback
        llm_view = None
        if self.llm.enabled:
            spot_now = (chain_analysis.spot if chain_analysis and chain_analysis.spot
                        else (daily[-1]["close"] if daily else 0.0))
            dossier = build_dossier(
                underlying=underlying.name, spot=spot_now,
                daily_detail=trend.detail, intraday_detail=momentum.detail,
                recent_closes=[c["close"] for c in daily[-15:]],
                chain=chain_analysis, vix=vix, flows=flows,
                headlines=sentiment.headlines,
                quant_components={k: round(v, 2) for k, v in components.items()},
            )
            llm_view = self.llm.analyze(dossier)
        if llm_view is not None:
            components["llm"] = round(llm_view.direction_score / 100.0, 3)
            score, confidence, blend_notes = apply_llm_view(
                score, confidence, llm_view,
                mode=str(s.llm.get("mode", "primary")),
                weight=float(s.llm.get("component_weight", 0.35)),
            )
            notes.append(f"LLM verdict: {llm_view.summary}")
            notes.extend(f"LLM factor: {f}" for f in llm_view.key_factors)
            notes.extend(f"LLM risk: {r}" for r in llm_view.risks)
            notes.extend(blend_notes)
            if vix is None and (chain_analysis is None or not chain_analysis.atm_iv):
                vol_regime = llm_view.volatility_view
                notes.append("vol regime taken from LLM (no VIX/IV data)")

        thr = float(s.signals.get("direction_threshold", 30))
        strong_thr = float(s.signals.get("strong_direction_threshold", 55))
        if score >= thr:
            direction = BULLISH
        elif score <= -thr:
            direction = BEARISH
        else:
            direction = NEUTRAL

        spot = (chain_analysis.spot if chain_analysis and chain_analysis.spot
                else (daily[-1]["close"] if daily else 0.0))

        return MarketView(
            underlying=underlying.name,
            spot=spot,
            direction_score=round(score, 1),
            direction=direction,
            strong=abs(score) >= strong_thr,
            vol_regime=vol_regime,
            confidence=confidence,
            vix=vix,
            chain=chain_analysis,
            expiry=expiry,
            components={k: round(v, 3) for k, v in components.items()},
            notes=notes,
            llm=llm_view,
        )

    def _fetch_vix(self) -> float | None:
        try:
            return self.client.index_ltp(INDIA_VIX)
        except Exception as exc:  # noqa: BLE001
            log.warning("VIX fetch failed: %s", exc)
            return None


def apply_llm_view(quant_score: float, quant_confidence: float,
                   llm_view: LLMViewOutput, mode: str,
                   weight: float) -> tuple[float, float, list[str]]:
    """Blend the LLM's view with the quantitative composite.

    primary:   the LLM view drives score and confidence; if the quant
               composite strongly disagrees (opposite signs, both directional)
               confidence is haircut so the selector demands more agreement.
    component: the LLM is one weighted input alongside the quant composite.
    """
    notes: list[str] = []
    llm_score = float(llm_view.direction_score)
    if mode == "component":
        score = (quant_score + llm_score * weight) / (1.0 + weight)
        confidence = round((quant_confidence + llm_view.conviction * weight)
                           / (1.0 + weight), 2)
        return round(score, 1), confidence, notes

    # primary mode
    score = llm_score
    confidence = round(llm_view.conviction, 2)
    if quant_score * llm_score < 0 and abs(quant_score) >= 30 and abs(llm_score) >= 30:
        confidence = round(max(0.0, confidence - 0.15), 2)
        notes.append(f"quant composite ({quant_score:+.0f}) disagrees with LLM "
                     f"({llm_score:+.0f}); confidence reduced")
    return round(score, 1), confidence, notes


def classify_vol(vix: float | None, atm_iv: float | None,
                 high: float, low: float) -> tuple[str, str | None]:
    ref = vix if vix else atm_iv
    if ref is None:
        return VOL_NORMAL, "no vol data; assuming NORMAL regime"
    if ref >= high:
        return VOL_HIGH, f"vol {ref:.1f} >= {high}: favour premium selling"
    if ref <= low:
        return VOL_LOW, f"vol {ref:.1f} <= {low}: favour premium buying"
    return VOL_NORMAL, None


def pick_expiry(expiries: list[str], min_days: int = 0) -> str:
    """Nearest expiry at least min_days away (ISO date strings, sorted)."""
    from datetime import date, timedelta
    if not expiries:
        raise ValueError("no expiries available")
    cutoff = (date.today() + timedelta(days=min_days)).isoformat()
    for e in expiries:
        if e >= cutoff:
            return e
    return expiries[-1]


def _agreement(scores: list[float]) -> float:
    """1.0 when all components point the same way, lower when they conflict.
    Neutral components (|s|<0.1) are ignored."""
    sided = [s for s in scores if abs(s) >= 0.1]
    if not sided:
        return 0.5
    pos = sum(1 for s in sided if s > 0)
    neg = len(sided) - pos
    return max(pos, neg) / len(sided)
