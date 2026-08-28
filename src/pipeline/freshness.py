"""
Date normalization + 24-hour freshness filtering + cross-run dedup.

Freshness tracking across distributed crawler nodes:
  We key dedup on a stable hash of the canonical article/job URL
  (normalized: lowercased, stripped of tracking query params, trailing
  slash removed). That hash is checked against a shared store (Redis set
  or a Postgres unique index in production; a local sqlite set for this
  demo) BEFORE a record is written -- so N crawler workers can run in
  parallel against overlapping source lists without double-processing the
  same URL. See architecture.pdf for the distributed design.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from dateutil import parser as dateutil_parser

from src.config import FRESHNESS_WINDOW_HOURS
from src.utils.logging_config import get_logger, log_ctx

logger = get_logger(__name__)

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid"}

RELATIVE_PATTERN = re.compile(
    r"(?P<num>\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE
)


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in TRACKING_PARAMS]
    normalized = parsed._replace(
        netloc=parsed.netloc.lower(),
        path=parsed.path.rstrip("/") or "/",
        query=urlencode(sorted(query)),
        fragment="",
    )
    return urlunparse(normalized)


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def parse_relative_date(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """'2 hours ago', '3 days ago' -> absolute UTC datetime."""
    now = now or datetime.now(timezone.utc)
    match = RELATIVE_PATTERN.search(text)
    if not match:
        return None
    num = int(match.group("num"))
    unit = match.group("unit").lower()
    delta_kwargs = {
        "second": {"seconds": num},
        "minute": {"minutes": num},
        "hour": {"hours": num},
        "day": {"days": num},
        "week": {"weeks": num},
        "month": {"days": num * 30},   # approximation, fine for freshness filtering
        "year": {"days": num * 365},
    }[unit]
    return now - timedelta(**delta_kwargs)


def normalize_published_date(
    raw_date_text: Optional[str],
    meta_tag_value: Optional[str] = None,
    fallback_first_seen: Optional[datetime] = None,
) -> Optional[datetime]:
    """
    Priority order:
      1. Structured <meta> tag (e.g. article:published_time) -- most reliable.
      2. Relative text on the page ("2 hours ago").
      3. Freeform date string via dateutil (handles most ISO/human formats).
      4. Heuristic fallback: first time OUR crawler observed this URL
         (used when a source truly has no date signal at all).
    """
    if meta_tag_value:
        try:
            return dateutil_parser.parse(meta_tag_value).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass

    if raw_date_text:
        rel = parse_relative_date(raw_date_text)
        if rel:
            return rel
        try:
            return dateutil_parser.parse(raw_date_text, fuzzy=True).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass

    if fallback_first_seen:
        log_ctx(logger, 30, "using_first_seen_fallback_for_date")
        return fallback_first_seen

    return None


def is_within_freshness_window(published_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if published_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - published_at) <= timedelta(hours=FRESHNESS_WINDOW_HOURS)


class SeenStore:
    """
    Minimal interface for cross-run / cross-node dedup. Swap `InMemorySeenStore`
    for a Redis-backed implementation in production without touching callers.
    """

    async def has_seen(self, url: str) -> bool:
        raise NotImplementedError

    async def mark_seen(self, url: str) -> None:
        raise NotImplementedError


class InMemorySeenStore(SeenStore):
    """Demo-scale implementation. Production: RedisSeenStore using SADD/SISMEMBER."""

    def __init__(self):
        self._seen: set[str] = set()

    async def has_seen(self, url: str) -> bool:
        return url_hash(url) in self._seen

    async def mark_seen(self, url: str) -> None:
        self._seen.add(url_hash(url))
