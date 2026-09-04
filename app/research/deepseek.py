"""DeepSeek research provider using a two-stage streamed Responses API flow.

Stage 1 performs bounded web discovery. Stage 2 reuses the returned
``web_search_call`` items exactly as documented by DeepSeek and produces a small
structured candidate list without executing another web search.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.deepseek import DeepSeekResponsesClient
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
                    "reasoning_quality", "academic_commentary_value",
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
        timeout_seconds: float = 180.0,
        connect_timeout_seconds: float = 15.0,
        system_prompt_path: Path | None = None,
        request_attempts: int = 1,
        synthesis_attempts: int = 1,
        max_search_calls_for_synthesis: int = 6,
        discovery_reasoning_effort: str = "none",
        synthesis_reasoning_effort: str = "low",
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        self.model = model
        self.request_attempts = max(1, int(request_attempts))
        self.synthesis_attempts = max(1, int(synthesis_attempts))
        self.max_search_calls_for_synthesis = max(1, int(max_search_calls_for_synthesis))
        self.discovery_reasoning_effort = discovery_reasoning_effort
        self.synthesis_reasoning_effort = synthesis_reasoning_effort
        self.client = DeepSeekResponsesClient(
            api_key=api_key,
            base_url=base_url,
            connect_timeout_seconds=connect_timeout_seconds,
            idle_timeout_seconds=timeout_seconds,
        )
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
            try:
                await _notify(
                    progress,
                    "🌐 جاري البحث في المصادر القضائية عبر DeepSeek…",
                )
                discovery = await self.client.create(
                    self._discovery_payload(instructions, user_input),
                    on_event=self._stream_progress(progress, phase="discovery"),
                )
                _log_response_metrics("discovery", discovery)
                search_calls = extract_web_search_calls(discovery)
                if not search_calls:
                    # Defensive fallback for a model that returned structured text directly.
                    direct_text = _try_extract_output_text(discovery)
                    if direct_text:
                        candidates, recovered_partial = parse_candidate_response(
                            direct_text, limit=limit
                        )
                        if candidates:
                            await _report_parse_result(progress, candidates, recovered_partial)
                            return candidates
                    raise ValueError(
                        "DeepSeek discovery completed without web_search_call results"
                    )

                bounded_calls = search_calls[: self.max_search_calls_for_synthesis]
                await _notify(
                    progress,
                    f"🔎 اكتمل جمع المصادر ({len(search_calls)} خطوة بحث). "
                    f"جاري تحليل أفضل {len(bounded_calls)} نتائج دون بحث ويب إضافي…",
                )
                logger.info(
                    "DeepSeek discovery produced %d web action(s); reusing %d for synthesis",
                    len(search_calls),
                    len(bounded_calls),
                )

                for synthesis_attempt in range(1, self.synthesis_attempts + 1):
                    synthesis = await self.client.create(
                        self._synthesis_payload(
                            instructions=instructions,
                            user_input=user_input,
                            search_calls=bounded_calls,
                            limit=min(limit, 5),
                            stricter=synthesis_attempt > 1,
                        ),
                        on_event=self._stream_progress(progress, phase="synthesis"),
                    )
                    _log_response_metrics(f"synthesis-{synthesis_attempt}", synthesis)
                    text = _try_extract_output_text(synthesis)
                    if not text:
                        last_error = ValueError(describe_empty_response(synthesis))
                        continue
                    try:
                        candidates, recovered_partial = parse_candidate_response(
                            text, limit=limit
                        )
                    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                        last_error = exc
                        if synthesis_attempt < self.synthesis_attempts:
                            await _notify(
                                progress,
                                "🧩 النتيجة المنظمة غير مكتملة؛ جاري إعادة تنظيم نفس نتائج البحث فقط…",
                            )
                            continue
                        raise
                    if not candidates:
                        raise ValueError("DeepSeek synthesis returned zero valid candidates")
                    await _report_parse_result(progress, candidates, recovered_partial)
                    return candidates

            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "DeepSeek research transport attempt %d/%d failed: %s",
                    research_attempt,
                    self.request_attempts,
                    exc,
                )
            except (ValueError, json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "DeepSeek research attempt %d/%d produced no usable result: %s",
                    research_attempt,
                    self.request_attempts,
                    exc,
                )

            if research_attempt < self.request_attempts:
                await asyncio.sleep(min(2.0, float(research_attempt)))

        raise ValueError(
            f"DeepSeek research failed after {self.request_attempts} web attempt(s): {last_error}"
        )

    def _discovery_payload(self, instructions: str, user_input: str) -> dict[str, Any]:
        # Discovery has one responsibility: search. We deliberately do not request
        # structured legal output in the same turn, and disable reasoning because
        # DeepSeek defaults to high reasoning effort otherwise.
        return {
            "model": self.model,
            "instructions": (
                instructions
                + "\nفي هذه المرحلة نفّذ البحث فقط. استخدم أقل عدد ممكن من عمليات البحث، "
                "وركّز على المصادر الرسمية والروابط المباشرة للأحكام. لا تكتب تحليلاً مطولاً."
            ),
            "input": user_input,
            "tools": [{"type": "web_search"}],
            "tool_choice": {"type": "web_search"},
            "reasoning": {"effort": self.discovery_reasoning_effort},
            "text": {"format": {"type": "text"}},
            "max_output_tokens": 1200,
        }

    def _synthesis_payload(
        self,
        *,
        instructions: str,
        user_input: str,
        search_calls: list[dict[str, Any]],
        limit: int,
        stricter: bool,
    ) -> dict[str, Any]:
        compact_note = (
            "هذه محاولة إعادة تنظيم: اجعل النصوص شديدة الاختصار ولا تكتب أي شيء خارج JSON."
            if stricter
            else "اجعل الحقول النصية موجزة ودقيقة."
        )
        continuation_input: list[dict[str, Any]] = [
            {"role": "user", "content": user_input},
            *search_calls,
            {
                "role": "user",
                "content": (
                    "اعتمد حصراً على نتائج web_search_call المرفقة أعلاه. "
                    "ممنوع تنفيذ بحث جديد. "
                    f"أخرج أفضل {limit} قضايا كحد أقصى وفق المخطط. "
                    "استخدم null لأي معلومة غير متحققة، ولا تخترع رقم قضية أو محكمة أو رابط PDF. "
                    f"{compact_note}"
                ),
            },
        ]
        return {
            "model": self.model,
            "instructions": instructions,
            "input": continuation_input,
            "reasoning": {"effort": self.synthesis_reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "judicial_case_candidates",
                    "schema": CANDIDATE_SCHEMA,
                }
            },
            "max_output_tokens": 6000 if not stricter else 4500,
        }

    def _stream_progress(
        self,
        progress: ResearchProgressCallback | None,
        *,
        phase: str,
    ) -> Callable[[str, dict[str, Any]], Awaitable[None]] | None:
        if progress is None:
            return None
        completed_searches = 0

        async def on_event(event_type: str, event: dict[str, Any]) -> None:
            nonlocal completed_searches
            if phase == "discovery":
                if event_type == "response.web_search_call.searching":
                    await _notify(progress, "🔍 DeepSeek يبحث الآن في المصادر القضائية…")
                elif event_type == "response.web_search_call.completed":
                    completed_searches += 1
                    await _notify(
                        progress,
                        f"✅ اكتملت خطوة بحث رقم {completed_searches}. جاري متابعة جمع المصادر…",
                    )
            elif phase == "synthesis" and event_type == "response.output_text.delta":
                # The StatusTicker keeps counting; avoid an edit for every token.
                return

        return on_event


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
    return [
        dict(item)
        for item in (payload.get("output") or [])
        if isinstance(item, dict) and item.get("type") == "web_search_call"
    ]


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
    details = usage.get("output_tokens_details") or {}
    logger.info(
        "DeepSeek %s status=%s web_calls=%d tokens(in=%s,out=%s,reasoning=%s,total=%s)",
        label,
        payload.get("status") or "unknown",
        len(extract_web_search_calls(payload)),
        usage.get("input_tokens", "?"),
        usage.get("output_tokens", "?"),
        details.get("reasoning_tokens", "?"),
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
            f"🧩 تم استعادة {len(candidates)} قضية كاملة من نتيجة منقطعة. جاري التحقق من المصادر…",
        )
    else:
        await _notify(
            progress,
            f"📋 تم تنظيم {len(candidates)} قضية مرشحة. جاري التحقق من ملفات الأحكام الرسمية…",
        )


async def _notify(progress: ResearchProgressCallback | None, text: str) -> None:
    if progress is not None:
        await progress(text)
