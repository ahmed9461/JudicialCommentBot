from app.catalog.text import detect_case_number
from app.pdf import extract_judgment_metadata


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
