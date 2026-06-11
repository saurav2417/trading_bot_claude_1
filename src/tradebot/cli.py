"""Command-line entry points.

  python -m tradebot.cli recommend   one-shot analysis + trade plan (no orders)
  python -m tradebot.cli run         autonomous loop (mode from settings.yaml)
  python -m tradebot.cli run --once  single tick (cron-friendly)
  python -m tradebot.cli status      open positions + capital
  python -m tradebot.cli squareoff   close everything now
  python -m tradebot.cli report      write/print today's report
  python -m tradebot.cli backtest    sanity-check the directional signal
"""

from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradebot")
    parser.add_argument("-c", "--config", help="path to settings.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("recommend", help="analyse and print trade plans (never orders)")
    run_p = sub.add_parser("run", help="autonomous trading loop")
    run_p.add_argument("--once", action="store_true", help="single tick then exit")
    run_p.add_argument("--until", metavar="HH:MM",
                       help="stop at this IST time (for capped cloud runners)")
    sub.add_parser("status", help="open positions and capital")
    sub.add_parser("squareoff", help="close all open positions now")
    rep_p = sub.add_parser("report", help="daily report")
    rep_p.add_argument("--date", help="YYYY-MM-DD (default today)")
    bt_p = sub.add_parser("backtest", help="directional-signal sanity check")
    bt_p.add_argument("--days", type=int, default=500)
    sim_p = sub.add_parser("simulate",
                           help="walk-forward historical simulation with synthetic "
                                "option pricing (real candles + VIX, BS premiums)")
    sim_p.add_argument("--weeks", type=int, default=6)
    sim_p.add_argument("--end-weeks-ago", type=int, default=0,
                       help="shift the test window back N weeks (for "
                            "non-overlapping validation windows)")
    sim_p.add_argument("--set", dest="overrides", action="append", default=[],
                       metavar="SECTION.KEY=VALUE",
                       help="override a setting for this run, e.g. "
                            "--set risk.max_risk_per_trade_pct=3.0 or "
                            "--set regime.enabled=false (repeatable; bare keys "
                            "default to the risk section)")
    sub.add_parser("analyze", help="setup-level P&L attribution from the journal")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    from .config import load_settings
    settings = load_settings(args.config)

    if args.command == "report":
        from .journal.journal import Journal
        from .journal.reports import daily_report
        journal = Journal(settings.db_path)
        print(daily_report(journal, settings, args.date))
        return 0

    if args.command == "analyze":
        from .journal.journal import Journal
        from .journal.reports import performance_breakdown
        print(performance_breakdown(Journal(settings.db_path)))
        return 0

    from .broker.dhan_client import DhanError
    from .orchestrator import Orchestrator
    try:
        orch = Orchestrator(settings)
    except DhanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "recommend":
        # force recommend semantics regardless of configured mode
        orch.settings.mode = "recommend"
        orch.scan_and_trade()
        return 0

    if args.command == "run":
        if args.once:
            orch.run_once()
        else:
            orch.run_forever(until=args.until)
        return 0

    if args.command == "status":
        trades = orch.journal.open_trades()
        capital = orch.risk.capital_now()
        print(f"mode={settings.mode} capital=₹{capital:,.0f} "
              f"(realized total ₹{orch.journal.total_realized_pnl():,.0f}, "
              f"today ₹{orch.journal.realized_pnl_today():,.0f})")
        if not trades:
            print("no open positions")
        for t in trades:
            print(f"  {t['plan_id']} {t['strategy']} {t['underlying']} {t['expiry']} "
                  f"entry_net ₹{t['entry_net']:,.0f} risk ₹{t['planned_risk']:,.0f}")
        return 0

    if args.command == "squareoff":
        results = orch.monitor.check_all(force_squareoff=True)
        for r in results:
            print(f"{r.plan_id} {r.strategy}: {r.action} ({r.reason}) pnl ₹{r.pnl:,.0f}")
        if not results:
            print("nothing to close")
        return 0

    if args.command == "simulate":
        from datetime import date as _date

        from .constants import INDIA_VIX
        from .simulator import Simulator, render_report
        sections = {"risk": settings.risk, "signals": settings.signals,
                    "regime": settings.regime, "events": settings.events,
                    "execution": settings.execution, "schedule": settings.schedule,
                    "llm": settings.llm}
        for item in args.overrides:
            key, _, val = item.partition("=")
            if not val:
                print(f"ignoring malformed override {item!r}")
                continue
            section, _, subkey = key.strip().partition(".")
            if not subkey:                       # bare key -> risk section
                section, subkey = "risk", section
            target = sections.get(section)
            if target is None:
                print(f"ignoring override for unknown section {section!r}")
                continue
            low = val.strip().lower()
            parsed = (low == "true") if low in ("true", "false") else None
            if parsed is None:
                try:
                    parsed = float(val)
                except ValueError:
                    parsed = val
            target[subkey] = parsed
            print(f"override: {section}.{subkey} = {parsed}")
        u = settings.underlyings[0]
        print(f"fetching history for {u.name} + India VIX...")
        daily = orch.client.daily_candles(u.security_id, u.segment, u.instrument,
                                          days=420)
        intraday = orch.client.intraday_candles(u.security_id, u.segment,
                                                u.instrument, interval=15,
                                                days=min(85, args.weeks * 7 + 30))
        vix_candles = orch.client.daily_candles(INDIA_VIX, u.segment, "INDEX",
                                                days=420)
        if args.end_weeks_ago:
            from datetime import timedelta
            cutoff = _date.today() - timedelta(weeks=args.end_weeks_ago)
            daily = [c for c in daily if c["time"] and c["time"].date() <= cutoff]
            intraday = [b for b in intraday if b["time"] and b["time"].date() <= cutoff]
            vix_candles = [c for c in vix_candles
                           if c["time"] and c["time"].date() <= cutoff]
            print(f"window shifted: testing data up to {cutoff.isoformat()}")
        # prior trading day's VIX close, keyed by session date; full series
        # kept for trailing IV-percentile classification
        vix_daily: dict[str, float] = {}
        vix_series: list[tuple[str, float]] = []
        prev_close = None
        for c in vix_candles:
            if c["time"] is None:
                continue
            day_iso = c["time"].date().isoformat()
            if prev_close is not None:
                vix_daily[day_iso] = prev_close
            prev_close = c["close"]
            vix_series.append((day_iso, c["close"]))
        if prev_close is not None:
            vix_daily[_date.today().isoformat()] = prev_close

        print(f"daily candles: {len(daily)} | 15-min bars: {len(intraday)} "
              f"| vix days: {len(vix_daily)}")
        sim = Simulator(settings, daily, intraday, vix_daily, weeks=args.weeks,
                        vix_series=vix_series)
        result = sim.run()
        report = render_report(result, args.weeks)
        if args.overrides or args.end_weeks_ago:
            lines = report.splitlines()
            lines.insert(1, f"\n_Run config: overrides={args.overrides or 'none'}, "
                            f"end_weeks_ago={args.end_weeks_ago}_")
            report = "\n".join(lines)
        from datetime import datetime as _dt
        stamp = _dt.now().strftime("%H%M%S")
        path = settings.reports_dir / f"simulation_{_date.today().isoformat()}_{stamp}.md"
        path.write_text(report)
        print(report)
        print(f"report written: {path}")
        from .notify.telegram import Notifier
        summary = "\n".join(report.splitlines()[:10])
        Notifier(settings).send(f"Historical simulation finished:\n{summary}")
        return 0

    if args.command == "backtest":
        from .backtest import backtest_daily_signal
        u = settings.underlyings[0]
        candles = orch.client.daily_candles(u.security_id, u.segment, u.instrument,
                                            days=args.days)
        if len(candles) < 120:
            print(f"not enough history ({len(candles)} candles)")
            return 1
        print(backtest_daily_signal(candles).summary())
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
