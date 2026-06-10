# tradebot — autonomous NIFTY options trading system

An end-to-end, zero-human-in-the-loop options trading system for the Indian
market, built on the **DhanHQ v2 API** and the strategy framework from
**Zerodha Varsity** (Modules 5 & 6). It forms a market view from technicals,
the option chain, FII/DII flows and news; picks a defined-risk option
structure; sizes it for the account; executes; monitors stop-loss/target/
trailing exits; squares off; and writes a daily report — every trading day,
automatically.

```
 ┌────────────────────────── DATA ──────────────────────────┐
 │ DhanHQ: spot, daily+15min candles, option chain, VIX     │
 │ NSE: FII/DII flows   ·   RSS: news sentiment             │
 └──────────────────────────┬───────────────────────────────┘
                            ▼
 ┌──────────────────── ANALYSIS ────────────────────────────┐
 │ EMA/RSI/MACD/ADX/Supertrend · PCR · max pain · OI walls  │
 │ → MarketView: direction score, vol regime, confidence    │
 └──────────────────────────┬───────────────────────────────┘
                            ▼
 ┌──────────────────── STRATEGY ────────────────────────────┐
 │ Varsity matrix: view × volatility → structure            │
 │ long opt / debit spread / credit spread / iron condor    │
 └──────────────────────────┬───────────────────────────────┘
                            ▼
 ┌──────────────────── RISK GATE ───────────────────────────┐
 │ ≤3% risk/trade · 5% daily kill switch · ≤2 positions     │
 │ unbounded loss rejected · margin vs capital              │
 └──────────────────────────┬───────────────────────────────┘
                            ▼
 ┌──────────────── EXECUTION & MONITORING ──────────────────┐
 │ recommend → paper → live (DhanHQ orders)                 │
 │ SL / target / trail / time exits · 15:12 square-off      │
 └──────────────────────────┬───────────────────────────────┘
                            ▼
              SQLite journal · daily markdown reports
              optional Telegram notifications
```

## Quick start

```bash
git clone <this repo> && cd trading_bot_claude_1
pip install -e ".[dev]"            # or: pip install -r requirements.txt

cp .env.example .env               # fill in DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN
python -m pytest                   # 50 tests should pass

# one-shot: what would the system trade right now? (no orders ever)
PYTHONPATH=src python3 -m tradebot.cli recommend

# the autonomous loop (mode comes from config/settings.yaml, default: paper)
PYTHONPATH=src python3 -m tradebot.cli run
```

Other commands: `status`, `squareoff`, `report [--date YYYY-MM-DD]`,
`backtest [--days 500]`, `run --once` (cron-friendly single tick).

## The three modes

| Mode | What happens | When to use |
|---|---|---|
| `recommend` | prints/notifies trade plans, never places orders | day 1 |
| `paper` | simulated fills at live chain prices + slippage, full monitoring & journaling | **weeks 1-6 (default)** |
| `live` | real LIMIT orders via DhanHQ, fund-limit checks, leg-ordering safety, auto-unwind on partial failure | only after paper results convince you |

Switch via `mode:` in `config/settings.yaml` or `TRADEBOT_MODE=live`.

## Running it hands-free

### Option A — GitHub Actions (no server needed)

The repo ships with `.github/workflows/trading-session.yml`, which runs the
bot entirely on GitHub's cloud:

