"""Shared parsing primitives for official Saudi judicial PDF headers.

Published Saudi judgments do not have one historical layout. Modern volumes
usually contain ``محكمة الدرجة الأولى`` / ``رقم القضية`` blocks, while older
Ministry of Justice compilations commonly begin with ``الصك`` / ``الدعوى`` /
``قرار التصديق`` plus headings such as ``الموضوعات`` and ``ملخص القضية``.
Committee decisions use a third layout based on a decision number.

Boundary detection recognizes those publication headers while rejecting case
numbers merely cited in the reasoning of another judgment.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SPACES = re.compile(r"\s+")
_DIACRITICS = re.compile(r"[ًٌٍَُِّْـ]")

_CASE_PATTERNS = (
    re.compile(
        r"(?:رقم\s*(?:القضية|القضيـة|الدعوى|الدعـوى)|"
        r"(?:القضية|القضيـة|الدعوى|الدعـوى)\s*(?:رقم)?)"
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
    r"(?:رقم\s*(?:القرار|قرار)|(?:القرار|قرار)\s*رقم)\s*[:：\-]?\s*"
    r"([0-9٠-٩۰-۹][0-9٠-٩۰-۹/\-ق\s]{2,40})",
    re.I,
)

_MODERN_MARKERS = (
    "محكمة الدرجة الاولى",
    "محكمة الاستئناف",
    "رقم القرار",
    "الرقم التسلسلي",
)
_LEGACY_MARKERS = (
    "رقم الصك",
    "الصك",
    "قرار التصديق",
    "رقم قرار التصديق",
    "محكمة الاستئناف",
    "الموضوعات",
    "السند الشرعي",
    "السند النظامي",
    "ملخص القضية",
    "ملخص الدعوى",
    "موضوع الدعوى",
)
_COMMITTEE_MARKERS = (
    "لجنة الفصل",
    "اللجنة الفصل",
    "اللجنة الابتدائية",
    "اللجنة الاستئنافية",
    "الدائرة الاستئنافية",
    "الامانة العامة",
)
_HEADER_MAX_CHARS = 3400
_HEADER_MAX_LINES = 48
_CASE_LABEL_MAX_OFFSET = 2200


@dataclass(frozen=True, slots=True)
class JudicialHeader:
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
    direct = _scan(text, allow_committee_decision=allow_committee_decision)
    if direct:
        return direct
    reversed_lines = "\n".join(line[::-1] for line in text.splitlines())
    return _scan(reversed_lines, allow_committee_decision=allow_committee_decision)


def first_labeled_case_number(text: str, *, allow_committee_decision: bool = True) -> str | None:
    values = labeled_case_numbers(text, allow_committee_decision=allow_committee_decision)
    return values[0] if values else None


def primary_judicial_header(text: str) -> JudicialHeader | None:
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
    normalized = _normalize_search(sample)

    modern_hits = {marker for marker in _MODERN_MARKERS if _marker_present(normalized, marker)}
    legacy_hits = {marker for marker in _LEGACY_MARKERS if _marker_present(normalized, marker)}
    committee_hits = {marker for marker in _COMMITTEE_MARKERS if _marker_present(normalized, marker)}

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

        if "محكمة الدرجة الاولى" in modern_hits and offset <= 1500:
            return JudicialHeader(value, 8 + len(modern_hits), "case-modern")

        has_instrument = _marker_present(normalized, "الصك")
        has_legacy_heading = any(
            _marker_present(normalized, marker)
            for marker in ("الموضوعات", "السند الشرعي", "السند النظامي", "ملخص القضية", "ملخص الدعوى")
        )
        has_appeal_metadata = (
            _marker_present(normalized, "قرار التصديق")
            or _marker_present(normalized, "محكمة الاستئناف")
        )
        legacy_confidence = len(legacy_hits) + (2 if has_instrument else 0) + (2 if has_legacy_heading else 0)
        if offset <= 1900 and has_instrument and (has_legacy_heading or has_appeal_metadata) and legacy_confidence >= 5:
            return JudicialHeader(value, legacy_confidence, "case-legacy")

        structured_count = len(modern_hits | legacy_hits)
        if offset <= 1400 and structured_count >= 3:
            return JudicialHeader(value, structured_count + 3, "case-structured")

    if committee_hits:
        decision = _DECISION_PATTERN.search(sample)
        if decision and decision.start() <= _CASE_LABEL_MAX_OFFSET:
            value = normalize_case_number(decision.group(1))
            if value and len(value) >= 3:
                return JudicialHeader(value, 6 + len(committee_hits), "decision")
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

    normalized = _normalize_search(sample)
    if allow_committee_decision and any(_marker_present(normalized, marker) for marker in _COMMITTEE_MARKERS):
        result = []
        for match in _DECISION_PATTERN.finditer(sample):
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3 and value not in result:
                result.append(value)
        return tuple(result)
    return ()


def _marker_present(normalized_text: str, marker: str) -> bool:
    return _normalize_search(marker) in normalized_text


def _normalize_search(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().replace("ـ", "")
    text = text.translate(_ARABIC_DIGITS)
    for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"), ("ة", "ه")):
        text = text.replace(source, target)
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[^0-9a-z\u0600-\u06ff]+", " ", text)
    return _SPACES.sub(" ", text).strip()
