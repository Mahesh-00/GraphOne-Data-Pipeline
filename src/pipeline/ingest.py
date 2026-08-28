
"""
Top-level pipeline orchestration.

Wires together scrapers, the LLM orchestrator, the entity resolver,
and storage for each vertical.

Papers use the arXiv ID as their unique identifier so that the same
paper is not stored multiple times across repeated pipeline runs.

Products additionally use listing/detail-page content when available
and normalize obvious directory UI labels such as "Featured", "New",
and "Trending" from product names.
"""

import asyncio
import ssl
import re
from typing import Any
from urllib.parse import urlparse

import aiohttp
import certifi

from src.config import (
    SCHEMA_VERSION,
    PRODUCTHUNT_API_TOKEN,
)
from src.llm.orchestrator import LLMOrchestrator
from src.resolution.resolver import EntityResolver
from src.pipeline.freshness import InMemorySeenStore, normalize_url, url_hash

from src.scrapers.papers_scraper import (
    ArxivScraper,
    enrich_github_stars,
)

from src.storage.db import Storage
from src.utils.logging_config import get_logger, log_ctx

from src.scrapers.directory_scraper import DirectoryScraper
from src.scrapers.jobs_scraper import JobListingScraper
from src.scrapers.news_scraper import NewsListingScraper, ArticleFetcher

from src.config import (
    STARTUP_SOURCES,
    PRODUCT_SOURCES,
    NEWS_SOURCES,
    JOB_SOURCES,
)


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# arXiv ID helpers
# ---------------------------------------------------------------------------

ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arXiv:)"
    r"([0-9]{4}\.[0-9]{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


def normalize_arxiv_id(paper_url: str | None) -> str | None:
    """
    Extract the canonical arXiv ID from a paper URL.

    Examples:

        http://arxiv.org/abs/2608.09928v1
            -> 2608.09928

        https://arxiv.org/abs/2608.09928v2
            -> 2608.09928

        https://arxiv.org/pdf/2608.09928v3
            -> 2608.09928

    The version number is intentionally removed because v1, v2, etc.
    represent the same arXiv paper.
    """

    if not paper_url:
        return None

    match = ARXIV_ID_RE.search(paper_url)

    if match:
        return match.group(1)

    return None


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

