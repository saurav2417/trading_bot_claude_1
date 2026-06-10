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

- **systemd** (recommended): `scripts/systemd/tradebot.service`
- **shell**: `scripts/run_bot.sh` (auto-restarts on crash)

The loop knows the IST session timeline: pre-market analysis 08:50, entries
only 09:30-14:30, monitoring every 45 s, square-off 15:12, EOD report 15:40,
sleeps through nights/weekends. All times configurable.

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
