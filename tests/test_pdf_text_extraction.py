from pathlib import Path

from app.pdf import text as pdf_text


def test_dual_engine_prefers_structured_arabic_judicial_text(monkeypatch) -> None:
    garbled = "xxxx 12345 " * 120
    structured = (
        "محكمة الدرجة الأولى المحكمة العامة رقم القضية ٣٥١٥٩٧٤٩ "
        "محكمة الاستئناف رقم القرار ٣٥٣٨٨٨٤٧ ملخص القضية المدعي المدعى عليه الحكم "
    ) * 12

    monkeypatch.setattr(pdf_text, "_extract_with_pypdf", lambda _path: [garbled, "صفحة ثانية"])
    monkeypatch.setattr(pdf_text, "_extract_with_mupdf", lambda _path: [structured, "صفحة ثانية"])

    pages = pdf_text.extract_pdf_page_texts(Path("fixture.pdf"))
    assert pages[0] == structured.strip()
    assert pages[1] == "صفحة ثانية"


def test_dual_engine_survives_one_extractor_failure(monkeypatch) -> None:
    text = "الصك 34201385 الدعوى 33659139 الموضوعات ملخص القضية " * 10
    monkeypatch.setattr(pdf_text, "_extract_with_pypdf", lambda _path: [])
    monkeypatch.setattr(pdf_text, "_extract_with_mupdf", lambda _path: [text])

    assert pdf_text.extract_pdf_page_texts(Path("fixture.pdf")) == [text.strip()]
