"""Google News RSS search. Grounds a topic in recent coverage for the gate
and the draft prompt. Never raises into the pipeline: any failure (timeout,
bad status, unparseable feed, zero results) returns an empty list and logs
why, so a flaky RSS fetch can never take down drafting.
"""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

logger = logging.getLogger(__name__)

RSS_TIMEOUT_SECONDS = 8.0
_SOURCE_SUFFIX_RE = re.compile(r"\s+-\s+[^-]+$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class NewsItem:
    headline: str
    source: str
    published: datetime  # timezone-aware, UTC
    link: str


def search_news_rss(
    topic: str,
    *,
    lookback_days: int,
    max_items: int,
    hl: str,
    gl: str,
    ceid: str,
) -> list[NewsItem]:
    """Search Google News RSS for `topic`. `hl`/`gl`/`ceid` are region/language
    settings and must come from config, never hard-coded here."""
    if not topic.strip():
        return []

    encoded_topic = quote_plus(topic.strip())
    url = (
        "https://news.google.com/rss/search"
        f"?q={encoded_topic}+when:{lookback_days}d&hl={hl}&gl={gl}&ceid={ceid}"
    )

    try:
        response = httpx.get(url, timeout=RSS_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("News RSS fetch failed for %r: %s", topic, exc)
        return []

    # Pass raw bytes so feedparser only parses — it must never make its own
    # network call (it will, if handed something that looks like a URL).
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        logger.warning("News RSS parse failed for %r: %s", topic, feed.get("bozo_exception"))
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items: list[NewsItem] = []
    for entry in feed.entries:
        published = _parse_published(entry)
        if published is None or published < cutoff:
            continue
        source = _entry_source(entry)
        headline = _strip_source_suffix((entry.get("title") or "").strip(), source)
        if not headline:
            continue
        items.append(NewsItem(headline=headline, source=source, published=published, link=entry.get("link") or ""))

    items.sort(key=lambda item: item.published, reverse=True)
    return _dedupe(items)[:max_items]


def _entry_source(entry) -> str:
    source = entry.get("source")
    if source is None:
        return ""
    if hasattr(source, "get"):
        return source.get("title", "") or ""
    return str(source)


def _strip_source_suffix(title: str, source: str) -> str:
    # Google News appends " - <Source>" to every title.
    if source and title.endswith(f" - {source}"):
        return title[: -(len(source) + 3)].strip()
    return _SOURCE_SUFFIX_RE.sub("", title).strip()


def _parse_published(entry) -> datetime | None:
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for item in items:
        key = _NON_ALNUM_RE.sub("", item.headline.lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
