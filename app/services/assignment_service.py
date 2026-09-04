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
        await _notify(progress, "🧾 تم استلام المسودة، جاري التحقق من الوقائع والبنية والممنوعات…")
        validate_commentary(draft)
        path = self.temp_dir / f"commentary-{secrets.token_hex(8)}.docx"
        await _notify(progress, "📄 جاري إنشاء ملف Word العربي وتطبيق تنسيق RTL…")
        self.renderer.render(
            draft,
            subject_name=subject.name_ar,
            subject_slug=subject.slug,
            output_path=path,
        )
        await _notify(progress, "🔍 جاري الفحص النهائي لملف Word قبل الإرسال…")
        validate_docx_file(path)
        return path


async def _notify(progress: ProgressCallback | None, text: str) -> None:
    if progress is not None:
        await progress(text)
