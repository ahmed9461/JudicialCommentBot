"""Locate, verify and extract original pages from official judicial compilation PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .errors import PdfValidationError
from .headers import first_labeled_case_number, labeled_case_numbers, normalize_case_number

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DECISION_LABEL = re.compile(r"رقم\s*القرار\s*[:：\-]?\s*([0-9٠-٩۰-۹/\-ق]{3,})", re.I)
_DECISION_DATE = re.compile(
    r"رقم\s*القرار\s*[:：\-]?\s*[0-9٠-٩۰-۹/\-ق]{3,}.{0,80}?(?:تاريخه|تاريخ(?:ه)?)\s*[:：\-]?\s*([0-9٠-٩۰-۹/\-]{6,})",
    re.I | re.S,
)
_CASE_YEAR = re.compile(
    r"رقم\s*(?:القضية|القضيـة|الدعوى|الدعـوى)\s*[:：\-]?\s*[0-9٠-٩۰-۹/\-ق]{3,}.{0,80}?(?:تاريخها|تاريخ(?:ها)?)\s*[:：\-]?\s*(14[0-9٠-٩۰-۹]{2})",
    re.I | re.S,
)
_FIRST_COURT = re.compile(r"محكمة\s*الدرجة\s*الأولى\s*[:：\-]?\s*([^\n]{3,180})", re.I)
_APPEAL_COURT = re.compile(r"محكمة\s*الاستئناف\s*[:：\-]?\s*([^\n]{3,180})", re.I)


@dataclass(frozen=True, slots=True)
class JudgmentMetadata:
    case_number: str | None = None
    court_name: str | None = None
    judgment_year: str | None = None
    decision_number: str | None = None
    decision_date: str | None = None
    appeal_court_name: str | None = None


def extract_page_range(source_pdf: Path, *, start_page: int, end_page: int, output_pdf: Path) -> int:
    """Extract a 1-based inclusive page range by copying original PDF pages."""
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


def extract_judgment_metadata(text: str) -> JudgmentMetadata:
    """Extract only explicitly labelled metadata from an official judgment header."""
    sample = text[:12000]
    case_number = first_labeled_case_number(sample)
    decision_match = _DECISION_LABEL.search(sample)
    decision_date_match = _DECISION_DATE.search(sample)
    year_match = _CASE_YEAR.search(sample.translate(_ARABIC_DIGITS))
    first_court_match = _FIRST_COURT.search(sample)
    appeal_match = _APPEAL_COURT.search(sample)
    return JudgmentMetadata(
        case_number=case_number,
        court_name=_clean_label(first_court_match.group(1)) if first_court_match else None,
        judgment_year=_digits(year_match.group(1)) if year_match else None,
        decision_number=_digits(decision_match.group(1)) if decision_match else None,
        decision_date=_digits(decision_date_match.group(1)) if decision_date_match else None,
        appeal_court_name=_clean_label(appeal_match.group(1)) if appeal_match else None,
    )


def extract_judgment_metadata_from_pdf(path: Path) -> JudgmentMetadata:
    reader = PdfReader(str(path), strict=False)
    text = "\n".join((page.extract_text() or "") for page in reader.pages[:4])
    return extract_judgment_metadata(text)


def labeled_case_numbers_in_pdf(path: Path) -> tuple[str, ...]:
    """Return distinct explicitly labelled case numbers in document order."""
    reader = PdfReader(str(path), strict=False)
    seen: set[str] = set()
    result: list[str] = []
    for page in reader.pages:
        for value in _case_numbers(page.extract_text() or ""):
            if value not in seen:
                seen.add(value)
                result.append(value)
    return tuple(result)


def refine_case_page_range(
    source_pdf: Path,
    *,
    hint_start: int,
    hint_end: int,
    expected_case_number: str | None = None,
    max_case_pages: int = 20,
) -> tuple[int, int, JudgmentMetadata]:
    """Tighten a non-authoritative page hint to one explicitly labelled judgment.

    This function is used for web/discovery hints.  Catalog ranges produced by
    the current catalog parser are already exact physical PDF ranges and are
    extracted directly after their source SHA-256 is matched.
    """
    reader = PdfReader(str(source_pdf), strict=False)
    total = len(reader.pages)
    if hint_start < 1 or hint_end < hint_start or hint_start > total:
        raise PdfValidationError("Invalid catalog page-range hint")
    hint_end = min(hint_end, total)
    expected = normalize_case_number(expected_case_number) if expected_case_number else None

    left = max(0, hint_start - 3)
    right = min(total, max(hint_start + max_case_pages + 2, hint_start + 3))
    texts: dict[int, str] = {
        index: (reader.pages[index].extract_text() or "")
        for index in range(left, right)
    }

    headers: list[tuple[int, str]] = []
    for index in range(left, right):
        numbers = _case_numbers(texts[index][:8000])
        if numbers:
            headers.append((index, numbers[0]))
    if not headers:
        raise PdfValidationError("No explicit case header found near page-range hint")

    chosen: tuple[int, str] | None = None
    if expected:
        chosen = next((item for item in headers if item[1] == expected), None)
    if chosen is None:
        in_hint = [item for item in headers if hint_start - 1 <= item[0] <= hint_end - 1]
        chosen = min(in_hint or headers, key=lambda item: abs(item[0] - (hint_start - 1)))

    start_index, canonical_case = chosen
    hard_end = min(total - 1, start_index + max(1, max_case_pages) - 1)
    for index in range(start_index, hard_end + 1):
        if index not in texts:
            texts[index] = reader.pages[index].extract_text() or ""

    end_index = hard_end
    for index in range(start_index + 1, hard_end + 1):
        numbers = _case_numbers(texts[index][:8000])
        if numbers and canonical_case not in numbers:
            end_index = index - 1
            break

    end_index = min(end_index, max(start_index, hint_end - 1))
    while end_index > start_index and _is_decorative_page(texts.get(end_index, "")):
        end_index -= 1

    metadata_text = "\n".join(
        texts.get(index, "")
        for index in range(start_index, min(end_index + 1, start_index + 4))
    )
    metadata = extract_judgment_metadata(metadata_text)
    if metadata.case_number and metadata.case_number != canonical_case:
        raise PdfValidationError("Conflicting case numbers in official judgment header")
    if metadata.case_number is None:
        metadata = JudgmentMetadata(case_number=canonical_case)
    return start_index + 1, end_index + 1, metadata


def locate_case_page_range(source_pdf: Path, case_number: str, *, max_case_pages: int = 20) -> tuple[int, int]:
    """Locate one explicitly labelled case inside an official compilation."""
    expected = normalize_case_number(case_number)
    if not expected:
        raise PdfValidationError("Case number has no stable token for compilation lookup")
    reader = PdfReader(str(source_pdf), strict=False)
    total = len(reader.pages)
    start_index: int | None = None
    for index in range(total):
        text = reader.pages[index].extract_text() or ""
        if expected in _case_numbers(text[:8000]):
            start_index = index
            break
    if start_index is None:
        raise PdfValidationError("Case number was not found as an explicit case header")

    hard_end = min(total - 1, start_index + max(1, max_case_pages) - 1)
    end_index = hard_end
    trailing_texts: dict[int, str] = {}
    for index in range(start_index + 1, hard_end + 1):
        text = reader.pages[index].extract_text() or ""
        trailing_texts[index] = text
        numbers = _case_numbers(text[:8000])
        if numbers and expected not in numbers:
            end_index = index - 1
            break
    while end_index > start_index:
        text = trailing_texts.get(end_index)
        if text is None:
            text = reader.pages[end_index].extract_text() or ""
        if not _is_decorative_page(text):
            break
        end_index -= 1
    return start_index + 1, end_index + 1


def verify_case_number_in_pdf(path: Path, case_number: str) -> bool:
    expected = normalize_case_number(case_number)
    if not expected:
        return False
    reader = PdfReader(str(path), strict=False)
    explicit_numbers: list[str] = []
    for page in reader.pages:
        explicit_numbers.extend(_case_numbers((page.extract_text() or "")[:8000]))
    if explicit_numbers:
        return expected in explicit_numbers

    # Legacy standalone judgments may not have a metadata table. Only in that
    # situation do we fall back to token matching in the body text.
    tokens = _case_number_tokens(case_number)
    return any(_tokens_match(page.extract_text() or "", tokens) for page in reader.pages)


def _case_numbers(text: str) -> tuple[str, ...]:
    return labeled_case_numbers(text)


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


def _digits(value: str | None) -> str | None:
    return normalize_case_number(value)


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .،:-")[:180]


def _is_decorative_page(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) < 220:
        return True
    legal_signals = ("المدعي", "المدعى", "المحكمة", "القاضي", "القايض", "الحكم", "القرار", "الدعوى")
    return len(normalized) < 420 and not any(signal in normalized for signal in legal_signals)
