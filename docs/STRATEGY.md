# Strategy playbook

The system follows the framework taught in **Zerodha Varsity, Module 5
(Options Theory) and Module 6 (Option Strategies)**: first form a *view*
(direction + conviction), then read *volatility*, and only then pick the
structure. Premium is bought when volatility is cheap and sold (with defined
risk) when it is rich. Naked short options are never allowed.

## 1. Forming the view

Five inputs are fused into a single direction score in [-100, +100]
(weights configurable in `settings.yaml`):

| Component | Weight | What it reads |
|---|---|---|
| Daily trend | 0.30 | EMA20/EMA50 structure, Supertrend(10,3), ADX gate (<20 halves the score) |
| Intraday momentum | 0.25 | 15-min RSI(14) and MACD(12,26,9) with histogram expansion |
| Option chain | 0.20 | PCR (writer positioning), max-pain drift, OI support/resistance proximity |
| FII/DII flows | 0.15 | NSE daily cash-market net activity (±3000 cr saturates) |
| News sentiment | 0.10 | keyword scoring on Google News / ET market headlines |

A **confidence** value = (data coverage) × (component agreement). If
components disagree or data is missing, confidence drops below the
`min_confidence` floor and the system stays out — *not losing money is the
first way of making money*.

|score| ≥ 30 → directional view; ≥ 55 → strong view; otherwise neutral.

## 2. Reading volatility

India VIX (fallback: ATM IV from the chain):

- VIX ≥ 17 → **HIGH** vol: premiums rich → sell premium with defined risk
- VIX ≤ 12.5 → **LOW** vol: premiums cheap → buy premium
- otherwise **NORMAL** → spreads (theta-neutral-ish, defined risk)

## 3. The selection matrix

| View \ Vol | LOW | NORMAL | HIGH |
|---|---|---|---|
| Strong bull | Long ATM call | Bull call spread | Bull put spread |
| Mild bull | Bull call spread | Bull call spread | Bull put spread |
| Neutral | **no trade** | **no trade** | Iron condor |
| Mild bear | Bear put spread | Bear put spread | Bear call spread |
| Strong bear | Long ATM put | Bear put spread | Bear call spread |

Strike rules (Varsity guidance):

- **Long options:** ATM. No deep-OTM lottery tickets, no illiquid deep-ITM.
- **Debit spreads:** buy ATM, sell 3 strike-steps OTM (150 pts on NIFTY).
- **Credit spreads:** sell the ~0.28-delta strike, buy a wing 4 steps further.
- **Iron condor:** short strangle at ~0.20 delta, wings 3 steps out.

## 4. Risk rules (non-negotiable)

With ₹50,000 capital:

- planned risk per trade ≤ **3%** (₹1,500), enforced before entry
- daily loss ≥ **5%** (₹2,500) → kill switch, no more trades that day
- max **2** open positions, max **3** entries/day
- **unbounded-loss structures are rejected outright**
- no entries before 09:30 (opening noise) or after 14:30
- intraday positions squared off at 15:12; expiry-day positions always closed
- long entries blocked after 13:30 on expiry day (gamma/theta cliff)

## 5. Exits

| Structure | Stop loss | Target | Trailing |
|---|---|---|---|
| Debit (long opt / debit spread) | −30% of premium paid | +60% of premium paid | after +1R, lock peak −0.5R |
| Credit (credit spread / condor) | loss = 1.5× credit received | +50% of max profit | same trail rule |

Rationale: option sellers' edge comes from *not* holding to expiry (book at
50% of max profit, a standard improvement over Varsity's hold-to-expiry
illustrations), and option buyers must cap theta bleed with premium stops.

## 6. Why these defaults for ₹50k

One NIFTY lot (75) ATM option costs roughly ₹8-15k premium; a hedged
NIFTY credit spread needs roughly ₹25-35k margin. The capital supports
exactly 1-2 defined-risk positions — which is what the position limits
encode. BANKNIFTY is intentionally excluded by default (larger premiums,
margin and gap risk); add it in `settings.yaml` only after the account grows.

## 7. Honest expectations

No signal stack guarantees profits. The system's edge comes from
discipline: defined risk on every trade, cutting losers mechanically,
and staying out when there is no edge. Run **paper mode for 4-6 weeks**,
review `reports/`, and only flip to live if the profit factor and drawdown
satisfy you. Expect losing days and losing weeks; the kill switch exists
because they will happen.
