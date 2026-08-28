import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.freshness import (
    parse_relative_date,
    normalize_published_date,
    is_within_freshness_window,
    normalize_url,
    url_hash,
)


def test_relative_date_hours():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    result = parse_relative_date("2 hours ago", now=now)
    assert result == now - timedelta(hours=2)


def test_relative_date_days():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    result = parse_relative_date("3 days ago", now=now)
    assert result == now - timedelta(days=3)


def test_meta_tag_priority_over_relative_text():
    result = normalize_published_date(
        raw_date_text="2 hours ago",
        meta_tag_value="2026-08-10T10:00:00Z",
    )
    assert result.year == 2026 and result.hour == 10


def test_freshness_window():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(hours=5)
    stale = now - timedelta(hours=48)
    assert is_within_freshness_window(fresh, now=now) is True
    assert is_within_freshness_window(stale, now=now) is False
    assert is_within_freshness_window(None, now=now) is False


def test_url_normalization_strips_tracking_params():
    a = "https://example.com/article/123?utm_source=twitter&ref=homepage"
    b = "https://example.com/article/123"
    assert url_hash(a) == url_hash(b)


def test_url_normalization_trailing_slash():
    a = "https://example.com/article/123/"
    b = "https://example.com/article/123"
    assert url_hash(a) == url_hash(b)


if __name__ == "__main__":
    test_relative_date_hours()
    test_relative_date_days()
    test_meta_tag_priority_over_relative_text()
    test_freshness_window()
    test_url_normalization_strips_tracking_params()
    test_url_normalization_trailing_slash()
    print("All freshness tests passed.")
