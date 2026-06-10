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
        u = settings.underlyings[0]
        print(f"fetching history for {u.name} + India VIX...")
        daily = orch.client.daily_candles(u.security_id, u.segment, u.instrument,
                                          days=420)
        intraday = orch.client.intraday_candles(u.security_id, u.segment,
                                                u.instrument, interval=15,
                                                days=min(85, args.weeks * 7 + 30))
        vix_candles = orch.client.daily_candles(INDIA_VIX, u.segment, "INDEX",
                                                days=120)
        # prior trading day's VIX close, keyed by session date
        vix_daily: dict[str, float] = {}
        prev_close = None
        for c in vix_candles:
            if c["time"] is None:
                continue
            day_iso = c["time"].date().isoformat()
            if prev_close is not None:
                vix_daily[day_iso] = prev_close
            prev_close = c["close"]
        if prev_close is not None:
            vix_daily[_date.today().isoformat()] = prev_close

        print(f"daily candles: {len(daily)} | 15-min bars: {len(intraday)} "
              f"| vix days: {len(vix_daily)}")
        sim = Simulator(settings, daily, intraday, vix_daily, weeks=args.weeks)
        result = sim.run()
        report = render_report(result, args.weeks)
        path = settings.reports_dir / f"simulation_{_date.today().isoformat()}.md"
        path.write_text(report)
        print(report)
        print(f"report written: {path}")
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
