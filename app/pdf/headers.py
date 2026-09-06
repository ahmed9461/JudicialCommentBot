"""Shared parsing primitives for official Saudi judicial PDF headers.

A crucial distinction in judicial compilations is the difference between a
*primary case header* (the metadata block that starts one published judgment)
and case numbers merely cited inside the body of another judgment.  Catalog
boundary detection and runtime verification must use the primary-header parser;
body references are useful for metadata/search only and must never create case
boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SPACES = re.compile(r"\s+")

_CASE_PATTERNS = (
    re.compile(
        r"(?:رقم\s*(?:القضية|القضيـة|الدعوى|الدعـوى)|(?:القضية|القضيـة|الدعوى|الدعـوى)\s*رقم)"
        r"\s*[:：\-]?\s*([0-9٠-٩۰-۹][0-9٠-٩۰-۹/\-ق\s]{2,40})",
        re.I,
    ),
    re.compile(
        r"(?:القضية|القضيـة|الدعوى|الدعـوى)\s*[:：\-]\s*"
        r"([0-9٠-٩۰-۹][0-9٠-٩۰-۹/\-ق\s]{2,40})",
        re.I,
    ),
)
_DECISION_PATTERN = re.compile(
    r"(?:رقم\s*القرار|القرار\s*رقم)\s*[:：\-]?\s*"
    r"([0-9٠-٩۰-۹][0-9٠-٩۰-۹/\-ق\s]{2,40})",
    re.I,
)
_COMMITTEE_MARKERS = ("لجنة", "اللجنة", "الدائرة الاستئنافية", "الأمانة العامة")

# Strong metadata labels used by Saudi official judicial publications.  These
# labels identify the summary/header block, unlike ordinary narrative text that
# may mention a different lawsuit, appeal or precedent.
_STRUCTURED_MARKERS = (
    "محكمة الدرجة الأولى",
    "محكمة الدرجه الأولى",
    "محكمة الدرجة الاولي",
    "محكمة الاستئناف",
    "رقم القرار",
    "الرقم التسلسلي",
    "السند الشرعي",
    "السند النظامي",
    "ملخص القضية",
    "ملخص الدعوى",
    "موضوع الدعوى",
    "الموضوعات",
)
_HEADER_MAX_CHARS = 2600
_HEADER_MAX_LINES = 36
_CASE_LABEL_MAX_OFFSET = 1700


@dataclass(frozen=True, slots=True)
class JudicialHeader:
    """One high-confidence primary judicial header found at the start of a page."""

    case_number: str
    confidence: int
    source: str = "case"


def normalize_case_number(value: str | None) -> str | None:
    if value is None:
        return None
    translated = value.translate(_ARABIC_DIGITS).replace("ـ", "")
    compact = _SPACES.sub("", translated).strip("-:/،. ")
    if not compact or not any(ch.isdigit() for ch in compact):
        return None
    return compact


def labeled_case_numbers(text: str, *, allow_committee_decision: bool = True) -> tuple[str, ...]:
    """Return explicitly-labelled judicial identifiers anywhere in the sample.

    This API intentionally includes references in judgment bodies.  It should
    not be used to create compilation boundaries; use ``primary_judicial_header``
    for that purpose.
    """

    direct = _scan(text, allow_committee_decision=allow_committee_decision)
    if direct:
        return direct
    reversed_lines = "\n".join(line[::-1] for line in text.splitlines())
    return _scan(reversed_lines, allow_committee_decision=allow_committee_decision)


def first_labeled_case_number(text: str, *, allow_committee_decision: bool = True) -> str | None:
    values = labeled_case_numbers(text, allow_committee_decision=allow_committee_decision)
    return values[0] if values else None


def primary_judicial_header(text: str) -> JudicialHeader | None:
    """Return the primary case header only when the page has header evidence.

    A sentence such as ``صدر حكم ... في القضية رقم ...`` inside a judgment is
    deliberately rejected.  The identifier must occur in the leading metadata
    zone and be accompanied by structured court/publication labels.  A reversed
    per-line view is attempted only when the normal extraction has no primary
    header, which handles Arabic PDFs extracted in visual order without
    corrupting normally extracted identifiers.
    """

    direct = _primary_scan(text)
    if direct is not None:
        return direct
    reversed_lines = "\n".join(line[::-1] for line in text.splitlines())
    return _primary_scan(reversed_lines)


def primary_case_number(text: str) -> str | None:
    header = primary_judicial_header(text)
    return header.case_number if header else None


def has_judicial_header(text: str) -> bool:
    """Compatibility helper: true only for a primary case-start header."""

    return primary_judicial_header(text) is not None


def _leading_sample(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sample = "\n".join(lines[:_HEADER_MAX_LINES])
    return sample[:_HEADER_MAX_CHARS]


def _primary_scan(text: str) -> JudicialHeader | None:
    sample = _leading_sample(text)
    if not sample:
        return None

    marker_count = sum(1 for marker in _STRUCTURED_MARKERS if marker in sample)
    committee_context = any(marker in sample for marker in _COMMITTEE_MARKERS)

    matches: list[tuple[int, str]] = []
    for pattern in _CASE_PATTERNS:
        for match in pattern.finditer(sample):
            if match.start() > _CASE_LABEL_MAX_OFFSET:
                continue
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3:
                matches.append((match.start(), value))

    # A Ministry/BOG-style case header normally has a case label plus at least
    # two other structured labels.  Requiring this prevents narrative references
    # from becoming false case starts.
    if matches:
        matches.sort(key=lambda item: item[0])
        offset, value = matches[0]
        confidence = marker_count + (2 if offset <= 900 else 1)
        if marker_count >= 2 and confidence >= 4:
            return JudicialHeader(case_number=value, confidence=confidence, source="case")

    # Some quasi-judicial publications identify the matter primarily by a
    # decision number.  Accept it only in an unmistakable committee header.
    if committee_context and marker_count >= 1:
        decision = _DECISION_PATTERN.search(sample)
        if decision and decision.start() <= _CASE_LABEL_MAX_OFFSET:
            value = normalize_case_number(decision.group(1))
            if value and len(value) >= 3:
                return JudicialHeader(
                    case_number=value,
                    confidence=marker_count + 3,
                    source="decision",
                )
    return None


def _scan(text: str, *, allow_committee_decision: bool) -> tuple[str, ...]:
    sample = text[:8000]
    found: list[tuple[int, str]] = []
    for pattern in _CASE_PATTERNS:
        for match in pattern.finditer(sample):
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3:
                found.append((match.start(), value))
    if found:
        found.sort(key=lambda item: item[0])
        result: list[str] = []
        for _, value in found:
            if value not in result:
                result.append(value)
        return tuple(result)

    if allow_committee_decision and any(marker in sample for marker in _COMMITTEE_MARKERS):
        result = []
        for match in _DECISION_PATTERN.finditer(sample):
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3 and value not in result:
                result.append(value)
        return tuple(result)
    return ()
