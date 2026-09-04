"""Research provider contract."""

from typing import Protocol

from app.knowledge import SubjectProfile

from .models import CaseCandidate


class ResearchProvider(Protocol):
    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
    ) -> list[CaseCandidate]: ...
