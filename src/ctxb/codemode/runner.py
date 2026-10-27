"""Code Mode runtime (md §3, §5, §6): chạy chương trình model viết, chỉ stdout vào context.

Tầng 1 — "bash tối giản" (md §8): script Python chạy trong subprocess ``python -I``,
    cwd = BẢN SAO workspace (không có file ẩn như .env), env gần như rỗng,
    timeout, output cap, lỗi trả về dạng ngắn.
Tầng 2 — ``tools.*`` proxy: script gọi ``tools.read_file(...)`` ... ; mỗi lời gọi đi qua
    JSON-RPC (stdout → harness → stdin), được Policy kiểm tra và ghi trace.

⚠️ Subprocess KHÔNG phải sandbox: script vẫn có thể dùng ``open``/``urllib`` để đi vòng proxy
(md §6.5). Production cần container không mạng, gVisor hoặc Firecracker.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..policy import Policy
from ..tokens import estimate
from ..workspace.tools import WorkspaceTools

RPC_PREFIX = "\x1eRPC"

PRELUDE = r'''
import json as _json, sys as _sys
class _ToolsProxy:
    """tools.* — mọi lời gọi được gửi về harness (RPC), không chạy trực tiếp trong runtime."""
    def __getattr__(self, name):
        def call(*args, **kwargs):
            _sys.__stdout__.write("\x1eRPC" + _json.dumps({"tool": name, "args": list(args), "kwargs": kwargs}) + "\n")
            _sys.__stdout__.flush()
            line = _sys.stdin.readline()
            if not line:
                raise RuntimeError("harness đã đóng kênh RPC")
            resp = _json.loads(line)
            if not resp.get("ok"):
                raise PermissionError(resp.get("error")) if "PERMISSION_DENIED" in str(resp.get("error")) else RuntimeError(resp.get("error"))
            return resp.get("value")
        return call
tools = _ToolsProxy()
del _ToolsProxy
# `python -I` bỏ qua PYTHONIOENCODING → tự đặt UTF-8, nếu không print tiếng Việt sẽ lỗi trên Windows (cp1252)
_sys.stdout.reconfigure(encoding="utf-8")
_sys.stderr.reconfigure(encoding="utf-8")
_sys.modules["tools"] = tools  # cho phép cả `import tools`
'''

# SDK mà model nhìn thấy (cách A ở md §4: nhúng vào description của run_code)
SDK_DOC = """SDK có sẵn trong script dưới tên `tools` (mọi lời gọi đi qua harness, có kiểm tra quyền):
  tools.list_files(glob: str = "**/*") -> list[str]
  tools.read_file(path: str) -> str
  tools.grep(pattern: str, glob: str = "**/*") -> list[str]        # mỗi phần tử 'path:line: text'
  tools.http_post(url: str, body: dict) -> dict                     # thường bị policy chặn
