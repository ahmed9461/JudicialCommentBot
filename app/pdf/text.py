"""Deterministic text extraction from verified judicial PDFs.

Saudi judicial publications span several PDF generations.  Some older Ministry
of Justice volumes use embedded fonts that pypdf cannot fully decode without
FontTools, while other files are extracted more faithfully by MuPDF.  Text
extraction is therefore a shared infrastructure concern rather than something
that each caller implements independently.

No OCR is performed here.  Both engines read the PDF's own text layer and the
best representation is selected per physical page using deterministic legal-
text signals.  Catalog indexing and runtime verification use the same output.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pymupdf
from pypdf import PdfReader

from .errors import PdfValidationError

_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_DIGIT_GROUP_RE = re.compile(r"[0-9٠-٩۰-۹]{3,}")
_SPACE_RE = re.compile(r"\s+")
_DIACRITICS_RE = re.compile(r"[ًٌٍَُِّْـ]")
_STRUCTURAL_SIGNALS = (
    "رقم القضية",
    "رقم الدعوى",
    "الدعوى",
    "رقم الصك",
    "الصك",
    "محكمة الدرجة الاولى",
    "محكمة الاستئناف",
    "رقم القرار",
    "قرار التصديق",
    "الموضوعات",
    "السند الشرعي",
    "السند النظامي",
    "ملخص القضية",
    "ملخص الدعوى",
    "المدعي",
    "المدعى عليه",
    "الحكم",
)


def extract_pdf_page_texts(path: Path) -> list[str]:
    """Return one selected text layer per physical PDF page.

    pypdf and PyMuPDF are both attempted.  A failure in one engine does not
    discard an otherwise valid official PDF.  Page order is never changed.
    """
    pypdf_pages = _extract_with_pypdf(path)
    mupdf_pages = _extract_with_mupdf(path)
    count = max(len(pypdf_pages), len(mupdf_pages))
    if count == 0:
        raise PdfValidationError("PDF has no pages")

    selected: list[str] = []
    for index in range(count):
        candidates: list[str] = []
        if index < len(pypdf_pages):
            candidates.append(pypdf_pages[index])
        if index < len(mupdf_pages):
            candidates.append(mupdf_pages[index])
        selected.append(_best_page_text(candidates))
    return selected


def extract_pdf_text(path: Path, *, max_chars: int) -> str:
    chunks: list[str] = []
    size = 0
    for text in extract_pdf_page_texts(path):
        text = text.strip()
        if not text:
            continue
        remaining = max_chars - size
        if remaining <= 0:
            break
        piece = text[:remaining]
        chunks.append(piece)
        size += len(piece)
    result = "\n\n".join(chunks).strip()
    if not result:
        raise PdfValidationError("PDF text extraction returned no usable text")
    return result


def _extract_with_pypdf(path: Path) -> list[str]:
    try:
        reader = PdfReader(str(path), strict=False)
    except Exception:
        return []
    result: list[str] = []
    for page in reader.pages:
        try:
            result.append((page.extract_text() or "").strip())
        except Exception:
            result.append("")
    return result


def _extract_with_mupdf(path: Path) -> list[str]:
    try:
        document = pymupdf.open(str(path))
    except Exception:
        return []
    result: list[str] = []
    try:
        for page in document:
            try:
                # sort=False preserves the source content stream order, which is
                # often more reliable for right-to-left official publications.
                result.append((page.get_text("text", sort=False) or "").strip())
            except Exception:
                result.append("")
    finally:
        document.close()
    return result


def _best_page_text(candidates: list[str]) -> str:
    usable = [value for value in candidates if value and value.strip()]
    if not usable:
        return ""
    return max(usable, key=_text_quality_score).strip()


def _text_quality_score(value: str) -> int:
    normalized = _normalize_for_signals(value)
    if not normalized:
        return 0
    signal_hits = sum(1 for signal in _STRUCTURAL_SIGNALS if signal in normalized)
    arabic_count = len(_ARABIC_RE.findall(value))
    digit_groups = len(_DIGIT_GROUP_RE.findall(value))
    replacement_penalty = value.count("�") * 40
    # Structural legal labels dominate raw length. This prevents choosing a long
    # garbled extraction over a shorter representation that preserves metadata.
    return (
        signal_hits * 220
        + min(arabic_count, 6000) // 3
        + min(digit_groups, 20) * 15
        + min(len(normalized), 8000) // 8
        - replacement_penalty
    )


def _normalize_for_signals(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().replace("ـ", "")
    for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"), ("ة", "ه")):
        text = text.replace(source, target)
    text = _DIACRITICS_RE.sub("", text)
    text = re.sub(r"[^0-9a-z\u0600-\u06ff]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()
