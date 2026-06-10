"""SQLite trade journal: single source of truth for positions and P&L."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from ..strategy.base import OptionLeg, TradePlan

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    plan_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiry TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',          -- OPEN | CLOSED | FAILED
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    entry_net REAL NOT NULL,                      -- +credit / -debit at entry
    planned_risk REAL NOT NULL,
    max_loss REAL,
    peak_pnl REAL NOT NULL DEFAULT 0,
    realized_pnl REAL,
    exit_reason TEXT,
    view_summary TEXT,
    rationale TEXT
);
CREATE TABLE IF NOT EXISTS legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES trades(plan_id),
    security_id INTEGER,
    trading_symbol TEXT,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    lot_size INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    underlying TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


class Journal:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------- writes
    def record_open(self, plan: TradePlan, mode: str, planned_risk: float,
                    fills: dict[int, float] | None = None) -> None:
        """fills: leg-index -> actual fill price (defaults to plan prices)."""
        fills = fills or {}
        entry_net = 0.0
        for i, leg in enumerate(plan.legs):
            px = fills.get(i, leg.price)
            entry_net += (px if leg.action == "SELL" else -px) * leg.quantity
        with self.conn:
            self.conn.execute(
                "INSERT INTO trades (plan_id, strategy, underlying, expiry, mode,"
                " opened_at, entry_net, planned_risk, max_loss, view_summary, rationale)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (plan.plan_id, plan.strategy, plan.underlying, plan.expiry, mode,
                 _now(), entry_net, planned_risk,
                 None if plan.max_loss == float("inf") else plan.max_loss,
                 plan.view_summary, plan.rationale),
            )
            for i, leg in enumerate(plan.legs):
                self.conn.execute(
                    "INSERT INTO legs (plan_id, security_id, trading_symbol, strike,"
                    " option_type, action, quantity, lot_size, entry_price)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (plan.plan_id, leg.security_id, leg.trading_symbol, leg.strike,
                     leg.option_type, leg.action, leg.quantity, leg.lot_size,
                     fills.get(i, leg.price)),
                )

    def record_close(self, plan_id: str, exit_prices: dict[int, float],
                     pnl: float, reason: str) -> None:
        with self.conn:
            for leg_id, px in exit_prices.items():
                self.conn.execute("UPDATE legs SET exit_price=? WHERE id=?", (px, leg_id))
            self.conn.execute(
                "UPDATE trades SET status='CLOSED', closed_at=?, realized_pnl=?,"
                " exit_reason=? WHERE plan_id=?",
                (_now(), pnl, reason, plan_id),
            )

    def update_peak(self, plan_id: str, peak_pnl: float) -> None:
        with self.conn:
            self.conn.execute("UPDATE trades SET peak_pnl=? WHERE plan_id=?",
                              (peak_pnl, plan_id))

    def mark_failed(self, plan_id: str, reason: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE trades SET status='FAILED', closed_at=?, exit_reason=?"
                " WHERE plan_id=?", (_now(), reason, plan_id))

    def record_signal(self, underlying: str, payload: dict) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO signals (at, underlying, payload) VALUES (?,?,?)",
                              (_now(), underlying, json.dumps(payload, default=str)))

    def log_event(self, kind: str, message: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO events (at, kind, message) VALUES (?,?,?)",
                              (_now(), kind, message))

    # -------------------------------------------------------------- reads
    def open_trades(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall()
        out = []
        for row in rows:
            trade = dict(row)
            trade["legs"] = [dict(l) for l in self.conn.execute(
                "SELECT * FROM legs WHERE plan_id=? ORDER BY id", (row["plan_id"],))]
            out.append(trade)
        return out

    def open_trade_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]

    def trades_opened_today(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM trades WHERE opened_at >= ?",
            (date.today().isoformat(),)).fetchone()[0]

    def realized_pnl_today(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades"
            " WHERE status='CLOSED' AND closed_at >= ?",
            (date.today().isoformat(),)).fetchone()
        return float(row[0])

    def total_realized_pnl(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades"
            " WHERE status='CLOSED'").fetchone()
        return float(row[0])

    def trades_for_day(self, day: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE opened_at LIKE ? OR closed_at LIKE ?"
            " ORDER BY opened_at", (f"{day}%", f"{day}%")).fetchall()
        return [dict(r) for r in rows]

    def all_closed_trades(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM trades WHERE status='CLOSED' ORDER BY closed_at")]

    def close(self) -> None:
        self.conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
