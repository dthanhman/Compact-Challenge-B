"""Mô phỏng token theo công thức (không gọi API) — tái tạo các bảng số trong ``code-mode-phan-2.md``.

* ``native_vs_code``: md §2 (100 file × 1.200 token → ~6,6M vs ~6,4k input).
* ``compaction_sim``: md §8 (40 lượt, window 200k, compact khi > 70%).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScaleResult:
    llm_calls: int
    peak_context: int
    total_input: int
    cost_usd: float
    contexts: list[int]


def native_vs_code(n_files: int = 100, tok_per_file: int = 1200, base: int = 3000, path_tok: int = 8,
                   call_tok: int = 30, code_tok: int = 200, result_tok: int = 120, parallel: int = 1,
                   price_per_m: float = 5.0) -> dict[str, ScaleResult]:
    # Native: call 1 = list_files; sau đó mỗi lượt đọc `parallel` file; lượt cuối trả lời.
    ctx = [base]
    cur = base + call_tok + n_files * path_tok
    remaining = n_files
    while remaining > 0:
        ctx.append(cur)
        k = min(parallel, remaining)
        cur += k * (call_tok + tok_per_file)
        remaining -= k
    ctx.append(cur)
    native = ScaleResult(len(ctx), max(ctx), sum(ctx), sum(ctx) * price_per_m / 1e6, ctx)
    # Code Mode: 1 lần viết code, 1 lần đọc kết quả.
    cctx = [base, base + code_tok + result_tok]
    code = ScaleResult(2, max(cctx), sum(cctx), sum(cctx) * price_per_m / 1e6, cctx)
    return {"native": native, "code": code}


def compaction_sim(turns: int = 40, base: int = 3000, per_turn: int = 5000, big_turn: int = 12000, every: int = 5,
                   code_ratio: float = 0.2, window: int = 200_000, threshold: float = 0.7,
                   reset_to: int = 12_000) -> dict[str, dict]:
    def run(ratio: float) -> dict:
        ctx, series, compacts = base, [], 0
        for t in range(1, turns + 1):
            ctx += int((big_turn if t % every == 0 else per_turn) * ratio)
            if ctx > threshold * window:
                compacts += 1
                ctx = reset_to
            series.append(ctx)
        return {"series": series, "peak": max(series), "compactions": compacts, "total_input": sum(series)}

    return {"native": run(1.0), "code": run(code_ratio)}


def markdown_report() -> str:
    r = native_vs_code()
    n, c = r["native"], r["code"]
    p8 = native_vs_code(parallel=8)["native"]
    sim = compaction_sim()
    lines = [
        "# Mô phỏng token (md §2, §8)", "",
        "## Native vs Code Mode — 100 file × 1.200 token, nền 3.000 token, $5/1M", "",
        "| Kết quả | Native (1 call/lượt) | Native (8 call song song) | Code Mode |", "|---|---|---|---|",
        f"| LLM call | {n.llm_calls} | {p8.llm_calls} | {c.llm_calls} |",
        f"| Context lớn nhất | {n.peak_context:,} | {p8.peak_context:,} | {c.peak_context:,} |",
        f"| Tổng input | {n.total_input:,} | {p8.total_input:,} | {c.total_input:,} |",
        f"| Chi phí input | ${n.cost_usd:.2f} | ${p8.cost_usd:.2f} | ${c.cost_usd:.4f} |",
        "", f"Native gửi gấp **{n.total_input / c.total_input:,.0f} lần** Code Mode. "
            "Song song giảm số LLM call nhưng đỉnh context giữ nguyên.",
        "", "## Compaction + Code Mode — 40 lượt, window 200k, compact khi > 70%", "",
        "| | Native | Code Mode |", "|---|---|---|",
        f"| Số lần compact | {sim['native']['compactions']} | {sim['code']['compactions']} |",
        f"| Context lớn nhất | {sim['native']['peak']:,} | {sim['code']['peak']:,} |",
        f"| Context cuối | {sim['native']['series'][-1]:,} | {sim['code']['series'][-1]:,} |",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(markdown_report())
