"""Structured commentary generation through the configured DeepSeek Responses API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.knowledge import SubjectProfile
from app.research import CaseCandidate
from app.research.deepseek import extract_output_text

from .models import CommentaryDraft


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
        timeout_seconds: float = 120.0,
        system_prompt_path: Path | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        root = Path(__file__).resolve().parents[2]
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
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
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "judicial_commentary",
                    "schema": COMMENTARY_SCHEMA,
                }
            },
            "max_output_tokens": 10000,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds), follow_redirects=True
        ) as client:
            response = await client.post(
                f"{self.base_url}/responses", headers=headers, json=payload
            )
            response.raise_for_status()
            raw = response.json()
        return CommentaryDraft.model_validate(json.loads(extract_output_text(raw)))
