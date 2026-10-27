"""Lớp LLM: message trung lập + adapter Gemini + model giả cho test.

Message trung lập (list[dict]):
    {"role": "user", "text": ..., "turn": n}
    {"role": "assistant", "text": ..., "tool_calls": [ToolCall], "raw": <Content gốc>, "turn": n}
    {"role": "tool", "results": [{"id", "name", "response": {...}, ...}], "turn": n}

``raw`` được giữ vì Gemini yêu cầu gửi trả nguyên phần function call của model
(kèm thought signature) ở request kế tiếp. Harness chỉ sửa ``response`` của tool
(khi prune), không bao giờ sửa message assistant.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None


USAGE_KEYS = ("input_tokens", "cached_tokens", "output_tokens", "thinking_tokens")


def empty_usage() -> dict[str, int]:
    return {k: 0 for k in USAGE_KEYS}


class LLM(Protocol):
    name: str

    def generate(
        self, system: str, messages: list[dict], tools: list[dict], json_mode: bool = False
    ) -> LLMReply: ...


# --------------------------------------------------------------------------- Gemini
class GeminiLLM:
    """Gọi Gemini qua ``google-genai``; tắt automatic function calling để harness tự chạy tool."""

    def __init__(self, api_key: str, model: str, max_retries: int = 8) -> None:
        from google import genai
        from google.genai import types

        # timeout (ms) cho mỗi request: tránh treo vô hạn khi mạng chập chờn
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120_000))
        self.model = model
        self.name = f"gemini:{model}"
        self.max_retries = max_retries

    def _contents(self, messages: list[dict]) -> list[Any]:
        from google.genai import types

        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m["text"])]))
            elif m["role"] == "assistant":
                if m.get("raw") is not None:
                    contents.append(m["raw"])
                else:
                    contents.append(types.Content(role="model", parts=[types.Part(text=m.get("text") or " ")]))
            elif m["role"] == "tool":
                parts = [
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=r.get("id"), name=r["name"], response=r["response"]
                        )
                    )
                    for r in m["results"]
                ]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    def generate(
        self, system: str, messages: list[dict], tools: list[dict], json_mode: bool = False
    ) -> LLMReply:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if json_mode:
            config.response_mime_type = "application/json"
        if tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t["name"], description=t["description"], parameters_json_schema=t["parameters"]
                        )
                        for t in tools
                    ]
                )
            ]

        for attempt in range(self.max_retries):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=self._contents(messages), config=config
                )
                break
            except errors.APIError as exc:
                # 429 (quota) và 5xx (quá tải) là lỗi tạm thời: chờ (theo retryDelay nếu có) rồi thử lại.
                if getattr(exc, "code", None) not in (429, 500, 503) or attempt == self.max_retries - 1:
                    raise
                hint = re.search(r"retry in ([\d.]+)s", str(exc))
                time.sleep(float(hint.group(1)) + 2 if hint else min(60, 4 * 2**attempt))
            except Exception as exc:  # timeout mạng (httpx) cũng là lỗi tạm thời
                if "timeout" not in type(exc).__name__.lower() or attempt == self.max_retries - 1:
                    raise
                time.sleep(5)

        candidate = resp.candidates[0] if resp.candidates else None
        parts = (candidate.content.parts or []) if candidate and candidate.content else []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = [
            ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id)
            for p in parts
            if p.function_call
        ]
        um = resp.usage_metadata
        usage = {
            "input_tokens": (um.prompt_token_count or 0) if um else 0,
            "cached_tokens": (um.cached_content_token_count or 0) if um else 0,
            "output_tokens": (um.candidates_token_count or 0) if um else 0,
            "thinking_tokens": (um.thoughts_token_count or 0) if um else 0,
        }
        return LLMReply(text=text, tool_calls=calls, usage=usage, raw=candidate.content if candidate else None)


# ----------------------------------------------------------------------- Fake (test)
class ScriptedLLM:
    """Model giả: mỗi lần generate gọi ``script(system, messages, json_mode)`` để lấy reply.

    Ghi lại mọi request để test kiểm tra đúng những gì harness đã gửi cho model.
    ``usage.input_tokens`` được giả lập bằng bộ ước lượng token để số liệu có nghĩa.
    """

    def __init__(self, script: Callable[[str, list[dict], bool], LLMReply]) -> None:
        self.script = script
        self.name = "scripted"
        self.requests: list[dict] = []

    def generate(
        self, system: str, messages: list[dict], tools: list[dict], json_mode: bool = False
    ) -> LLMReply:
        from .tokens import estimate_request

        self.requests.append({"system": system, "messages": list(messages), "tools": tools, "json_mode": json_mode})
        reply = self.script(system, messages, json_mode)
        if not reply.usage:
            reply.usage = {
                **empty_usage(),
                "input_tokens": estimate_request(system, messages, tools),
                "output_tokens": max(1, len(reply.text) // 4),
            }
        return reply
