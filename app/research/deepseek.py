"""DeepSeek Responses API research provider with server-side web search."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.knowledge import SubjectProfile

from .models import CaseCandidate
from .prompt import build_search_input


CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "case_number": {"type": ["string", "null"]},
                    "court_name": {"type": ["string", "null"]},
                    "judgment_year": {"type": ["string", "null"]},
                    "source_name": {"type": "string"},
                    "source_url": {"type": "string"},
                    "pdf_url": {"type": ["string", "null"]},
                    "pdf_page_start": {"type": ["integer", "null"], "minimum": 1},
                    "pdf_page_end": {"type": ["integer", "null"], "minimum": 1},
                    "legal_issue": {"type": "string"},
                    "suitability_reason": {"type": "string"},
                    "estimated_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "subject_relevance": {"type": ["integer", "null"], "minimum": 0, "maximum": 40},
                    "legal_issue_clarity": {"type": ["integer", "null"], "minimum": 0, "maximum": 20},
                    "reasoning_quality": {"type": ["integer", "null"], "minimum": 0, "maximum": 15},
                    "academic_commentary_value": {"type": ["integer", "null"], "minimum": 0, "maximum": 15},
                },
                "required": [
                    "title", "case_number", "court_name", "judgment_year",
                    "source_name", "source_url", "pdf_url", "pdf_page_start",
                    "pdf_page_end", "legal_issue", "suitability_reason",
                    "estimated_score", "subject_relevance", "legal_issue_clarity",
                    "reasoning_quality", "academic_commentary_value"
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


class DeepSeekResearchProvider:
    def __init__(self, *, api_key: str, base_url: str, model: str,
                 timeout_seconds: float = 120.0, system_prompt_path: Path | None = None) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        root = Path(__file__).resolve().parents[2]
        self.system_prompt_path = system_prompt_path or root / "templates" / "search_system_prompt.txt"

    async def search_cases(self, subject: SubjectProfile, *, excluded_cases: list[dict[str, str | None]], limit: int) -> list[CaseCandidate]:
        payload = {
            "model": self.model,
            "instructions": self.system_prompt_path.read_text(encoding="utf-8"),
            "input": build_search_input(subject, excluded_cases, limit),
            "tools": [{"type": "web_search"}],
            "tool_choice": {"type": "web_search"},
            "text": {"format": {"type": "json_schema", "name": "judicial_case_candidates", "schema": CANDIDATE_SCHEMA}},
            "max_output_tokens": 12000,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds), follow_redirects=True) as client:
            response = await client.post(f"{self.base_url}/responses", headers=headers, json=payload)
            response.raise_for_status()
            raw = response.json()
        parsed = json.loads(extract_output_text(raw))
        return [CaseCandidate.model_validate(item) for item in parsed.get("candidates", [])][:limit]


def extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                value = content.get("text")
                if isinstance(value, str):
                    chunks.append(value)
    if not chunks:
        raise ValueError("DeepSeek response did not contain output text")
    return "".join(chunks)
