"""Extract original page objects from an official judicial compilation PDF."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .errors import PdfValidationError


def extract_page_range(
    source_pdf: Path,
    *,
    start_page: int,
    end_page: int,
    output_pdf: Path,
) -> int:
    """Extract a 1-based inclusive page range without recreating page text."""
    if start_page < 1 or end_page < start_page:
        raise ValueError("Invalid page range")

    reader = PdfReader(str(source_pdf), strict=False)
    total = len(reader.pages)
    if end_page > total:
        raise PdfValidationError("Requested page range exceeds source PDF")

    writer = PdfWriter()
    for index in range(start_page - 1, end_page):
        writer.add_page(reader.pages[index])
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as handle:
        writer.write(handle)
    return end_page - start_page + 1
