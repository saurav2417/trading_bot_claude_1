"""Thin REST client for the DhanHQ v2 API.

Covers exactly what the bot needs: quotes, candles, option chain, expiry
list, instrument master lookup, funds, positions and order placement.
Docs: https://dhanhq.co/docs/v2/
"""

from __future__ import annotations

import csv
import io
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from ..constants import IDX_I, NSE_FNO, SCRIP_MASTER_URL

log = logging.getLogger(__name__)

BASE_URL = "https://api.dhan.co/v2"
OPTION_CHAIN_MIN_INTERVAL = 3.1  # Dhan rate-limits option chain to 1 req / 3s


class DhanError(RuntimeError):
    pass


class DhanClient:
    def __init__(self, client_id: str, access_token: str, cache_dir: Path | None = None):
        if not client_id or not access_token:
            raise DhanError(
                "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set. "
                "Copy .env.example to .env and fill in your DhanHQ credentials."
            )
        self.client_id = client_id
        self.session = requests.Session()
        self.session.headers.update(
            {
                "access-token": access_token,
                "client-id": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self.cache_dir = cache_dir or Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_chain_call = 0.0
        self._scrip_index: dict[tuple, dict] | None = None

    # ----------------------------------------------------------- helpers
    def _request(self, method: str, path: str, payload: dict | None = None,
                 retries: int = 3) -> Any:
        url = f"{BASE_URL}{path}"
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                resp = self.session.request(method, url, json=payload, timeout=20)
                if resp.status_code == 429:
                    raise DhanError("rate limited")
                resp.raise_for_status()
                body = resp.json() if resp.text else {}
                if isinstance(body, dict) and body.get("status") == "failed":
                    raise DhanError(f"Dhan API error on {path}: {body}")
                return body
            except (requests.RequestException, DhanError) as exc:
                if attempt == retries:
                    raise DhanError(f"{method} {path} failed: {exc}") from exc
                log.warning("Dhan %s %s failed (%s); retrying in %.0fs", method, path, exc, delay)
                time.sleep(delay)
                delay *= 2

    # ------------------------------------------------------- market data
    def ltp(self, instruments: dict[str, list[int]]) -> dict:
        """instruments: {"IDX_I": [13, 21], "NSE_FNO": [...]} -> nested LTP map."""
        body = self._request("POST", "/marketfeed/ltp", instruments)
        return body.get("data", {})

    def quote(self, instruments: dict[str, list[int]]) -> dict:
        body = self._request("POST", "/marketfeed/quote", instruments)
        return body.get("data", {})

    def index_ltp(self, security_id: int) -> float | None:
        data = self.ltp({IDX_I: [security_id]})
        node = data.get(IDX_I, {}).get(str(security_id), {})
        return node.get("last_price")

    def option_ltp(self, security_ids: list[int]) -> dict[int, float]:
        if not security_ids:
            return {}
        data = self.ltp({NSE_FNO: [int(s) for s in security_ids]})
        out = {}
        for sid, node in data.get(NSE_FNO, {}).items():
            if node.get("last_price") is not None:
                out[int(sid)] = float(node["last_price"])
        return out

    def daily_candles(self, security_id: int, segment: str, instrument: str,
                      days: int = 200) -> list[dict]:
        to_d, from_d = date.today(), date.today() - timedelta(days=days)
        body = self._request("POST", "/charts/historical", {
            "securityId": str(security_id),
            "exchangeSegment": segment,
            "instrument": instrument,
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_d.isoformat(),
            "toDate": to_d.isoformat(),
        })
        return _columns_to_candles(body)

    def intraday_candles(self, security_id: int, segment: str, instrument: str,
                         interval: int = 15, days: int = 5) -> list[dict]:
        to_d, from_d = date.today() + timedelta(days=1), date.today() - timedelta(days=days)
        body = self._request("POST", "/charts/intraday", {
            "securityId": str(security_id),
            "exchangeSegment": segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": False,
            "fromDate": from_d.isoformat(),
            "toDate": to_d.isoformat(),
        })
        return _columns_to_candles(body)

    def expiry_list(self, underlying_scrip: int, segment: str = IDX_I) -> list[str]:
        body = self._request("POST", "/optionchain/expirylist", {
            "UnderlyingScrip": underlying_scrip,
            "UnderlyingSeg": segment,
        })
        return sorted(body.get("data", []))

    def option_chain(self, underlying_scrip: int, expiry: str,
                     segment: str = IDX_I) -> dict:
        """Returns {"last_price": float, "oc": {"<strike>": {"ce": {...}, "pe": {...}}}}."""
        wait = OPTION_CHAIN_MIN_INTERVAL - (time.monotonic() - self._last_chain_call)
        if wait > 0:
            time.sleep(wait)
        body = self._request("POST", "/optionchain", {
            "UnderlyingScrip": underlying_scrip,
            "UnderlyingSeg": segment,
            "Expiry": expiry,
        })
        self._last_chain_call = time.monotonic()
        return body.get("data", {})

    # --------------------------------------------------- instrument master
    def _load_scrip_master(self) -> dict[tuple, dict]:
        """Download (and cache for the day) Dhan's scrip master, indexed for
        NSE index-option lookup by (underlying, expiry, strike, type)."""
        if self._scrip_index is not None:
            return self._scrip_index
        cache_file = self.cache_dir / f"scrip_master_{date.today().isoformat()}.csv"
        if cache_file.exists():
            text = cache_file.read_text()
        else:
            log.info("Downloading Dhan scrip master (cached daily)...")
            resp = requests.get(SCRIP_MASTER_URL, timeout=120)
            resp.raise_for_status()
            text = resp.text
            cache_file.write_text(text)

        index: dict[tuple, dict] = {}
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                if row.get("SEM_EXM_EXCH_ID") != "NSE":
                    continue
                if row.get("SEM_INSTRUMENT_NAME") not in ("OPTIDX",):
                    continue
                symbol = (row.get("SM_SYMBOL_NAME") or "").strip().upper()
                expiry = (row.get("SEM_EXPIRY_DATE") or "")[:10]
                strike = float(row.get("SEM_STRIKE_PRICE") or 0)
                opt_type = (row.get("SEM_OPTION_TYPE") or "").strip().upper()
                if not symbol or not expiry or not opt_type:
                    continue
                index[(symbol, expiry, strike, opt_type)] = {
                    "security_id": int(row["SEM_SMST_SECURITY_ID"]),
                    "lot_size": int(float(row.get("SEM_LOT_UNITS") or 0)) or None,
                    "trading_symbol": row.get("SEM_CUSTOM_SYMBOL")
                    or row.get("SEM_TRADING_SYMBOL"),
                }
            except (KeyError, ValueError, TypeError):
                continue
        if not index:
            raise DhanError("scrip master parsed but no NSE index options found "
                            "(format may have changed)")
        self._scrip_index = index
        return index

    def resolve_option(self, underlying: str, expiry: str, strike: float,
                       option_type: str) -> dict:
        """-> {"security_id": int, "lot_size": int|None, "trading_symbol": str}"""
        idx = self._load_scrip_master()
        key = (underlying.upper(), expiry, float(strike), option_type.upper())
        if key not in idx:
            raise DhanError(f"option contract not found in scrip master: {key}")
        return idx[key]

    # ------------------------------------------------------ account/orders
    def fund_limit(self) -> dict:
        return self._request("GET", "/fundlimit") or {}

    def positions(self) -> list[dict]:
        body = self._request("GET", "/positions")
        return body if isinstance(body, list) else body.get("data", [])

    def place_order(self, *, security_id: int, transaction_type: str, quantity: int,
                    order_type: str = "LIMIT", price: float = 0.0,
                    product_type: str = "INTRADAY", exchange_segment: str = NSE_FNO,
                    tag: str = "") -> dict:
        payload = {
            "dhanClientId": self.client_id,
            "correlationId": tag[:25] if tag else None,
            "transactionType": transaction_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "validity": "DAY",
            "securityId": str(security_id),
            "quantity": quantity,
            "disclosedQuantity": 0,
            "price": round(price, 2) if order_type == "LIMIT" else 0,
            "afterMarketOrder": False,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return self._request("POST", "/orders", payload)

    def order_status(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}") or {}

    def cancel_order(self, order_id: str) -> dict:
        return self._request("DELETE", f"/orders/{order_id}") or {}


def _columns_to_candles(body: dict) -> list[dict]:
    """Dhan chart APIs return parallel arrays; convert to a list of dicts."""
    if not body or "close" not in body:
        return []
    keys = ["open", "high", "low", "close", "volume", "timestamp"]
    cols = {k: body.get(k) or [] for k in keys}
    n = len(cols["close"])
    out = []
    for i in range(n):
        out.append({
            "open": float(cols["open"][i]),
            "high": float(cols["high"][i]),
            "low": float(cols["low"][i]),
            "close": float(cols["close"][i]),
            "volume": float(cols["volume"][i]) if i < len(cols["volume"]) else 0.0,
            "time": datetime.fromtimestamp(cols["timestamp"][i])
            if i < len(cols["timestamp"]) else None,
        })
    return out
