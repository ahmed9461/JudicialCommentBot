"""CLI for building and inspecting the official judicial catalog.

A full refresh is blue/green: build -> deterministic quality gate -> atomic
promotion.  The active generation is never mutated in place.
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
from .indexer import CATALOG_PARSER_VERSION, OfficialCatalogIndexer
from .manifest import CatalogManifestLoader
from .provider import CatalogResearchProvider
from .quality import evaluate_generation
from .store import CatalogStore


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    database = Database(settings.database_url)
    await database.initialize()
    store = CatalogStore(database)

    if args.command == "stats":
        active = await store.active_generation_state()
        latest = await store.latest_generation_state(CATALOG_PARSER_VERSION)
        if active is None:
            print(
                f"parser_version={CATALOG_PARSER_VERSION} active_generation=none "
                f"latest_generation={(latest.generation_id if latest else 'none')} "
                f"latest_status={(latest.status if latest else 'none')}"
            )
            return 2
        stats = await store.stats(generation_id=active.generation_id)
        print(
            f"parser_version={CATALOG_PARSER_VERSION} "
            f"active_generation={active.generation_id} active_parser={active.parser_version} "
            f"active_ready={str(active.is_ready and active.parser_version == CATALOG_PARSER_VERSION).lower()} "
            f"cases={stats.cases} collections={stats.collections} sources={stats.sources} "
            f"coverage={active.covered_subjects}/{active.total_subjects} "
            f"latest_generation={(latest.generation_id if latest else 'none')} "
            f"latest_status={(latest.status if latest else 'none')}"
        )
        return 0 if active.is_ready and active.parser_version == CATALOG_PARSER_VERSION else 2

    if args.command == "coverage":
        active = await store.active_generation_state()
        if active is None or not active.is_ready or active.parser_version != CATALOG_PARSER_VERSION:
            latest = await store.latest_generation_state(CATALOG_PARSER_VERSION)
            print(
                f"catalog_not_ready parser_version={CATALOG_PARSER_VERSION} "
                f"latest_status={(latest.status if latest else 'none')}"
            )
            return 2
        loader = SubjectLoader()
        provider = CatalogResearchProvider(store)
        minimum = max(1, int(args.minimum))
        missing = 0
        thin = 0
        for item in loader.list_subjects():
            try:
                candidates = await provider.search_generation_cases(
                    loader.get_subject(item.slug),
                    generation_id=active.generation_id or "",
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
            print(f"{status}\t{count}\t{item.slug}\t{item.name_ar}")
        print(
            f"coverage_summary generation={active.generation_id} parser_version={CATALOG_PARSER_VERSION} "
            f"subjects={len(loader.list_subjects())} minimum={minimum} missing={missing} thin={thin}"
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

    if not report.full_refresh:
        stats = await store.stats(generation_id=report.generation_id)
        print(
            "refresh_diagnostic_complete "
            f"generation={report.generation_id} parser_version={CATALOG_PARSER_VERSION} "
            f"documents_seen={report.documents_seen} documents_indexed={report.documents_indexed} "
            f"documents_failed={report.documents_failed} cases={stats.cases} activated=false"
        )
        return 0

    subject_loader = SubjectLoader()
    provider = CatalogResearchProvider(store)
    quality = await evaluate_generation(
        store=store,
        provider=provider,
        subject_loader=subject_loader,
        generation_id=report.generation_id,
        documents_seen=report.documents_seen,
        documents_failed=report.documents_failed,
        min_cases=settings.catalog_min_cases_for_activation,
        min_candidates_per_subject=settings.catalog_min_candidates_per_subject,
        required_subject_coverage_percent=settings.catalog_required_subject_coverage_percent,
        max_document_failure_ratio=settings.catalog_max_document_failure_ratio,
    )

    if not quality.passed:
        await store.update_generation_result(
            report.generation_id,
            status="failed",
            documents_seen=report.documents_seen,
            documents_indexed=report.documents_indexed,
            documents_failed=report.documents_failed,
            cases_indexed=report.cases_indexed,
            covered_subjects=quality.covered_subjects,
            total_subjects=quality.total_subjects,
            error=quality.reason,
        )
        await store.cleanup_inactive_generations(keep=settings.catalog_keep_inactive_generations)
        print(
            "refresh_rejected "
            f"generation={report.generation_id} parser_version={CATALOG_PARSER_VERSION} "
            f"cases={quality.cases} collections={quality.collections} sources={quality.sources} "
            f"coverage={quality.covered_subjects}/{quality.total_subjects} "
            f"failure_ratio={quality.failure_ratio:.4f} "
            f"missing_subjects={','.join(quality.missing_subjects) or '-'} "
            f"reason={quality.reason}"
        )
        return 2

    await store.promote_generation(
        report.generation_id,
        documents_seen=report.documents_seen,
        documents_indexed=report.documents_indexed,
        documents_failed=report.documents_failed,
        cases_indexed=report.cases_indexed,
        covered_subjects=quality.covered_subjects,
        total_subjects=quality.total_subjects,
    )
    await store.cleanup_inactive_generations(keep=settings.catalog_keep_inactive_generations)
    print(
        "refresh_complete "
        f"generation={report.generation_id} parser_version={CATALOG_PARSER_VERSION} activated=true "
        f"documents_seen={report.documents_seen} documents_indexed={report.documents_indexed} "
        f"documents_failed={report.documents_failed} cases={quality.cases} "
        f"collections={quality.collections} sources={quality.sources} "
        f"coverage={quality.covered_subjects}/{quality.total_subjects}"
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
    refresh.add_argument("--force", action="store_true", help="Compatibility flag; generations are always rebuilt")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
