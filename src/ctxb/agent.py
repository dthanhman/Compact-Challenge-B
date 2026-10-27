"""Agent loop + harness cho một session (kế thừa thiết kế ``pmem`` của Challenge A).

Trước MỖI lần gọi model, harness:
    1. hỏi ``Compactor`` có cần prune/compact không (observe token budget),
    2. ước lượng kích thước context, ghi lại cùng ``usage`` thật sau khi gọi.
Sau mỗi tool call, raw output được archive và bị giới hạn kích thước trước khi vào context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .codemode.runner import CodeRunner, run_code_spec
from .compaction.archive import READ_ARCHIVE_SPEC, Archive, read_archive
from .compaction.compactor import Compactor
from .compaction.prune import SMALL_RESULT_TOKENS, cap_at_ingestion, main_text
from .config import Settings
from .context import build_system_prompt
from .llm import LLM, empty_usage
from .recorder import Recorder
from .tokens import TokenCounter, estimate, estimate_request
from .workspace.tools import TOOL_SPECS, WorkspaceTools

NATIVE_TOOLS = ["list_files", "read_file", "grep", "run_tests", "write_file", "replace_in_file"]


@dataclass
class ToolEvent:
    name: str
    args: dict[str, Any]
    response: dict[str, Any]
    raw_tokens: int
    context_tokens: int
    archive_id: str | None = None


@dataclass
class TurnResult:
    text: str
    tool_events: list[ToolEvent] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    steps: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class Session:
    def __init__(
        self,
        llm: LLM,
        workspace: WorkspaceTools,
        settings: Settings,
        *,
        strategy: str = "structured",
        recorder: Recorder | None = None,
        archive_dir: str | Path | None = None,
        agents_md: str = "",
        code_mode: bool = False,
        tools: list[str] | None = None,
    ) -> None:
        self.llm = llm
        self.ws = workspace
        self.workspace_root = workspace.root
        self.settings = settings
        self.recorder = recorder
        self.compactor = Compactor(settings, strategy)
        self.counter = TokenCounter()
        self.archive = Archive(archive_dir or (recorder.dir / "archive" if recorder else workspace.root.parent / "archive"))
        self.tool_names = list(tools or NATIVE_TOOLS)
        self.runner: CodeRunner | None = None
        if code_mode:
            self.runner = CodeRunner(workspace, timeout=settings.code_timeout, output_cap=settings.code_output_cap,
                                     max_tool_calls=settings.code_max_tool_calls)
            if "run_code" not in self.tool_names:
                self.tool_names.append("run_code")
        if strategy == "structured" and "read_archive" not in self.tool_names:
            self.tool_names.append("read_archive")
        self.system = build_system_prompt(agents_md, code_mode=code_mode)
        self.messages: list[dict] = []
        self.turn = 0
        self.totals = {**empty_usage(), "llm_calls": 0, "compaction_input_tokens": 0}
        self.peak_context = 0
        self.over_window_calls = 0
        self._last_tests_passed: bool | None = None

    # ----------------------------------------------------------------- context
    def tool_specs(self) -> list[dict[str, Any]]:
        specs = []
        for name in self.tool_names:
            if name in TOOL_SPECS:
                specs.append(TOOL_SPECS[name])
            elif name == "read_archive":
                specs.append(READ_ARCHIVE_SPEC)
            elif name == "run_code":
                specs.append(run_code_spec(self.settings.code_output_cap))
        return specs

    def context_tokens(self) -> int:
        return self.counter.count(self.system, self.messages, self.tool_specs())

    def request_compaction(self, reason: str = "manual") -> None:
        self.compactor.request(reason)

    # -------------------------------------------------------------------- tools
    def _run_tool(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Trả về (response cho context, thông tin phụ để log)."""
        extra: dict[str, Any] = {}
        if name not in self.tool_names:
            return {"ok": False, "error": f"Tool không được bật: {name}"}, extra
        if name == "read_archive":
            try:
                return read_archive(self.archive, **args), extra
            except (TypeError, ValueError, FileNotFoundError) as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, extra
        if name == "run_code":
            res = self.runner.run(str(args.get("code", "")))
            extra = {"code_run": {"tool_calls": res.tool_calls, "runtime_tokens": res.runtime_tokens,
                                  "stdout_chars_total": res.stdout_chars_total, "elapsed_s": res.elapsed_s,
                                  "error": res.error, "denied": res.denied, "trace": res.trace[:50]}}
            return res.to_context(), extra
        return self.ws.dispatch(name, args), extra

    # --------------------------------------------------------------------- loop
    def send(self, user_text: str) -> TurnResult:
        self.turn += 1
        self.ws.turn = self.turn
        self.messages.append({"role": "user", "text": user_text, "turn": self.turn})
        usage = empty_usage()
        tool_events: list[ToolEvent] = []
        all_events: list[dict[str, Any]] = []
        text = ""

        for step in range(1, self.settings.max_steps + 1):
            events = self.compactor.maybe_compact(self, self.recorder)
            for ev in events:
                self.totals["compaction_input_tokens"] += ev.get("llm_usage", {}).get("input_tokens", 0)
                self._log({"type": ev["type"], "turn": self.turn, "step": step, **ev})
            all_events += events

            specs = self.tool_specs()
            est_raw = estimate_request(self.system, self.messages, specs)
            ctx = int(est_raw * self.counter.factor)
            over = ctx > self.settings.usable_window
            self.over_window_calls += int(over)
            reply = self.llm.generate(self.system, self.messages, specs)
            self.counter.calibrate(est_raw, reply.usage.get("input_tokens", 0))
            for k in usage:
                usage[k] += reply.usage.get(k, 0)
                self.totals[k] += reply.usage.get(k, 0)
            self.totals["llm_calls"] += 1
            self.peak_context = max(self.peak_context, reply.usage.get("input_tokens", 0) or ctx)

            self.messages.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls,
                                  "raw": reply.raw, "turn": self.turn})
            resume = self.compactor.resume_check(reply.tool_calls)
            if resume:
                self._log({"type": "resume_check", "turn": self.turn, "step": step, **resume})
                all_events.append(resume)

            step_log = []
            if reply.tool_calls:
                results = []
                for call in reply.tool_calls:
                    response, extra = self._run_tool(call.name, call.args or {})
                    raw_text = main_text(response)
                    raw_tokens = estimate(json.dumps(response, ensure_ascii=False))
                    entry = {"id": call.id, "name": call.name, "args": call.args, "response": response}
                    if raw_tokens > SMALL_RESULT_TOKENS:
                        entry["archive_id"] = self.archive.put(call.name, call.args, raw_text)
                        entry["response"] = cap_at_ingestion(entry, self.settings.tool_result_cap)
                    ctx_tokens = estimate(json.dumps(entry["response"], ensure_ascii=False))
                    results.append(entry)
                    tool_events.append(ToolEvent(call.name, call.args, entry["response"], raw_tokens, ctx_tokens,
                                                 entry.get("archive_id")))
                    step_log.append({"name": call.name, "args": _short_args(call.args), "raw_tokens": raw_tokens,
                                     "context_tokens": ctx_tokens, "archive_id": entry.get("archive_id"),
                                     "ok": response.get("ok"), **extra})
                    if call.name == "run_tests" and response.get("ok"):
                        passed = response.get("exit_code") == 0
                        if passed and self._last_tests_passed is False:
                            self.compactor.request("T4-milestone")
                        self._last_tests_passed = passed
                self.messages.append({"role": "tool", "results": results, "turn": self.turn})

            self._log({"type": "request", "turn": self.turn, "step": step, "model": self.llm.name,
                       "context_tokens_est": ctx, "utilization": round(self.compactor.utilization(ctx), 3),
                       "over_window": over, "usage": reply.usage, "tool_calls": step_log,
                       "text": (reply.text or "")[:2000], "n_messages": len(self.messages)})
            if not reply.tool_calls:
                text = reply.text
                return TurnResult(text, tool_events, usage, step, all_events)

        return TurnResult("(dừng: vượt giới hạn số bước gọi tool trong một lượt)", tool_events, usage,
                          self.settings.max_steps, all_events)

    def _log(self, record: dict[str, Any]) -> None:
        if self.recorder:
            self.recorder.log(record)

    def stats(self) -> dict[str, Any]:
        return {**self.totals, "peak_context": self.peak_context, "turns": self.turn,
                "n_compactions": self.compactor.n_full, "n_prunes": self.compactor.n_prune,
                "over_window_calls": self.over_window_calls, "final_context_est": self.context_tokens()}

    def close(self) -> None:
        if self.runner:
            self.runner.close()


def _short_args(args: dict[str, Any], limit: int = 400) -> dict[str, Any]:
    return {k: (v[:limit] + "…" if isinstance(v, str) and len(v) > limit else v) for k, v in (args or {}).items()}
