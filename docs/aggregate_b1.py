"""Gộp các run B1 lặp lại theo cấu hình (bỏ hậu tố -N) → reports/b1/repeat.md. Chạy: ``python docs/aggregate_b1.py``."""

from __future__ import annotations

import json
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

B1 = Path(__file__).resolve().parents[1] / "reports" / "b1"


def score(s: str) -> int:
    return int(s.split("/")[0])


def fmt(xs: list[float], digits: int = 0) -> str:
    m = st.mean(xs)
    if len(xs) < 2:
        return f"{m:,.{digits}f}"
    return f"{m:,.{digits}f} ± {st.stdev(xs):,.{digits}f}"


def main() -> None:
    main_runs, cold_runs = defaultdict(list), defaultdict(list)
    for p in sorted(B1.glob("*/result.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        cfg = re.sub(r"-\d+$", "", r["run"])
        (main_runs if "strategy" in r else cold_runs)[cfg].append(r)

    md = ["# B1 — gộp các lần chạy lặp", "",
          "Trung bình ± độ lệch chuẩn (n ≥ 2). Điểm ghi dạng tổng số đạt / tổng số tối đa qua các lần chạy.", "",
          "| Cấu hình | n | Context lớn nhất | Tổng input | LLM call | Call vượt window | P1–P5 | A1–A3 | Probe trượt |",
          "|---|---|---|---|---|---|---|---|---|"]
    for cfg, rs in main_runs.items():
        n = len(rs)
        missed = defaultdict(int)
        for r in rs:
            for k, v in r["probes"].items():
                if not v:
                    missed[k.split("_")[0]] += 1
        md.append(f"| {cfg} | {n} | {fmt([r['stats']['peak_context'] for r in rs])} | "
                  f"{fmt([r['stats']['input_tokens'] for r in rs])} | {fmt([r['stats']['llm_calls'] for r in rs], 1)} | "
                  f"{fmt([r['stats']['over_window_calls'] for r in rs], 1)} | "
                  f"{sum(score(r['probe_score']) for r in rs)}/{5 * n} | {sum(score(r['behavior_score']) for r in rs)}/{3 * n} | "
                  f"{', '.join(f'{k}×{v}' for k, v in missed.items()) or '—'} |")
    if cold_runs:
        md += ["", "## Cold-start", "", "| Cấu hình | n | A1–A3 | Input tokens |", "|---|---|---|---|"]
        for cfg, rs in cold_runs.items():
            md.append(f"| {cfg} | {len(rs)} | {sum(score(r['behavior_score']) for r in rs)}/{3 * len(rs)} | "
                      f"{fmt([r['stats']['input_tokens'] for r in rs])} |")
    (B1 / "repeat.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
