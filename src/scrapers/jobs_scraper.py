"""
Jobs vertical scraper.

Collects actual job-detail URLs from job listing pages and ignores
navigation, authentication, company, category, and other non-job links.
"""

from typing import Any, AsyncIterator, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.config import SourceConfig
from src.scrapers.base_scraper import BaseScraper, RawDocument


class JobListingScraper(BaseScraper):
    def __init__(
        self,
        source: SourceConfig,
        link_selector: str = "a",
        max_pages: int = 3,
        session=None,
    ):
        super().__init__(source, session)
        self.link_selector = link_selector
        self.max_pages = max_pages

    async def list_page_urls(
        self,
        limit: Optional[int] = None,
    ) -> AsyncIterator[str]:

        max_pages = self.max_pages

        if limit is not None:
            max_pages = min(max_pages, max(1, limit))

        for page in range(1, max_pages + 1):
            if page == 1:
                yield self.source.base_url
            else:
                separator = "&" if "?" in self.source.base_url else "?"
                yield f"{self.source.base_url}{separator}page={page}"

    def _is_valid_job_url(self, href: str) -> bool:
        """
        Return True only for URLs that look like actual job-detail pages.
        """

        if not href:
            return False

        href = href.strip()

        if href.startswith("#"):
            return False

        if href.startswith(("javascript:", "mailto:", "tel:")):
            return False

        parsed = urlparse(href)

        if parsed.scheme and parsed.scheme not in ("http", "https"):
            return False

        path = parsed.path.lower().rstrip("/")

        # Ignore common non-job pages.
        blocked_paths = {
            "",
            "/",
            "/about",
            "/login",
            "/signin",
            "/sign-in",
            "/signup",
            "/sign-up",
            "/register",
            "/contact",
            "/privacy",
            "/terms",
            "/companies",
            "/hire-remotely",
            "/pricing",
            "/auth",
            "/workers",
        }

        if path in blocked_paths:
            return False

        # Ignore obvious non-job URL keywords.
        blocked_keywords = (
            "/about",
            "/login",
            "/signin",
            "/sign-in",
            "/signup",
            "/sign-up",
            "/register",
            "/contact",
            "/privacy",
            "/terms",
            "/companies",
            "/company/",
            "/categories/",
            "/category/",
            "/tags/",
            "/tag/",
            "/search",
            "/pricing",
            "/auth/",
            "/workers/",
        )

        if any(keyword in path for keyword in blocked_keywords):
            return False

        # Source-specific URL patterns.
        host = parsed.netloc.lower()

        # We Work Remotely:
        # Example job URLs generally contain /remote-jobs/
        if "weworkremotely.com" in host:
            return "/remote-jobs/" in path

        # RemoteOK:
        # Job links commonly contain /remote-jobs/
        if "remoteok.com" in host:
            return "/remote-jobs/" in path

        # AI-Jobs.net:
        # Job pages commonly use /jobs/
        if "ai-jobs.net" in host:
            return "/jobs/" in path

        # LinkedIn and Wellfound are usually JS-rendered and can have
        # many different URL structures. Accept only likely job paths.
        if "linkedin.com" in host:
            return "/jobs/view/" in path

        if "wellfound.com" in host:
            return "/jobs/" in path or "/l/" in path

        # Generic fallback:
        # Require a reasonably specific path rather than the homepage.
                # Do not accept unknown/generic URLs.
        # If a source does not have a known job-detail URL pattern,
        # reject it instead of collecting unrelated links.
        return False

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

                if not self._is_valid_job_url(href):
                    continue

                normalized = href.rstrip("/")
                if normalized in seen:
                    continue
                seen.add(normalized)

                title_tag = item.find("title")
                title = title_tag.get_text(" ", strip=True) if title_tag else ""
                if not title:
                    continue

                records.append(
                    {
                        "job_url": href,
                        "listing_snippet": title[:500],
                        "_source_url": raw.source_url,
                        "_source_name": raw.source_name,
                    }
                )

            if records:
                return records

        soup = BeautifulSoup(raw.content, features="html.parser")
        cards = soup.select(self.link_selector)

        for card in cards:
            href = card.get("href")
            if not href:
                continue

            href = href.strip()
            href = urljoin(raw.source_url, href)

            if not self._is_valid_job_url(href):
                continue

            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)

            title = card.get_text(" ", strip=True)
            if not title:
                continue

            records.append(
                {
                    "job_url": href,
                    "listing_snippet": title[:500],
                    "_source_url": raw.source_url,
                    "_source_name": raw.source_name,
                }
            )

        return records