import asyncio
import time
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.core.settings import Settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.pdf import JudgmentMetadata, PdfAcquisitionError, PdfArtifact
from app.ranking import ScoringPolicy
from app.research import CaseCandidate
from app.services.case_workflow import CaseWorkflowService, NoSuitableCasesError
from app.sources import SourceRegistry


class FakeProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    async def search_cases(self, subject, *, excluded_cases, limit, progress=None):
        if progress is not None:
            await progress("بحث تجريبي")
        return self.candidates[:limit]


class FakePdfService:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls = 0

    async def acquire(self, url: str, *, suggested_name: str = "case", progress=None):
        self.calls += 1
        if self.calls == 1:
            raise PdfAcquisitionError("first candidate failed")
        path = self.tmp_path / "verified.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with path.open("wb") as handle:
            writer.write(handle)
        payload = path.read_bytes()
        if progress is not None:
            await progress("تم تنزيل ملف تجريبي")
        return PdfArtifact(
            path=path,
            source_url=url,
            sha256="c" * 64,
            size_bytes=len(payload),
            page_count=2,
        )


class CatalogPdfService:
    def __init__(self, tmp_path: Path, sha256: str = "d" * 64):
        self.tmp_path = tmp_path
        self.sha256 = sha256

    async def acquire(self, url: str, *, suggested_name: str = "case", progress=None):
        path = self.tmp_path / "catalog-source.pdf"
        writer = PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=595, height=842)
        with path.open("wb") as handle:
            writer.write(handle)
        payload = path.read_bytes()
        return PdfArtifact(
            path=path,
            source_url=url,
            sha256=self.sha256,
            size_bytes=len(payload),
            page_count=4,
        )


def candidate(number: str, score: int) -> CaseCandidate:
    return CaseCandidate(
        title=f"قضية {number}",
        case_number=number,
        court_name="المحكمة التجارية",
        source_name="وزارة العدل",
        source_url=f"https://www.moj.gov.sa/{number}",
        pdf_url=f"https://www.moj.gov.sa/{number}.pdf",
        legal_issue="مسألة قانونية واضحة",
        suitability_reason="صلة مباشرة بموضوع المقرر",
        estimated_score=score,
        subject_relevance=38,
        legal_issue_clarity=19,
        reasoning_quality=14,
        academic_commentary_value=14,
    )


def catalog_candidate(number: str = "777") -> CaseCandidate:
    return CaseCandidate(
        title=f"قضية {number}",
        case_number=number,
        court_name="المحكمة الجزائية",
        source_name="وزارة العدل",
        source_url="https://www.moj.gov.sa/collection.pdf",
        pdf_url="https://www.moj.gov.sa/collection.pdf",
        pdf_page_start=2,
        pdf_page_end=3,
        catalog_key="catalog-fixture",
        catalog_pdf_sha256="d" * 64,
        catalog_range_verified=True,
        legal_issue="مسألة قانونية واضحة",
        suitability_reason="صلة مباشرة بموضوع المقرر",
        estimated_score=93,
        subject_relevance=38,
        legal_issue_clarity=19,
        reasoning_quality=14,
        academic_commentary_value=14,
    )


@pytest.mark.asyncio
async def test_workflow_skips_failed_pdf_and_uses_next_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    await db.initialize()
    pdf = FakePdfService(tmp_path)
    settings = Settings(
        telegram_bot_token="123456:fixture",
        owner_telegram_id=1,
        temp_dir=str(tmp_path),
        candidate_display_count=1,
        search_retry_rounds=1,
        search_candidate_limit=2,
        commentary_min_text_chars=10,
    )
    monkeypatch.setattr(
        "app.services.case_workflow.verify_case_number_in_pdf",
        lambda path, number: True,
    )
    monkeypatch.setattr(
        "app.services.case_workflow.extract_pdf_text",
        lambda path, max_chars: "نص الحكم القضائي " * 20,
    )
    service = CaseWorkflowService(
        database=db,
        subject_loader=SubjectLoader(),
        research_provider=FakeProvider([candidate("111", 95), candidate("222", 94)]),
        source_registry=SourceRegistry(),
        pdf_service=pdf,
        scoring=ScoringPolicy(),
        settings=settings,
    )
    progress_events: list[str] = []

    async def progress(text: str) -> None:
        progress_events.append(text)

    batch = await service.prepare(1, "law_intro", progress=progress)
    assert pdf.calls == 2
    assert batch.cases[0].candidate.case_number == "222"
    assert "بحث تجريبي" in progress_events
    assert "تم تنزيل ملف تجريبي" in progress_events
    await service.cleanup_user(1)


