"""Lightweight market-news sentiment from public RSS feeds.

Keyword scoring over headlines — intentionally simple and low-weight in the
composite signal. Fails soft: returns neutral (0.0) when feeds are down.
"""

from __future__ import annotations

import logging
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

FEEDS = [
    "https://news.google.com/rss/search?q=nifty+OR+sensex+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
]

POSITIVE = {
    "surge", "rally", "rallies", "gains", "gain", "jumps", "jump", "record high",
    "all-time high", "bullish", "soars", "soar", "upbeat", "buying", "recovery",
    "rebound", "advances", "outperform", "strong", "boost", "rate cut", "optimism",
}
NEGATIVE = {
    "fall", "falls", "drop", "drops", "plunge", "plunges", "crash", "slump",
    "bearish", "selloff", "sell-off", "sell off", "losses", "weak", "decline",
    "declines", "tumbles", "tumble", "fears", "concerns", "tension", "war",
    "sanctions", "downgrade", "rate hike", "inflation worries", "recession",
}


@dataclass
class NewsSentiment:
    score: float                 # [-1, 1]
    headlines: list[str] = field(default_factory=list)


def _fetch_titles(url: str, timeout: int = 10) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        tree = ET.parse(resp)
    return [
        (item.findtext("title") or "").strip()
        for item in tree.iter("item")
    ][:25]


def fetch_news_sentiment() -> NewsSentiment:
    titles: list[str] = []
    for url in FEEDS:
        try:
            titles.extend(_fetch_titles(url))
        except Exception as exc:  # noqa: BLE001 - optional source
            log.warning("news feed failed (%s): %s", url.split("/")[2], exc)
    if not titles:
        return NewsSentiment(score=0.0)

    pos = neg = 0
    for title in titles:
        low = title.lower()
        pos += sum(1 for w in POSITIVE if w in low)
        neg += sum(1 for w in NEGATIVE if w in low)
    total = pos + neg
    score = 0.0 if total == 0 else (pos - neg) / total
    return NewsSentiment(score=max(-1.0, min(1.0, score)), headlines=titles[:10])
