"""DeepSeek Responses API research provider with server-side web search."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.knowledge import SubjectProfile

from .models import CaseCandidate
from .prompt import build_search_input

logger = logging.getLogger(__name__)


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
                 timeout_seconds: float = 120.0, system_prompt_path: Path | None = None,
                 request_attempts: int = 2) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.request_attempts = max(1, int(request_attempts))
        root = Path(__file__).resolve().parents[2]
        self.system_prompt_path = system_prompt_path or root / "templates" / "search_system_prompt.txt"

    async def search_cases(self, subject: SubjectProfile, *, excluded_cases: list[dict[str, str | None]], limit: int) -> list[CaseCandidate]:
        instructions = self.system_prompt_path.read_text(encoding="utf-8")
        user_input = build_search_input(subject, excluded_cases, limit)
        last_error: Exception | None = None

        for attempt in range(1, self.request_attempts + 1):
            try:
                raw = await self._post(self._search_payload(instructions, user_input))
                text = _try_extract_output_text(raw)

                # A forced server-side web search may legitimately return the completed
                # web_search_call item without a final assistant message. DeepSeek's
                # Responses API is stateless, but web_search_call items can be passed
                # back as-is and the server restores their search results. Continue the
                # same research turn without requesting another search.
                if not text:
                    search_calls = extract_web_search_calls(raw)
                    if search_calls:
                        logger.info(
                            "DeepSeek returned search actions without final text; continuing from %d web search call(s)",
                            len(search_calls),
                        )
                        raw = await self._post(
                            self._continuation_payload(
                                instructions=instructions,
                                user_input=user_input,
                                search_calls=search_calls,
                            )
                        )
                        text = _try_extract_output_text(raw)

                if not text:
                    raise ValueError(describe_empty_response(raw))

                parsed = json.loads(text)
                candidates = [
                    CaseCandidate.model_validate(item)
                    for item in parsed.get("candidates", [])
                ]
                return candidates[:limit]
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning(
                    "DeepSeek research attempt %d/%d produced no usable structured result: %s",
                    attempt,
                    self.request_attempts,
                    exc,
                )
                if attempt < self.request_attempts:
                    await asyncio.sleep(min(2.0, float(attempt)))

        raise ValueError(f"DeepSeek research failed after {self.request_attempts} attempts: {last_error}")

    def _search_payload(self, instructions: str, user_input: str) -> dict[str, Any]:
        return {
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

    def _continuation_payload(
        self, *, instructions: str, user_input: str,
        search_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        continuation_input: list[dict[str, Any]] = [
            {"role": "user", "content": user_input},
            *search_calls,
            {
                "role": "user",
                "content": (
                    "استخدم نتائج البحث التي تم تنفيذها أعلاه فقط. لا تنفذ بحثاً جديداً. "
                    "حلل النتائج وأخرج الآن كائن JSON مطابقاً للمخطط المطلوب، مع مرشحي الأحكام الحقيقيين فقط."
                ),
            },
        ]
        return {
            "model": self.model,
            "instructions": instructions,
            "input": continuation_input,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "judicial_case_candidates",
                    "schema": CANDIDATE_SCHEMA,
                }
            },
            "max_output_tokens": 12000,
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        if raw.get("status") == "failed":
            error = raw.get("error") or {}
            raise ValueError(
                f"DeepSeek response failed: {error.get('code') or 'unknown'} - {error.get('message') or 'no message'}"
            )
        return raw


def _try_extract_output_text(payload: dict[str, Any]) -> str | None:
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
                if isinstance(value, str) and value.strip():
                    chunks.append(value)
    return "".join(chunks) or None


def extract_output_text(payload: dict[str, Any]) -> str:
    text = _try_extract_output_text(payload)
    if not text:
        raise ValueError(describe_empty_response(payload))
    return text


def extract_web_search_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in payload.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "web_search_call":
            calls.append(dict(item))
    return calls


def describe_empty_response(payload: dict[str, Any]) -> str:
    output_types = [
        str(item.get("type"))
        for item in payload.get("output") or []
        if isinstance(item, dict)
    ]
    status = payload.get("status") or "unknown"
    incomplete = payload.get("incomplete_details") or {}
    reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
    error = payload.get("error") or {}
    error_code = error.get("code") if isinstance(error, dict) else None
    return (
        "DeepSeek response did not contain output text "
        f"(status={status}, output_types={output_types or ['none']}, "
        f"incomplete_reason={reason or 'none'}, error={error_code or 'none'})"
    )
