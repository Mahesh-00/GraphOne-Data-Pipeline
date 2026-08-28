import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.storage.db import RawDocumentRow, Storage


@pytest.fixture
def test_storage(tmp_path):
    db_path = tmp_path / "graphone_test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    storage = Storage(database_url=database_url)
    asyncio.run(storage.init_models())
    yield storage
    asyncio.run(storage.close())


def test_save_raw_document_handles_duplicate_url_hashes(test_storage):
    first_id = asyncio.run(
        test_storage.save_raw_document(
            source_name="Arxiv",
            source_url="https://export.arxiv.org/api/query?search_query=cat:cs.AI&start=0",
            url_hash="duplicate-hash",
            content="<xml>first</xml>",
            content_type="xml",
        )
    )

    # Simulate legacy duplicate rows with the same url_hash.
    async def insert_duplicate():
        async with test_storage.session_factory() as session:
            duplicate_row = RawDocumentRow(
                source_name="Arxiv",
                source_url="https://export.arxiv.org/api/query?search_query=cat:cs.AI&start=50",
                url_hash="duplicate-hash",
                content="<xml>second</xml>",
                content_type="xml",
            )
            session.add(duplicate_row)
            await session.commit()
            await session.refresh(duplicate_row)
            return duplicate_row.id

    second_id = asyncio.run(insert_duplicate())

    existing_id = asyncio.run(
        test_storage.save_raw_document(
            source_name="Arxiv",
            source_url="https://export.arxiv.org/api/query?search_query=cat:cs.AI&start=100",
            url_hash="duplicate-hash",
            content="<xml>third</xml>",
            content_type="xml",
        )
    )

    assert existing_id == first_id
    assert existing_id != second_id
