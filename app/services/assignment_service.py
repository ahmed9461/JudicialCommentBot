"""Generate, validate and render one commentary Word document."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.commentary import (
    CommentaryValidationError,
    DeepSeekCommentaryGenerator,
    DocxRenderer,
    validate_commentary,
    validate_docx_file,
)
from app.knowledge import SubjectProfile
from .case_workflow import PreparedCase

ProgressCallback = Callable[[str], Awaitable[None]]


class AssignmentService:
    def __init__(
        self,
        *,
        generator: DeepSeekCommentaryGenerator,
        renderer: DocxRenderer,
        temp_dir: str | Path,
        validation_attempts: int = 2,
    ) -> None:
        self.generator = generator
        self.renderer = renderer
        self.temp_dir = Path(temp_dir)
        self.validation_attempts = max(1, int(validation_attempts))
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def generate_docx(
        self,
        prepared: PreparedCase,
        subject: SubjectProfile,
        *,
        regeneration: bool = False,
        progress: ProgressCallback | None = None,
    ) -> Path:
        correction_hint: str | None = None
        draft = None

        for attempt in range(1, self.validation_attempts + 1):
            if attempt == 1:
                await _notify(progress, "✍️ جاري تحليل الحكم وكتابة التعليق القانوني الأكاديمي…")
            else:
                await _notify(
                    progress,
                    f"🛡️ المسودة لم تجتز التدقيق الدقيق. جاري تصحيحها من نفس الحكم…\n"
                    f"محاولة التدقيق {attempt}/{self.validation_attempts}",
                )

            variation_parts: list[str] = []
            if regeneration:
                variation_parts.append(
                    "أعد الصياغة بأسلوب أكاديمي طبيعي مختلف مع بقاء الوقائع والنتيجة كما هي."
                )
            if correction_hint:
                variation_parts.append(correction_hint)

            draft = await self.generator.generate(
                subject=subject,
                candidate=prepared.candidate,
                judgment_text=prepared.judgment_text,
                variation_hint="\n".join(variation_parts) or None,
                progress=progress,
            )
            await _notify(
                progress,
                "🧾 تم استلام المسودة، جاري مطابقة الأرقام والنصوص مع الحكم الرسمي…",
            )
            try:
                validate_commentary(draft, judgment_text=prepared.judgment_text)
                break
            except CommentaryValidationError as exc:
                if attempt >= self.validation_attempts:
                    raise
                correction_hint = (
                    "المسودة السابقة رفضها المدقق الآلي للسبب التالي: "
                    f"{exc}. صحح هذه النقطة فقط بالاعتماد على نص الحكم المرفق، "
                    "ولا تضف أي رقم مادة أو واقعة أو مرجع غير ظاهر فيه."
                )

        if draft is None:  # Defensive; loop always runs at least once.
            raise RuntimeError("Commentary draft was not produced")

        path = self.temp_dir / f"commentary-{secrets.token_hex(8)}.docx"
        candidate = prepared.candidate
        await _notify(progress, "📄 جاري إنشاء ملف Word وإضافة بيانات الحكم المتحققة…")
        await asyncio.to_thread(
            self.renderer.render,
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
        await asyncio.to_thread(
            validate_docx_file,
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
