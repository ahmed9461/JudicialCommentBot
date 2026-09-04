"""Generate, validate and render one commentary Word document."""

from __future__ import annotations

import secrets
from pathlib import Path

from app.commentary import (
    DeepSeekCommentaryGenerator,
    DocxRenderer,
    validate_commentary,
)
from app.knowledge import SubjectProfile

from .case_workflow import PreparedCase


class AssignmentService:
    def __init__(
        self,
        *,
        generator: DeepSeekCommentaryGenerator,
        renderer: DocxRenderer,
        temp_dir: str | Path,
    ) -> None:
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
    ) -> Path:
        draft = await self.generator.generate(
            subject=subject,
            candidate=prepared.candidate,
            judgment_text=prepared.judgment_text,
            variation_hint=(
                "أعد الصياغة بأسلوب أكاديمي طبيعي مختلف مع بقاء الوقائع والنتيجة كما هي."
                if regeneration
                else None
            ),
        )
        validate_commentary(draft)
        path = self.temp_dir / f"commentary-{secrets.token_hex(8)}.docx"
        self.renderer.render(draft, subject_name=subject.name_ar, output_path=path)
        return path
