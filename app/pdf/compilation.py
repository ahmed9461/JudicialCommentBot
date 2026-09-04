"""Locate and extract original pages from official judicial compilation PDFs."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .errors import PdfValidationError

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_HEADER_MARKERS = ("رقم القضية", "رقم الدعوى", "رقم الصك", "رقم القضيـة", "رقم الدعـوى")


def extract_page_range(source_pdf: Path, *, start_page: int, end_page: int, output_pdf: Path) -> int:
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


def locate_case_page_range(source_pdf: Path, case_number: str, *, max_case_pages: int = 20) -> tuple[int, int]:
    """Best-effort page locator for a known case number inside an official compilation.

    It never guesses a case without a usable case-number token. The resulting range
    must still be identity-verified by the caller before use.
    """
    tokens = _case_number_tokens(case_number)
    if not tokens:
        raise PdfValidationError("Case number has no stable token for compilation lookup")
    reader = PdfReader(str(source_pdf), strict=False)
    texts = [(page.extract_text() or "") for page in reader.pages]
    start_index = next((i for i, text in enumerate(texts) if _tokens_match(text, tokens)), None)
    if start_index is None:
        raise PdfValidationError("Case number was not found in official compilation text")

    hard_end = min(len(texts) - 1, start_index + max(1, max_case_pages) - 1)
    end_index = hard_end
    for index in range(start_index + 1, hard_end + 1):
        text = texts[index]
        normalized = _normalize(text)
        if any(_normalize(marker) in normalized for marker in _HEADER_MARKERS) and not _tokens_match(text, tokens):
            end_index = index - 1
            break
    return start_index + 1, end_index + 1


def verify_case_number_in_pdf(path: Path, case_number: str) -> bool:
    tokens = _case_number_tokens(case_number)
    if not tokens:
        return False
    reader = PdfReader(str(path), strict=False)
    return any(_tokens_match(page.extract_text() or "", tokens) for page in reader.pages)


def _case_number_tokens(value: str) -> tuple[str, ...]:
    translated = value.translate(_ARABIC_DIGITS)
    digit_tokens = tuple(token for token in re.findall(r"\d+", translated) if len(token) >= 3)
    if digit_tokens:
        return digit_tokens[-3:]
    compact = re.sub(r"\W+", "", translated, flags=re.UNICODE).casefold()
    return (compact,) if len(compact) >= 4 else ()


def _tokens_match(text: str, tokens: tuple[str, ...]) -> bool:
    haystack = _normalize(text)
    return all(token.casefold() in haystack for token in tokens)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.translate(_ARABIC_DIGITS)).casefold()
