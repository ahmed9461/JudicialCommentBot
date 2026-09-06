"""Shared parsing primitives for official Saudi judicial PDF headers.

A crucial distinction in judicial compilations is the difference between a
*primary case header* (the metadata block that starts one published judgment)
and case numbers merely cited inside the body of another judgment. Catalog
boundary detection and runtime verification use the primary-header parser;
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
_FIRST_INSTANCE_MARKERS = (
    "محكمة الدرجة الأولى",
    "محكمة الدرجه الأولى",
    "محكمة الدرجة الاولي",
)
_STRUCTURED_MARKERS = (
    *_FIRST_INSTANCE_MARKERS,
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

    This API intentionally includes references in judgment bodies. It must not
    be used to create compilation boundaries; use ``primary_judicial_header``.
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

    Narrative text such as ``صدر حكم ... في القضية رقم ...`` is rejected. A
    case identifier must occur in the leading metadata zone and be accompanied
    by either a first-instance court label or multiple other structured labels.
    This accepts official summary pages that omit an appeal block while keeping
    body references out of boundary detection.
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
    first_instance = any(marker in sample for marker in _FIRST_INSTANCE_MARKERS)
    committee_context = any(marker in sample for marker in _COMMITTEE_MARKERS)

    matches: list[tuple[int, str]] = []
    for pattern in _CASE_PATTERNS:
        for match in pattern.finditer(sample):
            if match.start() > _CASE_LABEL_MAX_OFFSET:
                continue
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3:
                matches.append((match.start(), value))

    if matches:
        matches.sort(key=lambda item: item[0])
        offset, value = matches[0]
        # ``محكمة الدرجة الأولى`` + an early explicit case label is itself a
        # strong publication-header signature. Some official entries do not
        # include appeal metadata on the first summary page. Body references do
        # not have this first-instance label, so this does not weaken the main
        # boundary invariant.
        if first_instance and offset <= 1100:
            return JudicialHeader(
                case_number=value,
                confidence=max(4, marker_count + 3),
                source="case",
            )
        confidence = marker_count + (2 if offset <= 900 else 1)
        if marker_count >= 2 and confidence >= 4:
            return JudicialHeader(case_number=value, confidence=confidence, source="case")

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
