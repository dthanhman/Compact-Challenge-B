import json

from ctxb.agent import Session
from ctxb.compaction.compactor import Compactor
from ctxb.llm import LLMReply, ScriptedLLM, ToolCall
from ctxb.recorder import Recorder, load_records
from ctxb.tokens import TokenCounter

from conftest import tool_then_answer


class FakeSession:
    """Session tối giản: context gồm toàn message text (không có tool) để thử trigger T2."""

    def __init__(self, llm, settings, n_turns, words=1500):
        self.llm = llm
        self.turn = n_turns
        self.messages = []
        for t in range(1, n_turns + 1):
            self.messages += [{"role": "user", "text": f"lượt {t}: " + "nội dung " * words, "turn": t},
                              {"role": "assistant", "text": "trả lời " * words, "tool_calls": [], "raw": None, "turn": t}]
        self.counter = TokenCounter()
        self.workspace_root = None

    def context_tokens(self):
        return self.counter.count("system", self.messages)


def test_full_compaction_triggers_at_threshold(settings):
    llm = ScriptedLLM(tool_then_answer())
    sess = FakeSession(llm, settings, n_turns=4)
    comp = Compactor(settings, "structured")
    before = sess.context_tokens()
    assert comp.utilization(before) >= settings.full_threshold
    events = comp.maybe_compact(sess)
    full = [e for e in events if e["type"] == "compaction"]
    assert len(full) == 1 and full[0]["covers_turns"] == [1, 3]
    assert sess.messages[0]["checkpoint"] and sess.messages[0]["text"].startswith("<checkpoint n=1")
    assert sess.messages[1]["role"] == "assistant"
    assert [m["turn"] for m in sess.messages[2:]] == [4, 4]  # chỉ giữ lượt gần nhất (K=1)
    assert sess.context_tokens() < before / 2
    assert llm.requests[-1]["json_mode"] is True


def test_no_compaction_below_threshold(settings):
    sess = FakeSession(ScriptedLLM(tool_then_answer()), settings, n_turns=1, words=100)
    assert Compactor(settings, "structured").maybe_compact(sess) == []


def test_invalid_checkpoint_retries_then_falls_back(settings):
    bad = {"goal": "", "next_action": ""}
    llm = ScriptedLLM(tool_then_answer(checkpoint=bad))
    sess = FakeSession(llm, settings, n_turns=4)
    snapshot = list(sess.messages)
    events = Compactor(settings, "structured").maybe_compact(sess)
    assert events[-1]["type"] == "checkpoint_failed" and events[-1]["attempts"] == 2
    assert sess.messages == snapshot  # không thay context bằng checkpoint hỏng
    assert sum(1 for r in llm.requests if r["json_mode"]) == 2


def test_truncate_strategy_loses_constraint(settings):
    sess = FakeSession(ScriptedLLM(tool_then_answer()), settings, n_turns=4)
    sess.messages[0]["text"] = "Lưu ý: phải giữ API backward compatible. " + sess.messages[0]["text"]
    ev = Compactor(settings, "truncate").maybe_compact(sess)
    assert ev[0]["type"] == "truncate" and 1 in ev[0]["dropped_turns"]
    assert not any("backward compatible" in m.get("text", "") for m in sess.messages)


def test_structured_keeps_constraint_verbatim(settings):
    sess = FakeSession(ScriptedLLM(tool_then_answer()), settings, n_turns=4)
    sess.messages[0]["text"] = "Lưu ý: phải giữ API backward compatible. " + sess.messages[0]["text"]
    Compactor(settings, "structured").maybe_compact(sess)
    assert "backward compatible" in sess.messages[0]["text"]


def test_session_end_to_end_with_tools(settings, ws, tmp_path):
    """Session thật + model giả: prune/compact chạy giữa các lần gọi model, system prompt không đổi."""
    llm = ScriptedLLM(tool_then_answer("run_tests"))
    rec = Recorder(tmp_path / "rec")
    sess = Session(llm, ws, settings, strategy="structured", recorder=rec)
    for i in range(4):
        sess.send(f"Chạy test lần {i + 1}")
    sess.request_compaction("manual")
    sess.send("Phải giữ API backward compatible. Chạy test lần nữa")

    assert len({r["system"] for r in llm.requests if not r["json_mode"]}) == 1  # static prefix
    records = load_records(rec.dir)
    assert any(r["type"] == "prune" for r in records)
    assert any(r["type"] == "compaction" and r["trigger"] == "manual" for r in records)
    assert any(r["type"] == "resume_check" for r in records)
    assert sess.messages[0]["checkpoint"]
    # mọi tool_call vẫn có tool_result tương ứng
    calls = [c.id for m in sess.messages if m["role"] == "assistant" for c in m.get("tool_calls") or []]
    results = [r["id"] for m in sess.messages if m["role"] == "tool" for r in m["results"]]
    assert calls == results
    assert (rec.dir / "checkpoints" / "checkpoint_1.json").exists()
    assert list((rec.dir / "snapshots").glob("*_after.json"))
    ckpt = json.loads((rec.dir / "checkpoints" / "checkpoint_1.json").read_text(encoding="utf-8"))
    assert ckpt["checkpoint"]["files"] == ["src/auth.ts", "tests/auth.test.ts"]


def test_milestone_triggers_compaction(settings, ws, tmp_path):
    def brain(system, messages, json_mode):
        if json_mode:
            return tool_then_answer()(system, messages, json_mode)
        last = messages[-1]
        if last["role"] == "user" and "sửa" in last["text"]:
            return LLMReply("", [ToolCall("replace_in_file", {"path": "src/auth.ts", "old": "  // rotate:",
                                                              "new": "  const inflight = 1;\n  // rotate:"}, id="r"),
                                 ToolCall("run_tests", {}, id="t")])
        if last["role"] == "user":
            return LLMReply("", [ToolCall("run_tests", {}, id="t0")])
        return LLMReply("ok")

    rec = Recorder(tmp_path / "r")
    sess = Session(ScriptedLLM(brain), ws, settings.with_(context_window=1_000_000), recorder=rec)
    sess.send("chạy test")
    sess.send("đọc lại")
    assert sess.compactor.n_full == 0  # window rất lớn: không có trigger theo ngưỡng
    sess.send("sửa đi")  # test fail → pass: milestone, compact ngay ở bước kế tiếp trong lượt
    assert sess.compactor.n_full == 1
    assert [r["trigger"] for r in load_records(rec.dir) if r["type"] == "compaction"] == ["T4-milestone"]


def test_none_strategy_never_compacts_but_flags_overflow(settings, ws):
    sess = Session(ScriptedLLM(tool_then_answer("run_tests")), ws, settings.with_(context_window=8_000), strategy="none")
    for i in range(4):
        sess.send(f"chạy test {i}")
    assert sess.compactor.n_full == 0 and sess.compactor.n_prune == 0
    assert sess.over_window_calls > 0


def test_full_compaction_skipped_when_gain_small(settings):
    sess = FakeSession(ScriptedLLM(tool_then_answer()), settings, n_turns=2, words=200)
    sess.messages[-1]["text"] = "trả lời " * 9000  # lượt hiện tại rất lớn, phần cũ nhỏ
    events = Compactor(settings, "structured").maybe_compact(sess)
    assert events[-1]["type"] == "compaction_skipped"
    assert not sess.llm.requests  # không tốn lời gọi LLM
