"""Web UI Challenge B — chạy: ``streamlit run app/streamlit_app.py`` (từ thư mục gốc của repo).

UI không chứa logic: chỉ gọi ``ctxb`` và đọc ``reports/``. Thí nghiệm dài chạy bằng CLI.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxb.agent import Session  # noqa: E402
from ctxb.config import AGENTS_PATH, load_settings  # noqa: E402
from ctxb.context import read_agents_md  # noqa: E402
from ctxb.experiments.simulate import compaction_sim, native_vs_code  # noqa: E402
from ctxb.llm import GeminiLLM  # noqa: E402
from ctxb.recorder import Recorder, load_records, summarize_messages  # noqa: E402
from ctxb.workspace.fixtures import generate  # noqa: E402
from ctxb.workspace.tools import WorkspaceTools  # noqa: E402

REPORTS = ROOT / "reports"
LABEL_COLORS = {"KEEP": "🟩", "TRUNCATE": "🟧", "DROP": "🟥"}

st.set_page_config(page_title="Challenge B — Context Management", layout="wide")
st.title("Challenge B — Context Management")
st.caption("B1 Compaction · B2 Code Mode · SE373 Buổi 7")


# ------------------------------------------------------------------ helpers
def run_dirs(kind: str) -> list[Path]:
    base = REPORTS / kind
    return sorted([p for p in base.iterdir() if p.is_dir()]) if base.exists() else []


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def render_context_table(items: list[dict]) -> pd.DataFrame:
    rows = []
    for it in items:
        labels = " ".join(f"{LABEL_COLORS.get(r['label'], '')}{r['name']}" for r in it.get("results", []))
        calls = ", ".join(c["name"] for c in it.get("tool_calls", []))
        rows.append({"#": it["i"], "role": it["role"] + (" (checkpoint)" if it.get("checkpoint") else ""),
                     "turn": it["turn"], "tokens": it["tokens"], "tool / nhãn": labels or calls,
                     "preview": it["preview"][:160].replace("\n", " ")})
    return pd.DataFrame(rows)


def new_live_session(strategy: str, window: int, code_mode: bool) -> None:
    settings = load_settings().with_(context_window=window)
    root = settings.runs_dir / "ui" / uuid.uuid4().hex[:8]
    fp = generate(root)
    rec = Recorder(root / "log")
    st.session_state.live = {
        "session": Session(GeminiLLM(settings.api_key, settings.model), WorkspaceTools(fp.workspace), settings,
                           strategy=strategy, recorder=rec, agents_md=read_agents_md(AGENTS_PATH), code_mode=code_mode),
        "history": [], "settings": settings, "rec_dir": rec.dir,
    }


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Session live")
    strategy = st.selectbox("Chiến lược compaction", ["structured", "truncate", "none"])
    window = st.number_input("Window ảo (token)", 16_000, 1_000_000, 48_000, step=4_000)
    code_mode = st.checkbox("Bật Code Mode (run_code)")
    if st.button("Tạo session mới", type="primary") or "live" not in st.session_state:
        try:
            new_live_session(strategy, int(window), code_mode)
        except SystemExit as exc:
            st.error(str(exc))
    live = st.session_state.get("live")
    if live:
        sess: Session = live["session"]
        tokens = sess.context_tokens()
        util = sess.compactor.utilization(tokens)
        st.progress(min(util, 1.0), text=f"Utilization {util:.0%} ({tokens:,} / {live['settings'].usable_window:,})")
        s = live["settings"]
        st.caption(f"micro (prune) ≥ {s.micro_threshold:.0%} · full (checkpoint) ≥ {s.full_threshold:.0%}")
        stats = sess.stats()
        c1, c2 = st.columns(2)
        c1.metric("Compact", stats["n_compactions"])
        c2.metric("Prune", stats["n_prunes"])
        c1.metric("LLM call", stats["llm_calls"])
        c2.metric("Input tổng", f"{stats['input_tokens']:,}")
        if st.button("/compact (thủ công)"):
            sess.request_compaction("manual")
            st.toast("Sẽ compact trước lần gọi model kế tiếp")

tabs = st.tabs(["💬 Chat", "🔍 Context inspector", "📌 Checkpoint", "📈 B1 Experiments", "🧮 B2 Code Mode", "🧪 Simulation"])

# ---------------------------------------------------------------------- chat
with tabs[0]:
    live = st.session_state.get("live")
    if not live:
        st.info("Tạo session ở sidebar (cần GEMINI_API_KEY trong .env).")
    else:
        st.caption("Workspace giả `authsvc`: thử 'Chạy toàn bộ test', 'Đọc src/auth.ts', 'Grep refresh trong logs'...")
        for h in live["history"]:
            with st.chat_message("user"):
                st.write(h["user"])
            with st.chat_message("assistant"):
                for e in h["events"]:
                    st.warning(f"harness · {e['type']} {e.get('trigger', '')}: {e.get('tokens_before')} → {e.get('tokens_after')} token")
                for t in h["tools"]:
                    st.caption(f"🔧 {t}")
                st.write(h["answer"])
                st.caption(h["usage"])
        if prompt := st.chat_input("Nhắn cho agent…"):
            with st.spinner("Agent đang làm việc…"):
                r = live["session"].send(prompt)
            live["history"].append({
                "user": prompt, "answer": r.text,
                "events": [e for e in r.events if e["type"] != "resume_check"],
                "tools": [f"{t.name} {json.dumps(t.args, ensure_ascii=False)[:120]} · raw {t.raw_tokens:,} → ctx {t.context_tokens:,}"
                          + (f" · archive {t.archive_id}" if t.archive_id else "") for t in r.tool_events],
                "usage": f"input {r.usage['input_tokens']:,} · cached {r.usage['cached_tokens']:,} · output {r.usage['output_tokens']:,}",
            })
            st.rerun()

# ------------------------------------------------------------ inspector
with tabs[1]:
    sources = (["(session live)"] if st.session_state.get("live") else []) + [str(p.relative_to(REPORTS)) for p in run_dirs("b1")]
    src = st.selectbox("Nguồn", sources, key="insp_src") if sources else None
    if src == "(session live)":
        st.subheader("Context hiện tại")
        st.dataframe(render_context_table(summarize_messages(st.session_state.live["session"].messages)), width="stretch")
        snap_dir = st.session_state.live["rec_dir"] / "snapshots"
    elif src:
        snap_dir = REPORTS / src / "snapshots"
    else:
        snap_dir = None
    if snap_dir and snap_dir.exists():
        befores = sorted(snap_dir.glob("*_before.json"))
        if befores:
            pick = st.selectbox("Lần compact", [p.name.split("_")[0] for p in befores])
            c1, c2 = st.columns(2)
            b, a = snap_dir / f"{pick}_before.json", snap_dir / f"{pick}_after.json"
            with c1:
                items = read_json(b)
                st.markdown(f"**Trước** — {sum(i['tokens'] for i in items):,} token, {len(items)} message")
                st.dataframe(render_context_table(items), width="stretch", height=420)
            with c2:
                if a.exists():
                    items = read_json(a)
                    st.markdown(f"**Sau** — {sum(i['tokens'] for i in items):,} token, {len(items)} message")
                    st.dataframe(render_context_table(items), width="stretch", height=420)
            st.caption("🟩 KEEP · 🟧 TRUNCATE · 🟥 DROP (nhãn của tool result)")
        else:
            st.info("Chưa có lần compact nào.")

# ----------------------------------------------------------- checkpoint
with tabs[2]:
    dirs = ([st.session_state.live["rec_dir"]] if st.session_state.get("live") else []) + run_dirs("b1")
    found = [(d, p) for d in dirs for p in sorted((d / "checkpoints").glob("*.json"))] if dirs else []
    if not found:
        st.info("Chưa có checkpoint.")
    for d, p in found:
        data = read_json(p)
        with st.expander(f"{d.name} / {p.name} — trigger {data.get('trigger')}, lượt {data.get('covers_turns')}"):
            st.json(data["checkpoint"])
            st.code(data.get("message", ""), language="markdown")
    for d in run_dirs("b1"):
        recs = [r for r in load_records(d) if r.get("type") in ("compaction", "checkpoint_failed")]
        for r in recs:
            if r.get("warnings") or r.get("errors"):
                st.warning(f"{d.name} turn {r['turn']}: {r.get('errors') or ''} {r.get('warnings') or ''}")

# --------------------------------------------------------------- B1
with tabs[3]:
    runs = [d for d in run_dirs("b1") if (d / "result.json").exists() and "strategy" in read_json(d / "result.json")]
    if not runs:
        st.info("Chưa có kết quả. Chạy: `python -m ctxb run-b1 --strategy all --window 48000 --cold-start`")
    else:
        series = []
        for d in runs:
            for k, r in enumerate([r for r in load_records(d) if r.get("type") == "request"], 1):
                series.append({"request": k, "run": d.name, "input_tokens": r["usage"].get("input_tokens", 0),
                               "turn": r["turn"]})
        df = pd.DataFrame(series)
        st.subheader("Input tokens mỗi lần gọi model")
        st.line_chart(df.pivot_table(index="request", columns="run", values="input_tokens"))
        rows = []
        for d in runs:
            r = read_json(d / "result.json")
            s = r["stats"]
            rows.append({"run": r["run"], "chiến lược": r["strategy"], "peak": s["peak_context"], "tổng input": s["input_tokens"],
                         "cached": s["cached_tokens"], "LLM call": s["llm_calls"], "compact": s["n_compactions"],
                         "prune": s["n_prunes"], "vượt window": s["over_window_calls"], "P1–P5": r["probe_score"],
                         "A1–A3": r["behavior_score"], **{k: "✅" if v else "❌" for k, v in r["probes"].items()},
                         **{k: "✅" if r["behavior"][k] else "❌" for k in ("A1_no_repeat", "A2_constraint_kept", "A3_task_done")}})
        st.dataframe(pd.DataFrame(rows), width="stretch")
        pick = st.selectbox("Xem chi tiết run", [d.name for d in runs])
        r = read_json(REPORTS / "b1" / pick / "result.json")
        st.markdown("**Câu trả lời ở lượt probe**")
        st.write(r["probe_answer"])
        st.markdown("**Sự kiện compaction**")
        st.dataframe(pd.DataFrame(r["compaction_events"]), width="stretch")
        st.markdown("**Các lượt**")
        st.dataframe(pd.DataFrame([{k: t[k] for k in ("turn", "user", "steps", "tools", "context_after")} for t in r["turns"]]),
                     width="stretch")

# --------------------------------------------------------------- B2
with tabs[4]:
    runs = [d for d in run_dirs("b2") if (d / "result.json").exists()]
    if not runs:
        st.info("Chưa có kết quả. Chạy: `python -m ctxb run-b2 --mode both --traps`")
    else:
        rows = []
        for d in runs:
            r = read_json(d / "result.json")
            for it in r["items"]:
                s = it["stats"]
                rows.append({"run": r["run"], "chế độ": r["mode"], "câu": it["id"], "đúng": "✅" if it["grade"]["correct"] else "❌",
                             "LLM call": s["llm_calls"], "peak": s["peak_context"], "tổng input": s["input_tokens"],
                             "dòng log thô trong context": it["log_lines_in_context"]})
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch")
        st.bar_chart(df.pivot_table(index="câu", columns="run", values="tổng input"))
        pick = st.selectbox("Chi tiết", [f"{r['run']}/{r['câu']}" for r in rows])
        run, qid = pick.split("/")
        it = next(i for i in read_json(REPORTS / "b2" / run / "result.json")["items"] if i["id"] == qid)
        st.markdown(f"**{it['question']}**")
        st.write(it["answer"])
        st.json(it["grade"])
        for code in it.get("code", []):
            st.code(code, language="python")
        for cr in it.get("code_runs", []):
            st.caption(f"runtime: {cr['tool_calls']} lời gọi tools.* · {cr['runtime_tokens']:,} token dữ liệu ở runtime · "
                       f"{cr['stdout_chars_total']:,} ký tự stdout · {cr['elapsed_s']}s · lỗi: {cr['error']}")
    traps = REPORTS / "b2" / "traps.json"
    if traps.exists():
        st.subheader("Bẫy (md §6)")
        st.dataframe(pd.DataFrame([{"bẫy": k, **{x: v[x] for x in ("ok", "error", "context_chars", "denied", "elapsed_s")}}
                                   for k, v in read_json(traps).items()]), width="stretch")

# --------------------------------------------------------- simulation
with tabs[5]:
    st.subheader("Native vs Code Mode (md §2)")
    c1, c2, c3, c4 = st.columns(4)
    n_files = c1.slider("Số file", 5, 500, 100)
    tok = c2.slider("Token mỗi file", 100, 5000, 1200, step=100)
    par = c3.slider("Tool call song song / lượt", 1, 20, 1)
    price = c4.number_input("$ / 1M input", 0.1, 50.0, 5.0)
    r = native_vs_code(n_files=n_files, tok_per_file=tok, parallel=par, price_per_m=price)
    n, c = r["native"], r["code"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("LLM call", f"{n.llm_calls} vs {c.llm_calls}")
    m2.metric("Context lớn nhất", f"{n.peak_context:,}", f"Code Mode {c.peak_context:,}", delta_color="off")
    m3.metric("Tổng input", f"{n.total_input:,}", f"Code Mode {c.total_input:,}", delta_color="off")
    m4.metric("Native gấp", f"{n.total_input / c.total_input:,.0f}×")
    st.line_chart(pd.DataFrame({"native": n.contexts}))

    st.subheader("Compaction + Code Mode (md §8)")
    c1, c2, c3 = st.columns(3)
    turns = c1.slider("Số lượt", 10, 100, 40)
    thr = c2.slider("Ngưỡng compact", 0.5, 0.95, 0.7)
    ratio = c3.slider("Code Mode thêm bao nhiêu % so với native", 0.05, 1.0, 0.2)
    sim = compaction_sim(turns=turns, threshold=thr, code_ratio=ratio)
    st.line_chart(pd.DataFrame({"native": sim["native"]["series"], "code mode": sim["code"]["series"]}))
    st.write(f"Số lần compact — native: **{sim['native']['compactions']}**, Code Mode: **{sim['code']['compactions']}**")
