
"""
Base class for all scrapers.

Concrete scrapers (papers, startups, products, news, jobs) implement
`list_page_urls` and `parse`.

Retry, concurrency, rate limiting, and HTTP session handling are centralized
here.

Every fetched document is persisted to the raw store BEFORE any LLM touches
it. This preserves provenance for every structured record.
"""

import abc
import asyncio
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, AsyncIterator, Optional

import aiohttp
import certifi

from src.config import (
    MAX_CONCURRENT_REQUESTS,
    MAX_RETRIES,
    BASE_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    SourceConfig,
)

from src.utils.async_pool import (
    ConcurrencyPool,
    RateLimiter,
    RetryableError,
    with_retry,
)

from src.utils.logging_config import get_logger, log_ctx


logger = get_logger(__name__)


@dataclass
class RawDocument:
    source_name: str
    source_url: str
    fetched_at: float
    content: str
    content_type: str
    meta: dict[str, Any]


class BaseScraper(abc.ABC):
    """
    Base scraper class.

    Subclasses implement:
        list_page_urls() -> async generator of URLs
        parse(raw) -> list of extracted records
    """

    def __init__(
        self,
        source: SourceConfig,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.source = source
        self._session = session
        self._owns_session = session is None
        self._pool = ConcurrencyPool(MAX_CONCURRENT_REQUESTS)
        self._rate_limiter = RateLimiter(source.rate_limit_rps)

    @staticmethod
    def _parse_retry_after(
        retry_after_value: str | None,
    ) -> float | None:
        if not retry_after_value:
            return None

        retry_after_value = retry_after_value.strip()

        try:
            return float(retry_after_value)
        except ValueError:
            pass

        try:
            retry_dt = parsedate_to_datetime(retry_after_value)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            delay = (retry_dt - datetime.now(timezone.utc)).total_seconds()
            return max(delay, 0.0)
        except Exception:
            return None

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Create and return the shared aiohttp session.

        certifi provides a trusted CA certificate bundle. This is useful
        on Windows environments where Python may not automatically locate
        the required CA certificates.
        """

        if self._session is None:
            timeout = aiohttp.ClientTimeout(
                total=REQUEST_TIMEOUT_SECONDS
            )

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; GraphOneBot/1.0; "
                    "+https://frontieratlas.example/bot)"
                )
            }

            # Use certifi's trusted CA certificate bundle.
            ssl_context = ssl.create_default_context(
                cafile=certifi.where()
            )

            # Configure aiohttp to use the SSL context.
            connector = aiohttp.TCPConnector(
                ssl=ssl_context
            )

            # Create the shared aiohttp session.
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
                connector=connector,
            )
            self._owns_session = True

        return self._session

    async def fetch(self, url: str) -> RawDocument:
        """
        Fetch a single URL with:
        - rate limiting
        - retries
        - exponential backoff
        - 429 handling
        - 5xx handling
        """

        async def _do_fetch() -> RawDocument:
            await self._rate_limiter.wait()

            session = await self._get_session()

            async with session.get(url) as resp:

                # HTTP 429: Too Many Requests
                if resp.status == 429:
                    retry_after = self._parse_retry_after(
                        resp.headers.get("Retry-After")
                    )

                    log_ctx(
                        logger,
                        30,
                        "arxiv_rate_limited",
                        url=url,
                        retry_after=retry_after,
                        status=resp.status,
                    )

                    raise RetryableError(
                        f"429 from {url}",
                        retry_after=retry_after,
                    )

                # HTTP 5xx: server-side errors
                if resp.status >= 500:
                    log_ctx(
                        logger,
                        30,
                        "arxiv_server_error",
                        url=url,
                        status=resp.status,
                    )

                    raise RetryableError(
                        f"{resp.status} from {url}"
                    )

                # Other HTTP 4xx errors
                if resp.status >= 400:
                    log_ctx(
                        logger,
                        30,
                        "non_retryable_http_error",
                        url=url,
                        status=resp.status,
                    )

                    raise RuntimeError(
                        f"HTTP {resp.status} for {url}"
                    )

                text = await resp.text()

                ct_header = resp.headers.get("Content-Type", "").lower()
                if "json" in ct_header:
                    content_type = "json"
                elif "xml" in ct_header or "rss" in ct_header or "atom" in ct_header:
                    content_type = "xml"
                elif text.lstrip().startswith("<?xml") or "<rss" in text[:200].lower() or "<feed" in text[:200].lower():
                    content_type = "xml"
                else:
                    content_type = "html"

                return RawDocument(
                    source_name=self.source.name,
                    source_url=url,
                    fetched_at=asyncio.get_event_loop().time(),
                    content=text,
                    content_type=content_type,
                    meta={
                        "status": resp.status,
                    },
                )

        def _on_retry(
            attempt: int,
            exc: Exception,
        ) -> None:
            event_name = (
                "arxiv_retry"
                if self.source.name == "Arxiv"
                else "retrying_fetch"
            )

            log_ctx(
                logger,
                30,
                event_name,
                url=url,
                attempt=attempt,
                error=str(exc),
                retry_after=getattr(exc, "retry_after", None),
            )

        async with self._pool:
            return await with_retry(
                _do_fetch,
                max_retries=MAX_RETRIES,
                base_backoff=BASE_BACKOFF_SECONDS,
                max_backoff=MAX_BACKOFF_SECONDS,
                on_retry=_on_retry,
            )

    @abc.abstractmethod
    async def list_page_urls(
        self,
        limit: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Yield URLs to fetch.

        Subclasses handle pagination/cursors.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def parse(
        self,
        raw: RawDocument,
    ) -> list[dict[str, Any]]:
        """
        Parse a raw document into loosely structured records.
        """
        raise NotImplementedError

    async def run(
        self,
        limit: Optional[int] = None,
    ) -> AsyncIterator[
        tuple[RawDocument, list[dict[str, Any]]]
    ]:
        """
        Run the scraper.

        URLs are fetched concurrently, parsed, and yielded as:

            (raw_document, parsed_records)
        """

        urls = [
            u
            async for u in self.list_page_urls(
                limit=limit
            )
        ]

        log_ctx(
            logger,
            20,
            "scrape_starting",
            source=self.source.name,
            url_count=len(urls),
        )

        async def _fetch_and_parse(url: str):
            try:
                raw = await self.fetch(url)
                records = self.parse(raw)

                return raw, records

            except Exception as exc:
                log_ctx(
                    logger,
                    40,
                    "fetch_or_parse_failed",
                    url=url,
                    error=str(exc),
                )

                return None

        tasks = [
            asyncio.create_task(
                _fetch_and_parse(url)
            )
            for url in urls
        ]

        for task in asyncio.as_completed(tasks):
            result = await task

            if result is not None:
                yield result

    async def close(self) -> None:
        """
        Close the aiohttp session if this scraper owns it.
        """

        if self._session is not None and self._owns_session:
            await self._session.close()

