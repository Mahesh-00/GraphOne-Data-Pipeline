import json
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.config import SourceConfig
from src.scrapers.base_scraper import BaseScraper, RawDocument
from src.scrapers.playwright_fetcher import PlaywrightFetcher
from src.utils.logging_config import get_logger, log_ctx

logger = get_logger(__name__)

STATE_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".scraper_state.json"


def load_scraper_state() -> dict[str, int]:
    if STATE_FILE_PATH.exists():
        try:
            with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_scraper_state(state: dict[str, int]) -> None:
    try:
        with open(STATE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def get_last_page(source_name: str, default: int = 1) -> int:
    state = load_scraper_state()
    return max(1, state.get(source_name, default))


def set_last_page(source_name: str, page: int) -> None:
    state = load_scraper_state()
    state[source_name] = max(1, page)
    save_scraper_state(state)


import asyncio

class DirectoryScraper(BaseScraper):
    def __init__(self, source: SourceConfig, list_selector: str,
                 name_selector: str, link_selector: str,
                 max_pages: int = 50, session=None):
        super().__init__(source, session)
        self.list_selector = list_selector
        self.name_selector = name_selector
        self.link_selector = link_selector
        self.max_pages = max_pages
        self._browser_fetcher: Optional[PlaywrightFetcher] = None
        self._browser_lock: Optional[asyncio.Lock] = None

    async def _get_browser_fetcher(self) -> PlaywrightFetcher:
        if self._browser_lock is None:
            self._browser_lock = asyncio.Lock()
        async with self._browser_lock:
            if self._browser_fetcher is None:
                fetcher = PlaywrightFetcher()
                await fetcher.__aenter__()
                self._browser_fetcher = fetcher
            return self._browser_fetcher

    async def list_page_urls(self, limit: Optional[int] = None) -> AsyncIterator[str]:
        pages_needed = max(1, min(self.max_pages, (limit // 10) + 2 if limit is not None else 5))
        if self.source.name == "YCombinator":
            yc_categories = [
                "",
                "?industry=B2B",
                "?industry=Fintech",
                "?industry=Healthcare",
                "?industry=Consumer",
                "?industry=Education",
                "?industry=Proptech",
                "?industry=Govtech",
                "?industry=Industrials",
                "?industry=Security",
            ]
            start_page = get_last_page(self.source.name, default=1)
            for i in range(start_page - 1, start_page - 1 + pages_needed):
                cat = yc_categories[i % len(yc_categories)]
                yield f"{self.source.base_url}{cat}"
            return

        start_page = get_last_page(self.source.name, default=1)
        for page in range(start_page, start_page + pages_needed):
            if page == 1:
                yield self.source.base_url
            else:
                separator = "&" if "?" in self.source.base_url else "?"
                yield f"{self.source.base_url}{separator}{self.source.pagination_param}={page}"

    async def fetch(self, url: str) -> RawDocument:
        if not self.source.requires_js:
            return await super().fetch(url)

        fetcher = await self._get_browser_fetcher()
        html = await fetcher.fetch_rendered_html(
            url, wait_selector=self.list_selector or None
        )
        return RawDocument(
            source_name=self.source.name,
            source_url=url,
            fetched_at=__import__("time").time(),
            content=html,
            content_type="html",
            meta={"status": 200, "fetch_mode": "playwright"},
        )

    def parse(self, raw: RawDocument) -> list[dict[str, Any]]:
        if raw.content_type != "html":
            return []

        html_lower = raw.content.lower()
        challenge_markers = (
            "just a moment...",
            "just a moment",
            "attention required",
            "access denied",
            "verify you are human",
            "checking your browser",
            "cf-challenge",
            "challenge-running",
            "challenge-form",
            "cf-turnstile",
        )
        if any(marker in html_lower for marker in challenge_markers):
            log_ctx(logger, 40, "bot_challenge_detected", url=raw.source_url, source=self.source.name)
            return []

        soup = BeautifulSoup(raw.content, "html.parser")

        source_name = self.source.name
        ignored_names = {
            "techstars portfolio",
            "yc startup directory",
            "yc program",
            "startup school",
            "work at a startup",
            "co-founder matching",
            "startup directory",
            "startup library",
            "demo day",
            "investors",
            "founders",
            "alumni",
            "partners",
            "mentors",
            "founder catalyst",
            "startup weekend",
            "apply",
            "apply today",
            "view unicorn registry",
            "portfolio",
            "locations",
            "location",
            "about",
            "about us",
            "blog",
            "newsroom",
            "careers",
            "resources",
            "search",
            "login",
            "sign up",
            "log in",
            "click here to join for free!",
            "click here to join for free",
            "tools",
            "mini tools",
            "home",
            "newsletter",
            "contact us",
            "create tool",
            "featured",
            "new",
            "trending",
            "lists",
            "leaders",
            "leaderboard",
            "jobs",
            "map",
            "tasks",
            "prompts",
            "deals",
            "launch / advertise",
            "merchandise",
            "development",
        }

        selectors = [
            self.list_selector,
            "a[href^='/companies/']",
            "a[href*='/companies/']",
            "a[href*='/company/']",
            "a[href*='/startup/']",
            "a[href*='/portfolio/']",
            "article",
            "li",
            "div[data-testid*='company']",
            "div[data-company]",
            "[data-company-name]",
            "[itemtype*='Organization']",
        ]

        cards: list[Any] = []
        for selector in selectors:
            if not selector:
                continue
            try:
                discovered = soup.select(selector)
            except Exception:
                discovered = []
            if discovered:
                cards = discovered
                break

        if not cards:
            if source_name in ("YCombinator", "ThereIsAnAIForThat", "TechstarsPortfolio"):
                log_ctx(logger, 30, "no_cards_found_check_selectors",
                        url=raw.source_url, selector=self.list_selector)
                return []
            cards = []
            for node in soup.find_all(["div", "li", "article", "section", "p", "h2", "h3", "span"]):
                text = node.get_text(" ", strip=True)
                if not text or len(text) > 80:
                    continue
                if len(text.split()) <= 3 and not any(
                    token in text.lower() for token in ("portfolio", "about", "blog", "careers", "locations", "resources", "search", "login", "sign up", "click here to join for free!")
                ):
                    cards.append(node)
            if not cards:
                log_ctx(logger, 30, "no_cards_found_check_selectors",
                        url=raw.source_url, selector=self.list_selector)
                return []

        records: list[dict[str, Any]] = []
        seen_links: set[str] = set()
        seen_names: set[str] = set()
        seen_hrefs: set[str] = set()

        for card in cards:
            card_href = ""
            if getattr(card, "name", None) == "a":
                card_href = (card.get("href") or "").lower()

            if source_name == "ThereIsAnAIForThat":
                has_ai_link = (
                    "/ai/" in card_href
                    or "/tools/" in card_href
                    or bool(card.select_one("a[href*='/ai/']"))
                    or bool(card.select_one("a[href*='/tools/']"))
                )
                if not has_ai_link:
                    continue
            link_el = card if getattr(card, "name", None) == "a" else (
                card.select_one(self.link_selector)
                or card.select_one("a[href^='/companies/']")
                or card.select_one("a[href*='/company/']")
                or card.select_one("a[href*='/startup/']")
                or card.select_one("a[href*='/ai/']")
                or card.find("a")
            )

            if source_name == "YCombinator":
                name_el = (
                    card.select_one("span[class*='_coName'], [class*='coName'], span[class*='coName'], h2, h3, strong")
                    or card.select_one(self.name_selector)
                    or link_el
                    or card
                )
            else:
                name_el = (
                    card.select_one(self.name_selector)
                    or card.find(["h2", "h3"])
                    or card.find(["div", "li", "p", "span"])
                    or link_el
                    or card
                )
            if not name_el:
                continue

            name = name_el.get_text(" ", strip=True)
            if not name or len(name) > 200:
                continue

            normalized_name = name.casefold()
            if normalized_name in ignored_names or any(
                token in normalized_name for token in ("click here to join for free", "login", "sign up", "about", "blog", "careers", "resources", "search", "portfolio", "tools")
            ):
                continue

            if source_name == "ThereIsAnAIForThat":
                words = name.split()
                if len(words) > 6 and any(token in normalized_name for token in (" and ", " for ", " with ", " the ", " first ", " free ", " is ", " are ", " can ", ".")):
                    continue

            href = link_el.get("href") if link_el is not None else None
            if isinstance(href, str):
                href = urljoin(raw.source_url, href)
            else:
                href = None

            if source_name == "ThereIsAnAIForThat":
                if not href:
                    continue

                href_lower = href.lower()

                if "/ai/" not in href_lower and "/tools/" not in href_lower:
                    continue
                if href.lower() in {
                    "https://theresanaiforthat.com/",
                    "https://theresanaiforthat.com",
                    "https://theresanaiforthat.com/tools/",
                    "https://theresanaiforthat.com/?page=1",
                    "https://theresanaiforthat.com/?page=1#",
                }:
                    continue

            if href:
                normalized = href.lower()
                if "/companies/" not in normalized and "/company/" not in normalized and "/startup/" not in normalized and "/portfolio/" not in normalized and "/ai/" not in normalized:
                    href = None

            key = (href or "") + "|" + normalized_name
            href_key = (href or "").lower()
            if href_key and href_key in seen_hrefs:
                continue
            if key in seen_links or normalized_name in seen_names:
                continue
            seen_links.add(key)
            seen_names.add(normalized_name)
            if href_key:
                seen_hrefs.add(href_key)

            records.append({
                "raw_name": name,
                "detail_url": href or raw.source_url,
                "_source_url": raw.source_url,
                "_snippet_html": str(card)[:6000],
            })

        if not records:
            log_ctx(logger, 30, "no_directory_records_found",
                    url=raw.source_url, selector=self.list_selector)
        return records

    async def run(
        self,
        limit: Optional[int] = None,
    ) -> AsyncIterator[tuple[RawDocument, list[dict[str, Any]]]]:
        """
        Run directory scraper. For browser/JS directories, fetch pages in controlled
        sequence to avoid Chromium context overload and timeouts.
        """
        urls = [u async for u in self.list_page_urls(limit=limit)]
        log_ctx(
            logger,
            20,
            "scrape_starting",
            source=self.source.name,
            url_count=len(urls),
        )

        for url in urls:
            try:
                raw = await self.fetch(url)
                records = self.parse(raw)
                if records:
                    yield raw, records
            except Exception as exc:
                log_ctx(
                    logger,
                    40,
                    "fetch_or_parse_failed",
                    url=url,
                    error=str(exc),
                )

    async def close(self) -> None:
        if self._browser_fetcher is not None:
            await self._browser_fetcher.__aexit__(None, None, None)
            self._browser_fetcher = None
        await super().close()
