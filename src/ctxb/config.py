"""Cấu hình: đọc biến môi trường, sau đó tới file ``.env`` ở thư mục project."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return (dotenv_values(ENV_PATH).get(name) or "").strip() or default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    runs_dir: Path
    # --- B1: ngân sách context (window ẢO để demo) ---
    context_window: int = 64_000
    output_reserve: int = 4_000
    micro_threshold: float = 0.5
    full_threshold: float = 0.7
    keep_recent_turns: int = 1  # full compaction giữ nguyên văn N lượt gần nhất
    keep_recent_steps: int = 2  # prune không đụng tới N tool message gần nhất (model có thể chưa đọc)
    min_compact_gain: int = 3_000  # chỉ gọi LLM tạo checkpoint khi phần nén được đủ lớn
    tool_result_cap: int = 6_000
    max_steps: int = 14  # số lần gọi model tối đa trong một lượt user
    # --- B2: Code Mode ---
    code_timeout: float = 10.0
    code_output_cap: int = 2_000
    code_max_tool_calls: int = 300

    @property
    def usable_window(self) -> int:
        """Phần window dành cho input (đã chừa chỗ cho output, slide 18)."""
        return self.context_window - self.output_reserve

    def with_(self, **changes) -> "Settings":
        return replace(self, **changes)


def load_settings(require_key: bool = True) -> Settings:
    api_key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    if require_key and not api_key:
        raise SystemExit("Thiếu GEMINI_API_KEY (hoặc GOOGLE_API_KEY) trong biến môi trường hoặc file .env")
    return Settings(
        api_key=api_key,
        model=_env("GEMINI_MODEL", DEFAULT_MODEL),
        runs_dir=Path(_env("CTXB_RUNS_DIR") or PROJECT_ROOT / "runs"),
        context_window=_int("CTXB_CONTEXT_WINDOW", 64_000),
        output_reserve=_int("CTXB_OUTPUT_RESERVE", 4_000),
        micro_threshold=_float("CTXB_MICRO_THRESHOLD", 0.5),
        full_threshold=_float("CTXB_FULL_THRESHOLD", 0.7),
        keep_recent_turns=_int("CTXB_KEEP_RECENT_TURNS", 1),
        keep_recent_steps=_int("CTXB_KEEP_RECENT_STEPS", 2),
        min_compact_gain=_int("CTXB_MIN_COMPACT_GAIN", 3_000),
        tool_result_cap=_int("CTXB_TOOL_RESULT_CAP", 6_000),
        code_timeout=_float("CTXB_CODE_TIMEOUT", 10.0),
        code_output_cap=_int("CTXB_CODE_OUTPUT_CAP", 2_000),
    )
