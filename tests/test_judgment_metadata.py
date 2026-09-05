from pathlib import Path

from app.catalog.text import detect_case_number
from app.pdf import extract_judgment_metadata, refine_case_page_range


def test_extract_verified_insurance_header_metadata() -> None:
    text = """
محكمة الدرجة الأولى: المحكمة العامة بمحافظة جدة
رقم القضية: ٣٤١٨١٦١٢ تاريخها: ١٤٣٤
محكمة الاستئناف: محكمة الاستئناف بمنطقة مكة المكرمة
رقم القرار: ٣٥٢٦٢٩٧٤ تاريخه: ١٤٣٥/٠٦/٠٢هـ
اختصاص - حادث سير - مطالبة شركة التأمين
"""
    metadata = extract_judgment_metadata(text)
    assert metadata.case_number == "34181612"
    assert metadata.court_name == "المحكمة العامة بمحافظة جدة"
    assert metadata.judgment_year == "1434"
    assert metadata.decision_number == "35262974"
    assert metadata.decision_date == "1435/06/02"
    assert metadata.appeal_court_name == "محكمة الاستئناف بمنطقة مكة المكرمة"


def test_catalog_case_number_never_falls_back_to_decision_number() -> None:
    text = "رقم القرار: ٣٥٢٦٢٩٧٤ تاريخه: ١٤٣٥/٠٦/٠٢هـ"
    assert detect_case_number(text) is None


def test_refine_broad_range_anchors_to_real_case_and_drops_dividers(monkeypatch) -> None:
    """Regression for a full compilation being sent as case ``436``.

    The catalog hint may be stale or overly broad. The official header must win,
    and the final range must stop before decorative pages and the next judgment.
    """

    insurance_header = """
محكمة الدرجة الأولى: المحكمة العامة بمحافظة جدة
رقم القضية: ٣٤١٨١٦١٢ تاريخها: ١٤٣٤
محكمة الاستئناف: محكمة الاستئناف بمنطقة مكة المكرمة
رقم القرار: ٣٥٢٦٢٩٧٤ تاريخه: ١٤٣٥/٠٦/٠٢هـ
اختصاص حادث سير مطالبة شركة التأمين منازعة ناشئة عن وثيقة تأمين
""" + ("وقائع الحكم والتعويض والاختصاص " * 25)
    substantive = "المحكمة المدعي المدعى عليها الحكم والتسبيب في منازعة التأمين " * 30
    next_case = """
محكمة الدرجة الأولى: المحكمة العامة بمحافظة عيون الجواء
رقم القضية: ٣٤٢٠٦٩٤٥ تاريخها: ١٤٣٤
اختصاص لجنة فض منازعات صناعة الكهرباء
""" + ("وقائع الدعوى والحكم " * 25)
    texts = [
        "مقدمة قديمة " * 30,
        "تابع قضية سابقة " * 30,
        "",
        "اختصاص لجان الفصل في المنازعات والمخالفات التأمينية",
        insurance_header,
        substantive,
        substantive,
        substantive,
        "",
        "اختصاص لجنة فض منازعات صناعة الكهرباء",
        next_case,
    ]

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class FakeReader:
        def __init__(self, *args, **kwargs) -> None:
            self.pages = [FakePage(text) for text in texts]

    monkeypatch.setattr("app.pdf.compilation.PdfReader", FakeReader)
    start, end, metadata = refine_case_page_range(
        Path("official-compilation.pdf"),
        hint_start=1,
        hint_end=39,
        expected_case_number="436",
    )
    assert (start, end) == (5, 8)
    assert metadata.case_number == "34181612"
    assert metadata.decision_number == "35262974"
