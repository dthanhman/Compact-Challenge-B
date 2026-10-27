"""Compaction pipeline (slide 26) — "controlled reboot" của working context.

    1 Observe budget → 2 Prune/archive → 3 Build checkpoint → 4 Reinject → 5 Resume & validate

Ba chiến lược để đối chứng (slide 21):
    none        không compact (chỉ ghi nhận khi vượt window ảo)
    truncate    bỏ các lượt cũ nhất cho tới khi dưới ngưỡng (rẻ, dễ mất ràng buộc)
    structured  pipeline đầy đủ ở trên

Compaction chỉ chạy GIỮA hai lần gọi model và chỉ xoá theo nguyên lượt (turn), nên
không bao giờ tách cặp tool_call ↔ tool_result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import Settings
from ..llm import LLM, empty_usage
from .checkpoint import (
    CHECKPOINT_ACK,
    CHECKPOINT_SYSTEM,
    Checkpoint,
    build_checkpoint_prompt,
    constraint_messages,
    parse_checkpoint,
    render_checkpoint_message,
    validate,
)
from .prune import fingerprint, prune, SMALL_RESULT_TOKENS, TRUNCATE, DROP
from ..tokens import estimate, estimate_message

STRATEGIES = ("none", "truncate", "structured")


class SessionLike(Protocol):
    messages: list[dict]
    turn: int
    llm: LLM

    def context_tokens(self) -> int: ...


@dataclass
class Compactor:
    settings: Settings
    strategy: str = "structured"
    checkpoint: Checkpoint | None = None
    pinned_user: list[dict] = field(default_factory=list)
    n_full: int = 0
    n_prune: int = 0
    pending_force: str | None = None  # "T4-milestone" | "manual"
    awaiting_resume_check: bool = False

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy phải là một trong {STRATEGIES}")

    # ------------------------------------------------------------- observe
    def utilization(self, tokens: int) -> float:
        return tokens / self.settings.usable_window

    def request(self, reason: str) -> None:
        """Yêu cầu full compaction ở lần gọi model kế tiếp (milestone hoặc /compact)."""
        if self.strategy == "structured":
            self.pending_force = reason

    def maybe_compact(self, session: SessionLike, recorder=None) -> list[dict[str, Any]]:
        tokens = session.context_tokens()
        util = self.utilization(tokens)
        force, self.pending_force = self.pending_force, None
        if self.strategy == "none":
            return []
        if self.strategy == "truncate":
            if util >= self.settings.full_threshold:
                ev = self._truncate(session, tokens, recorder)
                return [ev] if ev["dropped_turns"] else []  # chỉ còn lượt hiện tại: không bỏ được gì
            return []

        events: list[dict[str, Any]] = []
        dup = _has_duplicates(session.messages)
        if util >= self.settings.micro_threshold or dup or force:
            report = prune(session.messages, self.settings.keep_recent_steps)
            if report.actions:
                self.n_prune += 1
                after = session.context_tokens()
                events.append({
                    "type": "prune",
                    "trigger": "T3-duplicate" if dup and util < self.settings.micro_threshold else "T1-micro",
                    "tokens_before": tokens, "tokens_after": after,
                    "util_before": round(util, 3), "util_after": round(self.utilization(after), 3),
                    "actions": [a.__dict__ for a in report.actions],
                })
                tokens, util = after, self.utilization(after)

        if force or util >= self.settings.full_threshold:
            ev = self._full(session, tokens, force or "T2-full", recorder)
            if ev:
                events.append(ev)
        return events

    # ------------------------------------------------------------ strategies
    def _truncate(self, session: SessionLike, tokens: int, recorder) -> dict[str, Any]:
        if recorder:
            recorder.snapshot("before", session.messages)
        dropped_turns = []
        while self.utilization(session.context_tokens()) >= self.settings.micro_threshold:
            turns = sorted({m.get("turn", 0) for m in session.messages})
            if len(turns) <= 1:
                break
            oldest = turns[0]
            session.messages[:] = [m for m in session.messages if m.get("turn", 0) != oldest]
            dropped_turns.append(oldest)
        after = session.context_tokens()
        if recorder:
            recorder.snapshot("after", session.messages)
        return {"type": "truncate", "trigger": "T2-full", "dropped_turns": dropped_turns,
                "tokens_before": tokens, "tokens_after": after,
                "util_before": round(self.utilization(tokens), 3), "util_after": round(self.utilization(after), 3)}

    def _full(self, session: SessionLike, tokens: int, trigger: str, recorder) -> dict[str, Any] | None:
        cutoff = session.turn - self.settings.keep_recent_turns
        old = [m for m in session.messages if not m.get("checkpoint") and m.get("turn", 0) <= cutoff]
        if not old:
            return None  # chưa có lượt nào đủ cũ để nén
        gain = sum(estimate_message(m) for m in old)
        if trigger == "T2-full" and gain < self.settings.min_compact_gain:
            # Phần nén được quá nhỏ so với chi phí gọi LLM (và phá cache prefix): bỏ qua.
            return {"type": "compaction_skipped", "trigger": trigger, "tokens_before": tokens, "tokens_after": tokens,
                    "reason": f"phần cũ chỉ ~{gain} token < min_compact_gain={self.settings.min_compact_gain}"}
        if recorder:
            recorder.snapshot("before", session.messages)

        constraints = constraint_messages(self.pinned_user + old)
        usage = empty_usage()
        issues: list[str] = []
        cp = None
        cand = None
        warnings: list[str] = []
        attempts = 0
        for attempts in (1, 2):  # tạo + thử lại 1 lần nếu không hợp lệ
            prompt = build_checkpoint_prompt(self.checkpoint, old, issues or None)
            reply = session.llm.generate(CHECKPOINT_SYSTEM, [{"role": "user", "text": prompt}], [], json_mode=True)
            for k in usage:
                usage[k] += reply.usage.get(k, 0)
            try:
                cand = parse_checkpoint(reply.text)
            except (ValueError, TypeError) as exc:
                issues = [f"JSON không hợp lệ: {exc}"]
                continue
            cand, issues, warnings = validate(cand, constraints, getattr(session, "workspace_root", None))
            if not issues:
                cp = cand
                break

        base = {"trigger": trigger, "tokens_before": tokens, "util_before": round(self.utilization(tokens), 3),
                "llm_usage": usage, "attempts": attempts, "warnings": warnings}
        if cp is None:
            # Fallback an toàn: không thay context bằng checkpoint hỏng, chỉ giữ kết quả prune.
            return {**base, "type": "checkpoint_failed", "errors": issues,
                    "rejected": cand.to_dict() if cand else None,
                    "tokens_after": tokens, "util_after": base["util_before"]}

        self.checkpoint = cp
        self.n_full += 1
        self.pinned_user += [m for m in old if m["role"] == "user"]
        turns = [m.get("turn", 0) for m in old]
        covers = (min(turns), max(turns))
        recent = [m for m in session.messages if not m.get("checkpoint") and m.get("turn", 0) > cutoff]
        session.messages[:] = [
            {"role": "user", "text": render_checkpoint_message(cp, self.n_full, covers, self.pinned_user),
             "turn": 0, "checkpoint": True},
            {"role": "assistant", "text": CHECKPOINT_ACK, "tool_calls": [], "raw": None, "turn": 0, "checkpoint": True},
            *recent,
        ]
        after = session.context_tokens()
        self.awaiting_resume_check = True
        ckpt_file = recorder.save_checkpoint(cp, {"n": self.n_full, "covers_turns": covers, "trigger": trigger,
                                                  "at_turn": session.turn, "message": session.messages[0]["text"]}) if recorder else None
        if recorder:
            recorder.snapshot("after", session.messages)
        return {**base, "type": "compaction", "n": self.n_full, "covers_turns": list(covers),
                "tokens_after": after, "util_after": round(self.utilization(after), 3),
                "checkpoint_file": ckpt_file, "checkpoint": cp.to_dict(),
                "checkpoint_tokens": estimate(session.messages[0]["text"])}

    # ------------------------------------------------------- step 5: resume
    def resume_check(self, tool_calls: list) -> dict[str, Any] | None:
        """Ghi lại hành động đầu tiên sau compact để đối chiếu với next_action và failed_attempts."""
        if not self.awaiting_resume_check or self.checkpoint is None:
            return None
        self.awaiting_resume_check = False
        calls = [{"name": c.name, "args": c.args} for c in tool_calls]
        text = " ".join(f"{c['name']} {c['args']}" for c in calls).lower()
        repeats = [a for a in self.checkpoint.failed_attempts if _looks_like(a.get("what", ""), text)]
        return {"type": "resume_check", "next_action": self.checkpoint.next_action,
                "first_calls": calls, "possible_repeats": repeats}


def _has_duplicates(messages: list[dict]) -> bool:
    seen: set[str] = set()
    for m in messages:
        if m["role"] != "tool":
            continue
        for r in m["results"]:
            if r.get("label") in (TRUNCATE, DROP):
                continue
            if estimate(str(r["response"])) <= SMALL_RESULT_TOKENS:
                continue
            fp = fingerprint(r["response"])
            if fp in seen:
                return True
            seen.add(fp)
    return False


def _looks_like(attempt: str, call_text: str) -> bool:
    words = {w for w in attempt.lower().replace("/", " ").split() if len(w) >= 3}
    if not words or not call_text:
        return False
    return sum(1 for w in words if w in call_text) / len(words) >= 0.5
