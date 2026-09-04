"""JudicialCommentBot application entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from app.bot.middlewares import AccessMiddleware
from app.bot.routers import admin_router, start_router, subjects_router
from app.core.logging_config import setup_logging
from app.core.settings import get_settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.services import AccessService

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)

    database = Database(settings.database_url)
    await database.initialize()

    subject_loader = SubjectLoader()
    subject_loader.validate_all()
    logger.info("Loaded %d subject knowledge files", len(subject_loader.list_subjects()))

    access_service = AccessService(settings.owner_telegram_id, database)
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    dispatcher = Dispatcher()

    dispatcher["access_service"] = access_service
    dispatcher["subject_loader"] = subject_loader
    dispatcher["settings"] = settings

    dispatcher.message.outer_middleware(AccessMiddleware())
    dispatcher.callback_query.outer_middleware(AccessMiddleware())

    dispatcher.include_router(admin_router)
    dispatcher.include_router(start_router)
    dispatcher.include_router(subjects_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Starting Telegram polling")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
