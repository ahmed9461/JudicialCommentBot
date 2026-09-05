"""JudicialCommentBot application entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from app.bot.middlewares import AccessMiddleware
from app.bot.routers import admin_router, start_router, subjects_router
from app.catalog import (
    CATALOG_PARSER_VERSION,
    CatalogFirstResearchProvider,
    CatalogResearchProvider,
    CatalogStore,
)
from app.commentary import DeepSeekCommentaryGenerator, DocxRenderer
from app.core.logging_config import setup_logging
from app.core.settings import get_settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.pdf import PdfAcquisitionService
from app.ranking import ScoringPolicy
from app.research import DeepSeekResearchProvider, RobustResearchProvider
from app.services import (
    AccessService, AssignmentService, CaseWorkflowService, cleanup_stale_files,
)
from app.sources import SourceRegistry

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)
    removed = cleanup_stale_files(
        settings.temp_dir,
        max_age_hours=settings.stale_temp_max_age_hours,
    )
    if removed:
        logger.info("Removed %d stale temporary files", removed)

    database = Database(settings.database_url)
    await database.initialize()
    subject_loader = SubjectLoader()
    subject_loader.validate_all()
    source_registry = SourceRegistry()
    access_service = AccessService(settings.owner_telegram_id, database)
    catalog_store = CatalogStore(database)

    pdf_service = PdfAcquisitionService(
        source_registry=source_registry,
        temp_dir=settings.temp_dir,
        max_bytes=settings.pdf_max_bytes,
        max_pages=settings.pdf_max_pages,
        timeout_seconds=settings.pdf_download_timeout_seconds,
        connect_timeout_seconds=settings.pdf_connect_timeout_seconds,
        max_redirects=settings.pdf_max_redirects,
    )

    # Web research is intentionally optional. The primary path for all 34
    # subjects is the reusable local catalog built from official collections.
    web_fallback = None
    assignment_service = None
    if settings.deepseek_api_key and settings.deepseek_api_key.get_secret_value().strip():
        api_key = settings.deepseek_api_key.get_secret_value()
        deepseek_research = DeepSeekResearchProvider(
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_research_model,
            timeout_seconds=settings.deepseek_stream_idle_timeout_seconds,
            connect_timeout_seconds=settings.deepseek_connect_timeout_seconds,
            request_attempts=settings.deepseek_research_attempts,
            synthesis_attempts=settings.deepseek_synthesis_attempts,
            max_search_calls_for_synthesis=settings.deepseek_max_search_calls_for_synthesis,
            discovery_reasoning_effort=settings.deepseek_research_reasoning_effort,
            synthesis_reasoning_effort=settings.deepseek_synthesis_reasoning_effort,
        )
        web_fallback = RobustResearchProvider(
            inner=deepseek_research,
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_research_model,
            preflight_ttl_seconds=settings.deepseek_preflight_ttl_seconds,
        )
        commentary_generator = DeepSeekCommentaryGenerator(
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_commentary_model,
            timeout_seconds=settings.deepseek_commentary_idle_timeout_seconds,
            connect_timeout_seconds=settings.deepseek_connect_timeout_seconds,
            reasoning_effort=settings.deepseek_commentary_reasoning_effort,
        )
        assignment_service = AssignmentService(
            generator=commentary_generator,
            renderer=DocxRenderer(),
            temp_dir=settings.temp_dir,
            validation_attempts=settings.commentary_validation_attempts,
        )

    catalog_provider = CatalogResearchProvider(catalog_store)
    if settings.catalog_enabled:
        research_provider = CatalogFirstResearchProvider(
            catalog=catalog_provider,
            fallback=web_fallback,
            min_catalog_candidates=settings.catalog_min_candidates_before_fallback,
            fallback_enabled=settings.catalog_fallback_to_web,
        )
    else:
        research_provider = web_fallback

    workflow_service = None
    if research_provider is not None:
        workflow_service = CaseWorkflowService(
            database=database,
            subject_loader=subject_loader,
            research_provider=research_provider,
            source_registry=source_registry,
            pdf_service=pdf_service,
            scoring=ScoringPolicy(),
            settings=settings,
        )

    stats = await catalog_store.stats(parser_version=CATALOG_PARSER_VERSION)
    logger.info(
        "Verified official catalog generation=v%d cases=%d collections=%d sources=%d catalog_enabled=%s web_fallback=%s",
        CATALOG_PARSER_VERSION,
        stats.cases,
        stats.collections,
        stats.sources,
        settings.catalog_enabled,
        web_fallback is not None and settings.catalog_fallback_to_web,
    )

    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher["access_service"] = access_service
    dispatcher["subject_loader"] = subject_loader
    dispatcher["source_registry"] = source_registry
    dispatcher["catalog_store"] = catalog_store
    dispatcher["research_provider"] = research_provider
    dispatcher["workflow_service"] = workflow_service
    dispatcher["assignment_service"] = assignment_service
    dispatcher["database"] = database
    dispatcher["settings"] = settings

    dispatcher.message.outer_middleware(AccessMiddleware())
    dispatcher.callback_query.outer_middleware(AccessMiddleware())
    dispatcher.include_router(admin_router)
    dispatcher.include_router(start_router)
    dispatcher.include_router(subjects_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info(
            "Starting Telegram polling with %d subjects",
            len(subject_loader.list_subjects()),
        )
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
