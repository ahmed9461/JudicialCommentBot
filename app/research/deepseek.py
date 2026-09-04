"""DeepSeek Responses API research provider with bounded server-side web search."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.knowledge import SubjectProfile

from .models import CaseCandidate
from .prompt import build_search_input

logger = logging.getLogger(__name__)
ResearchProgressCallback = Callable[[str], Awaitable[None]]


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
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        system_prompt_path: Path | None = None,
        request_attempts: int = 1,
        synthesis_attempts: int = 2,
        max_search_calls_for_synthesis: int = 8,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.request_attempts = max(1, int(request_attempts))
        self.synthesis_attempts = max(1, int(synthesis_attempts))
        self.max_search_calls_for_synthesis = max(1, int(max_search_calls_for_synthesis))
        root = Path(__file__).resolve().parents[2]
        self.system_prompt_path = (
            system_prompt_path or root / "templates" / "search_system_prompt.txt"
        )

    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
        progress: ResearchProgressCallback | None = None,
    ) -> list[CaseCandidate]:
        instructions = self.system_prompt_path.read_text(encoding="utf-8")
        user_input = build_search_input(subject, excluded_cases, limit)
        last_error: Exception | None = None

        for research_attempt in range(1, self.request_attempts + 1):
            if research_attempt == 1:
                await _notify(progress, "🌐 جاري تنفيذ بحث ويب محدود في المصادر القضائية…")
            else:
                await _notify(
                    progress,
                    f"🔄 تعذر الاستفادة من البحث السابق، محاولة أخيرة {research_attempt}/{self.request_attempts}…",
                )
            try:
                raw = await self._post(self._search_payload(instructions, user_input))
                _log_response_metrics("search", raw)
                search_calls = extract_web_search_calls(raw)
                text = _try_extract_output_text(raw)

                if text:
                    try:
                        candidates, recovered_partial = parse_candidate_response(text, limit=limit)
                        await _report_parse_result(progress, candidates, recovered_partial)
                        return candidates
                    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
                        last_error = exc
                        logger.warning(
                            "DeepSeek web result contained malformed structured text; will synthesize from the same search results without re-searching: %s",
                            exc,
                        )

                if search_calls:
                    bounded_calls = search_calls[-self.max_search_calls_for_synthesis :]
                    logger.info(
                        "DeepSeek web phase produced %d action(s); synthesizing from latest %d without new web search",
                        len(search_calls),
                        len(bounded_calls),
                    )
                    await _notify(
                        progress,
                        f"🔎 اكتمل البحث ({len(search_calls)} خطوة). جاري تلخيص أفضل النتائج دون تنفيذ بحث جديد…",
                    )
                    for synthesis_attempt in range(1, self.synthesis_attempts + 1):
                        compact_limit = min(limit, 5 if synthesis_attempt == 1 else 3)
                        synthesis = await self._post(
                            self._continuation_payload(
                                instructions=instructions,
                                user_input=user_input,
                                search_calls=bounded_calls,
                                limit=compact_limit,
                                stricter=synthesis_attempt > 1,
                            )
                        )
                        _log_response_metrics(f"synthesis-{synthesis_attempt}", synthesis)
                        synthesis_text = _try_extract_output_text(synthesis)
                        if not synthesis_text:
                            last_error = ValueError(describe_empty_response(synthesis))
                            logger.warning(
                                "DeepSeek synthesis %d/%d returned no output text: %s",
                                synthesis_attempt,
                                self.synthesis_attempts,
                                last_error,
                            )
                            continue
                        try:
                            candidates, recovered_partial = parse_candidate_response(
                                synthesis_text, limit=limit
                            )
                            await _report_parse_result(progress, candidates, recovered_partial)
                            return candidates
                        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
                            last_error = exc
                            logger.warning(
                                "DeepSeek synthesis %d/%d returned malformed JSON; retrying synthesis only, not web search: %s",
                                synthesis_attempt,
                                self.synthesis_attempts,
                                exc,
                            )
                            if synthesis_attempt < self.synthesis_attempts:
                                await _notify(
                                    progress,
                                    "🧩 صيغة النتائج غير مكتملة؛ جاري إصلاحها من نفس نتائج البحث دون تكلفة بحث ويب جديدة…",
                                )
                elif not text:
                    last_error = ValueError(describe_empty_response(raw))

            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "DeepSeek HTTP research attempt %d/%d failed: %s",
                    research_attempt,
                    self.request_attempts,
                    exc,
                )

            if research_attempt < self.request_attempts:
                await asyncio.sleep(min(2.0, float(research_attempt)))

        raise ValueError(
            f"DeepSeek research failed after {self.request_attempts} web attempt(s): {last_error}"
        )

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
            "max_output_tokens": 6000,
        }

    def _continuation_payload(
        self,
        *,
        instructions: str,
        user_input: str,
        search_calls: list[dict[str, Any]],
        limit: int,
        stricter: bool,
    ) -> dict[str, Any]:
        compact_note = (
            "هذه محاولة إصلاح ثانية: أعد أفضل النتائج فقط، واختصر كل حقل نصي، ولا تكتب أي شيء خارج JSON."
            if stricter
            else "اختصر الحقول النصية حتى لا تنقطع الاستجابة."
        )
        continuation_input: list[dict[str, Any]] = [
            {"role": "user", "content": user_input},
            *search_calls,
            {
                "role": "user",
                "content": (
                    "استخدم نتائج البحث المنفذة أعلاه فقط. ممنوع تنفيذ بحث جديد. "
                    f"أخرج JSON مطابقاً للمخطط وفيه أفضل {limit} مرشحين كحد أقصى. "
                    "استخدم null لأي معلومة غير متحققة ولا تخترع شيئاً. "
                    f"{compact_note}"
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
            "max_output_tokens": 5000 if not stricter else 3500,
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=min(15.0, self.timeout_seconds),
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    response = await client.post(
                        f"{self.base_url}/responses", headers=headers, json=payload
                    )
                    response.raise_for_status()
                    raw = response.json()
        except TimeoutError as exc:
            raise httpx.ReadTimeout(
                f"DeepSeek request exceeded {self.timeout_seconds:.0f}s wall-clock limit"
            ) from exc
        if raw.get("status") == "failed":
            error = raw.get("error") or {}
            raise ValueError(
                f"DeepSeek response failed: {error.get('code') or 'unknown'} - {error.get('message') or 'no message'}"
            )
        return raw


def parse_candidate_response(text: str, *, limit: int) -> tuple[list[CaseCandidate], bool]:
    """Parse structured output and salvage only fully-complete candidates if truncated."""
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("DeepSeek structured root is not an object")
        items = parsed.get("candidates", [])
        if not isinstance(items, list):
            raise ValueError("DeepSeek JSON field 'candidates' is not a list")
        candidates = _validate_candidate_items(items, limit=limit)
        return candidates, False
    except json.JSONDecodeError:
        recovered_items = recover_complete_candidate_objects(text)
        candidates = _validate_candidate_items(recovered_items, limit=limit)
        if not candidates:
            raise
        return candidates, True


def _validate_candidate_items(items: list[Any], *, limit: int) -> list[CaseCandidate]:
    candidates: list[CaseCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            candidates.append(CaseCandidate.model_validate(item))
        except ValidationError as exc:
            logger.debug("Discarding invalid research candidate: %s", exc)
            continue
        if len(candidates) >= limit:
            break
    return candidates


def recover_complete_candidate_objects(text: str) -> list[dict[str, Any]]:
    marker = '"candidates"'
    marker_index = text.find(marker)
    if marker_index < 0:
        return []
    array_start = text.find("[", marker_index + len(marker))
    if array_start < 0:
        return []

    results: list[dict[str, Any]] = []
    depth = 0
    object_start: int | None = None
    in_string = False
    escaped = False

    for index in range(array_start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                object_start = index
            depth += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and object_start is not None:
                fragment = text[object_start : index + 1]
                object_start = None
                try:
                    value = json.loads(fragment)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    results.append(value)
            continue
        if char == "]" and depth == 0:
            break
    return results


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


def _log_response_metrics(label: str, payload: dict[str, Any]) -> None:
    usage = payload.get("usage") or {}
    logger.info(
        "DeepSeek %s status=%s web_calls=%d tokens(in=%s,out=%s,total=%s)",
        label,
        payload.get("status") or "unknown",
        len(extract_web_search_calls(payload)),
        usage.get("input_tokens", "?"),
        usage.get("output_tokens", "?"),
        usage.get("total_tokens", "?"),
    )


async def _report_parse_result(
    progress: ResearchProgressCallback | None,
    candidates: list[CaseCandidate],
    recovered_partial: bool,
) -> None:
    if recovered_partial:
        logger.warning(
            "Recovered %d complete candidate(s) from malformed/truncated DeepSeek JSON",
            len(candidates),
        )
        await _notify(
            progress,
            f"🧩 استعدت {len(candidates)} قضية كاملة من استجابة غير مكتملة. جاري التحقق من المصادر…",
        )
    else:
        await _notify(
            progress,
            f"📋 تم تنظيم {len(candidates)} قضية مرشحة. جاري التحقق من ملفات الأحكام الرسمية…",
        )


async def _notify(progress: ResearchProgressCallback | None, text: str) -> None:
    if progress is not None:
        await progress(text)
