"""CLI for building and inspecting the official judicial catalog.

Examples:
    python -m app.catalog stats
    python -m app.catalog coverage
    python -m app.catalog refresh
    python -m app.catalog refresh --source moj_1435 --max-documents 2
    python -m app.catalog refresh --force
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.logging_config import setup_logging
from app.core.settings import get_settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.pdf import PdfAcquisitionService
from app.sources import SourceRegistry

from .errors import CatalogNotReadyError
from .indexer import OfficialCatalogIndexer
from .manifest import CatalogManifestLoader
from .provider import CatalogResearchProvider
from .store import CatalogStore


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    database = Database(settings.database_url)
    await database.initialize()
    store = CatalogStore(database)

    if args.command == "stats":
        stats = await store.stats()
        print(f"cases={stats.cases} collections={stats.collections} sources={stats.sources}")
        return 0

    if args.command == "coverage":
        stats = await store.stats()
        if stats.cases == 0:
            print("catalog_not_ready cases=0; run: python -m app.catalog refresh")
            return 2
        loader = SubjectLoader()
        provider = CatalogResearchProvider(store)
        minimum = max(1, int(args.minimum))
        missing = 0
        thin = 0
        for subject in loader.list_subjects():
            try:
                candidates = await provider.search_cases(
                    loader.get_subject(subject.slug),
                    excluded_cases=[],
                    limit=max(minimum, 5),
                )
            except CatalogNotReadyError:
                candidates = []
            count = len(candidates)
            status = "ready" if count >= minimum else ("thin" if count else "missing")
            if status == "missing":
                missing += 1
            elif status == "thin":
                thin += 1
            print(f"{status}\t{count}\t{subject.slug}\t{subject.name_ar}")
        print(
            f"coverage_summary subjects={len(loader.list_subjects())} "
            f"minimum={minimum} missing={missing} thin={thin}"
        )
        return 1 if missing else 0

    manifest = CatalogManifestLoader(Path(settings.catalog_manifest_path)).load()
    source_registry = SourceRegistry()
    pdf_service = PdfAcquisitionService(
        source_registry=source_registry,
        temp_dir=settings.temp_dir,
        max_bytes=settings.pdf_max_bytes,
        max_pages=settings.pdf_max_pages,
        timeout_seconds=settings.pdf_download_timeout_seconds,
        connect_timeout_seconds=settings.pdf_connect_timeout_seconds,
        max_redirects=settings.pdf_max_redirects,
    )
    indexer = OfficialCatalogIndexer(
        store=store,
        manifest=manifest,
        source_registry=source_registry,
        pdf_service=pdf_service,
    )
    report = await indexer.refresh(
        source_filter=set(args.source or []) or None,
        max_documents=args.max_documents,
        force=args.force,
    )
    stats = await store.stats()
    print(
        "refresh_complete "
        f"documents_seen={report.documents_seen} "
        f"documents_indexed={report.documents_indexed} "
        f"documents_skipped={report.documents_skipped} "
        f"documents_failed={report.documents_failed} "
        f"cases_indexed={report.cases_indexed} "
        f"catalog_cases={stats.cases}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Official judicial catalog maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats")
    coverage = sub.add_parser("coverage")
    coverage.add_argument(
        "--minimum",
        type=int,
        default=3,
        help="Minimum local candidates required for a course to be marked ready",
    )
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--source", action="append", help="Manifest source id; may be repeated")
    refresh.add_argument("--max-documents", type=int, default=None)
    refresh.add_argument("--force", action="store_true", help="Re-index documents already present in the catalog")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
