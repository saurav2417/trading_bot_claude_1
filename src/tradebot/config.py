"""Configuration loading: settings.yaml + .env secrets, with env overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = PROJECT_ROOT / "config" / "settings.yaml"

VALID_MODES = ("recommend", "paper", "live")


@dataclass
class Underlying:
    name: str
    security_id: int
    segment: str = "IDX_I"
    instrument: str = "INDEX"
    lot_size: int = 75
    strike_step: int = 50


@dataclass
class Settings:
    raw: dict[str, Any]
    mode: str
    capital: float
    max_capital_per_trade: float
    underlyings: list[Underlying]
    risk: dict[str, Any]
    schedule: dict[str, Any]
    signals: dict[str, Any]
    execution: dict[str, Any]
    notifications: dict[str, Any]
    db_path: Path
    cache_dir: Path
    reports_dir: Path
    dhan_client_id: str = ""
    dhan_access_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def places_orders(self) -> bool:
        return self.mode in ("paper", "live")


def load_settings(path: str | Path | None = None) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    cfg_path = Path(path) if path else DEFAULT_SETTINGS
    with open(cfg_path) as fh:
        raw = yaml.safe_load(fh)

    mode = os.environ.get("TRADEBOT_MODE", raw.get("mode", "paper")).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")

    underlyings = [Underlying(**u) for u in raw.get("underlyings", [])]
    if not underlyings:
        raise ValueError("at least one underlying must be configured")

    paths = raw.get("paths", {})
    db_path = PROJECT_ROOT / paths.get("db", "data/tradebot.db")
    cache_dir = PROJECT_ROOT / paths.get("cache_dir", "data/cache")
    reports_dir = PROJECT_ROOT / paths.get("reports_dir", "reports")
    for d in (db_path.parent, cache_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    signals = raw.get("signals", {})
    return Settings(
        raw=raw,
        mode=mode,
        capital=float(raw["capital"]["initial"]),
        max_capital_per_trade=float(raw["capital"].get("max_capital_per_trade", 40000)),
        underlyings=underlyings,
        risk=raw.get("risk", {}),
        schedule=raw.get("schedule", {}),
        signals=signals,
        execution=raw.get("execution", {}),
        notifications=raw.get("notifications", {}),
        db_path=db_path,
        cache_dir=cache_dir,
        reports_dir=reports_dir,
        dhan_client_id=os.environ.get("DHAN_CLIENT_ID", ""),
        dhan_access_token=os.environ.get("DHAN_ACCESS_TOKEN", ""),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        weights=signals.get("weights", {}),
    )
