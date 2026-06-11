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
        equity = settings.capital
        peak, max_dd = equity, 0.0
        for t in closed:  # ordered by closed_at
            equity += t["realized_pnl"] or 0
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        month = day[:7]
        month_pnl = sum((t["realized_pnl"] or 0) for t in closed
                        if (t["closed_at"] or "").startswith(month))
        lines += [
            "",
            "## Cumulative",
            f"- Closed trades: {len(closed)} | Win rate: {len(wins)/len(closed)*100:.0f}%",
            f"- Gross profit: ₹{gross_win:,.0f} | Gross loss: ₹{gross_loss:,.0f}",
            f"- Net P&L: ₹{journal.total_realized_pnl():,.0f} "
            f"({journal.total_realized_pnl()/settings.capital*100:+.1f}% on capital)",
            f"- This month ({month}): ₹{month_pnl:,.0f} "
            f"({month_pnl/settings.capital*100:+.1f}%)",
            f"- Max drawdown to date: ₹{max_dd:,.0f} "
            f"({max_dd/settings.capital*100:.1f}% of starting capital)",
        ]
        if gross_loss < 0:
            lines.append(f"- Profit factor: {abs(gross_win/gross_loss):.2f}")
    return "\n".join(lines) + "\n"


def performance_breakdown(journal: Journal) -> str:
    """Setup-level attribution: P&L by strategy, vol regime, entry hour,
    confidence bucket and exit reason. This is the 'let the journal kill
    your losers' tool — meaningful once ~50 trades have accumulated."""
    import re
    closed = journal.all_closed_trades()
    if not closed:
        return "No closed trades yet — run the bot first.\n"

    def add(table: dict, key: str, pnl: float) -> None:
        n, total, wins = table.get(key, (0, 0.0, 0))
        table[key] = (n + 1, total + pnl, wins + (1 if pnl > 0 else 0))

    by_strategy: dict = {}
    by_vol: dict = {}
    by_hour: dict = {}
    by_conf: dict = {}
    by_exit: dict = {}
    for t in closed:
        pnl = t["realized_pnl"] or 0.0
        vs = t["view_summary"] or ""
        vol = (re.search(r"vol=(\w+)", vs) or [None, "unknown"])[1]
        conf_m = re.search(r"conf=([\d.]+)", vs)
        conf = float(conf_m[1]) if conf_m else None
        conf_bucket = ("unknown" if conf is None else
                       "<0.6" if conf < 0.6 else "0.6-0.8" if conf < 0.8 else ">=0.8")
        hour = (t["opened_at"] or "")[11:13] or "??"
        add(by_strategy, t["strategy"], pnl)
        add(by_vol, vol, pnl)
        add(by_hour, f"{hour}:00", pnl)
        add(by_conf, conf_bucket, pnl)
        add(by_exit, t["exit_reason"] or "unknown", pnl)

    def section(title: str, table: dict) -> list[str]:
        rows = [f"## {title}", "| Bucket | Trades | Win rate | P&L |", "|---|---|---|---|"]
        for key, (n, total, wins) in sorted(table.items()):
            rows.append(f"| {key} | {n} | {wins/n*100:.0f}% | ₹{total:,.0f} |")
        rows.append("")
        return rows

    lines = [f"# Performance breakdown — {len(closed)} closed trades", ""]
    if len(closed) < 50:
        lines += [f"_Only {len(closed)} trades: patterns below are weak evidence. "
                  "Re-check at 50+._", ""]
    for title, table in (("By strategy", by_strategy), ("By vol regime", by_vol),
                         ("By entry hour", by_hour),
                         ("By confidence", by_conf), ("By exit reason", by_exit)):
        lines += section(title, table)
    return "\n".join(lines)


def write_daily_report(journal: Journal, settings: Settings,
                       day: str | None = None) -> Path:
    day = day or date.today().isoformat()
    content = daily_report(journal, settings, day)
    path = settings.reports_dir / f"report_{day}.md"
    path.write_text(content)
    return path