_GENERIC_PLACEHOLDER_NAMES = {
    "yc program",
    "startup school",
    "work at a startup",
    "co-founder matching",
    "startup directory",
    "yc startup directory",
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
    "techstars portfolio",
    "ycombinator",
    "y combinator",
    "techstars",
    "product hunt",
    "producthunt",
    "there's an ai for that",
    "theres an ai for that",
    "there is an ai for that",
    "locations",
    "location",
    "home",
    "search",
    "about",
    "about us",
    "blog",
    "newsroom",
    "careers",
    "resources",
    "login",
    "sign up",
    "log in",
    "click here to join for free!",
    "click here to join for free",
    "tools",
    "mini tools",
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


def _looks_like_bad_company_name(value: str | None) -> bool:
    if not value:
        return True

    text = " ".join(str(value).strip().split())
    if not text or len(text) < 2:
        return True

    lower = text.lower()
    if lower in _GENERIC_PLACEHOLDER_NAMES:
        return True

    if any(lower.startswith(prefix) for prefix in ("click here to join", "sign up for", "log in to", "about us", "view all")):
        return True

    return bool(
        re.fullmatch(
            r"(?:winter|summer|spring|fall|autumn)\s+\d{4}",
            text,
            re.IGNORECASE,
        )
    )


def _startup_slug_from_url(source_url: str | None) -> str:
    if not source_url:
        return ""

    try:
        path = urlparse(source_url).path.rstrip("/")
    except Exception:
        return ""

    if not path:
        return ""

    last = path.split("/")[-1]

    if not last or last.lower() in {
        "companies",
        "company",
        "startup",
        "startups",
        "portfolio",
    }:
        return ""

    return last


def _startup_fallback_name(
    raw_name: str | None,
    source_url: str | None,
) -> str:
    raw_value = (raw_name or "").strip()
    if raw_value and not _looks_like_bad_company_name(raw_value):
        return raw_value

    slug = _startup_slug_from_url(source_url)
    if slug:
        slug_text = slug.replace("-", " ").replace("_", " ")
        slug_name = " ".join(
            part.capitalize()
            for part in slug_text.split()
            if part
        )
        if slug_name and not _looks_like_bad_company_name(slug_name):
            return slug_name

    return ""


# ---------------------------------------------------------------------------
# Product name cleanup
# ---------------------------------------------------------------------------

_PRODUCT_UI_LABELS = {
    "featured",
    "new",
    "trending",
    "popular",
    "sponsored",
    "promoted",
    "advertised",
    "top",
}


def _clean_product_name(value: str | None) -> str:
    """
    Clean obvious directory/listing UI labels from a product name.

    Examples:

        "Kilo | Code Reviewer Featured"
            -> "Kilo | Code Reviewer"

        "Kick Featured"
            -> "Kick"

        "Featured Kick"
            -> "Kick"

    This function deliberately performs conservative cleanup.
    It does not attempt to invent or infer a completely different name.
    """

    if not value:
        return ""

    text = " ".join(str(value).strip().split())

    if not text:
        return ""

    # Remove common separators around UI labels.
    text = re.sub(
        r"\s*[\|\-–—•]\s*(featured|new|trending|popular|sponsored|promoted|advertised|top)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove labels at the END of the name.
    changed = True

    while changed:
        changed = False

        original = text

        text = re.sub(
            r"\s+(featured|new|trending|popular|sponsored|promoted|advertised|top)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )

        if text != original:
            changed = True

    # Remove labels at the BEGINNING only when they are clearly
    # standalone directory labels.
    text = re.sub(
        r"^(featured|new|trending|popular|sponsored|promoted|advertised|top)"
        r"\s*[\|\-–—:]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Final whitespace normalization.
    text = " ".join(text.split()).strip(" |-–—:")

    return text


def _clean_product_record(
    data: dict[str, Any],
    raw_name: str | None,
) -> dict[str, Any]:
    """
    Normalize a PRODUCT extraction without inventing missing information.
    """

    cleaned = dict(data)

    extracted_name = cleaned.get("productName")

    # Prefer the extracted name when it exists.
    # Otherwise use the scraper's raw listing name.
    candidate_name = extracted_name or raw_name or ""

    cleaned_name = _clean_product_name(candidate_name)

    # If cleanup accidentally produces an empty string, retain the
    # original raw value rather than inventing anything.
    if not cleaned_name:
        cleaned_name = _clean_product_name(raw_name)

    cleaned["productName"] = cleaned_name or None

    return cleaned


async def _fetch_producthunt_api_records(
    session: aiohttp.ClientSession,
    source_name: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Prefer Product Hunt's official API when a token is configured.

    If no token is available, or the API rejects the request, we log a
    warning and return an empty result so the existing scraper fallback can
    continue without crashing the pipeline.
    """

    if not PRODUCTHUNT_API_TOKEN:
        log_ctx(
            logger,
            30,
            "producthunt_api_token_missing",
            source=source_name,
        )
        return []

    headers = {
        "Authorization": f"Bearer {PRODUCTHUNT_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "query": """
        {
          posts(first: 20, order: VOTES) {
            edges {
              node {
                id
                name
                tagline
                slug
                website
                url
                description
              }
            }
          }
        }
        """
    }

    try:
        async with session.post(
            "https://api.producthunt.com/v2/api/graphql",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status in (401, 403):
                log_ctx(
                    logger,
                    30,
                    "producthunt_api_auth_failed",
                    source=source_name,
                    status=response.status,
                )
                return []

            if response.status >= 400:
                log_ctx(
                    logger,
                    30,
                    "producthunt_api_unavailable",
                    source=source_name,
                    status=response.status,
                )
                return []

            data = await response.json()
            posts = data.get("data", {}).get("posts", {})
            edges = posts.get("edges") or []

            results: list[dict[str, Any]] = []
            seen_names: set[str] = set()

            for edge in edges:
                node = edge.get("node") if isinstance(edge, dict) else None
                if not isinstance(node, dict):
                    continue

                name = str(node.get("name") or "").strip()
                slug = str(node.get("slug") or "").strip()
                website = str(node.get("website") or node.get("url") or "").strip()
                tagline = str(node.get("tagline") or node.get("description") or "").strip()

                cleaned_name = _clean_product_name(name) or _clean_product_name(slug.replace("-", " "))
                if not cleaned_name:
                    continue

                normalized = cleaned_name.casefold()
                if normalized in seen_names:
                    continue
                seen_names.add(normalized)

                detail_url = website or (
                    f"https://www.producthunt.com/posts/{slug}" if slug else "https://www.producthunt.com"
                )

                results.append(
                    {
                        "raw_name": cleaned_name,
                        "detail_url": detail_url,
                        "_source_url": detail_url,
                        "_snippet_html": f"<div>{tagline or cleaned_name}</div>",
                        "_source_name": source_name,
                        "_raw_document_id": None,
                    }
                )

                if len(results) >= limit:
                    break

            return results

    except Exception as exc:
        log_ctx(
            logger,
            30,
            "producthunt_api_exception",
            source=source_name,
            error=str(exc),
        )
        return []


# ---------------------------------------------------------------------------
# Papers pipeline
# ---------------------------------------------------------------------------

async def run_papers_pipeline(
    storage: Storage,
    target: int = 1000,
) -> list[dict[str, Any]]:

    """
    Papers vertical.

    arXiv's Atom API provides:
    - title
    - authors
    - publication date
    - paper URL

    GitHub stars are enriched separately through the GitHub API.

    Duplicate protection:
    - Deduplicates papers within the current API response.
    - Checks existing database records before saving.
    - Uses canonical arXiv ID without version number as the unique key.
    """

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    connector = aiohttp.TCPConnector(
        ssl=ssl_context
    )

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; GraphOneBot/1.0; "
            "+https://frontieratlas.example/bot)"
        )
    }

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
    ) as session:

        scraper = ArxivScraper(
            session=session
        )

        all_records: list[dict[str, Any]] = []

        seen_arxiv_ids: set[str] = set()

        try:

            # ---------------------------------------------------------------
            # Load papers already stored in database.
            # ---------------------------------------------------------------

            existing_records = await storage.fetch_all(
                "RESEARCH_PAPER"
            )

            existing_arxiv_ids: set[str] = set()

            for existing in existing_records:

                content = existing.get(
                    "content",
                    existing,
                )

                if not isinstance(content, dict):
                    content = existing

                paper_url = content.get(
                    "paper_url"
                )

                arxiv_id = normalize_arxiv_id(
                    paper_url
                )

                if arxiv_id:
                    existing_arxiv_ids.add(
                        arxiv_id
                    )

            log_ctx(
                logger,
                20,
                "existing_arxiv_papers_loaded",
                count=len(existing_arxiv_ids),
            )

            # ---------------------------------------------------------------
            # Collect papers from arXiv.
            # ---------------------------------------------------------------

            async for raw, records in scraper.run(
                limit=max(target * 25, 200)
            ):

                raw_id = await storage.save_raw_document(
                    source_name=raw.source_name,
                    source_url=raw.source_url,
                    url_hash=url_hash(
                        raw.source_url
                    ),
                    content=raw.content,
                    content_type=raw.content_type,
                )

                for rec in records:

                    rec["_raw_document_id"] = raw_id

                    paper_url = rec.get(
                        "paper_url"
                    )

                    arxiv_id = normalize_arxiv_id(
                        paper_url
                    )

                    if not arxiv_id:

                        log_ctx(
                            logger,
                            30,
                            "arxiv_id_not_found",
                            paper_url=paper_url,
                        )

                        continue

                    rec["_arxiv_id"] = arxiv_id

                    if arxiv_id in seen_arxiv_ids:

                        log_ctx(
                            logger,
                            20,
                            "paper_duplicate_in_run",
                            arxiv_id=arxiv_id,
                        )

                        continue

                    if arxiv_id in existing_arxiv_ids:

                        log_ctx(
                            logger,
                            20,
                            "paper_duplicate_existing",
                            arxiv_id=arxiv_id,
                        )

                        continue

                    seen_arxiv_ids.add(
                        arxiv_id
                    )

                    all_records.append(
                        rec
                    )

                    log_ctx(
                        logger,
                        20,
                        "papers_records_collected",
                        current_count=len(all_records),
                        target=target,
                    )

                    if len(all_records) >= target:
                        break

                if len(all_records) >= target:
                    break

            all_records = all_records[:target]

            # ---------------------------------------------------------------
            # GitHub enrichment.
            # ---------------------------------------------------------------

            if all_records:

                try:

                    all_records = await enrich_github_stars(
                        all_records,
                        session,
                    )

                except Exception as exc:

                    log_ctx(
                        logger,
                        30,
                        "github_enrichment_failed_pipeline_continues",
                        error=str(exc),
                    )

            # ---------------------------------------------------------------
            # Save structured records.
            # ---------------------------------------------------------------

            saved_count = 0

            for rec in all_records:

                arxiv_id = rec.get(
                    "_arxiv_id"
                )

                paper_url = rec.get(
                    "paper_url"
                )

                if (
                    arxiv_id
                    and arxiv_id in existing_arxiv_ids
                ):

                    log_ctx(
                        logger,
                        20,
                        "paper_duplicate_save_prevented",
                        arxiv_id=arxiv_id,
                    )

                    continue

                payload = {
                    "schemaVersion": SCHEMA_VERSION,
                    "recordType": "RESEARCH_PAPER",

                    "arxiv_id": arxiv_id,

                    "content": {
                        "title": rec.get(
                            "title"
                        ),
                        "authors": rec.get(
                            "authors"
                        ),
                        "paper_url": paper_url,
                        "github_url": rec.get(
                            "github_url"
                        ),
                        "github_stars": rec.get(
                            "github_stars"
                        ),
                        "published_date": rec.get(
                            "published_date"
                        ),
                    },
                }

                try:

                    await storage.save_structured_record(
                        record_type="RESEARCH_PAPER",
                        schema_version=SCHEMA_VERSION,
                        source_name="Arxiv",
                        source_url=(
                            paper_url
                            or rec.get("_source_url")
                        ),
                        payload=payload,
                        raw_document_id=rec.get(
                            "_raw_document_id"
                        ),
                    )

                except Exception as exc:

                    log_ctx(
                        logger,
                        40,
                        "paper_save_failed",
                        error=str(exc),
                        arxiv_id=arxiv_id,
                        title=rec.get("title"),
                    )

                    continue

                existing_arxiv_ids.add(
                    arxiv_id
                )

                saved_count += 1

                log_ctx(
                    logger,
                    20,
                    "paper_saved",
                    arxiv_id=arxiv_id,
                    title=rec.get(
                        "title"
                    ),
                )

            log_ctx(
                logger,
                20,
                "papers_pipeline_complete",
                collected_count=len(all_records),
                saved_count=saved_count,
            )

            return all_records

        finally:

            await scraper.close()


# ---------------------------------------------------------------------------
# Directory / Startup / Product pipelines
# ---------------------------------------------------------------------------

async def _run_directory_pipeline_generic(
    storage: Storage,
    sources,
    record_type: str,
    target: int = 100,
):
    """
    Generic directory pipeline used for STARTUP and PRODUCT.
    """

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    connector = aiohttp.TCPConnector(
        ssl=ssl_context
    )

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GraphOneBot/1.0)"
    }

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
    ) as session:

        llm = LLMOrchestrator(
            session=session
        )

        resolver = EntityResolver()

        raw_candidates: list[dict[str, Any]] = []
        seen_in_batch: set[str] = set()

        try:
            for source in sources:
                try:
                    if source.name == "ProductHunt":
                        api_records = await _fetch_producthunt_api_records(
                            session=session,
                            source_name=source.name,
                            limit=max(1, target),
                        )

                        if api_records:
                            for rec in api_records:
                                d_url = rec.get("detail_url") or rec.get("_source_url") or ""
                                if d_url:
                                    norm_u = normalize_url(d_url)
                                    if norm_u in seen_in_batch or await storage.source_url_exists(record_type, d_url):
                                        continue
                                    seen_in_batch.add(norm_u)
                                raw_candidates.append(rec)
                                if len(raw_candidates) >= target:
                                    break

                            if len(raw_candidates) >= target:
                                break
                            continue

                        log_ctx(
                            logger,
                            30,
                            "producthunt_api_fallback_to_scraper",
                            source=source.name,
                            url=source.base_url,
                        )

                    scraper = DirectoryScraper(
                        source=source,
                        list_selector=(
                            source.list_selector
                            or (
                                "a[href^='/companies/']"
                                if source.name == "YCombinator"
                                else "a"
                            )
                        ),
                        name_selector=(
                            source.name_selector
                            or "a"
                        ),
                        link_selector=(
                            source.link_selector
                            or "a"
                        ),
                        max_pages=max(
                            10,
                            (target // 5) + 3
                        ),
                        session=session,
                    )

                    async for raw, records in scraper.run(
                        limit=target
                    ):
                        if not records:
                            log_ctx(
                                logger,
                                30,
                                "page_yielded_no_records",
                                source=source.name,
                                url=raw.source_url,
                            )
                            continue

                        raw_id = await storage.save_raw_document(
                            source_name=source.name,
                            source_url=raw.source_url,
                            url_hash=url_hash(
                                raw.source_url
                            ),
                            content=raw.content,
                            content_type=raw.content_type,
                        )

                        for r in records:
                            raw_name_cand = (r.get("raw_name") or "").strip()
                            if _looks_like_bad_company_name(raw_name_cand) and not _startup_slug_from_url(r.get("detail_url")):
                                log_ctx(
                                    logger,
                                    20,
                                    "skipping_generic_placeholder_record",
                                    raw_name=raw_name_cand,
                                    source_url=raw.source_url,
                                )
                                continue

                            detail_url = r.get("detail_url") or ""
                            if not detail_url or "?industry=" in detail_url or "?page=" in detail_url or "?batch=" in detail_url:
                                continue
                            if detail_url.rstrip("/") == source.base_url.rstrip("/"):
                                continue
                            if record_type == "STARTUP" and not any(p in detail_url.lower() for p in ("/companies/", "/company/", "/startup/")):
                                continue
                            if record_type == "PRODUCT" and not any(p in detail_url.lower() for p in ("/ai/", "/tools/", "/posts/")):
                                continue

                            norm_u = normalize_url(detail_url)
                            if norm_u in seen_in_batch:
                                continue
                            if await storage.source_url_exists(record_type, detail_url):
                                continue
                            seen_in_batch.add(norm_u)

                            r.setdefault(
                                "_source_name",
                                source.name
                            )
                            r.setdefault(
                                "_source_url",
                                raw.source_url
                            )
                            r["_raw_document_id"] = raw_id

                            raw_candidates.append(
                                r
                            )

                            if len(raw_candidates) >= target:
                                break

                        if len(raw_candidates) >= target:
                            break

                    await scraper.close()

                    if len(raw_candidates) >= target:
                        break

                except Exception as source_exc:
                    log_ctx(
                        logger,
                        40,
                        "directory_source_failed_pipeline_continues",
                        source=source.name,
                        error=str(source_exc),
                    )

            # ---------------------------------------------------------------
            # LLM extraction + entity resolution + persistence
            # ---------------------------------------------------------------

            results = await run_extraction_for_directory_records(
                storage=storage,
                llm=llm,
                resolver=resolver,
                record_type=record_type,
                raw_candidates=raw_candidates,
                target=target,
            )

            return results

        finally:

            await llm.close()


async def run_startups_pipeline(
    storage: Storage,
    target: int = 100,
) -> list[dict[str, Any]]:

    return await _run_directory_pipeline_generic(
        storage,
        STARTUP_SOURCES,
        "STARTUP",
        target=target,
    )


async def run_products_pipeline(
    storage: Storage,
    target: int = 100,
) -> list[dict[str, Any]]:

    return await _run_directory_pipeline_generic(
        storage,
        PRODUCT_SOURCES,
        "PRODUCT",
        target=target,
    )


# ---------------------------------------------------------------------------
# Jobs pipeline
# ---------------------------------------------------------------------------

async def run_jobs_pipeline(
    storage: Storage,
    target: int = 100,
) -> list[dict[str, Any]]:

    """
    Jobs pipeline:

        listing crawl
        ->
        freshness filter
        ->
        persistence
    """

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    connector = aiohttp.TCPConnector(
        ssl=ssl_context
    )

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GraphOneBot/1.0)"
    }

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
    ) as session:

        seen_store = InMemorySeenStore()

        async def fetch_jobs():

            count = 0

            for source in JOB_SOURCES:

                scraper = JobListingScraper(
                    source=source,
                    link_selector="a",
                    session=session,
                )

                async for raw, records in scraper.run(
                    limit=target
                ):

                    for r in records:

                        r.setdefault(
                            "_source_name",
                            source.name
                        )

                        r.setdefault(
                            "_source_url",
                            raw.source_url
                        )

                        yield r

                        count += 1

                        if count >= target:
                            return

                await scraper.close()

        return await run_freshness_filtered_pipeline(
            storage=storage,
            record_type="JOB",
            fetch_fn=fetch_jobs,
            seen_store=seen_store,
        )


# ---------------------------------------------------------------------------
# News pipeline
# ---------------------------------------------------------------------------

async def run_news_pipeline(
    storage: Storage,
    target: int = 100,
) -> list[dict[str, Any]]:

    """
    News pipeline:

        listing crawl
        ->
        article fetch
        ->
        freshness filter
        ->
        persistence
    """

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    connector = aiohttp.TCPConnector(
        ssl=ssl_context
    )

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GraphOneBot/1.0)"
    }

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
    ) as session:

        seen_store = InMemorySeenStore()

        async def fetch_articles():

            count = 0

            for source in NEWS_SOURCES:

                listing_scraper = NewsListingScraper(
                    source=source,
                    link_selector="a",
                    session=session,
                )

                article_fetcher = ArticleFetcher(
                    source=source,
                    session=session,
                )

                async for raw, records in listing_scraper.run(
                    limit=target
                ):

                    for rec in records:

                        article_url = rec.get(
                            "article_url"
                        )

                        if not article_url:
                            continue

                        article = await article_fetcher.fetch_article(
                            article_url
                        )

                        if article:

                            article.setdefault(
                                "source_name",
                                source.name
                            )

                            article.setdefault(
                                "source_url",
                                article_url
                            )

                            yield article

                            count += 1

                            if count >= target:
                                break

                    if count >= target:
                        break

                await listing_scraper.close()

                await article_fetcher.close()

                if count >= target:
                    break

        return await run_freshness_filtered_pipeline(
            storage=storage,
            record_type="NEWS",
            fetch_fn=fetch_articles,
            seen_store=seen_store,
        )


# ---------------------------------------------------------------------------
# Generic extraction pipeline
# ---------------------------------------------------------------------------

async def _fetch_product_detail_page(
    session: aiohttp.ClientSession,
    source_url: str,
) -> str:
    """
    Try to fetch the product detail page.

    Some directories such as ThereIsAnAIForThat may return HTTP 403.
    A failed detail fetch must never cause the whole product pipeline
    to fail. The caller will fall back to listing content.
    """

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with session.get(
            source_url,
            headers=headers,
            allow_redirects=True,
        ) as response:

            if response.status >= 400:

                log_ctx(
                    logger,
                    30,
                    "product_detail_page_fetch_failed",
                    source_url=source_url,
                    status=response.status,
                )

                return ""

            return await response.text()

    except Exception as exc:

        log_ctx(
            logger,
            30,
            "product_detail_page_fetch_exception",
            source_url=source_url,
            error=str(exc),
        )

        return ""


async def run_extraction_for_directory_records(
    storage: Storage,
    llm: LLMOrchestrator,
    resolver: EntityResolver,
    record_type: str,
    raw_candidates: list[dict[str, Any]],
    target: int = 100,
) -> list[dict[str, Any]]:

    """
    Shared path for startups/products/jobs.

    Each raw candidate is passed through:
        1. Optional detail-page enrichment for products
        2. LLM extraction
        3. Validation
        4. Product-name cleanup
        5. Entity resolution
        6. Persistence

    No information is fabricated if the LLM fails.
    """

    results: list[dict[str, Any]] = []

    seen_urls: set[str] = set()

    for cand in raw_candidates:

        # ---------------------------------------------------------------
        # Original listing content.
        # ---------------------------------------------------------------

        listing_content = (
            cand.get("_snippet_html")
            or cand.get("listing_snippet")
            or ""
        )

        source_url = cand.get("detail_url") or ""

        raw_name = (
            cand.get("raw_name")
            or ""
        )

        if not source_url or "?industry=" in source_url or "?page=" in source_url or "?batch=" in source_url:
            log_ctx(
                logger,
                30,
                "skipping_candidate_without_entity_detail_url",
                source_url=source_url,
                raw_name=raw_name,
            )
            continue

        # ---------------------------------------------------------------
        # Duplicate URL protection within this batch.
        # ---------------------------------------------------------------

        if source_url:

            normalized_url = normalize_url(
                source_url
            )

            if normalized_url in seen_urls:

                log_ctx(
                    logger,
                    20,
                    "directory_record_duplicate_within_batch",
                    record_type=record_type,
                    source_url=source_url,
                )

                continue

            seen_urls.add(
                normalized_url
            )

        # ---------------------------------------------------------------
        # Duplicate protection against database.
        #
        # Products are allowed to continue if the source URL exists,
        # because some product directories can expose multiple listing
        # URLs or unstable query parameters. URL normalization above
        # protects duplicates inside the current batch.
        # ---------------------------------------------------------------

        if (
            source_url
            and await storage.source_url_exists(
                record_type,
                source_url,
            )
        ):

            log_ctx(
                logger,
                20,
                "directory_record_duplicate_existing",
                record_type=record_type,
                source_url=source_url,
            )

            continue

        # ---------------------------------------------------------------
        # Build extraction content.
        #
        # For products, attempt to fetch the detail page first.
        # If the detail page returns 403/empty, use the listing content.
        # ---------------------------------------------------------------

        content = listing_content

        if (
            record_type == "PRODUCT"
            and cand.get("_source_name") != "ThereIsAnAIForThat"
            and source_url
            and source_url != cand.get("_source_url")
        ):

            session = getattr(
                llm,
                "_session",
                None,
            )

            if session is not None:

                detail_content = await _fetch_product_detail_page(
                    session,
                    source_url,
                )

                if detail_content:

                    content = detail_content

                    log_ctx(
                        logger,
                        20,
                        "product_detail_page_used",
                        source_url=source_url,
                    )

                else:

                    log_ctx(
                        logger,
                        30,
                        "product_detail_page_empty_using_listing_content",
                        source_url=source_url,
                        raw_name=raw_name,
                    )

        # ---------------------------------------------------------------
        # LLM extraction.
        # ---------------------------------------------------------------

        extraction = await llm.extract(
            record_type=record_type,
            source_url=source_url,
            title=raw_name,
            body=content,
        )

        # ---------------------------------------------------------------
        # If LLM extraction succeeds, use it.
        # Otherwise use source-only fallback.
        # ---------------------------------------------------------------

        if extraction.success and extraction.data:

            data = extraction.data

        else:

            if record_type == "STARTUP":

                data = {
                    "entityName": _startup_fallback_name(
                        raw_name,
                        source_url,
                    ),
                    "employeeCount": None,
                    "description": "",
                }

            elif record_type == "PRODUCT":

                data = {
                    "productName": _clean_product_name(
                        raw_name
                    ) or None,
                    "startupName": None,
                    "pricingModel": None,
                    "description": "",
                }

            else:

                data = {
                    "name": raw_name
                }

            log_ctx(
                logger,
                20,
                "directory_record_using_source_fallback",
                record_type=record_type,
                source_url=source_url,
                raw_name=raw_name,
                provider_used=extraction.provider_used,
                error=extraction.error,
            )

        # ---------------------------------------------------------------
        # Product cleanup.
        #
        # This is the important fix for:
        #
        #     "Kilo | Code Reviewer Featured"
        #     "Kick Featured"
        #
        # becoming:
        #
        #     "Kilo | Code Reviewer"
        #     "Kick"
        # ---------------------------------------------------------------

        if record_type == "PRODUCT":

            before_name = data.get(
                "productName"
            )

            data = _clean_product_record(
                data,
                raw_name,
            )

            after_name = data.get(
                "productName"
            )

            if before_name != after_name:

                log_ctx(
                    logger,
                    20,
                    "product_name_cleaned",
                    source_url=source_url,
                    before=before_name,
                    after=after_name,
                )

        # ---------------------------------------------------------------
        # Resolve entity name.
        #
        # For STARTUP, resolve entityName.
        # For PRODUCT, resolve startupName if available.
        #
        # Do NOT resolve productName because product names and startup
        # names are different entities.
        # ---------------------------------------------------------------

        if record_type == "STARTUP":

            name_field = "entityName"

        elif record_type == "PRODUCT":

            name_field = "startupName"

        else:

            name_field = None

        if name_field:

            candidate_name = (
                data.get(name_field)
                or ""
            )

            if record_type == "STARTUP":

                candidate_name = _startup_fallback_name(
                    candidate_name or raw_name,
                    source_url,
                )

            if candidate_name:

                resolution = resolver.resolve(
                    candidate_name,
                    source_name=cand.get(
                        "_source_name"
                    ),
                    source_url=source_url,
                )

                data[name_field] = (
                    resolution.canonical_name
                )

        # ---------------------------------------------------------------
        # Final product-name safety.
        # ---------------------------------------------------------------

        if record_type == "PRODUCT":

            final_product_name = _clean_product_name(
                data.get("productName")
                or raw_name
            )

            data["productName"] = (
                final_product_name
                or None
            )

        if record_type == "STARTUP":
            entity_name = (data.get("entityName") or "").strip()
            if not entity_name or _looks_like_bad_company_name(entity_name):
                log_ctx(
                    logger,
                    30,
                    "skipping_startup_with_invalid_or_placeholder_name",
                    source_url=source_url,
                    raw_name=raw_name,
                    entity_name=entity_name,
                )
                continue

        if record_type == "PRODUCT":
            product_name = (data.get("productName") or "").strip()
            if not product_name or _looks_like_bad_company_name(product_name):
                log_ctx(
                    logger,
                    30,
                    "skipping_product_with_invalid_or_placeholder_name",
                    source_url=source_url,
                    raw_name=raw_name,
                    product_name=product_name,
                )
                continue

        # ---------------------------------------------------------------
        # Persist structured record.
        # ---------------------------------------------------------------

        try:

            await storage.save_structured_record(
                record_type=record_type,
                schema_version=SCHEMA_VERSION,
                source_name=cand.get(
                    "_source_name",
                    "",
                ),
                source_url=source_url,
                payload=data,
                raw_document_id=cand.get(
                    "_raw_document_id"
                ),
                llm_provider_used=(
                    extraction.provider_used
                ),
            )

        except Exception as exc:

            log_ctx(
                logger,
                40,
                "directory_record_save_failed",
                error=str(exc),
                source_url=source_url,
                record_type=record_type,
            )

            continue

        # ---------------------------------------------------------------
        # Return result.
        # ---------------------------------------------------------------

        result_payload = {
            **data,
            "record_type": record_type,
            "source_name": cand.get(
                "_source_name",
                "",
            ),
            "source_url": source_url,
            "raw_document_id": cand.get(
                "_raw_document_id"
            ),
        }

        results.append(
            result_payload
        )

        log_ctx(
            logger,
            20,
            "directory_record_saved",
            record_type=record_type,
            product_name=(
                data.get("productName")
                if record_type == "PRODUCT"
                else None
            ),
            source_url=source_url,
        )

        if target and len(results) >= target:
            break

    return results


# ---------------------------------------------------------------------------
# Freshness-filtered pipeline
# ---------------------------------------------------------------------------

async def run_freshness_filtered_pipeline(
    storage: Storage,
    record_type: str,
    fetch_fn,
    seen_store: InMemorySeenStore,
) -> list[dict[str, Any]]:

    """
    Shared path for news/jobs.

    Freshness and cross-run deduplication determine whether
    a record gets persisted.
    """

    results: list[dict[str, Any]] = []

    async for item in fetch_fn():

        if item is None:
            continue

        source_url = (
            item.get("source_url")
            or item.get("article_url")
            or item.get("job_url")
        )

        if not source_url:
            continue

        if record_type == "JOB":
            if not item.get("title") and not item.get("company"):
                continue
            if any(p in source_url.lower() for p in ("/login", "/signup", "/sign-up", "/signin", "/sign-in", "/hire-remotely", "/about", "/contact")):
                continue

        if await storage.source_url_exists(
            record_type,
            source_url,
        ):

            log_ctx(
                logger,
                20,
                "freshness_duplicate_existing",
                record_type=record_type,
                source_url=source_url,
            )

            continue

        if await seen_store.has_seen(
            source_url
        ):
            continue

        await seen_store.mark_seen(
            source_url
        )

        await storage.save_structured_record(
            record_type=record_type,
            schema_version=SCHEMA_VERSION,
            source_name=item.get(
                "source_name",
                "",
            ),
            source_url=source_url,
            payload=item,
        )

        results.append(
            item
        )

    return results
