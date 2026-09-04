import json

from app.knowledge import SubjectLoader
from app.research.deepseek import extract_output_text
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
