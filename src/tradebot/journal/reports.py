"""Daily and cumulative performance reports rendered as markdown."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ..config import Settings
from .journal import Journal


def daily_report(journal: Journal, settings: Settings,
                 day: str | None = None) -> str:
    day = day or date.today().isoformat()
    trades = journal.trades_for_day(day)
    realized = sum(t["realized_pnl"] or 0 for t in trades if t["status"] == "CLOSED")
    capital = settings.capital + journal.total_realized_pnl()

    lines = [
        f"# Trade report — {day}",
        "",
        f"- Mode: **{settings.mode}**",
        f"- Capital (start ₹{settings.capital:,.0f}): **₹{capital:,.0f}**",
        f"- Day P&L: **₹{realized:,.0f}**",
        f"- Trades touched today: {len(trades)}",
        "",
    ]
    if trades:
        lines += [
            "| Plan | Strategy | Status | Entry net | Risk | P&L | Exit reason |",
            "|------|----------|--------|-----------|------|-----|-------------|",
        ]
        for t in trades:
            pnl = f"₹{t['realized_pnl']:,.0f}" if t["realized_pnl"] is not None else "—"
            lines.append(
                f"| {t['plan_id']} | {t['strategy']} | {t['status']} "
                f"| ₹{t['entry_net']:,.0f} | ₹{t['planned_risk']:,.0f} "
                f"| {pnl} | {t['exit_reason'] or '—'} |")
    else:
        lines.append("_No trades today._")

    closed = journal.all_closed_trades()
    if closed:
        wins = [t for t in closed if (t["realized_pnl"] or 0) > 0]
        gross_win = sum(t["realized_pnl"] for t in wins)
        gross_loss = sum(t["realized_pnl"] for t in closed if (t["realized_pnl"] or 0) <= 0)
        lines += [
            "",
            "## Cumulative",
            f"- Closed trades: {len(closed)} | Win rate: {len(wins)/len(closed)*100:.0f}%",
            f"- Gross profit: ₹{gross_win:,.0f} | Gross loss: ₹{gross_loss:,.0f}",
            f"- Net P&L: ₹{journal.total_realized_pnl():,.0f} "
            f"({journal.total_realized_pnl()/settings.capital*100:+.1f}% on capital)",
        ]
        if gross_loss < 0:
            lines.append(f"- Profit factor: {abs(gross_win/gross_loss):.2f}")
    return "\n".join(lines) + "\n"


def write_daily_report(journal: Journal, settings: Settings,
                       day: str | None = None) -> Path:
    day = day or date.today().isoformat()
    content = daily_report(journal, settings, day)
    path = settings.reports_dir / f"report_{day}.md"
    path.write_text(content)
    return path
