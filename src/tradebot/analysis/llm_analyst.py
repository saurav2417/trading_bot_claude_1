"""LLM market analyst: Claude reasons over the full market dossier.

The analyst receives everything the quantitative layer computed — candles,
indicator readings, option-chain positioning, India VIX, FII/DII flows and
news headlines — and produces a structured market view grounded in Zerodha
Varsity principles (structured JSON output, validated by the SDK).

Division of labour, by design:
  * the LLM forms the VIEW (direction, conviction, volatility read)
  * deterministic code keeps the GUARDRAILS (strategy construction, position
    sizing, risk caps, stop losses) — a bad model response can never oversize
    a trade or remove a stop.
Fails soft: any API problem logs a warning and the quantitative composite
is used instead, so the trading loop never stalls on the LLM.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are an options strategist for the Indian index options \
market (NIFTY), trading a small retail account strictly by the framework of \
Zerodha Varsity modules 5 and 6.

Your job each scan: study the dossier (price action, technical indicators, \
option-chain positioning, India VIX, FII/DII flows, news) and produce ONE \
honest market view for the near term (intraday to a few days).

Principles you must follow:
- First decide direction and conviction, then read volatility. Premium is \
bought when vol is cheap and sold (defined-risk only) when vol is rich.
- Writer positioning matters: heavy put OI below spot is support, heavy call \
OI above spot is resistance; PCR extremes read conventionally.
- Capital preservation beats opportunity. If evidence is mixed, say NEUTRAL \
with low conviction — "no trade" is a position. Never manufacture conviction.
- Event risk: if the dossier date or headlines imply a scheduled macro event \
(RBI policy, Union Budget, election results, Fed/US-CPI overnight, major \
earnings or expiry-day distortions), lower conviction and name it in risks — \
gaps invalidate intraday technicals.
- You do NOT size positions, set stops, or place orders; deterministic risk \
code does that. Your direction_score and conviction drive strategy selection \
from this menu only: LONG_CALL, LONG_PUT, BULL_CALL_SPREAD, BEAR_PUT_SPREAD, \
BULL_PUT_SPREAD, BEAR_CALL_SPREAD, IRON_CONDOR, NO_TRADE.

Scoring: direction_score in [-100, 100]; |score| >= 30 means directional, \
>= 55 strong. conviction in [0, 1] reflects how strongly the evidence agrees \
— disagreeing signals or stale/missing data must lower it below 0.5."""


class LLMView(BaseModel):
    """Structured output schema enforced via the Messages API."""

    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    direction_score: int = Field(description="-100 (max bearish) to +100 (max bullish)")
    conviction: float = Field(description="0 to 1; below 0.5 means do not trade")
    volatility_view: Literal["HIGH", "NORMAL", "LOW"]
    suggested_strategy: Literal[
        "LONG_CALL", "LONG_PUT", "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD",
        "BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR", "NO_TRADE",
    ]
    key_factors: list[str] = Field(description="3-6 decisive observations from the dossier")
    risks: list[str] = Field(description="what could invalidate this view")
    summary: str = Field(description="2-3 sentence plain-language verdict")


class LLMAnalyst:
    def __init__(self, llm_cfg: dict, api_key: str = ""):
        self.cfg = llm_cfg or {}
        self.model = self.cfg.get("model", DEFAULT_MODEL)
        self.max_tokens = int(self.cfg.get("max_tokens", 16000))
        self._client = None
        self._api_key = api_key
        self.enabled = bool(self.cfg.get("enabled", False)) and bool(api_key)
        if self.cfg.get("enabled") and not api_key:
            log.warning("llm.enabled is true but ANTHROPIC_API_KEY is not set — "
                        "falling back to the quantitative composite")

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = (anthropic.Anthropic(api_key=self._api_key)
                            if self._api_key else anthropic.Anthropic())
        return self._client

    def analyze(self, dossier: str) -> LLMView | None:
        """One scan -> one structured view. Returns None on any failure."""
        if not self.enabled:
            return None
        try:
            import anthropic
            client = self._get_client()
            response = client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": dossier}],
                output_format=LLMView,
            )
            view = response.parsed_output
            if view is None:
                log.warning("LLM returned no parseable output")
                return None
            return _clamp(view)
        except anthropic.APIError as exc:
            log.warning("LLM analysis failed (%s); falling back to quant composite", exc)
            return None
        except Exception as exc:  # noqa: BLE001 — never let the LLM stall the loop
            log.warning("LLM analysis errored (%s); falling back to quant composite", exc)
            return None


def _clamp(view: LLMView) -> LLMView:
    view.direction_score = max(-100, min(100, view.direction_score))
    view.conviction = max(0.0, min(1.0, view.conviction))
    return view


def build_dossier(*, underlying: str, spot: float, daily_detail: dict,
                  intraday_detail: dict, recent_closes: list[float],
                  chain=None, vix: float | None = None, flows=None,
                  headlines: list[str] | None = None,
                  quant_components: dict | None = None) -> str:
    """Assemble everything the quant layer measured into one prompt document."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    lines = [f"# Market dossier: {underlying}",
             f"As of: {now.strftime('%A %d %B %Y, %H:%M')} IST",
             f"Spot: {spot:.1f}"]

    if recent_closes:
        closes = ", ".join(f"{c:.0f}" for c in recent_closes[-15:])
        chg = (recent_closes[-1] / recent_closes[0] - 1) * 100 if recent_closes[0] else 0
        lines += ["", f"## Recent daily closes (oldest->newest): {closes}",
                  f"Change over window: {chg:+.2f}%"]

    lines += ["", "## Daily technicals (EMA20/50, Supertrend, ADX)", str(daily_detail),
              "", "## Intraday 15-min momentum (RSI, MACD)", str(intraday_detail)]

    if chain is not None:
        lines += ["", "## Option chain (nearest expiry)",
                  f"PCR: {chain.pcr} | max pain: {chain.max_pain} | ATM IV: {chain.atm_iv}",
                  f"Max put-OI support: {chain.oi_support} | "
                  f"max call-OI resistance: {chain.oi_resistance}"]
        if chain.net_gex is not None:
            lines.append(
                f"Net gamma exposure (dealer convention): {chain.net_gex:,.0f}"
                + (f" | flip strike ~{chain.gex_flip:.0f}" if chain.gex_flip else "")
                + " — positive dampens moves (pinning), negative amplifies them")
    if vix is not None:
        lines += ["", f"## India VIX: {vix:.2f}"]
    if flows is not None:
        lines += ["", f"## Institutional flows ({flows.date})",
                  f"FII net: {flows.fii_net:+.0f} cr | DII net: {flows.dii_net:+.0f} cr"]
    if headlines:
        lines += ["", "## News headlines"]
        lines += [f"- {h}" for h in headlines[:10]]
    if quant_components:
        lines += ["", "## Quantitative component scores (each -1..+1, for reference)",
                  str(quant_components)]

    lines += ["", "Produce your market view now."]
    return "\n".join(lines)
