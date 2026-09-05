"""Conservative Arabic text normalization and judgment metadata extraction.

The catalog and runtime PDF verifier deliberately share the same explicit
judicial-header parser.  This guarantees that a row admitted to the catalog can
be recognized by the delivery pipeline later.
"""

from __future__ import annotations

import re

from app.pdf.headers import first_labeled_case_number

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u06D6-\u06ED]")
_SPACES = re.compile(r"\s+")
_YEAR_PATTERN = re.compile(r"(?:14[0-9]{2})\s*هـ?")
_COURT_PATTERNS = (
    re.compile(
        r"((?:المحكمة|محكمة)\s+(?:العامة|الجزائية|التجارية|الإدارية|العمالية|الأحوال\s+الشخصية|الاستئناف)[^\n]{0,90})"
    ),
    re.compile(r"((?:الدائرة|دائرة)\s+(?:الإدارية|التجارية|الجزائية)[^\n]{0,90})"),
    re.compile(r"((?:لجنة|اللجنة)\s+(?:الفصل|الاستئنافية)[^\n]{0,110})"),
)


def normalize_arabic(value: str) -> str:
    text = value.translate(_ARABIC_DIGITS)
    text = _DIACRITICS.sub("", text)
    text = text.replace("ـ", "")
    for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        text = text.replace(source, target)
    text = re.sub(r"[^0-9A-Za-z\u0600-\u06FF/\- ]+", " ", text)
    return _SPACES.sub(" ", text).strip().lower()


def detect_case_number(text: str) -> str | None:
    return first_labeled_case_number(text, allow_committee_decision=True)


def detect_judgment_year(text: str) -> str | None:
    sample = text[:7000].translate(_ARABIC_DIGITS)
    match = _YEAR_PATTERN.search(sample)
    return match.group(1) if match else None


def detect_court_name(text: str) -> str | None:
    sample = _SPACES.sub(" ", text[:8000])
    for pattern in _COURT_PATTERNS:
        match = pattern.search(sample)
        if match:
            return match.group(1).strip(" .،:-")[:180]
    return None


def make_title(text: str, case_number: str | None) -> str:
    lines = [_SPACES.sub(" ", line).strip(" .،:-") for line in text[:7000].splitlines()]
    ignored = (
        "مجموعه الاحكام",
        "وزاره العدل",
        "بسم الله",
        "رقم القضيه",
        "رقم الدعوى",
        "رقم الصك",
        "رقم القرار",
    )
    for line in lines:
        normalized = normalize_arabic(line)
        if 12 <= len(line) <= 180 and not any(token in normalized for token in ignored):
            if sum(ch.isalpha() for ch in line) >= 6:
                return line
    return f"قضية رقم {case_number}" if case_number else "حكم قضائي منشور"
