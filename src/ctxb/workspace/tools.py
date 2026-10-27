"""Tool thao tác workspace giả lập: list_files, read_file, grep, run_tests, write_file, replace_in_file.

Mọi đường dẫn bị giới hạn trong workspace; mọi lời gọi đi qua ``Policy``.
``run_tests`` mô phỏng Jest: output ~7.000 dòng (slide 19), kết quả phụ thuộc nội dung code.
"""

from __future__ import annotations

import fnmatch
import random
import re
from pathlib import Path
from typing import Any

from ..policy import Policy
from .fixtures import REFRESH_SIGNATURE

LOCK_PATTERN = re.compile(
    r"inflight|in_flight|pendingRefresh|pending_refresh|refreshPromise|mutex|singleflight|single_flight"
    r"|\block\b|\.lock\(|Map<string,\s*Promise",
    re.IGNORECASE,
)

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "list_files": {
        "name": "list_files",
        "description": "Liệt kê file trong workspace theo glob (vd 'src/**/*.ts', 'logs/*.log'). Trả về danh sách đường dẫn.",
        "parameters": {
            "type": "object",
            "properties": {"glob": {"type": "string", "description": "Mẫu glob, mặc định '**/*'"}},
        },
    },
    "read_file": {
        "name": "read_file",
        "description": "Đọc file văn bản UTF-8 trong workspace. Có thể đọc một khoảng dòng (1-based, bao gồm hai đầu).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    "grep": {
        "name": "grep",
        "description": "Tìm regex trong các file khớp glob. Trả về các dòng 'path:line: text'.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "glob": {"type": "string", "description": "Mặc định '**/*'"},
                "max_matches": {"type": "integer", "description": "Mặc định 2000"},
            },
            "required": ["pattern"],
        },
    },
    "run_tests": {
        "name": "run_tests",
        "description": "Chạy toàn bộ test suite (jest --verbose) và trả về output đầy đủ.",
        "parameters": {"type": "object", "properties": {}},
    },
    "write_file": {
        "name": "write_file",
        "description": "Ghi đè toàn bộ nội dung một file trong workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "replace_in_file": {
        "name": "replace_in_file",
        "description": "Thay một đoạn văn bản chính xác (old) bằng new trong file. old phải xuất hiện đúng một lần.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
            "required": ["path", "old", "new"],
        },
    },
}


class WorkspaceError(Exception):
    pass


