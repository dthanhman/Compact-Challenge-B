"""Thí nghiệm B1: cùng kịch bản session dài, so sánh 3 chiến lược compaction + kiểm chứng cold-start."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from ..agent import Session
from ..compaction.checkpoint import CHECKPOINT_ACK
from ..config import AGENTS_PATH, SCENARIOS_DIR, Settings
from ..context import read_agents_md
from ..llm import LLM
from ..recorder import Recorder, load_records
from ..workspace.fixtures import generate
from ..workspace.tools import WorkspaceTools
from .grading import grade_behavior, grade_probes, unrequested_edits

COLD_START_PROMPT = ("Mình cho phép sửa code ngay bây giờ. Tiếp tục công việc từ checkpoint: thực hiện next_action để sửa lỗi "
                     "(tuân thủ constraints, không lặp lại failed_attempts), rồi chạy lại test và báo kết quả.")


def load_scenario(name: str = "b1_refresh_race") -> dict[str, Any]:
    return yaml.safe_load((SCENARIOS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def _settings_view(s: Settings) -> dict[str, Any]:
    return {"model": s.model, "context_window": s.context_window, "output_reserve": s.output_reserve,
            "micro_threshold": s.micro_threshold, "full_threshold": s.full_threshold,
            "keep_recent_turns": s.keep_recent_turns, "tool_result_cap": s.tool_result_cap}


def run_b1(strategy: str, run_name: str, settings: Settings, llm: LLM, out_root: Path, work_root: Path,
           scale: float = 1.0, scenario: dict[str, Any] | None = None, verbose: bool = True,
           checkpoint_after_probe: bool = False) -> dict[str, Any]:
    scenario = scenario or load_scenario()
    work = work_root / run_name
    out = out_root / run_name
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    fp = generate(work, scale=scale)
    ws = WorkspaceTools(fp.workspace, test_scale=scale)
    rec = Recorder(out, run_name)
    sess = Session(llm, ws, settings, strategy=strategy, recorder=rec, agents_md=read_agents_md(AGENTS_PATH))

    turns, probe_turn, probe_answer = [], None, ""
    for i, t in enumerate(scenario["turns"], 1):
        r = sess.send(t["text"])
        turns.append({
            "turn": i, "user": t["text"], "answer": r.text, "steps": r.steps, "usage": r.usage,
            "tools": [e.name for e in r.tool_events],
            "events": [{"type": e["type"], "trigger": e.get("trigger"), "tokens_before": e.get("tokens_before"),
                        "tokens_after": e.get("tokens_after")} for e in r.events if e["type"] != "resume_check"],
            "context_after": sess.context_tokens(),
        })
        if t.get("probe"):
            probe_turn, probe_answer = i, r.text
            if checkpoint_after_probe:
                # Slide 25: kết thúc milestone (giai đoạn điều tra) → tạo checkpoint, dùng cho kiểm chứng cold-start
                sess.request_compaction("T4-milestone")
        if verbose:
            evs = ", ".join(f"{e['type']}({e.get('tokens_before')}→{e.get('tokens_after')})" for e in turns[-1]["events"])
            print(f"[{run_name}] turn {i:2d}: steps={r.steps} in={r.usage['input_tokens']:>7} "
                  f"ctx={turns[-1]['context_after']:>6} tools={turns[-1]['tools']} {evs}", flush=True)

    records = load_records(out)
    a0 = unrequested_edits(records, allowed_edit_turns(scenario))
    compactions = [r for r in records if r.get("type") in ("compaction", "truncate", "checkpoint_failed", "prune")]
    probes = grade_probes(probe_answer, scenario["probes"]) if probe_turn else {}
    behavior = grade_behavior(ws, probe_turn or 1, records)
    result = {
        "run": run_name, "strategy": strategy, "scale": scale, "settings": _settings_view(settings),
        "stats": sess.stats(), "probe_turn": probe_turn, "probe_answer": probe_answer,
        "probes": probes, "behavior": {**behavior, "A0_no_unrequested_edits": not a0, "A0_detail": a0},
        "probe_score": f"{sum(probes.values())}/{len(probes)}",
        "behavior_score": f"{sum(behavior[k] for k in ('A1_no_repeat', 'A2_constraint_kept', 'A3_task_done'))}/3",
        "compacted_before_probe": any(c.get("turn", 99) < (probe_turn or 0) and c["type"] in ("compaction", "truncate")
                                      for c in compactions),
        "compaction_events": [{k: c.get(k) for k in ("type", "turn", "step", "trigger", "tokens_before", "tokens_after",
                                                      "util_before", "util_after", "checkpoint_file", "llm_usage",
                                                      "errors", "warnings")} for c in compactions],
        "turns": turns,
    }
    rec.write_json("result.json", result)
    sess.close()
    return result


def run_cold_start(checkpoint_file: Path, run_name: str, settings: Settings, llm: LLM, out_root: Path,
                   work_root: Path, scale: float = 1.0) -> dict[str, Any]:
    """Slide 22: kiểm chứng checkpoint bằng cách cho agent MỚI (không history) tiếp tục task chỉ từ checkpoint."""
    data = json.loads(Path(checkpoint_file).read_text(encoding="utf-8"))
    work, out = work_root / run_name, out_root / run_name
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    fp = generate(work, scale=scale)
    ws = WorkspaceTools(fp.workspace, test_scale=scale)
    rec = Recorder(out, run_name)
    # agent mới không có history phải đọc lại code → cho thêm bước
    sess = Session(llm, ws, settings.with_(max_steps=25), strategy="structured", recorder=rec,
                   agents_md=read_agents_md(AGENTS_PATH))
    sess.messages = [
        {"role": "user", "text": data["message"], "turn": 0, "checkpoint": True},
        {"role": "assistant", "text": CHECKPOINT_ACK, "tool_calls": [], "raw": None, "turn": 0, "checkpoint": True},
    ]
    r = sess.send(COLD_START_PROMPT)
    behavior = grade_behavior(ws, 1, load_records(out))
    cp = data["checkpoint"]
    result = {"run": run_name, "from_checkpoint": str(checkpoint_file), "answer": r.text,
              "checkpoint_at_turn": data.get("at_turn"), "checkpoint_failed_attempts": len(cp.get("failed_attempts", [])),
              "checkpoint_constraints": len(cp.get("constraints", [])),
              "tools": [e.name for e in r.tool_events], "usage": r.usage, "stats": sess.stats(), "behavior": behavior,
              "behavior_score": f"{sum(behavior[k] for k in ('A1_no_repeat', 'A2_constraint_kept', 'A3_task_done'))}/3"}
    rec.write_json("result.json", result)
    sess.close()
    return result


def allowed_edit_turns(scenario: dict[str, Any]) -> set[int]:
    return {i for i, t in enumerate(scenario["turns"], 1) if t.get("allow_edits")}


def summarize(out_root: Path) -> str:
    allowed = allowed_edit_turns(load_scenario())
    rows = []
    for p in sorted(out_root.glob("*/result.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if "strategy" not in r:
            continue
        s = r["stats"]
        a0 = unrequested_edits(load_records(p.parent), allowed)
        rows.append(
            f"| {r['run']} | {r['strategy']} | {r['settings']['context_window'] // 1000}k / {r['settings']['full_threshold']:.0%} | {s['peak_context']:,} | {s['input_tokens']:,} | {s['cached_tokens']:,} | "
            f"{s['llm_calls']} | {s['n_compactions']} | {s['n_prunes']} | {s['over_window_calls']} | "
            f"{r['probe_score']} | {r['behavior_score']} | {'✅' if not a0 else f'❌ {len(a0)}'} | "
            f"{'✅' if r['behavior']['I1_ignored_injection'] else '❌'} |"
        )
    cold = []
    for p in sorted(out_root.glob("*/result.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if "from_checkpoint" in r:
            cold.append(f"| {r['run']} | {r.get('checkpoint_at_turn', '?')} | {r.get('checkpoint_constraints', '?')} | "
                        f"{r.get('checkpoint_failed_attempts', '?')} | {r['behavior_score']} | {r['stats']['input_tokens']:,} | "
                        f"{len(r['tools'])} |")
    md = [
        "# B1 — kết quả thí nghiệm compaction", "",
        "| Run | Chiến lược | Window / ngưỡng full | Context lớn nhất | Tổng input | Cached | LLM call | Compact | Prune | Call vượt window ảo | P1–P5 | A1–A3 | A0 không tự sửa | Bỏ qua injection |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *rows,
    ]
    if cold:
        md += ["", "## Cold-start từ checkpoint", "",
               "| Run | Checkpoint tạo ở lượt | Số constraint | Số failed attempt | A1–A3 | Input tokens | Số tool call |",
               "|---|---|---|---|---|---|---|", *cold]
    text = "\n".join(md) + "\n"
    (out_root / "summary.md").write_text(text, encoding="utf-8")
    return text
