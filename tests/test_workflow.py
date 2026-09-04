from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.pdf import PdfAcquisitionError, PdfArtifact
from app.ranking import ScoringPolicy
from app.research import CaseCandidate
from app.services.case_workflow import CaseWorkflowService
from app.sources import SourceRegistry


class FakeProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    async def search_cases(self, subject, *, excluded_cases, limit):
        return self.candidates[:limit]


class FakePdfService:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls = 0

    async def acquire(self, url: str, *, suggested_name: str = "case"):
        self.calls += 1
        if self.calls == 1:
            raise PdfAcquisitionError("first candidate failed")
        path = self.tmp_path / "verified.pdf"
        path.write_bytes(b"fixture")
        return PdfArtifact(path=path, source_url=url, sha256="c" * 64, size_bytes=7, page_count=2)


def candidate(number: str, score: int) -> CaseCandidate:
    return CaseCandidate(
        title=f"قضية {number}", case_number=number, court_name="المحكمة التجارية",
        source_name="وزارة العدل", source_url=f"https://www.moj.gov.sa/{number}",
        pdf_url=f"https://www.moj.gov.sa/{number}.pdf", legal_issue="مسألة قانونية واضحة",
        suitability_reason="صلة مباشرة بموضوع المقرر", estimated_score=score,
        subject_relevance=38, legal_issue_clarity=19, reasoning_quality=14,
        academic_commentary_value=14,
    )


@pytest.mark.asyncio
async def test_workflow_skips_failed_pdf_and_uses_next_candidate(tmp_path: Path, monkeypatch) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    await db.initialize()
    pdf = FakePdfService(tmp_path)
    settings = Settings(
        telegram_bot_token="123456:fixture", owner_telegram_id=1,
        temp_dir=str(tmp_path), candidate_display_count=1, search_retry_rounds=1,
        search_candidate_limit=2, commentary_min_text_chars=10,
    )
    monkeypatch.setattr("app.services.case_workflow.verify_case_number_in_pdf", lambda path, number: True)
    monkeypatch.setattr("app.services.case_workflow.extract_pdf_text", lambda path, max_chars: "نص الحكم القضائي " * 20)

    service = CaseWorkflowService(
        database=db, subject_loader=SubjectLoader(), research_provider=FakeProvider([candidate("111", 95), candidate("222", 94)]),
        source_registry=SourceRegistry(), pdf_service=pdf, scoring=ScoringPolicy(), settings=settings,
    )
    batch = await service.prepare(1, "law_intro")
    assert pdf.calls == 2
    assert batch.cases[0].candidate.case_number == "222"
    service.cleanup_user(1)
