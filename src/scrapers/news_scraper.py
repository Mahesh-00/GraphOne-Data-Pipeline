"""
News vertical: crawls listing pages for article links, then fetches each
article and extracts full text + published date.

Full-text extraction uses `trafilatura`, a purpose-built library for this
(handles boilerplate removal far better than naive BeautifulSoup text
extraction). Falls back to a BeautifulSoup heuristic if trafilatura returns
nothing.
"""
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import trafilatura
from bs4 import BeautifulSoup

from src.config import SourceConfig
from src.scrapers.base_scraper import BaseScraper, RawDocument
from src.pipeline.freshness import normalize_published_date, is_within_freshness_window
from src.utils.logging_config import get_logger, log_ctx

logger = get_logger(__name__)

META_DATE_KEYS = [
    "article:published_time",
    "og:published_time",
    "publish-date",
    "date",
    "DC.date.issued",
]


def _extract_meta_date(soup: BeautifulSoup) -> Optional[str]:
    for key in META_DATE_KEYS:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"]
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"]
    return None


import re
from urllib.parse import urljoin, urlparse

_DATE_PATH_RE = re.compile(r"/\d{4}/\d{1,2}(?:/\d{1,2})?/")


class NewsListingScraper(BaseScraper):
    """
    Fetches a source's listing/category page and yields article URLs found
    on it. A second pass (`ArticleFetcher`, below) fetches full text per
    article -- kept separate so listing crawl and article crawl can be
    scaled/concurrency-tuned independently.
    """

    def __init__(self, source: SourceConfig, link_selector: str = "a", max_pages: int = 3, session=None):
        super().__init__(source, session)
        self.link_selector = link_selector
        self.max_pages = max_pages

    async def list_page_urls(self, limit: Optional[int] = None) -> AsyncIterator[str]:
        for page in range(1, self.max_pages + 1):
            yield f"{self.source.base_url}?page={page}" if page > 1 else self.source.base_url

    def _is_valid_article_url(self, href: str) -> bool:
        """
        Filter article links to reject category, tag, author, event, podcast,
        and newsletter index pages.
        """
        if not href:
            return False

        href = href.strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return False

        parsed = urlparse(href)
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            return False

        path = parsed.path.lower().rstrip("/")
        if not path or path in ("", "/"):
            return False

        blocked_keywords = (
            "/category/",
            "/categories/",
            "/tag/",
            "/tags/",
            "/author/",
            "/authors/",
            "/podcasts/",
            "/podcast/",
            "/newsletters/",
            "/newsletter/",
            "/events/",
            "/event/",
            "/about",
            "/contact",
            "/privacy",
            "/terms",
            "/advertise",
            "/sponsor",
            "/search",
            "/video/",
            "/videos/",
            "/latest/",
            "/topic/",
        )

        if any(keyword in path for keyword in blocked_keywords):
            return False

        host = parsed.netloc.lower()

        # TechCrunch: articles must match a date-like path /YYYY/MM/DD/slug/ or /YYYY/MM/slug/
        if "techcrunch.com" in host:
            return bool(_DATE_PATH_RE.search(path))

        # VentureBeat: /YYYY/MM/DD/slug/ or slug with sufficient path depth
        if "venturebeat.com" in host:
            if _DATE_PATH_RE.search(path):
                return True
            parts = [p for p in path.split("/") if p]
            return len(parts) >= 2 and parts[-1] not in ("ai", "enterprise", "security", "games")

        # The Verge: /YYYY/MM/DD/slug/ or multi-part slug
        if "theverge.com" in host:
            return bool(re.search(r"/\d{4}/", path)) or len([p for p in path.split("/") if p]) >= 2

        # Ars Technica: /YYYY/MM/slug/
        if "arstechnica.com" in host:
            return bool(re.search(r"/\d{4}/\d{1,2}/", path))

        # MIT Tech Review:
        if "technologyreview.com" in host:
            return bool(_DATE_PATH_RE.search(path)) or len([p for p in path.split("/") if p]) >= 2

        # Generic news fallback: requires date path or at least 2 segments
        if _DATE_PATH_RE.search(path):
            return True

        parts = [p for p in path.split("/") if p]
        return len(parts) >= 2

    def parse(self, raw: RawDocument) -> list[dict[str, Any]]:
        is_xml = (
            getattr(raw, "content_type", "") == "xml"
            or (raw.content and raw.content.lstrip().startswith("<?xml"))
            or (raw.content and "<rss" in raw.content[:200].lower())
            or (raw.content and "<feed" in raw.content[:200].lower())
        )

        records: list[dict[str, Any]] = []
        seen: set[str] = set()

        if is_xml:
            soup = BeautifulSoup(raw.content, features="xml")
            items = soup.find_all(["item", "entry"])
            for item in items:
                link_tag = item.find("link")
                href = ""
                if link_tag:
                    href = link_tag.get_text(strip=True) or link_tag.get("href", "")
                if not href:
                    guid_tag = item.find("guid")
                    if guid_tag and guid_tag.get_text(strip=True).startswith("http"):
                        href = guid_tag.get_text(strip=True)
                if not href:
                    continue

                href = href.strip()
                href = urljoin(raw.source_url, href)

                if not self._is_valid_article_url(href):
                    continue

                normalized = href.rstrip("/")
                if normalized in seen:
                    continue
                seen.add(normalized)

                records.append({"article_url": href, "_source_url": raw.source_url, "_source_name": raw.source_name})

            if records:
                return records

        soup = BeautifulSoup(raw.content, features="html.parser")
        links = soup.select(self.link_selector)

        for a in links:
            href = a.get("href")
            if not href:
                continue

            href = href.strip()
            href = urljoin(raw.source_url, href)

            if not self._is_valid_article_url(href):
                continue

            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)

            records.append({"article_url": href, "_source_url": raw.source_url, "_source_name": raw.source_name})

        return records


class ArticleFetcher(BaseScraper):
    """Fetches a single article and extracts full text + normalized date."""

    async def list_page_urls(self, limit: Optional[int] = None) -> AsyncIterator[str]:
        return
        yield  # pragma: no cover -- URLs are supplied externally via fetch_article()

    def parse(self, raw: RawDocument) -> list[dict[str, Any]]:
        return []  # unused; see fetch_article

    async def fetch_article(self, url: str, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
        raw = await self.fetch(url)
        soup = BeautifulSoup(raw.content, "html.parser")

        full_text = trafilatura.extract(raw.content, include_comments=False, favor_recall=True)
        if not full_text:
            paragraphs = soup.find_all("p")
            full_text = "\n".join(p.get_text(strip=True) for p in paragraphs)

        title_tag = soup.find("title")
        meta_date = _extract_meta_date(soup)
        published_at = normalize_published_date(raw_date_text=None, meta_tag_value=meta_date)

        if not is_within_freshness_window(published_at, now=now):
            log_ctx(logger, 20, "article_outside_freshness_window", url=url, published_at=str(published_at))
            return None

        return {
            "title": title_tag.get_text(strip=True) if title_tag else None,
            "full_text": full_text,
            "published_date": published_at.isoformat() if published_at else None,
            "source_url": url,
            "source_name": self.source.name,
        }
