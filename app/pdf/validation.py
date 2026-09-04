"""Local PDF validation."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .errors import PdfValidationError


def validate_pdf_file(path: Path, *, max_pages: int) -> int:
    try:
        with path.open("rb") as handle:
            magic = handle.read(5)
        if magic != b"%PDF-":
            raise PdfValidationError("File does not start with PDF magic bytes")

        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise PdfValidationError("Encrypted PDF files are not accepted")
        page_count = len(reader.pages)
    except PdfValidationError:
        raise
    except Exception as exc:
        raise PdfValidationError(f"Invalid PDF: {exc}") from exc

    if page_count < 1:
        raise PdfValidationError("PDF contains no pages")
    if page_count > max_pages:
        raise PdfValidationError("PDF exceeds configured page limit")
    return page_count
