from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.pdf.compilation import extract_page_range
from app.pdf.errors import PdfValidationError
from app.pdf.validation import validate_pdf_file


def _make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def test_validate_and_extract_pdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "extract.pdf"
    _make_pdf(source, 5)

    assert validate_pdf_file(source, max_pages=10) == 5
    assert extract_page_range(source, start_page=2, end_page=4, output_pdf=output) == 3
    assert validate_pdf_file(output, max_pages=10) == 3


def test_non_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(PdfValidationError):
        validate_pdf_file(path, max_pages=10)
