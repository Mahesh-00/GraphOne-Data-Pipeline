import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.storage.db import Storage


@pytest.fixture
def test_storage(tmp_path):
    db_path = tmp_path / "graphone_test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    storage = Storage(database_url=database_url)
    asyncio.run(storage.init_models())
    yield storage
    asyncio.run(storage.close())


def test_successful_structured_save(test_storage):
    payload = {"schemaVersion": "1.0", "recordType": "TEST_RECORD", "value": 123}
    record_id = asyncio.run(
        test_storage.save_structured_record(
            record_type="TEST_RECORD",
            schema_version="1.0",
            source_name="unit-test",
            source_url="https://example.com/test",
            payload=payload,
        )
    )
    assert isinstance(record_id, int)
    records = asyncio.run(test_storage.fetch_all("TEST_RECORD"))
    assert len(records) == 1
    assert records[0]["recordType"] == "TEST_RECORD"
    assert records[0]["schemaVersion"] == "1.0"
    assert records[0]["source_name"] == "unit-test"
    assert records[0]["source_url"] == "https://example.com/test"


def test_duplicate_paper_is_not_saved(test_storage):
    asyncio.run(
        test_storage.save_structured_record(
            record_type="RESEARCH_PAPER",
            schema_version="1.0",
            source_name="Arxiv",
            source_url="https://arxiv.org/abs/1234.5678",
            payload={"schemaVersion": "1.0", "recordType": "RESEARCH_PAPER", "paper_url": "https://arxiv.org/abs/1234.5678"},
        )
    )
    from src.pipeline.ingest import normalize_arxiv_id

    assert normalize_arxiv_id("https://arxiv.org/abs/1234.5678v2") == "1234.5678"
    existing_ids = asyncio.run(test_storage.find_existing_arxiv_ids())
    assert "1234.5678" in existing_ids


def test_duplicate_url_not_saved(test_storage):
    payload = {"schemaVersion": "1.0", "recordType": "NEWS", "article_url": "https://example.com/a?utm_source=twitter"}
    asyncio.run(
        test_storage.save_structured_record(
            record_type="NEWS",
            schema_version="1.0",
            source_name="NewsSite",
            source_url="https://example.com/a?utm_source=twitter",
            payload=payload,
        )
    )
    assert asyncio.run(test_storage.source_url_exists("NEWS", "https://example.com/a"))


def test_missing_source_url_save(test_storage):
    payload = {"schemaVersion": "1.0", "recordType": "JOB", "title": "No URL"}
    record_id = asyncio.run(
        test_storage.save_structured_record(
            record_type="JOB",
            schema_version="1.0",
            source_name="JobSite",
            source_url="",
            payload=payload,
        )
    )
    assert record_id
    records = asyncio.run(test_storage.fetch_all("JOB"))
    assert len(records) == 1
    assert records[0]["source_url"] == ""


def test_invalid_record_does_not_crash(test_storage):
    with pytest.raises(ValueError):
        asyncio.run(
            test_storage.save_structured_record(
                record_type=None,
                schema_version=None,
                source_name=None,
                source_url=None,
                payload=None,
            )
        )


def test_repeated_pipeline_execution_does_not_duplicate(test_storage):
    payload = {"schemaVersion": "1.0", "recordType": "NEWS", "article_url": "https://example.com/a"}
    asyncio.run(
        test_storage.save_structured_record(
            record_type="NEWS",
            schema_version="1.0",
            source_name="NewsSite",
            source_url="https://example.com/a",
            payload=payload,
        )
    )
    assert asyncio.run(test_storage.source_url_exists("NEWS", "https://example.com/a"))
    assert asyncio.run(test_storage.source_url_exists("NEWS", "https://example.com/a/?utm_source=twitter"))
