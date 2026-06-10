"""Option-chain analytics: PCR, max pain, ATM IV, support/resistance by OI.

Input is the Dhan option-chain payload:
  {"last_price": float, "oc": {"49500.000000": {"ce": {...}, "pe": {...}}}}
where each leg dict has last_price, oi, volume, implied_volatility, greeks...
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChainAnalysis:
    spot: float
    pcr: float | None = None              # total put OI / call OI
    max_pain: float | None = None
    atm_strike: float | None = None
    atm_iv: float | None = None           # average of ATM CE/PE IV
    oi_support: float | None = None       # strike with highest put OI
    oi_resistance: float | None = None    # strike with highest call OI
    direction_score: float = 0.0          # [-1, 1]
    notes: list[str] = field(default_factory=list)

    # raw per-strike data kept for strike selection downstream
    strikes: dict[float, dict] = field(default_factory=dict)


def parse_chain(chain: dict) -> ChainAnalysis:
    spot = float(chain.get("last_price") or 0.0)
    oc = chain.get("oc") or {}
    strikes: dict[float, dict] = {}
    for k, legs in oc.items():
        try:
            strikes[float(k)] = legs
        except (TypeError, ValueError):
            continue
    analysis = ChainAnalysis(spot=spot, strikes=strikes)
    if not strikes or spot <= 0:
        analysis.notes.append("empty option chain")
        return analysis

    total_ce_oi = total_pe_oi = 0.0
    ce_oi_by_strike: dict[float, float] = {}
    pe_oi_by_strike: dict[float, float] = {}
    for strike, legs in strikes.items():
        ce_oi = float((legs.get("ce") or {}).get("oi") or 0)
        pe_oi = float((legs.get("pe") or {}).get("oi") or 0)
        total_ce_oi += ce_oi
        total_pe_oi += pe_oi
        ce_oi_by_strike[strike] = ce_oi
        pe_oi_by_strike[strike] = pe_oi

    if total_ce_oi > 0:
        analysis.pcr = round(total_pe_oi / total_ce_oi, 3)
    if ce_oi_by_strike:
        analysis.oi_resistance = max(ce_oi_by_strike, key=ce_oi_by_strike.get)
        analysis.oi_support = max(pe_oi_by_strike, key=pe_oi_by_strike.get)

    analysis.max_pain = _max_pain(ce_oi_by_strike, pe_oi_by_strike)
    analysis.atm_strike = min(strikes, key=lambda s: abs(s - spot))
    atm = strikes[analysis.atm_strike]
    ivs = [
        float((atm.get(side) or {}).get("implied_volatility") or 0)
        for side in ("ce", "pe")
    ]
    ivs = [v for v in ivs if v > 0]
    if ivs:
        analysis.atm_iv = round(sum(ivs) / len(ivs), 2)

    analysis.direction_score = _chain_direction(analysis)
    return analysis


def _max_pain(ce_oi: dict[float, float], pe_oi: dict[float, float]) -> float | None:
    """Expiry price that minimises total option-writer payout."""
    strikes = sorted(set(ce_oi) | set(pe_oi))
    if not strikes:
        return None
    best, best_pain = None, float("inf")
    for expiry_at in strikes:
        pain = 0.0
        for s in strikes:
            pain += max(0.0, expiry_at - s) * ce_oi.get(s, 0.0)   # calls ITM
            pain += max(0.0, s - expiry_at) * pe_oi.get(s, 0.0)   # puts ITM
        if pain < best_pain:
            best, best_pain = expiry_at, pain
    return best


def _chain_direction(a: ChainAnalysis) -> float:
    """Writer-positioning read of the chain, scored in [-1, 1].

    Varsity framing: heavy put writing below spot = support / bullish;
    heavy call writing near or below spot = resistance / bearish.
    PCR extremes are read conventionally (high PCR -> put writers confident).
    """
    score = 0.0
    if a.pcr is not None:
        if a.pcr >= 1.3:
            score += 0.4
            a.notes.append(f"PCR {a.pcr} high: put writers aggressive (bullish)")
        elif a.pcr >= 1.1:
            score += 0.2
        elif a.pcr <= 0.7:
            score -= 0.4
            a.notes.append(f"PCR {a.pcr} low: call writers aggressive (bearish)")
        elif a.pcr <= 0.9:
            score -= 0.2

    if a.max_pain is not None and a.spot > 0:
        drift = (a.max_pain - a.spot) / a.spot
        # gentle pull toward max pain, capped at +/-0.3
        score += max(-0.3, min(0.3, drift * 20))

    if a.oi_support is not None and a.oi_resistance is not None and a.spot > 0:
        # spot near OI support -> bullish bounce zone; near resistance -> bearish
        if abs(a.spot - a.oi_support) / a.spot < 0.004:
            score += 0.2
            a.notes.append(f"spot near max put-OI support {a.oi_support:.0f}")
        if abs(a.spot - a.oi_resistance) / a.spot < 0.004:
            score -= 0.2
            a.notes.append(f"spot near max call-OI resistance {a.oi_resistance:.0f}")

    return max(-1.0, min(1.0, score))


def leg_price(analysis: ChainAnalysis, strike: float, option_type: str) -> float | None:
    legs = analysis.strikes.get(strike)
    if not legs:
        return None
    leg = legs.get(option_type.lower())
    if not leg:
        return None
    price = leg.get("last_price")
    return float(price) if price else None


def leg_delta(analysis: ChainAnalysis, strike: float, option_type: str) -> float | None:
    legs = analysis.strikes.get(strike)
    if not legs:
        return None
    greeks = (legs.get(option_type.lower()) or {}).get("greeks") or {}
    delta = greeks.get("delta")
    return float(delta) if delta is not None else None
