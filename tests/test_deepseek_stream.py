import json

import httpx
import pytest

from app.deepseek import DeepSeekResponsesClient


@pytest.mark.asyncio
async def test_streaming_client_uses_native_sse_and_returns_final_response() -> None:
    seen_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request.update(json.loads(request.content.decode("utf-8")))
        search_item = {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {"type": "search", "query": "حكم قضائي سعودي"},
        }
        final = {
            "status": "completed",
            "output": [search_item],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        }
        sse = "\n".join(
            [
                "event: response.created",
                'data: {"type":"response.created"}',
                "",
                "event: response.web_search_call.searching",
                'data: {"type":"response.web_search_call.searching"}',
                "",
                "event: response.output_item.done",
                "data: " + json.dumps({"type": "response.output_item.done", "item": search_item}),
                "",
                "event: response.completed",
                "data: " + json.dumps({"type": "response.completed", "response": final}),
                "",
            ]
        )
        return httpx.Response(
            200,
            content=sse.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    events: list[str] = []

    async def on_event(event_type: str, event: dict) -> None:
        events.append(event_type)

    client = DeepSeekResponsesClient(
        api_key="fixture",
        base_url="https://api.deepseek.test",
        transport=httpx.MockTransport(handler),
    )
    result = await client.create(
        {"model": "deepseek-v4-flash", "input": "test"},
        on_event=on_event,
    )

    assert seen_request["stream"] is True
    assert result["status"] == "completed"
    assert result["output"][0]["type"] == "web_search_call"
    assert "response.web_search_call.searching" in events
    assert "response.completed" in events


@pytest.mark.asyncio
async def test_streaming_client_preserves_output_when_terminal_event_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        item = {"type": "message", "id": "msg_1", "content": []}
        sse = "\n".join(
            [
                "event: response.output_item.done",
                "data: " + json.dumps({"type": "response.output_item.done", "item": item}),
                "",
                "event: response.output_text.delta",
                'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}',
                "",
            ]
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    client = DeepSeekResponsesClient(
        api_key="fixture",
        base_url="https://api.deepseek.test",
        transport=httpx.MockTransport(handler),
    )
    result = await client.create({"model": "deepseek-v4-flash", "input": "test"})

    assert result["status"] == "completed"
    assert result["output_text"] == '{"ok":true}'
