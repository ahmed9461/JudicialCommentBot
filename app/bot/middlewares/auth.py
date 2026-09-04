"""Reject Telegram users outside the owner/allowlist boundary."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.core.constants import UNAUTHORIZED_MESSAGE
from app.services import AccessService


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        access_service: AccessService = data["access_service"]
        if await access_service.is_allowed(user.id):
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(UNAUTHORIZED_MESSAGE)
        elif isinstance(event, CallbackQuery):
            await event.answer(UNAUTHORIZED_MESSAGE, show_alert=True)
        return None
