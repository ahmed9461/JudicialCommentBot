from pathlib import Path

import pytest

from app.catalog.indexer import OfficialCatalogIndexer
from app.commentary import CommentaryDraft, CommentaryValidationError, validate_commentary
from app.knowledge import SubjectLoader
from app.pdf.compilation import verify_case_number_in_pdf
from app.pdf.headers import primary_judicial_header
from app.ranking import assess_subject_relevance


TAIL_OF_PREVIOUS_CASE = """
اعتراضية فأفهم بأن له مراجعة المحكمة لاستلام نسخة الحكم.
وقد تم الاطلاع على اللائحة الاعتراضية ولم أجد بها ما يؤثر على ما حكمت به،
كما صدر حكم من الدائرة التجارية الخامسة بالمحكمة الإدارية بمحافظة جدة
في القضية رقم 7844/2 لعام 1433هـ ويتضمن عدم اختصاص القضاء التجاري.
ثم قررت بعث المعاملة لمحكمة الاستئناف.
""" * 8

CAR_CASE_HEADER = """
الرقم التسلسلي: 194
محكمة الدرجة الأولى: المحكمة العامة بعنيزة
رقم القضية: 35159749 تاريخها: 1435
محكمة الاستئناف: محكمة الاستئناف بمنطقة القصيم
رقم القرار: 35388847 تاريخه: 1435/09/19
شراكة - شراء سيارات - بيعها - قبض كامل الثمن - طلب الشريك نصيبه منه - إقرار.
""" + ("أقام المدعي دعواه طالباً نصيبه من ثمن السيارات وأقر الوكيل بصحة الدعوى. " * 30)

CAR_CASE_BODY = (
    "اشترى الطرفان سيارات مناصفة ثم بيعت وقبض المدعى عليه كامل الثمن، "
    "وأقر وكيله بصحة دعوى المدعي فقضت المحكمة بإلزامه بالمبلغ المدعى به. " * 35
)

NEXT_CASE_HEADER = """
الرقم التسلسلي: 195
محكمة الدرجة الأولى: المحكمة العامة بالرياض
رقم القضية: 33645244 تاريخها: 1433
محكمة الاستئناف: محكمة الاستئناف بمنطقة الرياض
رقم القرار: 35327012 تاريخه: 1435/07/22
شراكة - مضاربة - مساهمة عقارية - طلب رد رأس المال والأرباح.
""" + ("أقام المدعي دعواه بطلب رد رأس المال في مساهمة عقارية. " * 30)


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakeReader:
    texts: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        self.pages = [FakePage(text) for text in self.texts]


def test_body_reference_is_not_a_primary_case_header() -> None:
    assert primary_judicial_header(TAIL_OF_PREVIOUS_CASE) is None
    target = primary_judicial_header(CAR_CASE_HEADER)
    assert target is not None
    assert target.case_number == "35159749"


def test_catalog_boundaries_for_real_neighboring_case_shape() -> None:
    texts = [
        TAIL_OF_PREVIOUS_CASE,
        "الموافقة على الحكم وبالله التوفيق " * 25,
        CAR_CASE_HEADER,
        CAR_CASE_BODY,
        CAR_CASE_BODY,
        NEXT_CASE_HEADER,
        "تابع قضية المساهمة العقارية " * 40,
    ]
    assert OfficialCatalogIndexer._case_starts(texts) == [2, 5]


def test_runtime_rejects_prefixed_or_multi_case_extract(monkeypatch) -> None:
    import app.pdf.compilation as compilation

    FakeReader.texts = [TAIL_OF_PREVIOUS_CASE, CAR_CASE_HEADER, CAR_CASE_BODY]
    monkeypatch.setattr(compilation, "PdfReader", FakeReader)
    assert verify_case_number_in_pdf(Path("prefixed.pdf"), "35159749") is False

    FakeReader.texts = [CAR_CASE_HEADER, CAR_CASE_BODY, NEXT_CASE_HEADER]
    assert verify_case_number_in_pdf(Path("two-cases.pdf"), "35159749") is False

    FakeReader.texts = [CAR_CASE_HEADER, CAR_CASE_BODY, CAR_CASE_BODY]
    assert verify_case_number_in_pdf(Path("one-case.pdf"), "35159749") is True


def test_private_car_dispute_is_rejected_for_constitutional_law() -> None:
    subject = SubjectLoader().get_subject("constitutional_law")
    assessment = assess_subject_relevance(subject, CAR_CASE_HEADER + CAR_CASE_BODY)
    assert assessment.accepted is False
    assert assessment.score < 18


def test_direct_rights_and_legality_case_is_accepted_for_constitutional_law() -> None:
    subject = SubjectLoader().get_subject("constitutional_law")
    text = (
        "تناول الحكم مبدأ المشروعية والحقوق والحريات العامة وحدود تقييد حرية الفرد، "
        "وبحث رقابة القضاء على ممارسة السلطة ومدى مراعاة المساواة. " * 25
    )
    assessment = assess_subject_relevance(subject, text)
    assert assessment.accepted is True
    assert assessment.direct_keyword_hits >= 1
    assert assessment.score >= 18


def test_commentary_rejects_foreign_case_identity() -> None:
    draft = CommentaryDraft(
        title="حجية الإقرار",
        facts_and_course_link="تتلخص الوقائع في مطالبة مالية بين شريكين." * 5,
        legal_issue="تتعلق المسألة بحجية الإقرار في الإثبات." * 5,
        court_reasoning="اعتمدت المحكمة على الإقرار الصادر ممن يملكه." * 5,
        comment_and_opinion="يستقيم الحكم في حدود الوقائع الثابتة في الملف." * 5,
        references=["الحكم القضائي محل التعليق"],
    )
    # Adding the identity of a neighboring judgment must fail even if the prose
    # otherwise looks legally plausible.
    contaminated = draft.model_copy(
        update={"court_reasoning": draft.court_reasoning + " القضية رقم 4487/3."}
    )
    with pytest.raises(CommentaryValidationError, match="different labelled case"):
        validate_commentary(
            contaminated,
            judgment_text=CAR_CASE_HEADER + CAR_CASE_BODY,
            expected_case_number="35159749",
        )
