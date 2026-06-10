"""FII/DII cash-market activity from NSE.

NSE's public JSON endpoint needs a browser-like session (cookie warm-up).
Everything here is best-effort: on any failure we return None and the
market-view layer simply drops the FII/DII component for the day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

NSE_HOME = "https://www.nseindia.com"
FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports/fii-dii",
}


@dataclass
class FlowData:
    date: str
    fii_net: float   # INR crores; +ve = net buy
    dii_net: float

    @property
    def combined_bias(self) -> float:
        """Score in [-1, 1]. FII flows dominate short-term index direction
        (weight 0.7) with DII flows as a stabiliser (0.3); +/-3000 cr saturates."""
        score = 0.7 * _clamp(self.fii_net / 3000.0) + 0.3 * _clamp(self.dii_net / 3000.0)
        return _clamp(score)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def fetch_fii_dii(timeout: int = 15) -> FlowData | None:
    try:
        sess = requests.Session()
        sess.headers.update(HEADERS)
        sess.get(NSE_HOME, timeout=timeout)  # acquire cookies
        resp = sess.get(FII_DII_URL, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json()
        fii_net = dii_net = None
        as_of = ""
        for row in rows:
            cat = (row.get("category") or "").upper()
            net = float(str(row.get("netValue", "0")).replace(",", ""))
            as_of = row.get("date", as_of)
            if "FII" in cat or "FPI" in cat:
                fii_net = net
            elif "DII" in cat:
                dii_net = net
        if fii_net is None or dii_net is None:
            return None
        return FlowData(date=as_of, fii_net=fii_net, dii_net=dii_net)
    except Exception as exc:  # noqa: BLE001 - data source is optional
        log.warning("FII/DII fetch failed (continuing without it): %s", exc)
        return None
