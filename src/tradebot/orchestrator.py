"""The autonomous daily trading loop.

Timeline (IST, all configurable):
  08:50  pre-market: FII/DII + news + overnight view, report logged
  09:15  market open (no entries yet — let the open settle)
  09:30  entry window opens: scan every signal_interval_minutes
  14:30  last fresh entry
  15:12  intraday square-off of all open positions
  15:40  EOD report written + notified
The monitor runs every monitor_interval_seconds whenever positions are open.

Run `python -m tradebot.cli run` under systemd/cron and the system operates
end-to-end with no human input. The same loop powers `recommend` mode, where
plans are logged and notified but never executed.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .analysis.market_view import MarketViewBuilder
from .broker.dhan_client import DhanClient
from .config import Settings
from .execution.executor import Executor
from .execution.position_monitor import PositionMonitor
from .journal.journal import Journal
from .journal.reports import write_daily_report
from .notify.telegram import Notifier
from .risk.risk_manager import RiskManager, planned_risk
from .strategy.selector import select_strategy

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = DhanClient(settings.dhan_client_id, settings.dhan_access_token,
                                 settings.cache_dir)
        self.journal = Journal(settings.db_path)
        self.risk = RiskManager(settings, self.journal)
        self.executor = Executor(settings, self.client, self.journal)
        self.monitor = PositionMonitor(settings, self.executor, self.journal)
        self.notifier = Notifier(settings)
        self.view_builder = MarketViewBuilder(settings, self.client)
        self._premarket_done: str = ""
        self._eod_done: str = ""
        self._last_scan: datetime | None = None
        self._event_skip_notified: str = ""

    # ----------------------------------------------------------- schedule
    def _t(self, key: str, default: str) -> str:
        return str(self.settings.schedule.get(key, default))

    def now(self) -> datetime:
        return datetime.now(IST)

    def _hm(self, now: datetime) -> str:
        return now.strftime("%H:%M")

    def is_trading_day(self, now: datetime) -> bool:
        # NSE holidays are not hardcoded; on a holiday no fresh candles/quotes
        # arrive and entry scans simply find nothing actionable.
        return now.weekday() < 5

    # --------------------------------------------------------------- main
    def run_forever(self, until: str | None = None) -> None:
        """Run the loop, optionally stopping at IST time `until` (HH:MM).

        A deadline makes the loop suitable for capped cloud runners
        (e.g. GitHub Actions): state lives in the journal DB, so the next
        scheduled run picks up open positions seamlessly.
        """
        self._deadline = _todays_time(self.now(), until) if until else None
        log.info("orchestrator starting in %s mode (capital ₹%.0f)%s",
                 self.settings.mode, self.settings.capital,
                 f", until {until} IST" if until else "")
        self.notifier.send(f"tradebot started: mode={self.settings.mode}")
        while self._deadline is None or self.now() < self._deadline:
            try:
                self.tick()
            except KeyboardInterrupt:
                log.info("interrupted; exiting")
                return
            except Exception as exc:  # noqa: BLE001 — never die mid-session
                log.exception("tick failed: %s", exc)
                self.journal.log_event("ERROR", f"tick failed: {exc}")
                time.sleep(30)
        log.info("session deadline %s reached; exiting cleanly "
                 "(open positions persist in the journal)", until)

    def run_once(self) -> None:
        """Single pass: useful for cron-driven setups and smoke tests."""
        self.tick()

    # ------------------------------------------------------------- phases
    def tick(self) -> None:
        now = self.now()
        hm = self._hm(now)
        today = now.date().isoformat()

        if not self.is_trading_day(now):
            self._sleep_until_next_session(now)
            return

        if hm >= self._t("premarket_time", "08:50") and self._premarket_done != today:
            self._premarket(today)

        open_h = self._t("market_open", "09:15")
        close_h = self._t("market_close", "15:30")
        squareoff_h = self._t("intraday_squareoff_time", "15:12")
        eod_h = self._t("eod_report_time", "15:40")

        if hm < open_h:
            time.sleep(min(60, _seconds_until(now, open_h)))
            return

        if open_h <= hm < close_h:
            # square-off window
            if hm >= squareoff_h and self._is_intraday():
                if self.journal.open_trade_count():
                    log.info("square-off window: closing all open positions")
                    self.monitor.check_all(force_squareoff=True)
            else:
                self._monitor_positions()
                self._maybe_scan_for_entries(now)
            time.sleep(int(self.settings.schedule.get("monitor_interval_seconds", 45)))
            return

        if hm >= eod_h and self._eod_done != today:
            self._eod(today)
        self._sleep_until_next_session(now)

    def _premarket(self, today: str) -> None:
        log.info("pre-market analysis for %s", today)
        flows = self.view_builder.flows()
        news = self.view_builder.news()
        msg = [f"pre-market {today}:"]
        if flows:
            msg.append(f"FII {flows.fii_net:+.0f}cr / DII {flows.dii_net:+.0f}cr "
                       f"({flows.date})")
        msg.append(f"news sentiment {news.score:+.2f}")
        text = " | ".join(msg)
        self.journal.log_event("PREMARKET", text)
        self.notifier.send(text)
        self._premarket_done = today

    def _maybe_scan_for_entries(self, now: datetime) -> None:
        hm = self._hm(now)
        if hm < self._t("no_trade_before", "09:30") or hm > self._t("last_entry_time", "14:30"):
            return
        interval = timedelta(minutes=int(
            self.settings.schedule.get("signal_interval_minutes", 15)))
        if self._last_scan and now - self._last_scan < interval:
            return
        self._last_scan = now
        if self.risk.daily_loss_breached():
            log.warning("daily loss kill switch active — skipping entry scan")
            return
        self.scan_and_trade(now)

    def scan_and_trade(self, now: datetime | None = None) -> None:
        now = now or self.now()
        skip_dates = self.settings.events.get("skip_dates") or []
        if now.date().isoformat() in skip_dates:
            if self._event_skip_notified != now.date().isoformat():
                msg = (f"event day {now.date().isoformat()}: no fresh entries "
                       "(events.skip_dates)")
                log.info(msg)
                self.journal.log_event("EVENT_SKIP", msg)
                self.notifier.send(msg)
                self._event_skip_notified = now.date().isoformat()
            return
        for underlying in self.settings.underlyings:
            try:
                view = self.view_builder.build(underlying)
            except Exception as exc:  # noqa: BLE001
                log.warning("view build failed for %s: %s", underlying.name, exc)
                continue
            self.journal.record_signal(underlying.name, {
                "score": view.direction_score, "direction": view.direction,
                "vol": view.vol_regime, "confidence": view.confidence,
                "components": view.components,
                "llm": view.llm.model_dump() if view.llm else None,
            })
            log.info(view.summary())
            for note in view.notes:
                log.info("  %s", note)

            scan_msg = (f"scan {underlying.name}: {view.direction} "
                        f"{view.direction_score:+.0f} | vol {view.vol_regime} "
                        f"| conf {view.confidence:.2f}")
            if view.llm:
                scan_msg += f"\nLLM: {view.llm.summary}"

            # expiry-day guard: no fresh debit entries late on expiry day
            if (view.expiry == now.date().isoformat()
                    and self._hm(now) >= str(self.settings.execution.get(
                        "avoid_expiry_day_longs_after", "13:30"))):
                log.info("expiry-day late window: skipping fresh entries")
                self.notifier.send(scan_msg + "\nno trade: expiry-day late window")
                continue

            plan = self.risk.size_lots(
                lambda lots: _build(view, underlying, self.settings, lots))
            if plan is None:
                sel = select_strategy(view, underlying, self.settings, lots=1)
                reason = sel.reason if not sel.actionable else \
                    self.risk.evaluate(sel.plan).reason
                log.info("no trade for %s: %s", underlying.name, reason)
                self.notifier.send(scan_msg + f"\nno trade: {reason}")
                continue

            risk_amount = planned_risk(plan, self.settings)
            text = (f"RECOMMENDATION\n{plan.describe()}\n"
                    f"planned risk: ₹{risk_amount:,.0f}")
            if view.llm:
                text += f"\nLLM: {view.llm.summary}"
            self.notifier.send(text)
            self.journal.log_event("RECOMMENDATION", plan.describe())
            print(text)

            if self.settings.places_orders:
                ok = self.executor.open_trade(plan, risk_amount)
                if ok:
                    self.notifier.send(f"EXECUTED [{self.settings.mode}] "
                                       f"{plan.plan_id} {plan.strategy}")

    def _monitor_positions(self) -> None:
        if not self.journal.open_trade_count():
            return
        for status in self.monitor.check_all():
            if status.action == "EXIT":
                self.notifier.send(f"EXIT {status.plan_id} {status.strategy}: "
                                   f"{status.reason} (pnl ₹{status.pnl:,.0f})")

    def _eod(self, today: str) -> None:
        path = write_daily_report(self.journal, self.settings, today)
        log.info("EOD report written: %s", path)
        pnl = self.journal.realized_pnl_today()
        self.notifier.send(f"EOD {today}: day P&L ₹{pnl:,.0f} | report: {path.name}")
        self._eod_done = today

    # ------------------------------------------------------------ helpers
    def _is_intraday(self) -> bool:
        return str(self.settings.execution.get("product_type", "INTRADAY")) == "INTRADAY"

    def _sleep_until_next_session(self, now: datetime) -> None:
        nxt = now.replace(hour=8, minute=45, second=0, microsecond=0)
        while nxt <= now or nxt.weekday() >= 5:
            nxt += timedelta(days=1)
            nxt = nxt.replace(hour=8, minute=45)
        wait = min((nxt - now).total_seconds(), 3600)
        deadline = getattr(self, "_deadline", None)
        if deadline is not None:
            remaining = (deadline - now).total_seconds()
            if remaining <= 0:
                return
            wait = min(wait, remaining)
        log.info("market closed; sleeping %.0f min (next session %s)", wait / 60, nxt)
        time.sleep(max(30, wait))


def _build(view, underlying, settings, lots: int):
    sel = select_strategy(view, underlying, settings, lots)
    if not sel.actionable:
        raise ValueError(sel.reason)
    return sel.plan


def _todays_time(now: datetime, hm: str) -> datetime:
    h, m = map(int, hm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def _seconds_until(now: datetime, hm: str) -> float:
    h, m = map(int, hm.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return max(1.0, (target - now).total_seconds())
