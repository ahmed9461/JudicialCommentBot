"""Streaming DeepSeek Responses API client.

DeepSeek web-search responses are long-running semantic SSE streams. This client
uses the API's native streaming mode and waits on *idle* network time rather than
an arbitrary total wall-clock deadline. That prevents killing a healthy search
simply because server-side web search takes longer than a fixed number of seconds.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

StreamEventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class DeepSeekStreamError(RuntimeError):
    """The DeepSeek SSE stream ended without a usable final response."""


class DeepSeekResponsesClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        connect_timeout_seconds: float = 15.0,
        idle_timeout_seconds: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_seconds = max(1.0, float(connect_timeout_seconds))
        self.idle_timeout_seconds = max(5.0, float(idle_timeout_seconds))
        self.transport = transport

    async def create(
        self,
        payload: dict[str, Any],
        *,
        on_event: StreamEventCallback | None = None,
    ) -> dict[str, Any]:
        request_payload = dict(payload)
        request_payload["stream"] = True
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        timeout = httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=self.idle_timeout_seconds,
            write=30.0,
            pool=30.0,
        )

        final_response: dict[str, Any] | None = None
        output_items: list[dict[str, Any]] = []
        output_item_ids: set[str] = set()
        text_chunks: list[str] = []

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                headers=headers,
                json=request_payload,
            ) as response:
                response.raise_for_status()

                event_name: str | None = None
                data_lines: list[str] = []

                async def flush_event() -> None:
                    nonlocal final_response, event_name, data_lines
                    if not data_lines:
                        event_name = None
                        return
                    raw_data = "\n".join(data_lines)
                    data_lines = []
                    try:
                        event = json.loads(raw_data)
                    except json.JSONDecodeError as exc:
                        raise DeepSeekStreamError(
                            f"Invalid JSON in DeepSeek SSE event: {raw_data[:500]}"
                        ) from exc
                    if not isinstance(event, dict):
                        event_name = None
                        return

                    event_type = str(
                        event.get("type") or event.get("event") or event_name or "unknown"
                    )
                    if on_event is not None:
                        await on_event(event_type, event)

                    if event_type == "response.output_text.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            text_chunks.append(delta)
                    elif event_type == "response.output_text.done":
                        text = event.get("text")
                        if isinstance(text, str) and text and not text_chunks:
                            text_chunks.append(text)
                    elif event_type == "response.output_item.done":
                        item = event.get("item")
                        if isinstance(item, dict):
                            item_id = str(item.get("id") or "")
                            if not item_id or item_id not in output_item_ids:
                                output_items.append(item)
                                if item_id:
                                    output_item_ids.add(item_id)
                    elif event_type in {
                        "response.completed",
                        "response.incomplete",
                        "response.failed",
                    }:
                        candidate = event.get("response")
                        if isinstance(candidate, dict):
                            final_response = candidate

                    event_name = None

                async for line in response.aiter_lines():
                    if line == "":
                        await flush_event()
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        continue
                    # Ignore comments/keep-alives and unknown SSE fields.

                await flush_event()

        if final_response is not None:
            return final_response

        # Defensive compatibility fallback. The documented protocol ends with a
        # final response event, but retaining completed items/text makes the
        # integration tolerant of proxies that drop the terminal event.
        if output_items or text_chunks:
            text = "".join(text_chunks)
            fallback: dict[str, Any] = {
                "status": "completed",
                "output": output_items,
                "usage": {},
            }
            if text:
                fallback["output_text"] = text
            return fallback

        raise DeepSeekStreamError("DeepSeek SSE stream ended without a final response")
