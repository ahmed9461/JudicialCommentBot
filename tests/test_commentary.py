from pathlib import Path

import pytest
from docx import Document

from app.commentary import CommentaryDraft, CommentaryValidationError, DocxRenderer, validate_commentary, validate_docx_file


def _draft(**changes) -> CommentaryDraft:
    data = {
        "title": "التعسف في استعمال الحق والتعويض عن أتعاب التقاضي",
        "facts_and_course_link": "تتلخص الوقائع في نزاع قضائي ترتب عليه طلب تعويض عن مصروفات التقاضي، وترتبط القضية بنظرية الحق وحدود استعماله المشروع في المقرر. " * 2,
        "legal_issue": "تتمثل المسألة القانونية في تحديد متى يكون اللجوء إلى القضاء استعمالاً مشروعاً للحق ومتى يتجاوز إلى التعسف الذي يرتب المسؤولية.",
        "court_reasoning": "بحثت المحكمة سبب المطالبة ومدى ثبوت التجاوز في استعمال حق التقاضي، وربطت النتيجة بالوقائع المثبتة في ملف الدعوى دون افتراض وقائع خارج الحكم. " * 2,
        "comment_and_opinion": "أؤيد النتيجة متى كان ملف الحكم لا يثبت كيدية الخصومة، لأن مجرد خسارة الدعوى السابقة لا يكفي وحده لاعتبار استعمال حق التقاضي غير مشروع. " * 2,
        "references": ["الحكم القضائي محل التعليق"],
    }
    data.update(changes)
    return CommentaryDraft(**data)


def test_validator_rejects_markdown_and_ai_mentions() -> None:
    with pytest.raises(CommentaryValidationError):
        validate_commentary(_draft(comment_and_opinion="## رأي" + " نص قانوني" * 40))
    with pytest.raises(CommentaryValidationError):
        validate_commentary(_draft(comment_and_opinion="تم إنشاء النص بواسطة AI " + "تحليل" * 40))


def test_docx_renderer_is_rtl_and_passes_final_validation(tmp_path: Path) -> None:
    path = tmp_path / "comment.docx"
    DocxRenderer().render(_draft(), subject_name="المدخل لدراسة علم القانون", subject_slug="law_intro", output_path=path)
    validate_docx_file(path)
    doc = Document(path)
    assert "أولاً: تلخيص وقائع القضية وربطها بالمقرر" in [p.text for p in doc.paragraphs]
    assert doc.core_properties.author == ""
