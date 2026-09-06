"""Locate, verify and extract original pages from official judicial compilation PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .errors import PdfValidationError
from .headers import (
    first_labeled_case_number,
    labeled_case_numbers,
    normalize_case_number,
    primary_judicial_header,
)

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
_BAD_COURT_VALUES = {"بعد", "وقد", "رقم", "تاريخ", "تاريخه", "الموافق", "في", "من"}


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


def extract_judgment_metadata(text: str, *, require_primary_header: bool = False) -> JudgmentMetadata:
    """Extract metadata from the leading official judgment header."""
    sample = text[:5000]
    primary = primary_judicial_header(sample)
    if require_primary_header and primary is None:
        raise PdfValidationError("Judgment extract does not start with a primary judicial header")
    case_number = primary.case_number if primary else first_labeled_case_number(sample)
    decision_match = _DECISION_LABEL.search(sample)
    decision_date_match = _DECISION_DATE.search(sample)
    year_match = _CASE_YEAR.search(sample.translate(_ARABIC_DIGITS))
    first_court_match = _FIRST_COURT.search(sample)
    appeal_match = _APPEAL_COURT.search(sample)
    return JudgmentMetadata(
        case_number=case_number,
        court_name=_court_label(first_court_match.group(1)) if first_court_match else None,
        judgment_year=_digits(year_match.group(1)) if year_match else None,
        decision_number=_digits(decision_match.group(1)) if decision_match else None,
        decision_date=_digits(decision_date_match.group(1)) if decision_date_match else None,
        appeal_court_name=_court_label(appeal_match.group(1)) if appeal_match else None,
    )


def extract_judgment_metadata_from_pdf(path: Path, *, require_primary_header: bool = False) -> JudgmentMetadata:
    reader = PdfReader(str(path), strict=False)
    if not reader.pages:
        raise PdfValidationError("Judgment PDF has no pages")
    first = reader.pages[0].extract_text() or ""
    if require_primary_header:
        return extract_judgment_metadata(first, require_primary_header=True)
    second = reader.pages[1].extract_text() or "" if len(reader.pages) > 1 else ""
    return extract_judgment_metadata(first + "\n" + second)


def primary_case_numbers_in_pdf(path: Path) -> tuple[str, ...]:
    """Return primary case-start identifiers, ignoring references in judgment bodies."""
    reader = PdfReader(str(path), strict=False)
    result: list[str] = []
    for page in reader.pages:
        header = primary_judicial_header(page.extract_text() or "")
        if header and header.case_number not in result:
            result.append(header.case_number)
    return tuple(result)


def validate_extracted_judgment_pdf(path: Path, expected_case_number: str | None) -> JudgmentMetadata:
    """Hard gate for a page extract before it can be treated as one judgment."""
    expected = normalize_case_number(expected_case_number) if expected_case_number else None
    reader = PdfReader(str(path), strict=False)
    if not reader.pages:
        raise PdfValidationError("Extracted judgment PDF has no pages")

    first_text = reader.pages[0].extract_text() or ""
    first_header = primary_judicial_header(first_text)
    if first_header is None:
        raise PdfValidationError("Extracted judgment does not begin at a primary case header")
    if expected and first_header.case_number != expected:
        raise PdfValidationError(
            f"Extracted judgment starts with case {first_header.case_number}, expected {expected}"
        )

    canonical = first_header.case_number
    for index, page in enumerate(reader.pages[1:], start=2):
        header = primary_judicial_header(page.extract_text() or "")
        if header and header.case_number != canonical:
            raise PdfValidationError(
                f"Extracted judgment contains another primary case header on page {index}: {header.case_number}"
            )

    metadata = extract_judgment_metadata(first_text, require_primary_header=True)
    if metadata.case_number != canonical:
        raise PdfValidationError("Canonical metadata does not match the primary case header")
    return metadata


def labeled_case_numbers_in_pdf(path: Path) -> tuple[str, ...]:
    """Return primary judgment identifiers for PDF-level boundary checks.

    Historically this helper returned every body reference too, which caused
    legitimate judgments that cited another case to be rejected while still
    allowing a wrongly prefixed extract.  PDF-level identity checks need primary
    headers, so the compatibility name now delegates to the boundary-aware
    implementation.
    """
    return primary_case_numbers_in_pdf(path)


def refine_case_page_range(
    source_pdf: Path,
    *,
    hint_start: int,
    hint_end: int,
    expected_case_number: str | None = None,
    max_case_pages: int = 20,
) -> tuple[int, int, JudgmentMetadata]:
    """Tighten a non-authoritative page hint to one primary judicial judgment."""
    reader = PdfReader(str(source_pdf), strict=False)
    total = len(reader.pages)
    if hint_start < 1 or hint_end < hint_start or hint_start > total:
        raise PdfValidationError("Invalid catalog page-range hint")
    hint_end = min(hint_end, total)
    expected = normalize_case_number(expected_case_number) if expected_case_number else None

    left = max(0, hint_start - 3)
    right = min(total, max(hint_end + 3, hint_start + max_case_pages + 2))
    texts: dict[int, str] = {
        index: (reader.pages[index].extract_text() or "")
        for index in range(left, right)
    }

    headers: list[tuple[int, str]] = []
    for index in range(left, right):
        header = primary_judicial_header(texts[index])
        if header:
            headers.append((index, header.case_number))
    if not headers:
        raise PdfValidationError("No primary case header found near page-range hint")

    chosen: tuple[int, str] | None = None
    if expected:
        chosen = next((item for item in headers if item[1] == expected), None)
    if chosen is None:
        in_hint = [item for item in headers if hint_start - 1 <= item[0] <= hint_end - 1]
        chosen = min(in_hint or headers, key=lambda item: abs(item[0] - (hint_start - 1)))

    start_index, canonical_case = chosen
    later = [index for index, number in headers if index > start_index and number != canonical_case]
    if later:
        end_index = min(later) - 1
    else:
        end_index = min(total - 1, start_index + max(1, max_case_pages) - 1, hint_end - 1)

    while end_index > start_index:
        text = texts.get(end_index)
        if text is None:
            text = reader.pages[end_index].extract_text() or ""
        if not _is_decorative_page(text):
            break
        end_index -= 1

    metadata = extract_judgment_metadata(texts[start_index], require_primary_header=True)
    if metadata.case_number != canonical_case:
        raise PdfValidationError("Conflicting case number in primary judgment header")
    return start_index + 1, end_index + 1, metadata


def locate_case_page_range(source_pdf: Path, case_number: str, *, max_case_pages: int = 20) -> tuple[int, int]:
    """Locate one primary case header inside an official compilation."""
    expected = normalize_case_number(case_number)
    if not expected:
        raise PdfValidationError("Case number has no stable token for compilation lookup")
    reader = PdfReader(str(source_pdf), strict=False)
    total = len(reader.pages)
    start_index: int | None = None
    for index in range(total):
        header = primary_judicial_header(reader.pages[index].extract_text() or "")
        if header and header.case_number == expected:
            start_index = index
            break
    if start_index is None:
        raise PdfValidationError("Case number was not found in a primary case header")

    hard_end = min(total - 1, start_index + max(1, max_case_pages) - 1)
    end_index = hard_end
    for index in range(start_index + 1, hard_end + 1):
        text = reader.pages[index].extract_text() or ""
        header = primary_judicial_header(text)
        if header and header.case_number != expected:
            end_index = index - 1
            break
    while end_index > start_index:
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
    if not reader.pages:
        return False

    first_header = primary_judicial_header(reader.pages[0].extract_text() or "")
    primary: list[str] = []
    for page in reader.pages:
        header = primary_judicial_header(page.extract_text() or "")
        if header:
            primary.append(header.case_number)
    if primary:
        # If any structured primary header exists, the extract must start on it.
        # This prevents [tail of previous case + target case] from passing merely
        # because the target identifier appears on a later page.
        return (
            first_header is not None
            and first_header.case_number == expected
            and all(value == expected for value in primary)
        )

    explicit_numbers: list[str] = []
    for page in reader.pages:
        explicit_numbers.extend(labeled_case_numbers((page.extract_text() or "")[:8000]))
    if explicit_numbers:
        return expected in explicit_numbers

    tokens = _case_number_tokens(case_number)
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


def _digits(value: str | None) -> str | None:
    return normalize_case_number(value)


def _court_label(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" .،:-")[:180]
    normalized = cleaned.translate(_ARABIC_DIGITS).strip().casefold()
    if len(cleaned) < 6 or normalized in _BAD_COURT_VALUES:
        return None
    if not any(token in cleaned for token in ("محكمة", "لجنة", "دائرة", "الدائرة")):
        return None
    return cleaned


def _is_decorative_page(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) < 220:
        return True
    legal_signals = ("المدعي", "المدعى", "المحكمة", "القاضي", "القايض", "الحكم", "القرار", "الدعوى")
    return len(normalized) < 420 and not any(signal in normalized for signal in legal_signals)
