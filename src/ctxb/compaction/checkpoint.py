"""Bước 3 của pipeline: structured checkpoint (slide 22) — schema, prompt, validate, render.

Checkpoint là trạng thái đủ để làm **hành động tiếp theo** (slide 20), không phải bản recap chat.
Checkpoint được cập nhật tăng dần: checkpoint cũ + phần hội thoại sắp bị nén → checkpoint mới.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONSTRAINT_HINT = re.compile(
    r"\b(phải|không được|không đổi|giữ nguyên|giữ|lưu ý|bắt buộc|ràng buộc|must|keep|do not|don't|never)\b",
    re.IGNORECASE,
)
# next_action chỉ là "chờ user" → trạng thái tạm bị ghi nhầm thành hành động (báo cáo §4.8)
# Chỉ bắt chờ USER (chờ chỉ đạo/xác nhận/cho phép…); "chờ kết quả test" vẫn hợp lệ.
WAITING_ONLY = re.compile(
    r"^\W*(chờ|đợi|wait)\b.{0,40}\b(user|người dùng|chỉ đạo|chỉ thị|xác nhận|cho phép|phê duyệt|yêu cầu|phản hồi|quyết định)",
    re.IGNORECASE,
)


@dataclass
class Checkpoint:
    goal: str = ""
    current_state: str = ""
    constraints: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    failed_attempts: list[dict[str, str]] = field(default_factory=list)  # {what, result, evidence?}
    files: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_action: str = ""
    waiting_for_user: str = ""  # trạng thái TẠM (đang chờ user quyết định/cho phép); không phải ràng buộc
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Checkpoint":
        def _list(v):
            if v is None:
                return []
            return v if isinstance(v, list) else [v]

        attempts = []
        for a in _list(d.get("failed_attempts")):
            if isinstance(a, dict):
                attempts.append({k: str(v) for k, v in a.items() if v is not None})
            else:
                attempts.append({"what": str(a), "result": ""})
        return cls(
            goal=str(d.get("goal") or "").strip(),
            current_state=str(d.get("current_state") or "").strip(),
            constraints=[str(x) for x in _list(d.get("constraints"))],
            findings=[str(x) for x in _list(d.get("findings"))],
            failed_attempts=attempts,
            files=[str(x) for x in _list(d.get("files"))],
            open_questions=[str(x) for x in _list(d.get("open_questions"))],
            next_action=str(d.get("next_action") or "").strip(),
            waiting_for_user=str(d.get("waiting_for_user") or "").strip(),
            evidence_refs=[str(x) for x in _list(d.get("evidence_refs"))],
        )


CHECKPOINT_SYSTEM = """Bạn là bộ nén context của một coding agent. Nhiệm vụ: cập nhật CHECKPOINT có cấu trúc
để agent có thể tiếp tục công việc CHÍNH XÁC sau khi phần hội thoại cũ bị xoá khỏi context.

Checkpoint không phải bản kể lại; chỉ giữ thông tin cần cho hành động tiếp theo.
Trả về DUY NHẤT một JSON object với các trường:
{
  "goal": "mục tiêu hiện tại của user (1 câu)",
  "current_state": "trạng thái hiện tại: đã làm gì, test đang thế nào",
  "constraints": ["ràng buộc áp dụng cho CẢ PHIÊN user đã nêu — chép gần nguyên văn kèm điều kiện, KHÔNG được bỏ"],
  "findings": ["phát hiện kỹ thuật đã xác nhận bằng bằng chứng"],
  "failed_attempts": [{"what": "cách đã thử", "result": "vì sao không được", "evidence": "archive id nếu có"}],
  "files": ["đường dẫn file liên quan, đúng như trong workspace"],
  "open_questions": ["câu hỏi còn mở"],
  "next_action": "bước KỸ THUẬT cụ thể tiếp theo để đạt goal (sửa gì, ở file/hàm nào, kiểm tra bằng gì)",
  "waiting_for_user": "nếu đang chờ user quyết định/cho phép thì ghi ở đây (vd. 'chờ user cho phép sửa code'), không thì để rỗng",
  "evidence_refs": ["archive id (aNNN) chứa bằng chứng quan trọng"]
}
Quy tắc:
- Giữ mọi mục của checkpoint cũ trừ khi hội thoại mới cho thấy nó không còn đúng.
- Phân biệt RÀNG BUỘC VĨNH VIỄN với TRẠNG THÁI TẠM:
  * constraints chỉ chứa quy tắc user muốn áp dụng suốt phiên. Quy tắc có điều kiện phải giữ nguyên điều kiện
    (vd. "không sửa code KHI user chưa yêu cầu rõ ràng"), không rút gọn thành "không sửa code".
  * "đang chờ user", "chưa được phép sửa" là trạng thái tạm → ghi vào waiting_for_user, KHÔNG ghi vào constraints.
- next_action KHÔNG được là "chờ user"/"đợi chỉ đạo": luôn ghi bước kỹ thuật sẽ làm khi được phép
  (vd. "thêm single-flight lock cho refresh() trong src/auth.ts rồi chạy test").
