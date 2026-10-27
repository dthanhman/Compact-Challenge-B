"""Bước 2 của pipeline: prune tool output theo nhãn KEEP / TRUNCATE / DROP (slide 23).

Không gọi LLM. Chỉ sửa ``response`` của tool result (giữ nguyên cặp tool_call ↔ tool_result
và message assistant), nên API vẫn hợp lệ. Raw output luôn có trong archive trước khi bị cắt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..tokens import estimate

KEEP, TRUNCATE, DROP = "KEEP", "TRUNCATE", "DROP"

SMALL_RESULT_TOKENS = 300
TRUNCATE_TOOLS = {"run_tests"}
DROP_TOOLS = {"read_file", "grep", "list_files", "read_archive", "run_code"}
KEY_LINE = re.compile(r"FAIL|●|✕|Tests:|Test Suites:|Error|Expected|Received|at refresh")


@dataclass
class PruneAction:
    turn: int
    tool: str
    label: str
    reason: str
    tokens_before: int
    tokens_after: int
    archive_id: str | None = None


@dataclass
class PruneReport:
    actions: list[PruneAction] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return sum(a.tokens_before - a.tokens_after for a in self.actions)


def _size(response: dict) -> int:
    return estimate(json.dumps(response, ensure_ascii=False))


def main_text(response: dict) -> str:
    for key in ("output", "content", "matches", "stdout"):
        if isinstance(response.get(key), str):
            return response[key]
    if isinstance(response.get("files"), list):
        return "\n".join(response["files"])
    return json.dumps(response, ensure_ascii=False)


def fingerprint(response: dict) -> str:
    """Hash nội dung sau khi bỏ số đo thời gian (ms, s) — để phát hiện output lặp lại (trigger T3)."""
    text = re.sub(r"\d+(\.\d+)?\s*m?s\b", "#", main_text(response))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def key_lines(text: str, limit: int = 20) -> list[str]:
    out = [l.rstrip() for l in text.splitlines() if KEY_LINE.search(l)]
    return out[:limit]


def truncate_response(result: dict) -> dict:
    resp = result["response"]
    return {
        "ok": resp.get("ok", True),
        "exit_code": resp.get("exit_code"),
        "summary": "\n".join(key_lines(main_text(resp))),
        "archived": result.get("archive_id"),
        "note": f"[TRUNCATE] Output gốc đã được archive; dùng read_archive('{result.get('archive_id')}', pattern) nếu cần thêm.",
    }


def drop_response(result: dict, reason: str) -> dict:
    args = result.get("args") or {}
    hint = {
        "read_file": f"đọc lại bằng read_file('{args.get('path', '')}')",
        "grep": "chạy lại grep nếu cần",
        "list_files": "chạy lại list_files nếu cần",
    }.get(result["name"], f"read_archive('{result.get('archive_id')}')")
    return {"ok": True, "archived": result.get("archive_id"), "args": args,
            "note": f"[DROP] {reason}. Dữ liệu dễ tái tạo: {hint}."}


def _label(result: dict, response: dict) -> tuple[str, str]:
    if result.get("label") in (TRUNCATE, DROP):
        return result["label"], "đã xử lý trước đó"
    if _size(response) <= SMALL_RESULT_TOKENS or not response.get("ok", True):
        return KEEP, "nhỏ hoặc là lỗi (bằng chứng cần giữ)"
    if result["name"] in TRUNCATE_TOOLS:
        return TRUNCATE, "output test dài → giữ dòng lỗi chính"
    if result["name"] in DROP_TOOLS:
        return DROP, "dữ liệu dễ tái tạo"
    return KEEP, "không thuộc nhóm prune"


def prune(messages: list[dict], keep_recent_steps: int) -> PruneReport:
    """Prune tool result, trừ ``keep_recent_steps`` tool message gần nhất; bản trùng thì prune ở mọi vị trí.

    Xét theo BƯỚC (tool message) chứ không theo lượt: một lượt user có thể kéo theo nhiều tool call lớn,
    nên chỉ bảo vệ vài kết quả mới nhất (model có thể chưa đọc chúng).
    """
    report = PruneReport()
    tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    protected = set(tool_idx[-keep_recent_steps:]) if keep_recent_steps > 0 else set()

    # T3: output trùng nhau → chỉ giữ bản mới nhất
    latest: dict[str, tuple[int, int]] = {}
    for mi, m in enumerate(messages):
        if m["role"] == "tool":
            for ri, r in enumerate(m["results"]):
                if r.get("label") not in (TRUNCATE, DROP) and _size(r["response"]) > SMALL_RESULT_TOKENS:
                    latest[fingerprint(r["response"])] = (mi, ri)

    for mi, m in enumerate(messages):
        if m["role"] != "tool":
            continue
        for ri, r in enumerate(m["results"]):
            resp = r["response"]
            if r.get("label") in (TRUNCATE, DROP):
                continue
            before = _size(resp)
            fp = fingerprint(resp) if before > SMALL_RESULT_TOKENS else None
            if fp and latest.get(fp) not in (None, (mi, ri)) and mi not in protected:
                r["response"] = drop_response(r, "trùng với một kết quả mới hơn")
                r["label"] = DROP
                report.actions.append(PruneAction(m.get("turn", 0), r["name"], DROP, "trùng lặp (T3)", before,
                                                  _size(r["response"]), r.get("archive_id")))
                continue
            if mi in protected:
                continue
            label, reason = _label(r, resp)
            if label == KEEP:
                r.setdefault("label", KEEP)
                continue
            r["response"] = truncate_response(r) if label == TRUNCATE else drop_response(r, reason)
            r["label"] = label
            report.actions.append(PruneAction(m.get("turn", 0), r["name"], label, reason, before,
                                              _size(r["response"]), r.get("archive_id")))
    return report


def label_counts(messages: list[dict]) -> dict[str, int]:
    counts = {KEEP: 0, TRUNCATE: 0, DROP: 0}
    for m in messages:
        if m["role"] == "tool":
            for r in m["results"]:
                counts[r.get("label", KEEP)] = counts.get(r.get("label", KEEP), 0) + 1
    return counts


def cap_at_ingestion(result: dict[str, Any], cap_tokens: int) -> dict[str, Any]:
    """Giới hạn kích thước MỘT tool result khi vừa vào context (lưới an toàn, như output cap ở md §6.2).

    Giữ đầu (25%) và cuối (75%) của trường văn bản chính — output test của Jest để
    phần tóm tắt lỗi ở cuối nên phần cuối quan trọng hơn.
    """
    resp = result["response"]
    if _size(resp) <= cap_tokens:
        return resp
    key = next((k for k in ("output", "content", "matches", "stdout") if isinstance(resp.get(k), str)), None)
    if key is None:
        return resp
    text = resp[key]
    budget = cap_tokens * 4
    head, tail = text[: budget // 4], text[-(budget * 3 // 4):]
    cut_lines = text.count("\n") - head.count("\n") - tail.count("\n")
    new = dict(resp)
    new[key] = (
        f"{head}\n... [harness: đã lược {cut_lines} dòng ở giữa; bản đầy đủ: "
        f"read_archive('{result.get('archive_id')}', pattern)] ...\n{tail}"
    )
    new["truncated_at_ingestion"] = True
    return new
