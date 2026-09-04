import time

import pytest

from app.knowledge import SubjectLoader
from app.research.robust import ResearchServiceError, RobustResearchProvider, _http_error


class FakeInner:
    async def search_cases(self, subject, *, excluded_cases, limit, progress=None):
        return []


def test_deepseek_http_errors_have_actionable_messages() -> None:
    insufficient = _http_error(402, "fixture")
    assert insufficient.code == "deepseek_balance"
    assert "رصيد" in insufficient.user_message

    invalid = _http_error(422, "fixture")
    assert invalid.code == "deepseek_parameters"
    assert "422" in invalid.user_message


@pytest.mark.asyncio
async def test_cached_preflight_allows_inner_provider_without_network() -> None:
    provider = RobustResearchProvider(
        inner=FakeInner(),
        api_key="fixture",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        preflight_ttl_seconds=300,
    )
    provider._preflight_ok_at = time.monotonic()
    subject = SubjectLoader().get_subject("law_intro")
    result = await provider.search_cases(subject, excluded_cases=[], limit=3)
    assert result == []


def test_research_service_error_keeps_safe_user_message() -> None:
    exc = ResearchServiceError("code", "رسالة آمنة", detail="private diagnostic")
    assert exc.user_message == "رسالة آمنة"
    assert exc.detail == "private diagnostic"
