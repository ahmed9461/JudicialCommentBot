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
                    "legal_issue": {"type": "string"},
                    "suitability_reason": {"type": "string"},
                    "estimated_score": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": [
                    "title",
                    "case_number",
                    "court_name",
                    "judgment_year",
                    "source_name",
                    "source_url",
                    "pdf_url",
                    "legal_issue",
                    "suitability_reason",
                    "estimated_score",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


class DeepSeekResearchProvider:
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
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        repo_root = Path(__file__).resolve().parents[2]
        self.system_prompt_path = system_prompt_path or repo_root / "templates" / "search_system_prompt.txt"

    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
    ) -> list[CaseCandidate]:
        instructions = self.system_prompt_path.read_text(encoding="utf-8")
        user_input = build_search_input(subject, excluded_cases, limit)
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": user_input,
            "tools": [{"type": "web_search"}],
            "tool_choice": {"type": "web_search"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "judicial_case_candidates",
                    "schema": CANDIDATE_SCHEMA,
                }
            },
            "max_output_tokens": 12000,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(
                f"{self.base_url}/responses", headers=headers, json=payload
            )
            response.raise_for_status()
            raw = response.json()

        text = extract_output_text(raw)
        parsed = json.loads(text)
        candidates = [CaseCandidate.model_validate(item) for item in parsed.get("candidates", [])]
        return candidates[:limit]


def extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                value = content.get("text")
                if isinstance(value, str):
                    chunks.append(value)
    if not chunks:
        raise ValueError("DeepSeek response did not contain output text")
    return "".join(chunks)
