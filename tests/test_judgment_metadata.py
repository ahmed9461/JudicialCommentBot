from pathlib import Path

from app.catalog.text import detect_case_number
from app.pdf import extract_judgment_metadata, refine_case_page_range
from app.pdf.headers import primary_judicial_header


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


def test_legacy_moj_publication_header_is_primary_not_body_reference() -> None:
    text = """
رد مهر وشبكة
الصك: ٣٤٢٠١٣٨٥ تاريخه: ١٤٣٤/٠٤/٢٩هـ
الدعوى: ٣٣٦٥٩١٣٩
رقم قرار التصديق: ٣٤٢٥١٢٦٢ تاريخه: ١٤٣٤/٠٦/٢٥هـ
الموضوعات
رد المهر والشبكة بعد فسخ النكاح
السند الشرعي أو النظامي
الأصل بقاء ما كان على ما كان
ملخص القضية
أقام المدعي دعواه طالباً ما يراه مستحقاً.
"""
    header = primary_judicial_header(text)
    assert header is not None
    assert header.case_number == "33659139"
    assert header.source == "case-legacy"
    metadata = extract_judgment_metadata(text, require_primary_header=True)
    assert metadata.case_number == "33659139"
    assert metadata.decision_number == "34251262"
    assert metadata.decision_date == "1434/06/25"


def test_body_case_reference_without_publication_block_is_not_primary() -> None:
    body = (
        "وبعد دراسة أوراق الدعوى تبين أن المدعى عليه سبق أن أقام الدعوى رقم ٣٥١٥٩٧٤٩ "
        "أمام المحكمة العامة ثم صدر الحكم فيها، وتمت الإشارة إلى ذلك ضمن أسباب الحكم. "
    ) * 8
    assert primary_judicial_header(body) is None


def test_catalog_case_number_never_falls_back_to_decision_number() -> None:
    text = "رقم القرار: ٣٥٢٦٢٩٧٤ تاريخه: ١٤٣٥/٠٦/٠٢هـ"
    assert detect_case_number(text) is None


def test_refine_broad_range_anchors_to_real_case_and_drops_dividers(monkeypatch) -> None:
    """Regression for a full compilation being sent as case ``436``."""
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

    monkeypatch.setattr("app.pdf.compilation.extract_pdf_page_texts", lambda _path: texts)
    start, end, metadata = refine_case_page_range(
        Path("official-compilation.pdf"),
        hint_start=1,
        hint_end=39,
        expected_case_number="436",
    )
    assert (start, end) == (5, 8)
    assert metadata.case_number == "34181612"
    assert metadata.decision_number == "35262974"
