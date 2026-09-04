"""Structured commentary generation through the streamed DeepSeek Responses API."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.deepseek import DeepSeekResponsesClient
from app.knowledge import SubjectProfile
from app.research import CaseCandidate
from app.research.deepseek import extract_output_text

from .models import CommentaryDraft

ProgressCallback = Callable[[str], Awaitable[None]]


COMMENTARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "facts_and_course_link": {"type": "string"},
        "legal_issue": {"type": "string"},
        "court_reasoning": {"type": "string"},
        "comment_and_opinion": {"type": "string"},
        "references": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "facts_and_course_link",
        "legal_issue",
        "court_reasoning",
        "comment_and_opinion",
        "references",
    ],
    "additionalProperties": False,
}


class DeepSeekCommentaryGenerator:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 180.0,
        connect_timeout_seconds: float = 15.0,
        reasoning_effort: str = "high",
        system_prompt_path: Path | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        root = Path(__file__).resolve().parents[2]
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = DeepSeekResponsesClient(
            api_key=api_key,
            base_url=base_url,
            connect_timeout_seconds=connect_timeout_seconds,
            idle_timeout_seconds=timeout_seconds,
        )
        self.system_prompt_path = (
            system_prompt_path or root / "templates" / "commentary_system_prompt.txt"
        )

    async def generate(
        self,
        *,
        subject: SubjectProfile,
        candidate: CaseCandidate,
        judgment_text: str,
        variation_hint: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> CommentaryDraft:
        instructions = self.system_prompt_path.read_text(encoding="utf-8")
        input_payload = {
            "course": {
                "name": subject.name_ar,
                "priority_topics": list(subject.priority_topics),
                "commentary_focus": list(subject.commentary_focus),
            },
            "case": {
                "title": candidate.title,
                "case_number": candidate.case_number,
                "court_name": candidate.court_name,
                "judgment_year": candidate.judgment_year,
                "legal_issue_from_research": candidate.legal_issue,
                "source_name": candidate.source_name,
                "source_url": candidate.source_url_str,
            },
            "judgment_text": judgment_text,
            "variation_hint": variation_hint or "",
        }
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps(input_payload, ensure_ascii=False),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "judicial_commentary",
                    "schema": COMMENTARY_SCHEMA,
                }
            },
            "max_output_tokens": 12000,
        }

        started_writing = False

        async def on_event(event_type: str, event: dict[str, Any]) -> None:
            nonlocal started_writing
            if progress is None:
                return
            if event_type == "response.in_progress":
                await progress("🧠 جاري تحليل وقائع الحكم وتسبيبه وربطه بالمقرر…")
            elif event_type == "response.output_text.delta" and not started_writing:
                started_writing = True
                await progress("✍️ اكتمل التحليل، جاري صياغة التعليق الأكاديمي المنظم…")

        raw = await self.client.create(payload, on_event=on_event if progress else None)
        if raw.get("status") == "failed":
            error = raw.get("error") or {}
            raise ValueError(
                f"DeepSeek commentary failed: {error.get('code') or 'unknown'} - "
                f"{error.get('message') or 'no message'}"
            )
        text = extract_output_text(raw)
        return CommentaryDraft.model_validate(json.loads(text))
