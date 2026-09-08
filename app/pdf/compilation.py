"""Locate, verify and extract original pages from official judicial compilations.

All textual decisions in this module use the same dual-engine text extraction
pipeline as catalog indexing. PDF page extraction itself still copies original
page objects with pypdf; no judgment is re-rendered or reconstructed.
"""

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
from .text import extract_pdf_page_texts

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ID = r"[0-9٠-٩۰-۹A-Za-z/\.\-قسهـ]{2,80}"
_DECISION_LABELS = (
    re.compile(rf"رقم\s*قرار\s*لجنة\s*الفصل\s*[:：\-]?\s*[\(\)（）]*({_ID})", re.I),
    re.compile(rf"رقم\s*القرار\s*الابتدائي\s*[:：\-]?\s*[\(\)（）]*({_ID})", re.I),
    re.compile(rf"قرار\s*رقم\s*[:：\-]?\s*[\(\)（）]*({_ID})", re.I),
    re.compile(rf"رقم\s*القرار\s*[:：\-]?\s*[\(\)（）]*({_ID})", re.I),
    re.compile(rf"رقم\s*قرار\s*التصديق\s*[:：\-]?\s*[\(\)（）]*({_ID})", re.I),
    re.compile(rf"قرار\s*التصديق\s*رقم\s*[:：\-]?\s*[\(\)（）]*({_ID})", re.I),
)
_DECISION_DATES = (
    re.compile(
        rf"(?:رقم\s*القرار(?:\s*الابتدائي)?|رقم\s*قرار\s*التصديق|قرار\s*التصديق\s*رقم|قرار\s*رقم)"
        rf"\s*[:：\-]?\s*[\(\)（）]*{_ID}[\(\)（）]*.{{0,160}}?"
        r"(?:تاريخه|تاريخ(?:ه)?|تاريخ\s*صدور\s*القرار(?:\s*الابتدائي)?)\s*[:：\-]?\s*([0-9٠-٩۰-۹/\-]{6,})",
        re.I | re.S,
    ),
)
_CASE_YEAR = re.compile(
    rf"(?:رقم\s*)?(?:القضية|القضيـة|الدعوى|الدعـوى)(?:\s*(?:في\s*المحكمة\s*الإدارية|لدى\s*لجنة\s*الفصل))?(?:\s*رقم)?"
    rf"\s*[:：\-]?\s*[\(\)（）]*{_ID}[\(\)（）]*.{{0,120}}?"
    r"(?:تاريخها|تاريخ(?:ها)?|لعام|عام)\s*[:：\-]?\s*(14[0-9٠-٩۰-۹]{2})",
    re.I | re.S,
)
_FIRST_COURT = re.compile(r"محكمة\s*الدرجة\s*الأولى\s*[:：\-]?\s*([^\n]{3,180})", re.I)
_APPEAL_COURT = re.compile(r"محكمة\s*الاستئناف\s*[:：\-]?\s*([^\n]{3,180})", re.I)
_BOG_COURT = re.compile(r"رقم\s*القضية\s*في\s*(المحكمة\s*الإدارية(?:\s*ب[^\n\d]{2,80})?)", re.I)
_IDC_COURT = re.compile(r"قرار\s+(اللجنة\s*الابتدائية[^\n]{0,100})", re.I)
_GSTC_COURT = re.compile(r"^(الدائرة\s+(?:الاستئنافية|االستئنافية|الأولى|الثانية)[^\n]{8,180})$", re.I | re.M)
_CRSD_COURT = re.compile(r"(لجنة\s*(?:الفصل|الاستئناف)\s*في\s*منازعات\s*الأوراق\s*المالية)", re.I)
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
    """Extract metadata from the leading official judgment publication header."""
    sample = text[:9000]
    variants = (sample, "\n".join(line[::-1] for line in sample.splitlines()))
    primary = primary_judicial_header(sample)
    if require_primary_header and primary is None:
        raise PdfValidationError("Judgment extract does not start with a primary judicial header")
    case_number = primary.case_number if primary else first_labeled_case_number(sample)

    decision_number = None
    decision_date = None
    year = None
    court_name = None
    appeal_name = None
    for variant in variants:
        if decision_number is None:
            decision_number = _first_group(_DECISION_LABELS, variant)
        if decision_date is None:
            decision_date = _first_group(_DECISION_DATES, variant)
        if year is None:
            year_match = _CASE_YEAR.search(variant.translate(_ARABIC_DIGITS))
            year = _digits(year_match.group(1)) if year_match else None
        if court_name is None:
            first_court_match = _FIRST_COURT.search(variant)
            court_name = _court_label(first_court_match.group(1)) if first_court_match else None
        if court_name is None:
            for pattern in (_BOG_COURT, _IDC_COURT, _GSTC_COURT, _CRSD_COURT):
                match = pattern.search(variant)
                if match:
                    court_name = _court_label(match.group(1))
                    if court_name:
                        break
        if appeal_name is None:
            appeal_match = _APPEAL_COURT.search(variant)
            appeal_name = _court_label(appeal_match.group(1)) if appeal_match else None

    return JudgmentMetadata(
        case_number=case_number,
        court_name=court_name,
        judgment_year=year,
        decision_number=_digits(decision_number),
        decision_date=_digits(decision_date),
        appeal_court_name=appeal_name,
    )