class WorkspaceTools:
    def __init__(self, root: str | Path, policy: Policy | None = None, test_scale: float = 1.0) -> None:
        self.root = Path(root).resolve()
        self.policy = policy or Policy()
        self.test_scale = test_scale
        self.test_runs: list[dict[str, Any]] = []  # lịch sử kết quả test (cho milestone + chấm điểm)
        self.writes: list[dict[str, Any]] = []  # lịch sử ghi file (cho chấm điểm A1)
        self.turn = 0  # lượt hiện tại, do Session cập nhật

    # ---------------------------------------------------------------- helpers
    def resolve(self, path: str) -> Path:
        p = (self.root / path.replace("\\", "/").lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise WorkspaceError(f"đường dẫn nằm ngoài workspace: {path}")
        return p

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def _iter_files(self, glob: str):
        glob = (glob or "**/*").replace("\\", "/")
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                rel = self.rel(p)
                if fnmatch.fnmatch(rel, glob) or (glob.startswith("**/") and fnmatch.fnmatch(rel, glob[3:])):
                    yield p, rel

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return {"ok": False, "error": f"Tool không tồn tại: {name}"}
        decision = self.policy.check(name, args or {})
        if not decision.allowed:
            return {"ok": False, "error": f"PERMISSION_DENIED: {decision.reason}"}
        try:
            return handler(**(args or {}))
        except TypeError as exc:
            return {"ok": False, "error": f"Tham số không hợp lệ: {exc}"}
        except (WorkspaceError, FileNotFoundError, ValueError, re.error) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ tools
    def tool_list_files(self, glob: str = "**/*") -> dict[str, Any]:
        files = [rel for _, rel in self._iter_files(glob)][:1000]
        return {"ok": True, "count": len(files), "files": files}

    def tool_read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> dict[str, Any]:
        p = self.resolve(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        lines = p.read_text(encoding="utf-8").splitlines()
        s = max(1, int(start_line or 1))
        e = min(len(lines), int(end_line or len(lines)))
        return {"ok": True, "path": path, "total_lines": len(lines), "start_line": s, "end_line": e,
                "content": "\n".join(lines[s - 1 : e])}

    def tool_grep(self, pattern: str, glob: str = "**/*", max_matches: int = 2000) -> dict[str, Any]:
        rx = re.compile(pattern)
        out: list[str] = []
        for p, rel in self._iter_files(glob):
            if not self.policy.allow_dotfiles and Policy.is_dotfile(rel):
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{rel}:{i}: {line}")
                    if len(out) >= max_matches:
                        return {"ok": True, "count": len(out), "truncated": True, "matches": "\n".join(out)}
        return {"ok": True, "count": len(out), "truncated": False, "matches": "\n".join(out)}

    def tool_write_file(self, path: str, content: str) -> dict[str, Any]:
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.writes.append({"tool": "write_file", "path": self.rel(p), "turn": self.turn, "text": content})
        return {"ok": True, "path": self.rel(p), "bytes": len(content.encode("utf-8"))}

    def tool_replace_in_file(self, path: str, old: str, new: str) -> dict[str, Any]:
        p = self.resolve(path)
        text = p.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            raise ValueError(f"'old' xuất hiện {n} lần trong {path} (cần đúng 1)")
        p.write_text(text.replace(old, new), encoding="utf-8")
        self.writes.append({"tool": "replace_in_file", "path": self.rel(p), "turn": self.turn, "old": old, "text": new})
        return {"ok": True, "path": self.rel(p)}

    def tool_run_tests(self) -> dict[str, Any]:
        failing = self.failing_tests()
        output = render_jest_output(failing, scale=self.test_scale)
        self.test_runs.append({"failing": failing, "passed": not failing, "turn": self.turn})
        return {"ok": True, "exit_code": 1 if failing else 0, "output": output}

    # ------------------------------------------------------- mô phỏng test
    def code_state(self) -> dict[str, bool]:
        src = ""
        for name in ("src/auth.ts", "src/session.ts"):
            p = self.root / name
            if p.exists():
                src += p.read_text(encoding="utf-8")
        auth = (self.root / "src/auth.ts").read_text(encoding="utf-8") if (self.root / "src/auth.ts").exists() else ""
        return {
            "race_fixed": bool(LOCK_PATTERN.search(src)),
            "signature_ok": " ".join(REFRESH_SIGNATURE.split()) in " ".join(auth.split()),
        }

    def failing_tests(self) -> list[str]:
        st = self.code_state()
        failing = []
        if not st["race_fixed"]:
            failing += [
                "auth.refresh › concurrent refresh returns same token",
                "auth.refresh › refresh after expiry",
                "auth.refresh › parallel logout",
            ]
        if not st["signature_ok"]:
            failing.append("auth.refresh › api: refresh signature is backward compatible")
        return failing


SUITES = ["session", "orders", "payments", "users", "cart", "policy", "claims", "config", "utils", "tokenStore", "logout"]

FAIL_DETAIL = {
    "concurrent refresh returns same token": ("AuthError: ERR_TOKEN_REUSED", "src/auth.ts:34:11"),
    "refresh after expiry": ("AuthError: ERR_TOKEN_REUSED", "src/session.ts:17:20"),
    "parallel logout": ("AuthError: ERR_TOKEN_REUSED", "src/auth.ts:34:11"),
    "api: refresh signature is backward compatible": ("expect(received).toBe(expected)\n\n    Expected: 1\n    Received: 2", "tests/auth.test.ts:37:28"),
}


def render_jest_output(failing: list[str], scale: float = 1.0, seed: int = 11) -> str:
    """Output kiểu ``jest --verbose``, deterministic, ~7.000 dòng khi scale=1."""
    rng = random.Random(seed + len(failing))
    target = int(7000 * scale)
    lines = ["> authsvc@1.0.0 test", "> jest --verbose", ""]
    auth_tests = ["rotates refresh token", "concurrent refresh returns same token", "refresh after expiry",
                  "parallel logout", "api: refresh signature is backward compatible"]
    failing_names = {f.split(" › ", 1)[1] for f in failing}
    lines.append("FAIL tests/auth.test.ts" if failing else "PASS tests/auth.test.ts")
    lines.append("  auth.refresh")
    for t in auth_tests:
        mark = "✕" if t in failing_names else "✓"
        lines.append(f"    {mark} {t} ({rng.randint(3, 40)} ms)")
    lines.append("")

    passed = len(auth_tests) - len(failing_names)
    body: list[str] = []
    suite_i = 0
    budget = target - 60 - 14 * len(failing)
    while len(body) < budget:
        suite = SUITES[suite_i % len(SUITES)]
        suite_i += 1
        body.append(f"PASS tests/{suite}.test.ts")
        body.append(f"  {suite}")
        for k in range(rng.randint(15, 30)):
            body.append(f"    ✓ {suite} case {suite_i}.{k} handles input variant {rng.randint(1, 999)} ({rng.randint(1, 30)} ms)")
            passed += 1
            if rng.random() < 0.35:  # log retry lặp lại (slide 19: "cộng log retry lặp lại")
                attempt = rng.randint(1, 3)
                body += [
                    "  console.log",
                    f"    [retry] refresh attempt={attempt} backoff={attempt * 100}ms",
                    "",
                    "      at Object.<anonymous> (src/session.ts:17:11)",
                    "",
                ]
        body.append("")
    lines += body[:budget]

    if failing:
        lines += ["", "Summary of all failing tests"]
        for f in failing:
            name = f.split(" › ", 1)[1]
            err, where = FAIL_DETAIL[name]
            lines += [
                "FAIL tests/auth.test.ts",
                f"  ● {f}",
                "",
                f"    {err}",
                "",
                "      33 |   if (!record || record.revoked) {",
                '    > 34 |     throw new AuthError("ERR_TOKEN_REUSED");',
                "         |           ^",
                "      35 |   }",
                "",
                f"      at refresh ({where})",
                "      at async Promise.all (index 1)",
                "",
            ]
    total = passed + len(failing)
    lines += [
        f"Test Suites: {'1 failed, ' if failing else ''}{suite_i + (0 if failing else 1)} passed, {suite_i + 1} total",
        f"Tests:       {str(len(failing)) + ' failed, ' if failing else ''}{passed} passed, {total} total",
        "Snapshots:   0 total",
        f"Time:        {8 + rng.random() * 3:.3f} s",
        "Ran all test suites.",
    ]
    return "\n".join(lines)
