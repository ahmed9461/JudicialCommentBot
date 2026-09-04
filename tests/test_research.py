import json

import pytest

from app.knowledge import SubjectLoader
from app.research.deepseek import (
    describe_empty_response,
    extract_output_text,
    extract_web_search_calls,
    parse_candidate_response,
    recover_complete_candidate_objects,
)
from app.research.prompt import build_search_input


def test_extract_output_text_from_responses_payload() -> None:
    payload = {
        "output": [
            {"type": "web_search_call", "id": "ws_1"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"candidates": []}, ensure_ascii=False),
                    }
                ],
            },
        ]
    }
    assert json.loads(extract_output_text(payload)) == {"candidates": []}


def test_search_only_response_is_detected_for_continuation() -> None:
    payload = {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_1",
                "status": "completed",
                "action": {"type": "search", "query": "حكم قضائي سعودي"},
            }
        ],
    }
    calls = extract_web_search_calls(payload)
    assert len(calls) == 1
    assert calls[0]["id"] == "ws_1"
    with pytest.raises(ValueError, match="output_types"):
        extract_output_text(payload)
    description = describe_empty_response(payload)
    assert "web_search_call" in description
    assert "status=completed" in description


def _candidate_payload(number: str) -> dict:
    return {
        "title": f"قضية {number}",
        "case_number": number,
        "court_name": "المحكمة التجارية",
        "judgment_year": "1445",
        "source_name": "وزارة العدل",
        "source_url": f"https://www.moj.gov.sa/{number}",
        "pdf_url": f"https://www.moj.gov.sa/{number}.pdf",
        "pdf_page_start": None,
        "pdf_page_end": None,
        "legal_issue": "مسألة قانونية",
        "suitability_reason": "صلة مباشرة بالمقرر",
        "estimated_score": 90,
        "subject_relevance": 38,
        "legal_issue_clarity": 18,
        "reasoning_quality": 13,
        "academic_commentary_value": 13,
    }


def test_truncated_json_recovers_only_complete_candidates() -> None:
    first = json.dumps(_candidate_payload("111"), ensure_ascii=False)
    second = json.dumps(_candidate_payload("222"), ensure_ascii=False)
    truncated = '{"candidates": [' + first + "," + second[: len(second) // 2]

    recovered = recover_complete_candidate_objects(truncated)
    assert len(recovered) == 1
    assert recovered[0]["case_number"] == "111"

    candidates, was_recovered = parse_candidate_response(truncated, limit=8)
    assert was_recovered is True
    assert [item.case_number for item in candidates] == ["111"]


def test_search_prompt_uses_subject_knowledge_and_exclusions() -> None:
    subject = SubjectLoader().get_subject("law_intro")
    prompt = build_search_input(
        subject,
        excluded_cases=[
            {
                "case_number": "123",
                "court_name": "المحكمة التجارية",
                "source_url": "https://example.test/case",
            }
        ],
        limit=8,
    )
    assert "التعسف في استعمال الحق" in prompt
    assert "رقم القضية: 123" in prompt
    assert "حتى 8 مرشحين" in prompt
