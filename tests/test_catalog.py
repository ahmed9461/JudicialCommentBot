from pathlib import Path

import pytest

from app.catalog import (
    CatalogFirstResearchProvider,
    CatalogNotReadyError,
    CatalogResearchProvider,
    CatalogStore,
    SubjectSourceMap,
)
from app.catalog.indexer import OfficialCatalogIndexer
from app.catalog.models import CatalogCase
from app.catalog.text import detect_case_number, detect_court_name, normalize_arabic
from app.db import Database
from app.knowledge import SubjectLoader


@pytest.mark.asyncio
async def test_catalog_search_returns_official_candidate_without_web(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    await db.initialize()
    store = CatalogStore(db)
    text = (
        "رقم القضية: 12345 المحكمة الجزائية الحكم على المتهم. "
        "ثبتت سوابق المتهم وناقشت المحكمة تشديد العقوبة ثم رأت تخفيف العقوبة "
        "ومراعاة ظروف الجاني وأغراض العقوبة والردع والإصلاح."
    ) * 8
    await store.upsert(
        CatalogCase(
            catalog_key="fixture-1",
            collection_id="moj_fixture",
            source_id="ministry_of_justice",
            source_name="وزارة العدل",
            source_url="https://www.moj.gov.sa/fixture.pdf",
            pdf_url="https://www.moj.gov.sa/fixture.pdf",
            page_start=10,
            page_end=13,
            title="تخفيف العقوبة ومراعاة ظروف الجاني",
            case_number="12345",
            court_name="المحكمة الجزائية",
            judgment_year="1445",
            text=text,
            normalized_text=normalize_arabic(text),
        )
    )

    class Fallback:
        called = False

        async def search_cases(self, *args, **kwargs):
            self.called = True
            raise AssertionError("web fallback must not be called")

    fallback = Fallback()
    provider = CatalogFirstResearchProvider(
        catalog=CatalogResearchProvider(store),
        fallback=fallback,
        min_catalog_candidates=1,
    )
    subject = SubjectLoader().get_subject("criminology_penology")
    result = await provider.search_cases(subject, excluded_cases=[], limit=1)
    assert result[0].case_number == "12345"
    assert result[0].pdf_page_start == 10
    assert fallback.called is False


@pytest.mark.asyncio
async def test_empty_catalog_never_spends_web_fallback(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    await db.initialize()
    store = CatalogStore(db)

    class Fallback:
        called = False

        async def search_cases(self, *args, **kwargs):
            self.called = True
            return []

    fallback = Fallback()
    provider = CatalogFirstResearchProvider(
        catalog=CatalogResearchProvider(store),
        fallback=fallback,
    )
    subject = SubjectLoader().get_subject("commercial_law")
    with pytest.raises(CatalogNotReadyError) as error:
        await provider.search_cases(subject, excluded_cases=[], limit=5)
    assert error.value.code == "catalog_not_ready"
    assert fallback.called is False


def test_every_configured_subject_has_official_source_preferences() -> None:
    loader = SubjectLoader()
    source_map = SubjectSourceMap()
    missing = [item.slug for item in loader.list_subjects() if not source_map.preferred_for(item.slug)]
    assert missing == []
    assert len(loader.list_subjects()) == 34


def test_indexer_rejects_toc_like_pages_and_detects_case_starts() -> None:
    toc = ("رقم القضية 1 رقم القضية 2 رقم القضية 3 رقم القضية 4 رقم القضية 5 " * 20)
    first = "رقم القضية: 1111 المحكمة الجزائية الدائرة الأولى الحكم على المتهم " + ("وقائع " * 100)
    second = "رقم الدعوى: 2222 المحكمة العامة الدائرة الثانية الحكم في الدعوى " + ("تسبيب " * 100)
    assert OfficialCatalogIndexer._case_starts([toc, first, "تابع الحكم " * 100, second]) == [1, 3]


def test_metadata_detection_supports_committee_decisions() -> None:
    text = "رقم القرار: 1432-112 اللجنة الفصل في المنازعات والمخالفات التأمينية "
    assert detect_case_number(text) == "1432-112"
    assert "لجنة" in (detect_court_name(text) or "")
