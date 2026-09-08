"""Shared parsing primitives for official Saudi judicial PDF headers.

Saudi judicial publishers use several stable but different publication grammars.
This module recognizes those grammars explicitly instead of forcing every source
through one generic ``رقم القضية`` pattern. The same parser is used by catalog
indexing and runtime verification, so source-specific support does not weaken the
single-source-of-truth invariant for judgment boundaries.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SPACES = re.compile(r"\s+")
_DIACRITICS = re.compile(r"[ًٌٍَُِّْـ]")
_ID = r"[0-9٠-٩۰-۹A-Za-z\u0600-\u06ff/\.\-\s]{2,80}"
_SIMPLE_ID = r"[0-9٠-٩۰-۹A-Za-z/\.\-]{2,60}"

_CASE_PATTERNS = (
    re.compile(
        rf"(?:رقم\s*(?:القضية|القضيـة|الدعوى|الدعـوى)|"
        rf"(?:القضية|القضيـة|الدعوى|الدعـوى)\s*(?:رقم)?)"
        rf"\s*[:：\-]?\s*[\(\)（）]*({_SIMPLE_ID})",
        re.I,
    ),
    re.compile(
        rf"(?:القضية|القضيـة|الدعوى|الدعـوى)\s*[:：\-]\s*[\(\)（）]*({_SIMPLE_ID})",
        re.I,
    ),
)
_BOG_CASE_PATTERN = re.compile(
    rf"رقم\s*القضية\s*في\s*المحكمة\s*الإدارية\s*[:：\-]?\s*({_ID}?)"
    rf"(?=\s*(?:لعام|عام|رقم\s*القضية\s*في\s*محكمة\s*الاستئناف|تاريخ\s*الجلسة|الموضوعات|مستند\s*الحكم|$))",
    re.I | re.S,
)
_CRSD_CASE_PATTERN = re.compile(
    rf"رقم\s*القضية\s*(?:لدى|أمام)\s*لجنة\s*الفصل(?:\s*في\s*منازعات\s*الأوراق\s*المالية)?"
    rf"\s*[:：\-]?\s*[\(\)（）]*({_SIMPLE_ID})",
    re.I,
)
_GSTC_APPEAL_PATTERN = re.compile(
    rf"(?:الاستئناف|االستئناف)\s*(?:المقيد)?\s*برقم\s*[:：\-]?\s*[\(\)（）]*({_SIMPLE_ID})",
    re.I,
)
_GSTC_CASE_PATTERN = re.compile(
    rf"(?:رقم\s*الدعوى|الدعوى\s*رقم)\s*[:：\-]?\s*[\(\)（）]*({_SIMPLE_ID})",
    re.I,
)
_DECISION_PATTERN = re.compile(
    rf"(?:رقم\s*(?:القرار|قرار)|(?:القرار|قرار)\s*رقم)\s*[:：\-]?\s*[\(\)（）]*({_SIMPLE_ID})",
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
_BOG_MARKERS = (
    "رقم القضية في المحكمة الادارية",
    "رقم القضية في محكمة الاستئناف الادارية",
    "الموضوعات",
    "مستند الحكم",
    "الاسباب",
)
_CRSD_MARKERS = (
    "لجنة الفصل في منازعات الاوراق المالية",
    "لجنة الاستئناف في منازعات الاوراق المالية",
    "رقم قرار لجنة الفصل",
    "نوع الدعوى",
    "التصنيف",
)
_IDC_MARKERS = (
    "لجان الفصل في المنازعات والمخالفات التامينية",
    "قرار اللجنة الابتدائية",
    "رقم القرار الابتدائي",
    "نوع الوثيقة",
    "التصنيف الموضوعي",
)
_GSTC_MARKERS = (
    "الزكاة والضريبة والجمارك",
    "مخالفات ومنازعات ضريبة",
    "اللجنة الجمركية",
    "دائرة الفصل",
    "الدائرة الاستئنافية",
    "الدائرة االستئنافية",
    "منطوق القرار",
)
_COMMITTEE_MARKERS = tuple(dict.fromkeys((*_CRSD_MARKERS, *_IDC_MARKERS, *_GSTC_MARKERS)))
_HEADER_MAX_CHARS = 7200
_HEADER_MAX_LINES = 100
_CASE_LABEL_MAX_OFFSET = 4600


@dataclass(frozen=True, slots=True)
class JudicialHeader:
    case_number: str
    confidence: int
    source: str = "case"


def normalize_case_number(value: str | None) -> str | None:
    if value is None:
        return None
    translated = unicodedata.normalize("NFKC", value).translate(_ARABIC_DIGITS).replace("ـ", "")
    translated = translated.replace("(", "").replace(")", "").replace("（", "").replace("）", "")
    compact = _SPACES.sub("", translated).strip("-:/،. ")
    compact = re.sub(r"(?:هـ|ه)$", "", compact)
    if not compact or not any(ch.isdigit() for ch in compact):
        return None
    # Publication labels occasionally bleed into a greedy text-layer match.
    compact = re.split(r"(?:لعام|تاريخ|الموضوعات|مستندالحكم)", compact, maxsplit=1)[0]
    return compact[:80] or None


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


def _first_normalized(pattern: re.Pattern[str], sample: str) -> tuple[int, str] | None:
    match = pattern.search(sample)
    if not match or match.start() > _CASE_LABEL_MAX_OFFSET:
        return None
    value = normalize_case_number(match.group(1))
    if not value or len(value) < 2:
        return None
    return match.start(), value


def _primary_scan(text: str) -> JudicialHeader | None:
    sample = _leading_sample(text)
    if not sample:
        return None
    normalized = _normalize_search(sample)

    modern_hits = {marker for marker in _MODERN_MARKERS if _marker_present(normalized, marker)}
    legacy_hits = {marker for marker in _LEGACY_MARKERS if _marker_present(normalized, marker)}
    bog_hits = {marker for marker in _BOG_MARKERS if _marker_present(normalized, marker)}
    crsd_hits = {marker for marker in _CRSD_MARKERS if _marker_present(normalized, marker)}
    idc_hits = {marker for marker in _IDC_MARKERS if _marker_present(normalized, marker)}
    gstc_hits = {marker for marker in _GSTC_MARKERS if _marker_present(normalized, marker)}
    committee_hits = crsd_hits | idc_hits | gstc_hits

    # Board of Grievances publications identify the case as
    # "رقم القضية في المحكمة الإدارية ... لعام ...".
    bog = _first_normalized(_BOG_CASE_PATTERN, sample)
    if bog and len(bog_hits) >= 2:
        return JudicialHeader(bog[1], 10 + len(bog_hits), "case-bog")

    # Securities decisions have a stable table label distinct from ordinary
    # court publications.
    crsd = _first_normalized(_CRSD_CASE_PATTERN, sample)
    if crsd and len(crsd_hits) >= 2:
        return JudicialHeader(crsd[1], 10 + len(crsd_hits), "case-crsd")

    # GSTC immediate-publication decisions frequently use an appeal identifier
    # rather than the literal label "رقم القضية" on page one.
    gstc_appeal = _first_normalized(_GSTC_APPEAL_PATTERN, sample)
    gstc_case = _first_normalized(_GSTC_CASE_PATTERN, sample)
    if len(gstc_hits) >= 2 and (gstc_appeal or gstc_case):
        identity = (gstc_appeal or gstc_case)[1]
        return JudicialHeader(identity, 9 + len(gstc_hits), "case-gstc")

    matches: list[tuple[int, str]] = []
    for pattern in _CASE_PATTERNS:
        for match in pattern.finditer(sample):
            if match.start() > _CASE_LABEL_MAX_OFFSET:
                continue
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 2:
                matches.append((match.start(), value))

    if matches:
        matches.sort(key=lambda item: item[0])
        offset, value = matches[0]

        if "محكمة الدرجة الاولى" in modern_hits and offset <= 2000:
            return JudicialHeader(value, 8 + len(modern_hits), "case-modern")

        # Insurance committee decisions expose رقم الدعوى beside رقم القرار
        # and document/classification fields.
        if len(idc_hits) >= 2 and offset <= 3000:
            return JudicialHeader(value, 9 + len(idc_hits), "case-idc")

        # Some CRSD exports use only the generic رقم القضية label but retain
        # the committee/table markers.
        if len(crsd_hits) >= 2 and offset <= 3000:
            return JudicialHeader(value, 9 + len(crsd_hits), "case-crsd")

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
        if offset <= 3600 and has_instrument and (has_legacy_heading or has_appeal_metadata) and legacy_confidence >= 5:
            return JudicialHeader(value, legacy_confidence, "case-legacy")

        structured_count = len(modern_hits | legacy_hits)
        if offset <= 2200 and structured_count >= 3:
            return JudicialHeader(value, structured_count + 3, "case-structured")

    if committee_hits:
        decision = _first_normalized(_DECISION_PATTERN, sample)
        if decision:
            return JudicialHeader(decision[1], 6 + len(committee_hits), "decision")
    return None


def _scan(text: str, *, allow_committee_decision: bool) -> tuple[str, ...]:
    sample = text[:12000]
    found: list[tuple[int, str]] = []
    for pattern in (_BOG_CASE_PATTERN, _CRSD_CASE_PATTERN, _GSTC_APPEAL_PATTERN, _GSTC_CASE_PATTERN, *_CASE_PATTERNS):
        for match in pattern.finditer(sample):
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 2:
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
            if value and len(value) >= 2 and value not in result:
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
