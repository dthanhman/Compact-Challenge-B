import json
from pathlib import Path

import pytest

from ctxb.config import Settings
from ctxb.llm import LLMReply, ToolCall
from ctxb.workspace.fixtures import generate
from ctxb.workspace.tools import WorkspaceTools

CHECKPOINT_JSON = {
    "goal": "Sửa race condition khi refresh token",
    "current_state": "3 test fail",
    "constraints": ["giữ API backward compatible, không đổi signature refresh()"],
    "findings": ["refresh() thu hồi token cũ trước khi phát hành token mới, không có lock"],
    "failed_attempts": [{"what": "tăng ttlSeconds lên 1800", "result": "test vẫn fail"}],
    "files": ["src/auth.ts", "tests/auth.test.ts", "src/khong_ton_tai.ts"],
    "next_action": "thêm single-flight lock quanh refresh()",
}


@pytest.fixture(scope="session")
def fixture_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("fx")
    generate(root, scale=0.3, log_files=6, log_lines=80)
    return root


@pytest.fixture
def ws(tmp_path) -> WorkspaceTools:
    fp = generate(tmp_path / "fx", scale=0.3, log_files=6, log_lines=80)
    return WorkspaceTools(fp.workspace, test_scale=0.3)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(api_key="test", model="scripted", runs_dir=tmp_path / "runs", context_window=20_000,
                    output_reserve=0, micro_threshold=0.5, full_threshold=0.7, keep_recent_turns=1,
                    tool_result_cap=3_000, code_timeout=3.0)


def tool_then_answer(tool: str = "run_tests", args: dict | None = None, checkpoint: dict | None = None):
    """Model giả: lượt user mới → gọi một tool; sau khi có kết quả tool → trả lời; json_mode → checkpoint."""
    counter = {"n": 0}

    def brain(system, messages, json_mode):
        if json_mode:
            return LLMReply(text=json.dumps(checkpoint or CHECKPOINT_JSON, ensure_ascii=False))
        last = messages[-1]
        if last["role"] == "user" and not last.get("checkpoint"):
            counter["n"] += 1
            return LLMReply(text="", tool_calls=[ToolCall(tool, dict(args or {}), id=f"c{counter['n']}")])
        return LLMReply(text="Đã xem kết quả.")

    return brain
