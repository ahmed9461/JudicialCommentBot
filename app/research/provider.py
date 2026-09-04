"""Research provider contract."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.knowledge import SubjectProfile

from .models import CaseCandidate

ResearchProgressCallback = Callable[[str], Awaitable[None]]


class ResearchProvider(Protocol):
    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
        progress: ResearchProgressCallback | None = None,
    ) -> list[CaseCandidate]: ...
