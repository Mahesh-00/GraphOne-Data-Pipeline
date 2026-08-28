import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.orchestrator import ExtractionResult
from src.pipeline.ingest import run_extraction_for_directory_records
from src.resolution.resolver import EntityResolver
from src.storage.db import Storage


def _make_storage(tmp_path):
    db_path = tmp_path / "graphone_startup_test.db"
    storage = Storage(database_url=f"sqlite+aiosqlite:///{db_path}")
    asyncio.run(storage.init_models())
    return storage


class FakeLLM:
    def __init__(self, payloads=None, fail_for=None):
        self.payloads = payloads or {}
        self.fail_for = fail_for or set()
        self.calls = []

    async def extract(self, record_type, source_url, title, body):
        self.calls.append({
            "record_type": record_type,
            "source_url": source_url,
            "title": title,
            "body": body,
        })
        if source_url in self.fail_for:
            return ExtractionResult(success=False, provider_used="mock", data=None, error="429")
        payload = self.payloads.get(source_url)
        if payload is not None:
            return ExtractionResult(success=True, provider_used="mock", data=payload)
        return ExtractionResult(success=True, provider_used="mock", data={"entityName": title, "employeeCount": None, "description": ""})


def test_new_startup_record_is_saved_and_returned(tmp_path):
    storage = _make_storage(tmp_path)
    llm = FakeLLM({
        "https://www.ycombinator.com/companies/airbnb": {
            "entityName": "Airbnb",
            "employeeCount": None,
            "description": "",
        }
    })

    try:
        results = asyncio.run(
            run_extraction_for_directory_records(
                storage=storage,
                llm=llm,
                resolver=EntityResolver(),
                record_type="STARTUP",
                raw_candidates=[{
                    "raw_name": "Airbnb",
                    "detail_url": "https://www.ycombinator.com/companies/airbnb",
                    "_source_name": "YCombinator",
                    "_source_url": "https://www.ycombinator.com/companies",
                    "_raw_document_id": None,
                }],
                target=10,
            )
        )
        assert len(results) == 1
        assert results[0]["entityName"] == "Airbnb"
        persisted = asyncio.run(storage.fetch_all("STARTUP"))
        assert len(persisted) == 1
        assert persisted[0]["source_url"] == "https://www.ycombinator.com/companies/airbnb"
    finally:
        asyncio.run(storage.close())


def test_existing_duplicate_startup_is_skipped(tmp_path):
    storage = _make_storage(tmp_path)
    asyncio.run(
        storage.save_structured_record(
            record_type="STARTUP",
            schema_version="1.0",
            source_name="YCombinator",
            source_url="https://www.ycombinator.com/companies/airbnb",
            payload={"entityName": "Airbnb", "employeeCount": None, "description": ""},
        )
    )
    llm = FakeLLM({
        "https://www.ycombinator.com/companies/airbnb": {
            "entityName": "Airbnb",
            "employeeCount": None,
            "description": "",
        }
    })

    try:
        results = asyncio.run(
            run_extraction_for_directory_records(
                storage=storage,
                llm=llm,
                resolver=EntityResolver(),
                record_type="STARTUP",
                raw_candidates=[{
                    "raw_name": "Airbnb",
                    "detail_url": "https://www.ycombinator.com/companies/airbnb",
                    "_source_name": "YCombinator",
                    "_source_url": "https://www.ycombinator.com/companies",
                    "_raw_document_id": None,
                }],
                target=10,
            )
        )
        assert results == []
    finally:
        asyncio.run(storage.close())


