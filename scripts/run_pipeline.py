"""
CLI entrypoint.

Usage:
    python scripts/run_pipeline.py --vertical papers --target 1000
    python scripts/run_pipeline.py --vertical all --target 1000 --export-sheets
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.orchestrator import LLMOrchestrator
from src.pipeline.freshness import InMemorySeenStore
from src.pipeline.ingest import run_papers_pipeline
from src.resolution.resolver import EntityResolver
from src.storage.db import Storage
from src.exporters.google_sheets_exporter import GoogleSheetsExporter
from src.utils.logging_config import get_logger, log_ctx
from src.pipeline.ingest import (
    run_startups_pipeline,
    run_products_pipeline,
    run_jobs_pipeline,
    run_news_pipeline,
)

logger = get_logger("run_pipeline")


async def _export_vertical_records(storage: Storage, record_type: str, worksheet_name: str) -> None:
    if not getattr(storage, "engine", None):
        return

    try:
        exporter = GoogleSheetsExporter()
        await exporter.export_records(record_type=record_type, worksheet_name=worksheet_name, storage=storage)
    except Exception as exc:
        log_ctx(
            logger,
            40,
            "google_sheets_export_failed",
            worksheet=worksheet_name,
            error=str(exc),
        )


async def _export_entity_mapping_log() -> None:
    try:
        exporter = GoogleSheetsExporter()
        await exporter.export_entity_mapping_log()
    except Exception as exc:
        log_ctx(
            logger,
            40,
            "google_sheets_mapping_log_export_failed",
            error=str(exc),
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="GraphOne / FrontierAtlas ingestion pipeline")
    parser.add_argument("--vertical", choices=["papers", "startups", "products", "news", "jobs", "all"], default="papers")
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--export-sheets", action="store_true")
    args = parser.parse_args()

    storage = Storage()
    await storage.init_models()

    if args.vertical in ("papers", "all"):
        try:
            records = await run_papers_pipeline(storage, target=args.target)
            log_ctx(logger, 20, "papers_done", count=len(records))
        except Exception as exc:
            log_ctx(logger, 40, "papers_pipeline_failed", error=str(exc))
        if args.export_sheets:
            await _export_vertical_records(storage, "RESEARCH_PAPER", "Research Papers")

    if args.vertical in ("startups", "all"):
        try:
            records = await run_startups_pipeline(storage, target=args.target)
            log_ctx(logger, 20, "startups_done", count=len(records))
        except Exception as exc:
            log_ctx(logger, 40, "startups_pipeline_failed", error=str(exc))
        if args.export_sheets:
            await _export_vertical_records(storage, "STARTUP", "Startups")

    if args.vertical in ("products", "all"):
        try:
            records = await run_products_pipeline(storage, target=args.target)
            log_ctx(logger, 20, "products_done", count=len(records))
        except Exception as exc:
            log_ctx(logger, 40, "products_pipeline_failed", error=str(exc))
        if args.export_sheets:
            await _export_vertical_records(storage, "PRODUCT", "Products")

    if args.vertical in ("jobs", "all"):
        try:
            records = await run_jobs_pipeline(storage, target=args.target)
            log_ctx(logger, 20, "jobs_done", count=len(records))
        except Exception as exc:
            log_ctx(logger, 40, "jobs_pipeline_failed", error=str(exc))
        if args.export_sheets:
            await _export_vertical_records(storage, "JOB", "Jobs")

    if args.vertical in ("news", "all"):
        try:
            records = await run_news_pipeline(storage, target=args.target)
            log_ctx(logger, 20, "news_done", count=len(records))
        except Exception as exc:
            log_ctx(logger, 40, "news_pipeline_failed", error=str(exc))
        if args.export_sheets:
            await _export_vertical_records(storage, "NEWS", "News")

    if args.export_sheets:
        await _export_entity_mapping_log()

    # startups / products / news / jobs follow the same pattern -- wired up
    # in src/pipeline/ingest.py's run_extraction_for_directory_records and
    # run_freshness_filtered_pipeline. Left as explicit CLI branches so each
    # vertical can be run/debugged independently during development:
    #
    # if args.vertical in ("startups", "all"):
    #     ...instantiate DirectoryScraper(startup source config)...
    #     records = await run_extraction_for_directory_records(...)
    #
    # if args.vertical in ("news", "all"):
    #     ...instantiate NewsListingScraper + ArticleFetcher per NEWS_SOURCES...
    #     records = await run_freshness_filtered_pipeline(...)

    await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
