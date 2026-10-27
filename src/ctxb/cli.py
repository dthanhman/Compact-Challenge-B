"""Giao diện dòng lệnh.

    python -m ctxb chat [--strategy structured] [--code-mode] [--window 48000]
    python -m ctxb run-b1 --strategy structured --runs 1 [--window 48000] [--cold-start]
    python -m ctxb run-b2 --mode native|code|both [--traps]
    python -m ctxb traps
    python -m ctxb simulate
    python -m ctxb summary
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import AGENTS_PATH, PROJECT_ROOT, load_settings

REPORTS = PROJECT_ROOT / "reports"


def _llm(settings):
    from .llm import GeminiLLM

    return GeminiLLM(settings.api_key, settings.model)


def _apply_overrides(settings, args):
    changes = {}
    if getattr(args, "window", None):
        changes["context_window"] = args.window
    if getattr(args, "keep_recent", None) is not None:
        changes["keep_recent_turns"] = args.keep_recent
    if getattr(args, "tool_cap", None):
        changes["tool_result_cap"] = args.tool_cap
    if getattr(args, "full_threshold", None):
        changes["full_threshold"] = args.full_threshold
    return settings.with_(**changes) if changes else settings


def cmd_chat(args) -> None:
    from .agent import Session
    from .context import read_agents_md
    from .recorder import Recorder
    from .workspace.fixtures import generate
    from .workspace.tools import WorkspaceTools

    settings = _apply_overrides(load_settings(), args)
    root = settings.runs_dir / "chat"
    shutil.rmtree(root, ignore_errors=True)
    fp = generate(root)
    sess = Session(_llm(settings), WorkspaceTools(fp.workspace), settings, strategy=args.strategy,
                   recorder=Recorder(root / "log"), agents_md=read_agents_md(AGENTS_PATH), code_mode=args.code_mode)
    print(f"Workspace: {fp.workspace}\nGõ /compact để compact thủ công, /stats để xem số liệu, /quit để thoát.")
    while True:
        try:
            text = input("\nuser> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/stats":
            print(sess.stats())
            continue
        if text == "/compact":
            sess.request_compaction("manual")
            print("(sẽ compact trước lần gọi model kế tiếp)")
            continue
        r = sess.send(text)
        for e in r.events:
            print(f"  [harness] {e['type']} {e.get('trigger', '')}: {e.get('tokens_before')} → {e.get('tokens_after')} token")
        for t in r.tool_events:
            print(f"  [tool] {t.name} raw={t.raw_tokens} ctx={t.context_tokens} archive={t.archive_id}")
        print(f"\nagent> {r.text}\n  (input={r.usage['input_tokens']} cached={r.usage['cached_tokens']} "
              f"ctx≈{sess.context_tokens()} / {settings.usable_window})")
    sess.close()


def cmd_run_b1(args) -> None:
    from .experiments import b1

    settings = _apply_overrides(load_settings(), args)
    llm = _llm(settings)
    out, work = REPORTS / "b1", settings.runs_dir / "b1"
    strategies = ["none", "truncate", "structured"] if args.strategy == "all" else [args.strategy]
    for strategy in strategies:
        for i in range(args.start, args.start + args.runs):
            name = f"{strategy}-{args.tag}-{i}" if args.tag else f"{strategy}-{i}"
            res = b1.run_b1(strategy, name, settings, llm, out, work, scale=args.scale,
                            checkpoint_after_probe=args.checkpoint_after_probe and strategy == "structured")
            print(f"==> {res['run']}: probes {res['probe_score']} behavior {res['behavior_score']} "
                  f"compacted_before_probe={res['compacted_before_probe']} stats={res['stats']}")
            if args.cold_start and strategy == "structured":
                ckpts = sorted((out / res["run"] / "checkpoints").glob("checkpoint_*.json"))
                probe = res["probe_turn"] or 99
                if args.checkpoint_after_probe:  # checkpoint milestone ngay sau lượt probe
                    before_probe = [c for c in ckpts if _ckpt_turn(c) == probe + 1] or ckpts
                else:
                    before_probe = [c for c in ckpts if _ckpt_turn(c) < probe] or ckpts
                if before_probe:
                    cs = b1.run_cold_start(before_probe[-1], f"coldstart-{args.tag + '-' if args.tag else ''}{i}",
                                           settings, llm, out, work, scale=args.scale)
                    print(f"==> {cs['run']}: behavior {cs['behavior_score']}")
    print(b1.summarize(out))


def _ckpt_turn(path: Path) -> int:
    import json

    return json.loads(path.read_text(encoding="utf-8")).get("at_turn", 0)


def cmd_run_b2(args) -> None:
    from .experiments import b2

    settings = load_settings()
    llm = _llm(settings)
    out, work = REPORTS / "b2", settings.runs_dir / "b2"
    modes = ["native", "native-strict", "code"] if args.mode == "all" else (["native", "code"] if args.mode == "both" else [args.mode])
    for mode in modes:
        for i in range(args.start, args.start + args.runs):
            b2.run_b2(mode, f"{mode}-{i}", settings, llm, out, work, log_lines=args.log_lines)
    if args.traps:
        b2.run_traps(settings, work, out)
    print(b2.summarize(out))


def cmd_traps(args) -> None:
    from .experiments import b2

    settings = load_settings(require_key=False)
    out = REPORTS / "b2"
    b2.run_traps(settings, settings.runs_dir / "b2", out)
    print(b2.summarize(out))


def cmd_simulate(args) -> None:
    from .experiments.simulate import markdown_report

    text = markdown_report()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "simulation.md").write_text(text, encoding="utf-8")
    print(text)


def cmd_summary(args) -> None:
    from .experiments import b1, b2

    if (REPORTS / "b1").exists():
        print(b1.summarize(REPORTS / "b1"))
    if (REPORTS / "b2").exists():
        print(b2.summarize(REPORTS / "b2"))


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="ctxb", description="Challenge B: compaction + Code Mode")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat", help="chat tương tác trên workspace giả")
    c.add_argument("--strategy", choices=["none", "truncate", "structured"], default="structured")
    c.add_argument("--code-mode", action="store_true")
    c.add_argument("--window", type=int)
    c.set_defaults(func=cmd_chat)

    r1 = sub.add_parser("run-b1", help="thí nghiệm B1 (session dài)")
    r1.add_argument("--strategy", choices=["none", "truncate", "structured", "all"], default="structured")
    r1.add_argument("--runs", type=int, default=1)
    r1.add_argument("--start", type=int, default=1, help="số thứ tự run đầu tiên (chạy lặp không ghi đè run cũ)")
    r1.add_argument("--scale", type=float, default=1.0)
    r1.add_argument("--window", type=int)
    r1.add_argument("--keep-recent", type=int)
    r1.add_argument("--tool-cap", type=int)
    r1.add_argument("--cold-start", action="store_true")
    r1.add_argument("--full-threshold", type=float, help="ngưỡng full compaction (mặc định theo .env)")
    r1.add_argument("--tag", default="", help="hậu tố tên run, vd t60")
    r1.add_argument("--checkpoint-after-probe", action="store_true",
                    help="tạo checkpoint milestone ngay sau lượt probe; cold-start dùng checkpoint này")
    r1.set_defaults(func=cmd_run_b1)

    r2 = sub.add_parser("run-b2", help="thí nghiệm B2 (native vs Code Mode)")
    r2.add_argument("--mode", choices=["native", "native-strict", "code", "both", "all"], default="all")
    r2.add_argument("--runs", type=int, default=1)
    r2.add_argument("--start", type=int, default=1, help="số thứ tự run đầu tiên (chạy lặp không ghi đè run cũ)")
    r2.add_argument("--log-lines", type=int, default=200)
    r2.add_argument("--traps", action="store_true")
    r2.set_defaults(func=cmd_run_b2)

    sub.add_parser("traps", help="chạy các bẫy Code Mode (không cần API)").set_defaults(func=cmd_traps)
    sub.add_parser("simulate", help="mô phỏng token theo công thức").set_defaults(func=cmd_simulate)
    sub.add_parser("summary", help="tổng hợp lại reports/").set_defaults(func=cmd_summary)

    args = p.parse_args(argv)
    args.func(args)
