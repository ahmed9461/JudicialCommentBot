from pathlib import Path
from types import SimpleNamespace

import pytest

from app.commentary import CommentaryDraft, DocxRenderer
from app.core.settings import Settings
from app.knowledge import SubjectLoader
from app.services import AssignmentService


class CorrectingGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.hints: list[str | None] = []

    async def generate(self, **kwargs):
        self.calls += 1
        self.hints.append(kwargs.get("variation_hint"))
        article = "78" if self.calls == 1 else "87"
        return CommentaryDraft(
            title="أثر النص النظامي في تسبيب الحكم",
            facts_and_course_link=(
                "تتلخص الوقائع في نزاع قضائي وردت تفاصيله في الحكم الرسمي، "
                "وترتبط القضية مباشرة بمحاور المقرر من حيث فهم الواقعة وأثر القاعدة النظامية. "
            ) * 2,
            legal_issue=(
                "تتمثل المسألة القانونية في تحديد أثر القاعدة النظامية التي ناقشها الحكم "
                "على النتيجة القضائية وربطها بالمقرر دون إضافة وقائع من خارج الملف."
            ),
            court_reasoning=(
                f"ناقشت المحكمة المادة {article} من النظام في ضوء الوقائع الثابتة في الحكم، "
                "ثم بنت النتيجة على ما ظهر لها من مستندات وأسباب دون افتراض عناصر غير ثابتة. "
            ) * 2,
            comment_and_opinion=(
                "يظهر من التسبيب أن سلامة التعليق الأكاديمي تتطلب الالتزام بما ورد في الحكم نفسه، "
                "وهو ما يجعل تقييم النتيجة مرتبطاً بالنص والوقائع الموثقة لا بمعلومات خارجية. "
            ) * 2,
            references=["الحكم القضائي محل التعليق"],
        )


@pytest.mark.asyncio
async def test_assignment_retries_only_after_validator_rejects_completed_draft(tmp_path: Path) -> None:
    generator = CorrectingGenerator()
    service = AssignmentService(
        generator=generator,  # type: ignore[arg-type]
        renderer=DocxRenderer(),
        temp_dir=tmp_path,
        validation_attempts=2,
    )
    candidate = SimpleNamespace(
        case_number="12345",
        court_name="المحكمة العامة",
        judgment_year="1435",
        decision_number=None,
        decision_date=None,
        appeal_court_name=None,
        source_name="وزارة العدل",
    )
    prepared = SimpleNamespace(
        candidate=candidate,
        judgment_text=(
            "ثبت في الحكم أن المحكمة ناقشت المادة 87 من النظام وبنت النتيجة على الوقائع الثابتة. "
            * 20
        ),
        artifact=SimpleNamespace(source_url="https://www.moj.gov.sa/example.pdf"),
    )
    subject = SubjectLoader().get_subject("law_intro")

    path = await service.generate_docx(prepared, subject)  # type: ignore[arg-type]

    assert path.exists()
    assert generator.calls == 2
    assert generator.hints[0] is None
    assert generator.hints[1] is not None
    assert "78" in generator.hints[1]


def test_commentary_has_separate_longer_stream_idle_timeout() -> None:
    settings = Settings(
        telegram_bot_token="123456:fixture",
        owner_telegram_id=1,
    )
    assert settings.deepseek_stream_idle_timeout_seconds == 180
    assert settings.deepseek_commentary_idle_timeout_seconds == 420
    assert settings.deepseek_commentary_idle_timeout_seconds > settings.deepseek_stream_idle_timeout_seconds
