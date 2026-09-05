"""Shared parsing primitives for official Saudi judicial PDF headers.

The catalog indexer and the runtime verifier must use the same parser.  A case
that can be indexed must therefore also be verifiable later; this prevents
parser drift from producing catalog rows that the delivery workflow rejects.
"""

from __future__ import annotations

import re

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


def normalize_case_number(value: str | None) -> str | None:
    if value is None:
        return None
    translated = value.translate(_ARABIC_DIGITS).replace("ـ", "")
    compact = _SPACES.sub("", translated).strip("-:/،. ")
    if not compact or not any(ch.isdigit() for ch in compact):
        return None
    return compact


def labeled_case_numbers(text: str, *, allow_committee_decision: bool = True) -> tuple[str, ...]:
    """Return explicitly-labelled judicial identifiers in document order.

    Some official PDFs expose Arabic text in visual rather than logical order.
    We first parse the original extraction.  Only if it contains no labelled
    identifier do we try a per-line reversed variant, avoiding duplicate or
    reversed identifiers when the normal extraction is already correct.
    """

    direct = _scan(text, allow_committee_decision=allow_committee_decision)
    if direct:
        return direct
    reversed_lines = "\n".join(line[::-1] for line in text.splitlines())
    return _scan(reversed_lines, allow_committee_decision=allow_committee_decision)


def first_labeled_case_number(text: str, *, allow_committee_decision: bool = True) -> str | None:
    values = labeled_case_numbers(text, allow_committee_decision=allow_committee_decision)
    return values[0] if values else None


def has_judicial_header(text: str) -> bool:
    return bool(labeled_case_numbers(text))


def _scan(text: str, *, allow_committee_decision: bool) -> tuple[str, ...]:
    sample = text[:8000]
    result: list[str] = []
    for pattern in _CASE_PATTERNS:
        for match in pattern.finditer(sample):
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3 and value not in result:
                result.append(value)
    if result:
        return tuple(result)

    if allow_committee_decision and any(marker in sample for marker in _COMMITTEE_MARKERS):
        for match in _DECISION_PATTERN.finditer(sample):
            value = normalize_case_number(match.group(1))
            if value and len(value) >= 3 and value not in result:
                result.append(value)
    return tuple(result)
