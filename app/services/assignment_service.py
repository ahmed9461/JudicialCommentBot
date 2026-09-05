"""Generate, validate and render one commentary Word document."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.commentary import DeepSeekCommentaryGenerator, DocxRenderer, validate_commentary, validate_docx_file
from app.knowledge import SubjectProfile
from .case_workflow import PreparedCase

ProgressCallback = Callable[[str], Awaitable[None]]


class AssignmentService:
    def __init__(self, *, generator: DeepSeekCommentaryGenerator, renderer: DocxRenderer, temp_dir: str | Path) -> None:
        self.generator = generator
        self.renderer = renderer
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def generate_docx(
        self,
        prepared: PreparedCase,
        subject: SubjectProfile,
        *,
        regeneration: bool = False,
        progress: ProgressCallback | None = None,
    ) -> Path:
        await _notify(progress, "✍️ جاري تحليل الحكم وكتابة التعليق القانوني الأكاديمي…")
        draft = await self.generator.generate(
            subject=subject,
            candidate=prepared.candidate,
            judgment_text=prepared.judgment_text,
            variation_hint=(
                "أعد الصياغة بأسلوب أكاديمي طبيعي مختلف مع بقاء الوقائع والنتيجة كما هي."
                if regeneration else None
            ),
            progress=progress,
        )
        await _notify(progress, "🧾 تم استلام المسودة، جاري مطابقة الأرقام والنصوص مع الحكم الرسمي…")
        validate_commentary(draft, judgment_text=prepared.judgment_text)
        path = self.temp_dir / f"commentary-{secrets.token_hex(8)}.docx"
        candidate = prepared.candidate
        await _notify(progress, "📄 جاري إنشاء ملف Word وإضافة بيانات الحكم المتحققة…")
        self.renderer.render(
            draft,
            subject_name=subject.name_ar,
            subject_slug=subject.slug,
            output_path=path,
            case_number=candidate.case_number,
            court_name=candidate.court_name,
            judgment_year=candidate.judgment_year,
            decision_number=candidate.decision_number,
            decision_date=candidate.decision_date,
            appeal_court_name=candidate.appeal_court_name,
            source_name=candidate.source_name,
            source_url=prepared.artifact.source_url,
        )
        await _notify(progress, "🔍 جاري الفحص النهائي لملف Word قبل الإرسال…")
        validate_docx_file(
            path,
            expected_metadata={
                "رقم القضية": candidate.case_number,
                "المحكمة": candidate.court_name,
                "سنة القضية": candidate.judgment_year,
                "رقم قرار الاستئناف": candidate.decision_number,
                "تاريخ القرار": candidate.decision_date,
            },
        )
        return path


async def _notify(progress: ProgressCallback | None, text: str) -> None:
    if progress is not None:
        await progress(text)
