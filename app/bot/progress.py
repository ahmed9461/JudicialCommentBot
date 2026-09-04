"""Live Telegram progress updates for long-running workflows."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

logger = logging.getLogger(__name__)


def format_progress_text(phase: str, elapsed_seconds: int, interval_seconds: float = 3.0) -> str:
    interval = max(1, int(round(interval_seconds)))
    return (
        f"{phase}\n\n"
        f"⏱️ الوقت المنقضي: {max(0, elapsed_seconds)} ثانية\n"
        f"🔄 يتم تحديث الحالة كل {interval} ثوانٍ"
    )


class StatusTicker:
    """Edit one Telegram message every few seconds while the workflow is running."""

    def __init__(self, message: Any, *, initial_phase: str, interval_seconds: float = 3.0) -> None:
        self.message = message
        self.phase = initial_phase
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.started_at = time.monotonic()
        self._task: asyncio.Task[None] | None = None
        self._last_text: str | None = None
        self._stopped = False

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._render()
        self._task = asyncio.create_task(self._loop(), name="telegram-status-ticker")

    async def set_phase(self, phase: str, *, immediate: bool = False) -> None:
        self.phase = phase
        if immediate and not self._stopped:
            await self._render()

    async def stop(self, final_text: str | None = None) -> None:
        if self._stopped:
            return
        self._stopped = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if final_text:
            await self._safe_edit(final_text)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self._render()

    async def _render(self) -> None:
        elapsed = int(time.monotonic() - self.started_at)
        text = format_progress_text(self.phase, elapsed, self.interval_seconds)
        if text == self._last_text:
            return
        await self._safe_edit(text)
        self._last_text = text

    async def _safe_edit(self, text: str) -> None:
        try:
            await self.message.edit_text(text, disable_web_page_preview=True)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.debug("Progress message edit rejected: %s", exc)
        except TelegramAPIError as exc:
            logger.debug("Progress message edit failed: %s", exc)
