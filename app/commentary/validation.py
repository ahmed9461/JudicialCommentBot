"""Final content gate before any Word file is sent."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from app.core.constants import FORBIDDEN_OUTPUT_MARKERS

from .models import CommentaryDraft


class CommentaryValidationError(ValueError):
    pass


def _validate_text(text: str) -> None:
    lowered = text.casefold()
    for marker in FORBIDDEN_OUTPUT_MARKERS:
        if marker.casefold() in lowered:
            raise CommentaryValidationError(f"Forbidden output marker: {marker}")
    if "#" in text or "```" in text or "**" in text:
        raise CommentaryValidationError("Markdown formatting is not allowed")
    if re.search(r"(^|\s)\*(?=\S)", text):
        raise CommentaryValidationError("Markdown bullet/emphasis marker is not allowed")
    if re.search(r"\bAI\b", text, flags=re.IGNORECASE):
        raise CommentaryValidationError("AI reference is not allowed")


def validate_commentary(draft: CommentaryDraft) -> None:
    sections = (
        draft.title,
        draft.facts_and_course_link,
        draft.legal_issue,
        draft.court_reasoning,
        draft.comment_and_opinion,
        *draft.references,
    )
    for value in sections[:5]:
        if not value.strip():
            raise CommentaryValidationError("Required commentary section is empty")
    _validate_text("\n".join(sections))


def validate_docx_file(path: Path) -> None:
    document = Document(path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    if not text.strip():
        raise CommentaryValidationError("Generated DOCX contains no text")
    _validate_text(text)