def test_multiple_startup_records_return_correctly(tmp_path):
    storage = _make_storage(tmp_path)
    llm = FakeLLM({
        "https://www.ycombinator.com/companies/airbnb": {"entityName": "Airbnb", "employeeCount": None, "description": ""},
        "https://www.ycombinator.com/companies/dropbox": {"entityName": "Dropbox", "employeeCount": None, "description": ""},
        "https://www.ycombinator.com/companies/doordash": {"entityName": "DoorDash", "employeeCount": None, "description": ""},
    })

    try:
        results = asyncio.run(
            run_extraction_for_directory_records(
                storage=storage,
                llm=llm,
                resolver=EntityResolver(),
                record_type="STARTUP",
                raw_candidates=[
                    {"raw_name": "Airbnb", "detail_url": "https://www.ycombinator.com/companies/airbnb", "_source_name": "YCombinator", "_source_url": "https://www.ycombinator.com/companies", "_raw_document_id": None},
                    {"raw_name": "Dropbox", "detail_url": "https://www.ycombinator.com/companies/dropbox", "_source_name": "YCombinator", "_source_url": "https://www.ycombinator.com/companies", "_raw_document_id": None},
                    {"raw_name": "DoorDash", "detail_url": "https://www.ycombinator.com/companies/doordash", "_source_name": "YCombinator", "_source_url": "https://www.ycombinator.com/companies", "_raw_document_id": None},
                ],
                target=10,
            )
        )
        assert [r["entityName"] for r in results] == ["Airbnb", "Dropbox", "Doordash"]
    finally:
        asyncio.run(storage.close())


def test_llm_fallback_uses_company_name_from_url_when_llm_429(tmp_path):
    storage = _make_storage(tmp_path)
    llm = FakeLLM(fail_for={"https://www.ycombinator.com/companies/doordash"})

    try:
        results = asyncio.run(
            run_extraction_for_directory_records(
                storage=storage,
                llm=llm,
                resolver=EntityResolver(),
                record_type="STARTUP",
                raw_candidates=[{
                    "raw_name": "Winter 2015",
                    "detail_url": "https://www.ycombinator.com/companies/doordash",
                    "_source_name": "YCombinator",
                    "_source_url": "https://www.ycombinator.com/companies",
                    "_raw_document_id": None,
                }],
                target=10,
            )
        )
        assert len(results) == 1
        assert results[0]["entityName"] == "Doordash"
        assert results[0]["entityName"] != "Winter 2015"
        assert results[0]["source_url"] == "https://www.ycombinator.com/companies/doordash"
    finally:
        asyncio.run(storage.close())


def test_target_ten_does_not_incorrectly_return_zero(tmp_path):
    storage = _make_storage(tmp_path)
    llm = FakeLLM({
        f"https://www.ycombinator.com/companies/{slug}": {"entityName": slug.title(), "employeeCount": None, "description": ""}
        for slug in [
            "airbnb", "doordash", "dropbox", "coinbase", "gitlab",
            "matterport", "meesho", "oklo", "groww", "billiontoone",
            "techstars", "notion",
        ]
    })

    try:
        raw_candidates = [
            {"raw_name": name.title(), "detail_url": f"https://www.ycombinator.com/companies/{slug}", "_source_name": "YCombinator", "_source_url": "https://www.ycombinator.com/companies", "_raw_document_id": None}
            for slug, name in [
                ("airbnb", "Airbnb"), ("doordash", "DoorDash"), ("dropbox", "Dropbox"), ("coinbase", "Coinbase"), ("gitlab", "GitLab"),
                ("matterport", "Matterport"), ("meesho", "Meesho"), ("oklo", "Oklo"), ("groww", "Groww"), ("billiontoone", "BillionToOne"),
                ("techstars", "Techstars"), ("notion", "Notion"),
            ]
        ]
        results = asyncio.run(
            run_extraction_for_directory_records(
                storage=storage,
                llm=llm,
                resolver=EntityResolver(),
                record_type="STARTUP",
                raw_candidates=raw_candidates,
                target=10,
            )
        )
        assert len(results) == 10
        assert all(item["source_url"].startswith("https://www.ycombinator.com/companies/") for item in results)
    finally:
        asyncio.run(storage.close())