Script cũng có thể đọc file trực tiếp bằng open() vì cwd là bản sao workspace (không có file ẩn).
CHỈ những gì script print ra mới được trả về cho bạn (tối đa {cap} ký tự). Hãy lọc và tổng hợp
trong script, print kết quả cuối cùng kèm số liệu kiểm chứng (số file đã quét, số dòng khớp, file lỗi)."""

SDK_PARAMS = {"list_files": ["glob"], "read_file": ["path"], "grep": ["pattern", "glob"], "http_post": ["url", "body"]}


def run_code_spec(output_cap: int) -> dict[str, Any]:
    return {
        "name": "run_code",
        "description": "Chạy một chương trình Python 3 (Code Mode) trên dữ liệu của workspace.\n" + SDK_DOC.format(cap=output_cap),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Mã Python hoàn chỉnh; dùng print() cho kết quả cuối"}},
            "required": ["code"],
        },
    }


@dataclass
class CodeRunResult:
    ok: bool
    stdout: str
    error: str | None
    tool_calls: int
    denied: list[dict[str, Any]]
    elapsed_s: float
    runtime_tokens: int  # token dữ liệu tool đã trả cho runtime (KHÔNG vào context)
    stdout_chars_total: int
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_context(self) -> dict[str, Any]:
        """Phần đi vào context của LLM: chỉ stdout (đã cap) + vài số liệu nhỏ."""
        out: dict[str, Any] = {"ok": self.ok, "stdout": self.stdout, "tool_calls": self.tool_calls}
        if self.error:
            out["error"] = self.error
        if self.denied:
            out["denied"] = [d["reason"] for d in self.denied]
        return out


class CodeRunner:
    def __init__(self, workspace: WorkspaceTools, policy: Policy | None = None, timeout: float = 10.0,
                 output_cap: int = 2000, max_tool_calls: int = 300) -> None:
        self.ws = workspace
        self.policy = policy or workspace.policy
        self.timeout = timeout
        self.output_cap = output_cap
        self.max_tool_calls = max_tool_calls
        self.runs: list[CodeRunResult] = []
        self.outbox: list[dict[str, Any]] = []  # http_post được cho phép thì chỉ ghi lại, không gửi thật
        self._copy_dir = Path(tempfile.mkdtemp(prefix="ctxb_rt_"))
        self._sync_copy()

    def _sync_copy(self) -> None:
        """Bản sao workspace cho runtime, bỏ mọi file/thư mục ẩn (.env ...)."""
        dst = self._copy_dir / "ws"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(self.ws.root, dst, ignore=lambda d, names: [n for n in names if n.startswith(".")])

    # ------------------------------------------------------------------ RPC
    def _handle_rpc(self, payload: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
        tool = payload.get("tool", "")
        params = SDK_PARAMS.get(tool)
        if params is None:
            return {"ok": False, "error": f"tools.{tool} không tồn tại"}
        args = dict(zip(params, payload.get("args") or []))
        args.update(payload.get("kwargs") or {})
        decision = self.policy.check(tool, args)
        entry: dict[str, Any] = {"tool": tool, "args": args, "allowed": decision.allowed}
        if not decision.allowed:
            entry["reason"] = decision.reason
            trace.append(entry)
            return {"ok": False, "error": f"PERMISSION_DENIED: {decision.reason}"}
        if tool == "http_post":
            self.outbox.append(args)
            value: Any = {"status": 200, "simulated": True}
        else:
            res = self.ws.dispatch(tool, args)
            if not res.get("ok"):
                entry["error"] = res.get("error")
                trace.append(entry)
                return {"ok": False, "error": res.get("error")}
            value = {"list_files": lambda r: r["files"], "read_file": lambda r: r["content"],
                     "grep": lambda r: r["matches"].splitlines() if r["matches"] else []}[tool](res)
        entry["result_tokens"] = estimate(json.dumps(value, ensure_ascii=False))
        trace.append(entry)
        return {"ok": True, "value": value}

    # ------------------------------------------------------------------- run
    def run(self, code: str) -> CodeRunResult:
        self._sync_copy()  # phản ánh thay đổi mới nhất của workspace
        script = self._copy_dir / "main.py"
        script.write_text(PRELUDE + "\n" + code, encoding="utf-8")
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        if os.name == "nt":  # Python trên Windows cần SYSTEMROOT để khởi động
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        start = time.monotonic()
        proc = subprocess.Popen(
            [sys.executable, "-I", str(script)], cwd=self._copy_dir / "ws", env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        lines: queue.Queue = queue.Queue()
        stderr_chunks: list[str] = []

        def pump_stdout() -> None:
            for l in proc.stdout:
                lines.put(l)
            lines.put(None)  # EOF

        threading.Thread(target=pump_stdout, daemon=True).start()
        threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True).start()

        trace: list[dict[str, Any]] = []
        out_parts: list[str] = []
        out_chars = 0
        error = None
        calls = 0
        while True:
            remaining = self.timeout - (time.monotonic() - start)
            if remaining <= 0:
                proc.kill()
                error = f"TimeoutError: script chạy quá {self.timeout:g}s và đã bị dừng"
                break
            try:
                line = lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith(RPC_PREFIX):
                calls += 1
                if calls > self.max_tool_calls:
                    proc.kill()
                    error = f"ToolCallLimit: vượt {self.max_tool_calls} lời gọi tools.*"
                    break
                try:
                    resp = self._handle_rpc(json.loads(line[len(RPC_PREFIX):]), trace)
                except json.JSONDecodeError as exc:
                    resp = {"ok": False, "error": f"RPC hỏng: {exc}"}
                try:
                    proc.stdin.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    proc.stdin.flush()
                except OSError:
                    pass
                continue
            out_chars += len(line)
            if out_chars <= 1_000_000:  # chặn bộ nhớ khi script in vô hạn
                out_parts.append(line)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.05)
        if error is None and proc.returncode not in (0, None):
            err_lines = [l for l in "".join(stderr_chunks).splitlines() if l.strip()]
            error = err_lines[-1].strip() if err_lines else f"exit code {proc.returncode}"

        stdout = "".join(out_parts)
        if len(stdout) > self.output_cap:
            cut = len(stdout) - self.output_cap
            stdout = stdout[: self.output_cap] + f"\n…[harness: đã cắt {cut} ký tự, output cap = {self.output_cap}]"
        result = CodeRunResult(
            ok=error is None, stdout=stdout, error=error, tool_calls=calls,
            denied=[t for t in trace if not t["allowed"]], elapsed_s=round(time.monotonic() - start, 3),
            runtime_tokens=sum(t.get("result_tokens", 0) for t in trace), stdout_chars_total=out_chars, trace=trace,
        )
        self.runs.append(result)
        return result

    def close(self) -> None:
        shutil.rmtree(self._copy_dir, ignore_errors=True)