@pytest.mark.asyncio
async def test_verified_catalog_range_uses_fingerprint_and_does_not_refine_hint(
    tmp_path: Path, monkeypatch
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'catalog-workflow.db'}")
    await db.initialize()
    settings = Settings(
        telegram_bot_token="123456:fixture",
        owner_telegram_id=1,
        temp_dir=str(tmp_path),
        candidate_display_count=1,
        search_candidate_limit=1,
        commentary_min_text_chars=10,
    )
    service = CaseWorkflowService(
        database=db,
        subject_loader=SubjectLoader(),
        research_provider=FakeProvider([catalog_candidate()]),
        source_registry=SourceRegistry(),
        pdf_service=CatalogPdfService(tmp_path),
        scoring=ScoringPolicy(),
        settings=settings,
    )

    monkeypatch.setattr(
        "app.services.case_workflow.refine_case_page_range",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("catalog range must not be rediscovered")),
    )
    monkeypatch.setattr(
        service,
        "_extract_compilation_case",
        lambda artifact, **kwargs: PdfArtifact(
            path=artifact.path,
            source_url=artifact.source_url,
            sha256="e" * 64,
            size_bytes=artifact.size_bytes,
            page_count=2,
        ),
    )
    monkeypatch.setattr(
        "app.services.case_workflow.extract_judgment_metadata_from_pdf",
        lambda path: JudgmentMetadata(case_number="777", court_name="المحكمة الجزائية"),
    )
    monkeypatch.setattr(
        "app.services.case_workflow.labeled_case_numbers_in_pdf",
        lambda path: ("777",),
    )
    monkeypatch.setattr(
        "app.services.case_workflow.verify_case_number_in_pdf",
        lambda path, number: number == "777",
    )
    monkeypatch.setattr(
        "app.services.case_workflow.extract_pdf_text",
        lambda path, max_chars: "نص الحكم القضائي " * 20,
    )

    batch = await service.prepare(1, "criminal_general")
    assert batch.cases[0].source_page_start == 2
    assert batch.cases[0].source_page_end == 3
    await service.cleanup_user(1)


@pytest.mark.asyncio
async def test_stale_catalog_fingerprint_is_rejected_before_page_use(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'stale-workflow.db'}")
    await db.initialize()
    service = CaseWorkflowService(
        database=db,
        subject_loader=SubjectLoader(),
        research_provider=FakeProvider([catalog_candidate()]),
        source_registry=SourceRegistry(),
        pdf_service=CatalogPdfService(tmp_path, sha256="f" * 64),
        scoring=ScoringPolicy(),
        settings=Settings(
            telegram_bot_token="123456:fixture",
            owner_telegram_id=1,
            temp_dir=str(tmp_path),
            search_candidate_limit=1,
        ),
    )
    with pytest.raises(NoSuitableCasesError):
        await service.prepare(1, "criminal_general")


@pytest.mark.asyncio
async def test_pdf_stage_does_not_block_asyncio_event_loop(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}")
    await db.initialize()
    service = CaseWorkflowService(
        database=db,
        subject_loader=SubjectLoader(),
        research_provider=FakeProvider([]),
        source_registry=SourceRegistry(),
        pdf_service=FakePdfService(tmp_path),
        scoring=ScoringPolicy(),
        settings=Settings(
            telegram_bot_token="123456:fixture",
            owner_telegram_id=1,
            temp_dir=str(tmp_path),
            pdf_processing_timeout_seconds=2,
        ),
    )

    def slow_pdf_parse() -> str:
        time.sleep(0.20)
        return "done"

    task = asyncio.create_task(service._run_pdf_stage("فحص", slow_pdf_parse))
    started = time.monotonic()
    await asyncio.sleep(0.03)
    elapsed = time.monotonic() - started
    assert elapsed < 0.12
    assert await task == "done"


@pytest.mark.asyncio
async def test_reservation_blocks_same_case_for_another_session(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'reservation.db'}")
    await db.initialize()
    assert await db.reserve_case(
        "one", case_number="55", court_name="محكمة", pdf_sha256="d" * 64
    )
    assert not await db.reserve_case(
        "two", case_number="55", court_name="محكمة", pdf_sha256="e" * 64
    )
    await db.release_reservation("one")
    assert await db.reserve_case(
        "two", case_number="55", court_name="محكمة", pdf_sha256="e" * 64
    )
