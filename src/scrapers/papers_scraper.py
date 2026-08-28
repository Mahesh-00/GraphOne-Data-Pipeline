"""
Research papers vertical.

Fetches research papers from the official arXiv API and enriches papers
with GitHub repository information.

Features:
- Official arXiv API
- Conservative rate limiting
- Pagination for large targets
- arXiv ID based deduplication
- GitHub URL extraction
- GitHub star enrichment
- GitHub rate-limit handling
"""

import re
import xml.etree.ElementTree as ET
from typing import Any, AsyncIterator, Optional

import aiohttp

from src.config import (
    SourceConfig,
    GITHUB_API_BASE,
    GITHUB_API_TOKEN,
)

from src.scrapers.base_scraper import (
    BaseScraper,
    RawDocument,
)

from src.utils.async_pool import (
    RetryableError,
    with_retry,
)

from src.utils.logging_config import (
    get_logger,
    log_ctx,
)


logger = get_logger(__name__)


# ===========================================================================
# CONSTANTS
# ===========================================================================

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom"
}


GITHUB_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/"
    r"[\w.-]+/[\w.-]+",
    re.IGNORECASE,
)


ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arXiv:)([0-9]{4}\.[0-9]{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


# ===========================================================================
# ARXIV SCRAPER
# ===========================================================================

class ArxivScraper(BaseScraper):
    """
    Fetches AI research papers from arXiv.

    arXiv IDs are used as the unique paper identifier.
    """

    CATEGORIES = [
        "cs.AI",
        "cs.LG",
        "cs.CL",
        "cs.CV",
    ]

    PAGE_SIZE = 50

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        source = SourceConfig(
            name="Arxiv",
            base_url="https://export.arxiv.org/api/query",
            kind="paper_index",
            requires_js=False,
            rate_limit_rps=0.25,
        )

        super().__init__(
            source,
            session,
        )

    async def run(
        self,
        limit: Optional[int] = None,
    ) -> AsyncIterator[tuple[RawDocument, list[dict[str, Any]]]]:
        """
        Run the arXiv scraper sequentially, honoring rate limits and
        stopping once enough unique arXiv IDs are collected.
        """
        target = max(1, int(limit or 1000))
        seen_arxiv_ids: set[str] = set()
        max_candidate_pages = max(target * 50, 200)

        async for url in self.list_page_urls(limit=max_candidate_pages):
            log_ctx(
                logger,
                20,
                "arxiv_request",
                url=url,
            )

            try:
                raw = await self.fetch(url)
            except Exception as exc:
                log_ctx(
                    logger,
                    40,
                    "arxiv_page_failed",
                    url=url,
                    error=str(exc),
                )
                continue

            records = self.parse(raw)

            filtered_records: list[dict[str, Any]] = []
            unique_added = 0

            for record in records:
                arxiv_id = record.get("arxiv_id")

                if not arxiv_id:
                    continue

                if arxiv_id in seen_arxiv_ids:
                    log_ctx(
                        logger,
                        20,
                        "arxiv_duplicate_skipped",
                        arxiv_id=arxiv_id,
                        source_url=raw.source_url,
                    )
                    continue

                seen_arxiv_ids.add(arxiv_id)
                filtered_records.append(record)
                unique_added += 1

            log_ctx(
                logger,
                20,
                "arxiv_page_completed",
                url=raw.source_url,
                unique_added=unique_added,
                page_total=len(records),
                total_unique=len(seen_arxiv_ids),
            )

            yield raw, filtered_records

            if len(seen_arxiv_ids) >= target:
                break

        log_ctx(
            logger,
            20,
            "arxiv_collection_complete",
            target=target,
            unique_found=len(seen_arxiv_ids),
        )

    # =======================================================================
    # GENERATE ARXIV API URLS
    # =======================================================================

    async def list_page_urls(
        self,
        limit: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Generate arXiv API URLs sequentially.
        """

        target = limit or 1000

        # If many papers already exist in the DB we may need to
        # scan a larger window of arXiv search results to find
        # enough unique new papers. Generate a larger candidate
        # target to improve pagination coverage without changing
        # the scraper architecture.
        candidate_target = max(
            target * 20,
            100,
        )

        generated = 0

        for category in self.CATEGORIES:

            start = 0

            while generated < candidate_target:

                batch = min(
                    self.PAGE_SIZE,
                    candidate_target - generated,
                )

                url = (
                    f"{self.source.base_url}"
                    f"?search_query=cat:{category}"
                    f"&sortBy=submittedDate"
                    f"&sortOrder=descending"
                    f"&start={start}"
                    f"&max_results={batch}"
                )

                yield url

                generated += batch
                start += batch

                if generated >= candidate_target:
                    break

            if generated >= candidate_target:
                break

    # =======================================================================
    # EXTRACT ARXIV ID
    # =======================================================================

    @staticmethod
    def extract_arxiv_id(
        url: Optional[str],
    ) -> Optional[str]:
        """
        Extract canonical arXiv ID.

        Example:
            https://arxiv.org/abs/2608.09928v1

        Returns:
            2608.09928
        """

        if not url:
            return None

        match = ARXIV_ID_RE.search(url)

        if not match:
            return None

        return match.group(1)

    # =======================================================================
    # NORMALIZE GITHUB URL
    # =======================================================================

    @staticmethod
    def normalize_github_url(
        url: Optional[str],
    ) -> Optional[str]:
        """
        Normalize a GitHub repository URL.

        Handles URLs appearing inside:
        - plain text
        - Markdown
        - parentheses
        - trailing punctuation
        """

        if not url:
            return None

        match = GITHUB_URL_RE.search(
            url.strip()
        )

        if not match:
            return None

        normalized = match.group(0)

        normalized = normalized.rstrip(
            ".,;:)]}>\"'"
        )

        return normalized.rstrip("/")

    # =======================================================================
    # PARSE ARXIV XML
    # =======================================================================

    def parse(
        self,
        raw: RawDocument,
    ) -> list[dict[str, Any]]:
        """
        Parse an arXiv Atom XML response into paper records.
        """

        records: list[dict[str, Any]] = []

        try:
            root = ET.fromstring(
                raw.content
            )

        except ET.ParseError as exc:

            log_ctx(
                logger,
                40,
                "arxiv_xml_parse_failed",
                url=raw.source_url,
                error=str(exc),
            )

            return records

        for entry in root.findall(
            "atom:entry",
            ARXIV_NS,
        ):

            title_el = entry.find(
                "atom:title",
                ARXIV_NS,
            )

            summary_el = entry.find(
                "atom:summary",
                ARXIV_NS,
            )

            id_el = entry.find(
                "atom:id",
                ARXIV_NS,
            )

            published_el = entry.find(
                "atom:published",
                ARXIV_NS,
            )

            updated_el = entry.find(
                "atom:updated",
                ARXIV_NS,
            )

            # ----------------------------------------------------------------
            # Authors
            # ----------------------------------------------------------------

            authors: list[str] = []

            for author in entry.findall(
                "atom:author",
                ARXIV_NS,
            ):

                name_el = author.find(
                    "atom:name",
                    ARXIV_NS,
                )

                if (
                    name_el is not None
                    and name_el.text
                ):
                    authors.append(
                        name_el.text.strip()
                    )

            # ----------------------------------------------------------------
            # Validate required fields
            # ----------------------------------------------------------------

            if (
                title_el is None
                or id_el is None
            ):
                continue

            paper_url = (
                id_el.text.strip()
                if id_el.text
                else raw.source_url
            )

            arxiv_id = self.extract_arxiv_id(
                paper_url
            )

            if not arxiv_id:

                log_ctx(
                    logger,
                    30,
                    "arxiv_id_missing",
                    url=paper_url,
                )

                continue

            # ----------------------------------------------------------------
            # Abstract
            # ----------------------------------------------------------------

            abstract_text = ""

            if (
                summary_el is not None
                and summary_el.text
            ):
                abstract_text = (
                    summary_el.text.strip()
                )

            # ----------------------------------------------------------------
            # GitHub repository
            # ----------------------------------------------------------------

            github_url = None

            # Search abstract and title for GitHub URLs
            search_text = abstract_text or ""

            title_text = (
                title_el.text.strip()
                if title_el is not None and title_el.text
                else ""
            )

            search_text = f"{title_text}\n{search_text}"

            github_match = GITHUB_URL_RE.search(search_text)

            # Also inspect any link hrefs in the entry (some arXiv
            # comments/metadata appear as links).
            if not github_match:

                for link in entry.findall(
                    "atom:link",
                    ARXIV_NS,
                ):

                    href = link.attrib.get("href")

                    if href:
                        m = GITHUB_URL_RE.search(href)

                        if m:
                            github_match = m
                            break

            if github_match:

                github_url = self.normalize_github_url(
                    github_match.group(0)
                )

            # ----------------------------------------------------------------
            # Create record
            # ----------------------------------------------------------------

            record: dict[str, Any] = {

                "paper_id": arxiv_id,

                "arxiv_id": arxiv_id,

                "title": (
                    title_el.text.strip()
                    .replace("\n", " ")
                    if title_el.text
                    else None
                ),

                "authors": authors,

                "paper_url": paper_url,

                "abstract": abstract_text,

                "published_date": (
                    published_el.text
                    if published_el is not None
                    else None
                ),

                "updated_date": (
                    updated_el.text
                    if updated_el is not None
                    else None
                ),

                "github_url": github_url,

                "github_stars": None,

                "_source_url": raw.source_url,
            }

            records.append(
                record
            )

        return self.deduplicate_records(
            records
        )

    # =======================================================================
    # DEDUPLICATE PAPERS
    # =======================================================================

    @staticmethod
    def deduplicate_records(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Deduplicate papers using arXiv ID.
        """

        unique: dict[
            str,
            dict[str, Any],
        ] = {}

        duplicate_count = 0

        for record in records:

            paper_id = record.get(
                "arxiv_id"
            )

            if not paper_id:
                continue

            if paper_id in unique:

                duplicate_count += 1

                existing = unique[
                    paper_id
                ]

                if (
                    not existing.get(
                        "github_url"
                    )
                    and record.get(
                        "github_url"
                    )
                ):

                    existing[
                        "github_url"
                    ] = record[
                        "github_url"
                    ]

                continue

            unique[
                paper_id
            ] = record

        if duplicate_count:

            log_ctx(
                logger,
                20,
                "arxiv_duplicates_removed",
                duplicate_count=duplicate_count,
                unique_count=len(unique),
            )

        return list(
            unique.values()
        )


# ===========================================================================
# GITHUB HELPERS
# ===========================================================================

def _extract_github_repo(
    github_url: Optional[str],
) -> Optional[str]:
    """
    Convert a GitHub URL into owner/repository.

    Examples:

        https://github.com/yhy-whu/Medpixel
        -> yhy-whu/Medpixel

        https://github.com/yzc-666/TIDE/
        -> yzc-666/TIDE
    """

    if not github_url:
        return None

    match = GITHUB_URL_RE.search(github_url)

    if not match:
        return None

    url = match.group(0).rstrip("/")

    # Capture owner/repo explicitly to avoid trailing paths like
    # `/tree/main` being interpreted as the repo name.
    m = re.search(r"github\.com/([^/]+)/([^/]+)", url, re.IGNORECASE)

    if not m:
        return None

    owner = m.group(1)
    repo = m.group(2)

    # Strip common suffixes
    if repo.endswith('.git'):
        repo = repo[:-4]

    if not owner or not repo:
        return None

    return f"{owner}/{repo}"


# ===========================================================================
# MODULE-LEVEL GITHUB ENRICHMENT FUNCTION
# ===========================================================================

async def enrich_github_stars(
    records: list[dict[str, Any]],
    session: aiohttp.ClientSession,
) -> list[dict[str, Any]]:
    """
    Enrich papers with GitHub repository information and star counts.

    This function is imported directly by ingest.py.
    """

    logger.info(
        "github_enrichment_starting"
    )

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GraphOne-Pipeline/1.0",
    }

    if GITHUB_API_TOKEN:

        headers[
            "Authorization"
        ] = (
            f"Bearer {GITHUB_API_TOKEN}"
        )

    # Cache repository results during this run.
    stars_cache: dict[
        str,
        Optional[int],
    ] = {}

    # -----------------------------------------------------------------------
    # Fetch stars for one repository
    # -----------------------------------------------------------------------

    async def _fetch_stars(
        repo_key: str,
    ) -> Optional[int]:

        if repo_key in stars_cache:

            return stars_cache[
                repo_key
            ]

        url = (
            f"{GITHUB_API_BASE.rstrip('/')}"
            f"/repos/{repo_key}"
        )

        async def _do():

            async with session.get(
                url,
                headers=headers,
            ) as resp:

                # -----------------------------------------------------------
                # Rate limit
                # -----------------------------------------------------------

                if (
                    resp.status == 403
                    and resp.headers.get(
                        "X-RateLimit-Remaining"
                    ) == "0"
                ):

                    # Try to compute a sensible retry delay. If
                    # GitHub provides `X-RateLimit-Reset` (epoch seconds)
                    # prefer that; otherwise fall back to Retry-After
                    # or a small default.
                    retry_after = resp.headers.get("Retry-After")

                    reset = resp.headers.get("X-RateLimit-Reset")

                    retry_seconds = None

                    if reset:
                        try:
                            import time

                            reset_ts = int(reset)
                            now_ts = int(time.time())
                            retry_seconds = max(5.0, float(reset_ts - now_ts))
                        except Exception:
                            retry_seconds = None

                    if retry_seconds is None and retry_after:
                        try:
                            retry_seconds = float(retry_after)
                        except Exception:
                            retry_seconds = None

                    if retry_seconds is None:
                        retry_seconds = 5.0

                    raise RetryableError(
                        "github_rate_limited",
                        retry_after=retry_seconds,
                    )

                # -----------------------------------------------------------
                # Repository not found
                # -----------------------------------------------------------

                if resp.status == 404:

                    log_ctx(
                        logger,
                        20,
                        "github_repository_not_found",
                        repo=repo_key,
                    )

                    return None

                # -----------------------------------------------------------
                # Server errors
                # -----------------------------------------------------------

                if resp.status >= 500:

                    raise RetryableError(
                        f"github_5xx_{resp.status}"
                    )

                # -----------------------------------------------------------
                # Other client errors
                # -----------------------------------------------------------

                if resp.status >= 400:

                    body = await resp.text()

                    log_ctx(
                        logger,
                        30,
                        "github_api_error",
                        repo=repo_key,
                        status=resp.status,
                        response=body[:300],
                    )

                    return None

                # -----------------------------------------------------------
                # Successful response
                # -----------------------------------------------------------

                data = await resp.json()

                stars = data.get(
                    "stargazers_count"
                )

                if isinstance(
                    stars,
                    int,
                ):

                    log_ctx(
                        logger,
                        20,
                        "github_stars_fetched",
                        repo=repo_key,
                        stars=stars,
                    )

                    return stars

                return None

        try:

            stars = await with_retry(
                _do,
                max_retries=2,
                base_backoff=2.0,
            )

        except Exception as exc:

            log_ctx(
                logger,
                30,
                "github_star_fetch_failed",
                repo=repo_key,
                error=str(exc),
            )

            stars = None

        stars_cache[
            repo_key
        ] = stars

        return stars

    # -----------------------------------------------------------------------
    # Process every paper
    # -----------------------------------------------------------------------

    for record in records:

        # Always reset before enrichment.
        record[
            "github_stars"
        ] = None

        github_url = record.get(
            "github_url"
        )

        if not github_url:
            continue

        repo_key = _extract_github_repo(
            github_url
        )

        if not repo_key:

            log_ctx(
                logger,
                30,
                "github_url_invalid",
                github_url=github_url,
            )

            continue

        stars = await _fetch_stars(
            repo_key
        )

        record[
            "github_stars"
        ] = stars

    logger.info(
        "github_enrichment_complete"
    )

    return records