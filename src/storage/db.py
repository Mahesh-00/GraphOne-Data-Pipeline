
"""
Storage layer.

Demo uses SQLite (via aiosqlite) so the pipeline runs with zero external
infra. Swap DATABASE_URL to a Postgres DSN in production -- SQLAlchemy's
async engine makes this a one-line config change.

Research papers use the arXiv ID as their unique identifier so that the
same paper is not stored multiple times.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from src.pipeline.freshness import normalize_url
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    delete,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from src.config import DATABASE_URL


Base = declarative_base()


class RawDocumentRow(Base):
    __tablename__ = "raw_documents"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    source_name = Column(
        String,
        index=True,
    )

    source_url = Column(
        String,
        index=True,
        unique=False,
    )

    url_hash = Column(
        String,
        index=True,
    )

    content = Column(Text)

    content_type = Column(String)

    fetched_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )


class StructuredRecordRow(Base):
    __tablename__ = "structured_records"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    record_type = Column(
        String,
        index=True,
    )

    schema_version = Column(String)

    source_name = Column(String)

    source_url = Column(String)

    raw_document_id = Column(
        Integer,
        ForeignKey("raw_documents.id"),
        nullable=True,
    )

    payload_json = Column(Text)

    llm_provider_used = Column(
        String,
        nullable=True,
    )

    collected_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )


class DeadLetterRow(Base):
    __tablename__ = "dead_letter_items"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    record_type = Column(String)

    source_url = Column(String)

    content_snippet = Column(Text)

    error = Column(Text)

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )


class Storage:

    def __init__(
        self,
        database_url: str = DATABASE_URL,
    ):
        self.engine = create_async_engine(
            database_url,
            echo=False,
        )

        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def init_models(self) -> None:
        """
        Create database tables if they do not already exist.
        """

        async with self.engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all
            )

    async def save_raw_document(
        self,
        source_name: str,
        source_url: str,
        url_hash: str,
        content: str,
        content_type: str,
    ) -> int:

        async with self.session_factory() as session:

            existing = await session.execute(
                select(RawDocumentRow).where(
                    RawDocumentRow.url_hash == url_hash
                )
            )
            existing_row = existing.scalars().first()
            if existing_row is not None:
                return existing_row.id

            row = RawDocumentRow(
                source_name=source_name,
                source_url=source_url,
                url_hash=url_hash,
                content=content,
                content_type=content_type,
            )

            session.add(row)

            await session.commit()

            await session.refresh(row)

            return row.id

    async def source_url_exists(
        self,
        record_type: str,
        source_url: str,
    ) -> bool:
        if not source_url or not source_url.strip():
            return False

        try:
            normalized_candidate = normalize_url(source_url)
        except Exception:
            return False

        async with self.session_factory() as session:

            result = await session.execute(
                select(StructuredRecordRow.source_url).where(
                    StructuredRecordRow.record_type == record_type,
                    StructuredRecordRow.source_url.is_not(None),
                )
            )

            for existing_url in result.scalars().all():
                if not existing_url:
                    continue

                try:
                    if normalize_url(existing_url) == normalized_candidate:
                        return True
                except Exception:
                    continue

            return False

    async def save_structured_record(
        self,
        record_type: str,
        schema_version: str,
        source_name: str,
        source_url: str,
        payload: dict[str, Any],
        raw_document_id: Optional[int] = None,
        llm_provider_used: Optional[str] = None,
    ) -> int:

        if record_type is None or schema_version is None or payload is None:
            raise ValueError("record_type, schema_version, and payload are required")

        if source_name is None:
            source_name = ""

        if source_url is None:
            source_url = ""

        async with self.session_factory() as session:

            row = StructuredRecordRow(
                record_type=record_type,
                schema_version=schema_version,
                source_name=source_name,
                source_url=source_url,
                raw_document_id=raw_document_id,
                payload_json=json.dumps(
                    payload,
                    default=str,
                ),
                llm_provider_used=llm_provider_used,
            )

            session.add(row)

            await session.commit()

            await session.refresh(row)

            return row.id

    async def save_dead_letter(
        self,
        record_type: str,
        source_url: str,
        content_snippet: str,
        error: str,
    ) -> None:

        async with self.session_factory() as session:

            session.add(
                DeadLetterRow(
                    record_type=record_type,
                    source_url=source_url,
                    content_snippet=content_snippet,
                    error=error,
                )
            )

            await session.commit()

    async def fetch_all(
        self,
        record_type: str,
    ) -> list[dict[str, Any]]:

        async with self.session_factory() as session:

            result = await session.execute(
                select(StructuredRecordRow)
                .where(
                    StructuredRecordRow.record_type
                    == record_type
                )
                .order_by(
                    StructuredRecordRow.id.asc()
                )
            )

            rows = result.scalars().all()

            out = []

            for row in rows:

                try:
                    payload = json.loads(
                        row.payload_json
                    )

                except (
                    json.JSONDecodeError,
                    TypeError,
                ):
                    payload = {}

                payload["_record_id"] = row.id
                payload["record_type"] = row.record_type
                payload["schemaVersion"] = row.schema_version
                payload["source_name"] = row.source_name
                payload["source_url"] = row.source_url
                payload["raw_document_id"] = row.raw_document_id
                payload["_source_name"] = row.source_name
                payload["_source_url"] = row.source_url
                payload["_collected_at"] = (
                    row.collected_at.isoformat()
                    if row.collected_at
                    else None
                )

                out.append(payload)

            return out

    # ---------------------------------------------------------
    # arXiv helpers
    # ---------------------------------------------------------

    @staticmethod
    def extract_arxiv_id(
        value: Optional[str],
    ) -> Optional[str]:
        """
        Extract the canonical arXiv ID from different URL formats.

        Examples:

        http://arxiv.org/abs/2608.09928v1
        https://arxiv.org/abs/2608.09928
        http://export.arxiv.org/abs/2608.09928v1

        All become:

        2608.09928
        """

        if not value:
            return None

        value = value.strip()

        match = re.search(
            r"arxiv\.org/(?:abs|pdf)/"
            r"([A-Za-z0-9.\-]+)"
            r"(?:v\d+)?",
            value,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

        # Also support a plain arXiv ID.
        plain_match = re.fullmatch(
            r"([A-Za-z0-9.\-]+)(?:v\d+)?",
            value,
        )

        if plain_match:
            return plain_match.group(1)

        return None

    async def find_existing_arxiv_ids(
        self,
    ) -> set[str]:
        """
        Return all arXiv IDs currently stored in the
        RESEARCH_PAPER records.
        """

        async with self.session_factory() as session:

            result = await session.execute(
                select(StructuredRecordRow)
                .where(
                    StructuredRecordRow.record_type
                    == "RESEARCH_PAPER"
                )
            )

            rows = result.scalars().all()

            arxiv_ids: set[str] = set()

            for row in rows:

                arxiv_id = self.extract_arxiv_id(
                    row.source_url
                )

                if arxiv_id:
                    arxiv_ids.add(arxiv_id)
                    continue

                try:
                    payload = json.loads(
                        row.payload_json
                    )

                except (
                    json.JSONDecodeError,
                    TypeError,
                ):
                    continue

                paper_url = payload.get(
                    "paper_url"
                )

                arxiv_id = self.extract_arxiv_id(
                    paper_url
                )

                if arxiv_id:
                    arxiv_ids.add(arxiv_id)

            return arxiv_ids

    async def delete_duplicate_research_papers(
        self,
    ) -> dict[str, int]:
        """
        Remove duplicate RESEARCH_PAPER records.

        The first occurrence of each arXiv ID is kept.
        Later occurrences are deleted.

        Returns statistics:

        {
            "before": ...,
            "after": ...,
            "deleted": ...
        }
        """

        async with self.session_factory() as session:

            result = await session.execute(
                select(StructuredRecordRow)
                .where(
                    StructuredRecordRow.record_type
                    == "RESEARCH_PAPER"
                )
                .order_by(
                    StructuredRecordRow.id.asc()
                )
            )

            rows = result.scalars().all()

            before = len(rows)

            seen_ids: set[str] = set()

            duplicate_row_ids: list[int] = []

            for row in rows:

                arxiv_id = self.extract_arxiv_id(
                    row.source_url
                )

                if not arxiv_id:

                    try:
                        payload = json.loads(
                            row.payload_json
                        )

                    except (
                        json.JSONDecodeError,
                        TypeError,
                    ):
                        payload = {}

                    arxiv_id = (
                        self.extract_arxiv_id(
                            payload.get(
                                "paper_url"
                            )
                        )
                    )

                # If we cannot identify the paper,
                # don't delete it automatically.
                if not arxiv_id:
                    continue

                if arxiv_id in seen_ids:

                    duplicate_row_ids.append(
                        row.id
                    )

                else:

                    seen_ids.add(arxiv_id)

            if duplicate_row_ids:

                await session.execute(
                    delete(
                        StructuredRecordRow
                    ).where(
                        StructuredRecordRow.id.in_(
                            duplicate_row_ids
                        )
                    )
                )

                await session.commit()

            after = before - len(
                duplicate_row_ids
            )

            return {
                "before": before,
                "after": after,
                "deleted": len(
                    duplicate_row_ids
                ),
            }

    async def close(self) -> None:
        await self.engine.dispose()
