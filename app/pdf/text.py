"""Text extraction from verified judicial PDFs."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .errors import PdfValidationError


def extract_pdf_text(path: Path, *, max_chars: int) -> str:
    reader = PdfReader(str(path), strict=False)
    chunks: list[str] = []
    size = 0
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        remaining = max_chars - size
        if remaining <= 0:
            break
        piece = text[:remaining]
        chunks.append(piece)
        size += len(piece)
    result = "\n\n".join(chunks).strip()
    if not result:
        raise PdfValidationError("PDF text extraction returned no usable text")
    return result
