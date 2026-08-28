import asyncio
import sys
from pathlib import Path  

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.pipeline.ingest import run_papers_pipeline, normalize_arxiv_id
from src.scrapers.papers_scraper import ArxivScraper
from src.storage.db import RawDocumentRow, Storage
from src.scrapers.base_scraper import RawDocument


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], text: str):
        self.status = status
        self.headers = headers
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = responses
        self._index = 0

    def get(self, url: str):
        if self._index >= len(self._responses):
            raise RuntimeError("No more fake responses")

        response = self._responses[self._index]
        self._index += 1
        return response


@pytest.fixture
def test_storage(tmp_path):
    db_path = tmp_path / "graphone_test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    storage = Storage(database_url=database_url)
    asyncio.run(storage.init_models())
    yield storage
    asyncio.run(storage.close())


def test_normalize_arxiv_id_handles_versions():
    assert normalize_arxiv_id("https://arxiv.org/abs/2608.09928v1") == "2608.09928"
    assert normalize_arxiv_id("https://arxiv.org/abs/2608.09928v2") == "2608.09928"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2608.09928v3") == "2608.09928"
    assert normalize_arxiv_id("arXiv:2608.09928v4") == "2608.09928"


def test_arxiv_fetch_respects_retry_after(monkeypatch):
    xml_payload = (
        "<feed xmlns=\"http://www.w3.org/2005/Atom\">"
        "<entry><id>http://arxiv.org/abs/2608.99999v1</id>"
        "<title>Test</title></entry></feed>"
    )

    session = FakeSession(
        [
            FakeResponse(429, {"Retry-After": "0.01"}, ""),
            FakeResponse(200, {"Content-Type": "application/xml"}, xml_payload),
        ]
    )

    scraper = ArxivScraper(session=session)
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float):
        sleep_delays.append(delay)

    async def noop_wait():
        return None

    monkeypatch.setattr("src.utils.async_pool.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("src.scrapers.base_scraper.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(scraper._rate_limiter, "wait", noop_wait)

    async def invoke():
        return await scraper.fetch("https://example.com/test")

    document = asyncio.run(invoke())

    assert document.content == xml_payload
    assert sleep_delays == [0.01]


def test_arxiv_scraper_run_deduplicates_across_pages(monkeypatch):
    scraper = ArxivScraper(session=None)

    async def fake_list_page_urls(limit=None):
        yield "page1"
        yield "page2"
        yield "page3"

    async def fake_fetch(url: str):
        return RawDocument(
            source_name="Arxiv",
            source_url=url,
            fetched_at=0.0,
            content="",
            content_type="xml",
            meta={},
        )

    def fake_parse(raw: RawDocument):
        if raw.source_url == "page1":
            return [
                {"arxiv_id": "2608.10000", "paper_url": "https://arxiv.org/abs/2608.10000"},
                {"arxiv_id": "2608.10001", "paper_url": "https://arxiv.org/abs/2608.10001"},
            ]
        if raw.source_url == "page2":
            return [
                {"arxiv_id": "2608.10001", "paper_url": "https://arxiv.org/abs/2608.10001"},
                {"arxiv_id": "2608.10002", "paper_url": "https://arxiv.org/abs/2608.10002"},
            ]
        return [
            {"arxiv_id": "2608.10002", "paper_url": "https://arxiv.org/abs/2608.10002"},
            {"arxiv_id": "2608.10003", "paper_url": "https://arxiv.org/abs/2608.10003"},
        ]

    monkeypatch.setattr(scraper, "list_page_urls", fake_list_page_urls)
    monkeypatch.setattr(scraper, "fetch", fake_fetch)
    monkeypatch.setattr(scraper, "parse", fake_parse)

    async def collect():
        results = []
        async for raw, records in scraper.run(limit=3):
            results.append((raw.source_url, records))
        return results

    results = asyncio.run(collect())

    assert len(results) == 2
    assert [page for page, _ in results] == ["page1", "page2"]
    unique_ids = {record["arxiv_id"] for _, records in results for record in records}
    assert unique_ids == {"2608.10000", "2608.10001", "2608.10002"}


def test_run_papers_pipeline_skips_existing_arxiv_ids(test_storage, monkeypatch):
    existing_url = "https://arxiv.org/abs/2608.11204"
    asyncio.run(
        test_storage.save_structured_record(
            record_type="RESEARCH_PAPER",
            schema_version="1.0",
            source_name="Arxiv",
            source_url=existing_url,
            payload={
                "schemaVersion": "1.0",
                "recordType": "RESEARCH_PAPER",
                "paper_url": existing_url,
            },
        )
    )

    class FakeArxivScraper:
        def __init__(self, session=None):
            pass

        async def run(self, limit=None):
            raw = RawDocument(
                source_name="Arxiv",
                source_url="https://export.arxiv.org/api/query?search_query=cat:cs.AI&start=0",
                fetched_at=0.0,
                content="",
                content_type="xml",
                meta={},
            )
            yield raw, [
                {
                    "arxiv_id": "2608.11204",
                    "paper_url": existing_url,
                    "title": "Existing Paper",
                    "authors": [],
                    "github_url": None,
                },
                {
                    "arxiv_id": "2608.99999",
                    "paper_url": "https://arxiv.org/abs/2608.99999",
                    "title": "New Paper",
                    "authors": [],
                    "github_url": None,
                },
            ]

        async def close(self):
            pass

    monkeypatch.setattr("src.pipeline.ingest.ArxivScraper", FakeArxivScraper)

    records = asyncio.run(run_papers_pipeline(test_storage, target=2))

    assert len(records) == 1
    assert records[0]["_arxiv_id"] == "2608.99999"


def test_extract_arxiv_id_rejects_invalid_urls():
    assert ArxivScraper.extract_arxiv_id("http") is None
    assert ArxivScraper.extract_arxiv_id("not-an-arxiv-url") is None
    assert ArxivScraper.extract_arxiv_id("https://arxiv.org/abs/2608.09928v4") == "2608.09928"


def test_scraper_does_not_close_external_session():
    class DummySession:
        def __init__(self):
            self.close_called = 0

        async def close(self):
            self.close_called += 1

    session = DummySession()
    scraper = ArxivScraper(session=session)
    asyncio.run(scraper.close())
    assert session.close_called == 0