- failed_attempts phải liệt kê MỌI cách đã thử mà thất bại, để agent không lặp lại.
- Không bịa file hay kết quả không có trong hội thoại.
- Viết bằng tiếng Việt; tên file, tên hàm, mã lỗi giữ nguyên."""


def render_turns_for_compaction(messages: list[dict], max_result_chars: int = 1500) -> str:
    """Chuyển phần hội thoại sắp bị nén thành transcript gọn để đưa cho model nén."""
    out: list[str] = []
    for m in messages:
        turn = m.get("turn", "?")
        if m["role"] == "user":
            out.append(f"[turn {turn}] USER: {m['text']}")
        elif m["role"] == "assistant":
            if m.get("text"):
                out.append(f"[turn {turn}] ASSISTANT: {m['text']}")
            for c in m.get("tool_calls") or []:
                out.append(f"[turn {turn}] TOOL_CALL {c.name} {json.dumps(c.args, ensure_ascii=False)[:600]}")
        elif m["role"] == "tool":
            for r in m["results"]:
                body = json.dumps(r["response"], ensure_ascii=False)
                if len(body) > max_result_chars:
                    body = body[: max_result_chars // 3] + " …[lược]… " + body[-(max_result_chars * 2 // 3):]
                aid = f" (archive {r['archive_id']})" if r.get("archive_id") else ""
                out.append(f"[turn {turn}] TOOL_RESULT {r['name']}{aid}: {body}")
    return "\n".join(out)


def build_checkpoint_prompt(previous: Checkpoint | None, old_messages: list[dict], issues: list[str] | None = None) -> str:
    parts = [
        "CHECKPOINT CŨ:",
        json.dumps(previous.to_dict(), ensure_ascii=False, indent=2) if previous else "(chưa có)",
        "",
        "PHẦN HỘI THOẠI SẮP BỊ NÉN:",
        render_turns_for_compaction(old_messages),
    ]
    if issues:
        parts += ["", "LẦN TRƯỚC CHECKPOINT KHÔNG HỢP LỆ, hãy sửa các lỗi sau:", *[f"- {i}" for i in issues]]
    parts += ["", "Trả về checkpoint mới (JSON)."]
    return "\n".join(parts)


def parse_checkpoint(text: str) -> Checkpoint:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("không tìm thấy JSON object")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("checkpoint phải là JSON object")
    return Checkpoint.from_dict(data)


def constraint_messages(messages: list[dict]) -> list[str]:
    """Các lượt user có dấu hiệu nêu ràng buộc — dùng để kiểm tra checkpoint không làm mất constraint."""
    return [m["text"] for m in messages if m["role"] == "user" and CONSTRAINT_HINT.search(m.get("text", ""))]


def validate(cp: Checkpoint, user_constraints: list[str], workspace: Path | None) -> tuple[Checkpoint, list[str], list[str]]:
    """Trả về (checkpoint đã làm sạch, lỗi nghiêm trọng, cảnh báo).

    Lỗi nghiêm trọng → harness yêu cầu tạo lại; vẫn lỗi → không dùng checkpoint (chỉ prune).
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not cp.goal:
        errors.append("thiếu goal")
    if not cp.next_action:
        errors.append("thiếu next_action")
    elif WAITING_ONLY.search(cp.next_action):
        # Chỉ lỗi khi bỏ vế "chờ user" (tới dấu ; hoặc .) thì không còn bước kỹ thuật nào.
        rest = re.split(r"[;.]", cp.next_action, maxsplit=1)[1:] or [""]
        if len(rest[0].split()) < 5:
            errors.append("next_action chỉ là trạng thái chờ user; hãy ghi bước kỹ thuật cụ thể, "
                          "trạng thái chờ đưa vào waiting_for_user")
        else:
            warnings.append("next_action mở đầu bằng trạng thái chờ user (nên để ở waiting_for_user)")
    if user_constraints and not cp.constraints:
        errors.append("user đã nêu ràng buộc nhưng constraints rỗng: " + " | ".join(c[:120] for c in user_constraints))
    if workspace is not None:
        kept = []
        for f in cp.files:
            path = f.strip().lstrip("./")
            if (workspace / path).exists():
                kept.append(path)
            else:
                warnings.append(f"bỏ file không tồn tại trong workspace: {f}")
        cp.files = kept
    return cp, errors, warnings


def render_checkpoint_message(cp: Checkpoint, n: int, covers: tuple[int, int], pinned_user: list[dict]) -> str:
    """Nội dung message được reinject thay cho phần hội thoại đã nén (bước 4)."""
    lines = [
        f"<checkpoint n={n} covers_turns={covers[0]}-{covers[1]}>",
        "Context đã được compact. Đây là trạng thái công việc thay cho phần hội thoại cũ:",
        "```json",
        json.dumps(cp.to_dict(), ensure_ascii=False, indent=2),
        "```",
    ]
    if pinned_user:
        lines.append("Các yêu cầu gốc của user trong phần đã nén (KEEP nguyên văn):")
        for m in pinned_user:
            lines.append(f"- [turn {m.get('turn')}] {m['text'][:500]}")
    lines += [
        "Thứ tự ưu tiên: constraints > yêu cầu MỚI NHẤT của user > next_action / waiting_for_user của checkpoint.",
        "waiting_for_user là trạng thái tạm: hết hiệu lực ngay khi user đưa yêu cầu mới.",
        "Raw output cũ đã được archive; dùng read_archive(id, pattern) khi cần lại bằng chứng.",
        "</checkpoint>",
    ]
    return "\n".join(lines)


CHECKPOINT_ACK = ("Đã nạp checkpoint. Tôi tuân thủ constraints, không lặp lại failed_attempts, "
                  "làm theo yêu cầu mới nhất của user; nếu không có yêu cầu mới thì tiếp tục từ next_action.")