1. **Add secrets** (repo → Settings → Secrets and variables → Actions →
   *New repository secret*): `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`,
   `ANTHROPIC_API_KEY` (for the LLM analyst), and optionally
   `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. Telegram turns on
   automatically once its secrets exist.
2. **Set the mode** (optional): repo → Settings → Secrets and variables →
   Actions → *Variables* → add `TRADEBOT_MODE` = `recommend`/`paper`/`live`
   (defaults to `paper`).
3. That's it. Every trading day two scheduled jobs run — **09:20–12:30 IST**
   and **12:25–15:50 IST** (GitHub caps a job at 6 h, so the session is
   split; the afternoon job queues behind the morning one and picks up open
   positions from the journal). State (trade journal + reports) persists on
   the **`bot-state` branch**, and each run also uploads reports as an
   artifact. You can trigger a session manually from the Actions tab
   (*Run workflow*), including a one-off `recommend` run.

**Caveat for live mode:** GitHub's cron scheduler can fire several minutes
late and (rarely) skip a run. Fine for recommendations and paper trading;
if real money is on the line, an always-on host is safer:

### Option B — always-on host (VPS / free tiers)

- **systemd**: `scripts/systemd/tradebot.service`
- **shell**: `scripts/run_bot.sh` (auto-restarts on crash)

Any ₹300–500/month VPS (or Oracle Cloud's free tier) is sufficient —
the bot is a single lightweight Python process.

The loop knows the IST session timeline: pre-market analysis 08:50, entries
only 09:30-14:30, monitoring every 45 s, square-off 15:12, EOD report 15:40,
sleeps through nights/weekends. All times configurable.

## The LLM analyst (Claude)

With `llm.enabled: true` (default) and an `ANTHROPIC_API_KEY` secret set, a
Claude model (`claude-opus-4-8`) forms the market view each scan: it reads the
full dossier — price action, indicator readings, option-chain positioning,
VIX, FII/DII flows, news — and returns a structured verdict (direction score,
conviction, volatility read, suggested structure, key factors, risks),
grounded in the Varsity framework via its system prompt. Its reasoning is
logged to the journal and sent to Telegram with every scan.

The division of labour is deliberate: **the LLM forms the view; deterministic
code keeps the guardrails.** Strategy construction, position sizing, risk
caps, stop losses and the kill switch are all mechanical — a bad model
response can never oversize a trade or remove a stop. If the quant composite
strongly disagrees with the LLM, confidence is haircut; if the API is down or
the key is missing, the system falls back to the quant composite and keeps
running. Cost: roughly ₹40–130 per trading day at ~22 scans (tune
`llm.model`/`llm.mode` in settings.yaml).

## What it trades and why

See [docs/STRATEGY.md](docs/STRATEGY.md) for the full playbook. Summary: a
weighted composite (daily trend 30%, intraday momentum 25%, option-chain
positioning 20%, FII/DII 15%, news 10%) produces a direction score; India
VIX classifies the volatility regime; the Varsity matrix maps the pair to a
defined-risk structure (ATM long options only in cheap vol with strong
conviction, credit spreads/condors when premiums are rich, debit spreads
otherwise). Every trade has a hard stop, a target, and a trailing lock.

## Risk controls (the part that matters)

- planned risk per trade capped at **3% of capital** (₹1,500 on ₹50k)
- **daily-loss kill switch** at 5% — the bot stops itself for the day
- max 2 open positions, 3 entries/day, naked shorts impossible by construction
- expiry-day and late-entry guards; forced intraday square-off
- capital tracks realized P&L, so position sizing shrinks after losses

## Operational notes

- **Token expiry:** Dhan access tokens last ~30 days. Regenerate and update
  `.env`; the bot fails loudly (and Telegram-notifies if configured) when
  auth breaks.
- **Lot sizes** are verified against Dhan's scrip master at order time, so
  exchange lot-size revisions are picked up automatically.
- **Holidays:** weekends are skipped; on NSE holidays no fresh data appears
  and the system simply finds nothing actionable.
- **The backtest command** validates only the directional signal against
  next-day index moves — paper mode is the true validation environment.

## ⚠️ Disclaimer

Options trading carries substantial risk of loss; index options are
leveraged instruments and most retail option buyers lose money. This
software places real orders when configured in `live` mode — you are
solely responsible for trades executed through your account, for SEBI/
exchange compliance, and for taxes. Past signals (and paper results)
do not guarantee future returns. Start in paper mode, and never trade
capital you cannot afford to lose.
