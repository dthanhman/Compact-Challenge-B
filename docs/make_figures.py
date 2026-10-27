"""Vẽ hình cho báo cáo từ reports/ — chạy: ``python docs/make_figures.py`` (cần matplotlib)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT = ROOT / "docs" / "figures"
WINDOW = 32_000
COLORS = {"none-1": "#d62728", "truncate-1": "#ff7f0e", "structured-t60-1": "#2ca02c"}


def load(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line]


def fig_b1() -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    for run, color in COLORS.items():
        recs = load(REPORTS / "b1" / run)
        reqs = [r for r in recs if r["type"] == "request"]
        ax.plot(range(1, len(reqs) + 1), [r["usage"]["input_tokens"] for r in reqs], color=color, lw=1.8, label=run)
        # đánh dấu compaction (sao) và prune (tam giác) tại lần gọi model kế tiếp
        k = 0
        for r in recs:
            if r["type"] == "request":
                k += 1
            elif r["type"] in ("compaction", "prune"):
                ax.scatter(k + 0.5, r["tokens_after"], color=color, zorder=3, s=90 if r["type"] == "compaction" else 30,
                           marker="*" if r["type"] == "compaction" else "v", edgecolor="black", lw=0.5)
    ax.axhline(WINDOW, color="gray", ls="--", lw=1)
    ax.text(1, WINDOW * 1.04, "window ảo 32k", color="gray")
    ax.scatter([], [], marker="*", s=90, color="white", edgecolor="black", label="compact (checkpoint)")
    ax.scatter([], [], marker="v", s=30, color="white", edgecolor="black", label="prune (micro)")
    ax.set(xlabel="Lần gọi model", ylabel="Input tokens", title="B1 — Input tokens mỗi lần gọi model theo chiến lược")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "b1_context.png", dpi=150)


def fig_b2() -> None:
    runs = ["code-1", "native-free-1", "native-strict-1"]
    colors = ["#2ca02c", "#ff7f0e", "#d62728"]
    qs = ["Q1", "Q2", "Q3"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    width = 0.27
    for j, (run, color) in enumerate(zip(runs, colors)):
        items = {it["id"]: it for it in json.loads((REPORTS / "b2" / run / "result.json").read_text(encoding="utf-8"))["items"]}
        for i, q in enumerate(qs):
            if q not in items:
                continue
            v = items[q]["stats"]["input_tokens"]
            bar = ax.bar(i + (j - 1) * width, v, width, color=color, label=run if i == 0 else None)
            ok = items[q]["grade"].get("correct")
            ax.text(bar[0].get_x() + width / 2, v * 1.15, f"{v:,}\n{'✓' if ok else '✗'}", ha="center", fontsize=8)
    ax.set_yscale("log")
    ax.set_xticks(range(len(qs)), qs)
    ax.set(ylabel="Tổng input tokens (log)", title="B2 — Code Mode vs native read_file (✓ đúng / ✗ sai)")
    ax.set_ylim(1_000, 3e7)
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "b2_input.png", dpi=150)


def box(ax, x, y, w, h, text, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", fc=color, ec="black", lw=1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9)


def arrow(ax, x1, y1, x2, y2, text=""):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="->", lw=1.2))
    if text:
        ax.text((x1 + x2) / 2 + 0.05, (y1 + y2) / 2, text, fontsize=8, color="#444")


def fig_arch() -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.set(xlim=(0, 11), ylim=(0, 6.4))
    ax.axis("off")
    box(ax, 0.2, 5.2, 2.2, 0.8, "CLI (ctxb.cli)\nStreamlit UI", "#e8eaf6")
    box(ax, 3.4, 4.9, 4.2, 1.3, "Agent loop — Session (agent.py)\nmessages[] trung lập · AGENTS.md trong system\n"
        "policy.py: rules / quyền tool", "#bbdefb")
    box(ax, 8.6, 5.2, 2.2, 0.8, "GeminiLLM (llm.py)\nusage: input / cached", "#e1f5fe")
    box(ax, 0.2, 2.5, 3.6, 1.8, "compaction/\ncompactor.py: trigger T1–T4\nprune.py: KEEP / TRUNCATE / DROP\n"
        "checkpoint.py: checkpoint JSON\narchive.py: lưu output gốc", "#c8e6c9")
    box(ax, 4.2, 2.5, 3.0, 1.8, "workspace/tools.py\nrun_tests · read_file · grep\nreplace_in_file …\n"
        "(workspace giả authsvc)", "#fff9c4")
    box(ax, 7.6, 2.5, 3.2, 1.8, "codemode/runner.py\nrun_code: subprocess riêng\ntools.* proxy · cap stdout\n"
        "→ chỉ kết quả cuối vào context", "#ffe0b2")
    box(ax, 0.2, 0.3, 4.4, 1.3, "recorder.py → runs/, reports/\nrequests.jsonl · snapshots before/after\ncheckpoints/ · archive/",
        "#eeeeee")
    box(ax, 5.2, 0.3, 5.6, 1.3, "experiments/ (tạo Session như CLI)\nb1.py: none / truncate / structured + probe P1–P5, A1–A3\n"
        "b2.py: native vs code · grading.py · simulate.py", "#f3e5f5")
    arrow(ax, 2.4, 5.6, 3.4, 5.6)
    arrow(ax, 7.6, 5.6, 8.6, 5.6, "")
    arrow(ax, 4.0, 4.9, 2.4, 4.3)
    ax.text(2.0, 4.65, "trước mỗi call", fontsize=8, color="#444")
    arrow(ax, 5.5, 4.9, 5.7, 4.3, "tool call")
    arrow(ax, 7.0, 4.9, 8.8, 4.3, "run_code")
    arrow(ax, 7.6, 3.4, 7.2, 3.4)
    ax.text(7.25, 3.5, "tools.*", fontsize=8, color="#444")
    arrow(ax, 2.0, 2.5, 2.0, 1.6, "log / snapshot")
    ax.set_title("Kiến trúc package ctxb (Challenge B)", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "architecture.png", dpi=150)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_b1()
    fig_b2()
    fig_arch()
    print("saved to", OUT)
