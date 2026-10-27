"""Ước lượng token offline (≈4 ký tự/token) + hiệu chỉnh theo ``usage`` thật.

Ước lượng chỉ dùng để harness QUYẾT ĐỊNH khi nào compact (trước khi gọi model thì
chưa có ``usage``). Mọi số liệu báo cáo đều lấy từ ``usage`` của Gemini.
"""

from __future__ import annotations

import json
import math
from typing import Any

CHARS_PER_TOKEN = 4.0


def estimate(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def render_message(m: dict) -> str:
    """Chuỗi đại diện cho một message — dùng để đo kích thước và để đưa vào prompt compaction."""
    if m["role"] == "user":
        return m.get("text", "")
    if m["role"] == "assistant":
        calls = [{"name": c.name, "args": c.args} for c in m.get("tool_calls") or []]
        return (m.get("text") or "") + (json.dumps(calls, ensure_ascii=False) if calls else "")
    if m["role"] == "tool":
        return json.dumps(
            [{"name": r["name"], "response": r["response"]} for r in m["results"]], ensure_ascii=False
        )
    return ""


def estimate_message(m: dict) -> int:
    return estimate(render_message(m)) + 4  # overhead role/format


def estimate_request(system: str, messages: list[dict], tools: list[dict[str, Any]] | None = None) -> int:
    total = estimate(system)
    if tools:
        total += estimate(json.dumps(tools, ensure_ascii=False))
    return total + sum(estimate_message(m) for m in messages)


class TokenCounter:
    """Ước lượng + hệ số hiệu chỉnh ``factor = usage_thật / ước_lượng`` (trung bình trượt)."""

    def __init__(self, alpha: float = 0.5) -> None:
        self.factor = 1.0
        self.alpha = alpha

    def count(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> int:
        return int(estimate_request(system, messages, tools) * self.factor)

    def calibrate(self, estimated_raw: int, actual: int) -> None:
        if estimated_raw <= 0 or actual <= 0:
            return
        ratio = actual / estimated_raw
        if 0.2 < ratio < 5:  # bỏ qua giá trị bất thường
            self.factor = (1 - self.alpha) * self.factor + self.alpha * ratio