def extract_judgment_metadata_from_pdf(path: Path, *, require_primary_header: bool = False) -> JudgmentMetadata:
    texts = extract_pdf_page_texts(path)
    if not texts:
        raise PdfValidationError("Judgment PDF has no pages")
    first = texts[0]
    if require_primary_header:
        return extract_judgment_metadata(first, require_primary_header=True)
    second = texts[1] if len(texts) > 1 else ""
    return extract_judgment_metadata(first + "\n" + second)


def primary_case_numbers_in_pdf(path: Path) -> tuple[str, ...]:
    """Return primary case-start identifiers, ignoring body references."""
    result: list[str] = []
    for text in extract_pdf_page_texts(path):
        header = primary_judicial_header(text)
        if header and header.case_number not in result:
            result.append(header.case_number)
    return tuple(result)


def validate_extracted_judgment_pdf(path: Path, expected_case_number: str | None) -> JudgmentMetadata:
    """Hard gate for a page extract before it can be treated as one judgment."""
    expected = normalize_case_number(expected_case_number) if expected_case_number else None
    texts = extract_pdf_page_texts(path)
    if not texts:
        raise PdfValidationError("Extracted judgment PDF has no pages")

    first_text = texts[0]
    first_header = primary_judicial_header(first_text)
    if first_header is None:
        raise PdfValidationError("Extracted judgment does not begin at a primary case header")
    if expected and first_header.case_number != expected:
        raise PdfValidationError(
            f"Extracted judgment starts with case {first_header.case_number}, expected {expected}"
        )

    canonical = first_header.case_number
    for index, text in enumerate(texts[1:], start=2):
        header = primary_judicial_header(text)
        if header and header.case_number != canonical:
            raise PdfValidationError(
                f"Extracted judgment contains another primary case header on page {index}: {header.case_number}"
            )

    metadata = extract_judgment_metadata(first_text, require_primary_header=True)
    if metadata.case_number != canonical:
        raise PdfValidationError("Canonical metadata does not match the primary case header")
    return metadata


def labeled_case_numbers_in_pdf(path: Path) -> tuple[str, ...]:
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
    texts = extract_pdf_page_texts(source_pdf)
    total = len(texts)
    if hint_start < 1 or hint_end < hint_start or hint_start > total:
        raise PdfValidationError("Invalid catalog page-range hint")
    hint_end = min(hint_end, total)
    expected = normalize_case_number(expected_case_number) if expected_case_number else None

    left = max(0, hint_start - 3)
    right = min(total, max(hint_end + 3, hint_start + max_case_pages + 2))
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

    while end_index > start_index and _is_decorative_page(texts[end_index]):
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
    texts = extract_pdf_page_texts(source_pdf)
    total = len(texts)
    start_index: int | None = None
    for index, text in enumerate(texts):
        header = primary_judicial_header(text)
        if header and header.case_number == expected:
            start_index = index
            break
    if start_index is None:
        raise PdfValidationError("Case number was not found in a primary case header")

    hard_end = min(total - 1, start_index + max(1, max_case_pages) - 1)
    end_index = hard_end
    for index in range(start_index + 1, hard_end + 1):
        header = primary_judicial_header(texts[index])
        if header and header.case_number != expected:
            end_index = index - 1
            break
    while end_index > start_index and _is_decorative_page(texts[end_index]):
        end_index -= 1
    return start_index + 1, end_index + 1


def verify_case_number_in_pdf(path: Path, case_number: str) -> bool:
    expected = normalize_case_number(case_number)
    if not expected:
        return False
    texts = extract_pdf_page_texts(path)
    if not texts:
        return False

    first_header = primary_judicial_header(texts[0])
    primary: list[str] = []
    for text in texts:
        header = primary_judicial_header(text)
        if header:
            primary.append(header.case_number)
    if primary:
        return (
            first_header is not None
            and first_header.case_number == expected
            and all(value == expected for value in primary)
        )

    explicit_numbers: list[str] = []
    for text in texts:
        explicit_numbers.extend(labeled_case_numbers(text[:8000]))
    if explicit_numbers:
        return expected in explicit_numbers

    tokens = _case_number_tokens(case_number)
    return any(_tokens_match(text, tokens) for text in texts)


def _first_group(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


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
    # Committee/district labels are canonical adjudicating bodies too.
    if not any(token in cleaned for token in ("محكمة", "لجنة", "اللجنة", "دائرة", "الدائرة")):
        return None
    return cleaned


def _is_decorative_page(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) < 220:
        return True
    legal_signals = ("المدعي", "المدعى", "المحكمة", "القاضي", "القايض", "الحكم", "القرار", "الدعوى")
    return len(normalized) < 420 and not any(signal in normalized for signal in legal_signals)
