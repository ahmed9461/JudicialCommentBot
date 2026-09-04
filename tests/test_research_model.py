import pytest
from pydantic import ValidationError

from app.research import CaseCandidate


def base_candidate(**extra):
    data = dict(
        title="قضية تجريبية", source_name="وزارة العدل",
        source_url="https://www.moj.gov.sa/case", pdf_url="https://www.moj.gov.sa/case.pdf",
        legal_issue="مسألة قانونية واضحة", suitability_reason="مرتبطة مباشرة بالمقرر",
        estimated_score=90,
    )
    data.update(extra)
    return data


def test_page_range_requires_both_bounds_and_order() -> None:
    with pytest.raises(ValidationError):
        CaseCandidate(**base_candidate(pdf_page_start=2))
    with pytest.raises(ValidationError):
        CaseCandidate(**base_candidate(pdf_page_start=5, pdf_page_end=3))
    assert CaseCandidate(**base_candidate(pdf_page_start=2, pdf_page_end=4)).has_page_range
