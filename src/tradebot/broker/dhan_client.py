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

# Index-option underlyings we keep from the scrip master (keeps the index lean
# and lets us derive the underlying from the trading symbol robustly)
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                     "NIFTYNXT50", "SENSEX", "BANKEX", "SENSEX50"}


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
                if resp.status_code >= 400:
                    raise DhanError(f"HTTP {resp.status_code}: {resp.text[:300]}")
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
        # Dhan 400s when toDate has no market data yet (e.g. today before the
        # session); walk the end date back until the request succeeds.
        return self._candles_with_date_fallback("/charts/historical", {
            "securityId": str(security_id),
            "exchangeSegment": segment,
            "instrument": instrument,
            "expiryCode": 0,
            "oi": False,
        }, base_to=date.today(), days=days)

    def intraday_candles(self, security_id: int, segment: str, instrument: str,
                         interval: int = 15, days: int = 5) -> list[dict]:
        return self._candles_with_date_fallback("/charts/intraday", {
            "securityId": str(security_id),
            "exchangeSegment": segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": False,
        }, base_to=date.today() + timedelta(days=1), days=days)

    def _candles_with_date_fallback(self, path: str, payload: dict,
                                    base_to: date, days: int) -> list[dict]:
        last_exc: Exception | None = None
        for shift in range(4):
            to_d = base_to - timedelta(days=shift)
            from_d = to_d - timedelta(days=days)
            body_payload = {**payload, "fromDate": from_d.isoformat(),
                            "toDate": to_d.isoformat()}
            try:
                body = self._request("POST", path, body_payload,
                                     retries=0 if shift < 3 else 2)
                candles = _columns_to_candles(body)
                if candles:
                    return candles
                last_exc = DhanError(f"{path} returned no candles up to {to_d}")
            except DhanError as exc:
                if "400" not in str(exc):
                    raise
                log.warning("%s rejected toDate=%s; retrying with earlier end date",
                            path, to_d)
                last_exc = exc
        raise DhanError(f"{path} failed for all end dates: {last_exc}")

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
        cache_file = self.cache_dir / f"scrip_master_v2_{date.today().isoformat()}.csv"
        if cache_file.exists():
            text = cache_file.read_text()
        else:
            log.info("Downloading Dhan scrip master (cached daily)...")
            resp = requests.get(SCRIP_MASTER_URL, timeout=120)
            resp.raise_for_status()
            text = resp.text
            cache_file.write_text(text)

        import re

        index: dict[tuple, dict] = {}
        reader = csv.DictReader(io.StringIO(text))

        def pick(row: dict, *names: str) -> str:
            for n in names:
                v = row.get(n)
                if v not in (None, ""):
                    return str(v)
            return ""

        def derive_symbol(row: dict) -> str:
            """Underlying for an index-option row, robust to which symbol
            columns Dhan populates: prefer an explicit symbol field, else take
            the leading alpha run of the trading/custom symbol."""
            explicit = pick(row, "SM_SYMBOL_NAME", "UNDERLYING_SYMBOL",
                            "SYMBOL_NAME").strip().upper()
            if explicit in INDEX_UNDERLYINGS:
                return explicit
            for col in ("SEM_CUSTOM_SYMBOL", "SEM_TRADING_SYMBOL",
                        "DISPLAY_NAME", "SYMBOL_NAME", "SM_SYMBOL_NAME"):
                v = pick(row, col).strip().upper()
                if not v:
                    continue
                compact = v.replace(" ", "")
                for idx in sorted(INDEX_UNDERLYINGS, key=len, reverse=True):
                    if compact.startswith(idx):       # longest name first
                        return idx
                m = re.match(r"[A-Z]+", v)
                if m and m.group(0) in INDEX_UNDERLYINGS:
                    return m.group(0)
            return ""

        for row in reader:
            try:
                # identify option rows by what's always reliable — an option
                # type and a positive strike — rather than exact instrument or
                # exchange label values, which vary across Dhan's master files
                opt_type = pick(row, "SEM_OPTION_TYPE", "OPTION_TYPE").strip().upper()
                if opt_type not in ("CE", "PE"):
                    continue
                strike = float(pick(row, "SEM_STRIKE_PRICE", "STRIKE_PRICE") or 0)
                if strike <= 0:
                    continue
                symbol = derive_symbol(row)
                if symbol not in INDEX_UNDERLYINGS:   # keep only index options
                    continue
                expiry = pick(row, "SEM_EXPIRY_DATE", "SM_EXPIRY_DATE",
                              "EXPIRY_DATE")[:10]
                sec_id = pick(row, "SEM_SMST_SECURITY_ID", "SECURITY_ID")
                if not expiry or not sec_id:
                    continue
                lot = pick(row, "SEM_LOT_UNITS", "LOT_SIZE")
                index[(symbol, expiry, strike, opt_type)] = {
                    "security_id": int(sec_id),
                    "lot_size": int(float(lot)) if lot else None,
                    "trading_symbol": pick(row, "SEM_CUSTOM_SYMBOL",
                                           "SEM_TRADING_SYMBOL", "DISPLAY_NAME",
                                           "SYMBOL_NAME"),
                }
            except (KeyError, ValueError, TypeError):
                continue
        if not index:
            headers = list(reader.fieldnames or [])[:14]
            raise DhanError("scrip master parsed but no index options found; "
                            f"columns seen: {headers}")
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

    def resolve_lot_size(self, underlying: str) -> int | None:
        """Authoritative current lot size for an index's options, read from the
        Dhan scrip master (uniform across strikes/expiries for an index).
        Returns None if the underlying isn't found so callers can fall back."""
        idx = self._load_scrip_master()
        u = underlying.upper()
        sizes = {info["lot_size"] for (sym, *_), info in idx.items()
                 if sym == u and info.get("lot_size")}
        if not sizes:
            return None
        # if Dhan ever lists a transitional mix, the largest is the safe choice
        return max(sizes)

    # ------------------------------------------------------ account/orders
    def fund_limit(self) -> dict:
        return self._request("GET", "/fundlimit") or {}

    def order_margin(self, *, security_id: int, transaction_type: str,
                     quantity: int, price: float, product_type: str = "INTRADAY",
                     exchange_segment: str = NSE_FNO) -> dict:
        """Real margin for a single order from Dhan's calculator.
        -> {totalMargin, spanMargin, exposureMargin, availableBalance, ...}.
        For a bought option this is ~premium*qty; for a sold option it is the
        full SPAN+exposure (≈₹1+ lakh per NIFTY lot) before any hedge benefit."""
        return self._request("POST", "/margincalculator", {
            "dhanClientId": self.client_id,
            "exchangeSegment": exchange_segment,
            "transactionType": transaction_type,
            "quantity": int(quantity),
            "productType": product_type,
            "securityId": str(security_id),
            "price": round(price, 2),
        }) or {}

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
    """Dhan chart APIs return parallel arrays; convert to a list of dicts.
    Timestamps become IST-aware datetimes (exchange time, runner-independent)."""
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
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
            "time": datetime.fromtimestamp(cols["timestamp"][i], tz=ist)
            if i < len(cols["timestamp"]) else None,
        })
    return out
