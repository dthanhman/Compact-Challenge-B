from ctxb.compaction.prune import DROP, KEEP, TRUNCATE, cap_at_ingestion, label_counts, prune
from ctxb.llm import ToolCall
from ctxb.tokens import estimate_message

BIG = "x " * 4000


def turn(n, tool, response, args=None):
    return [
        {"role": "user", "text": f"yêu cầu {n}", "turn": n},
        {"role": "assistant", "text": "", "tool_calls": [ToolCall(tool, args or {}, id=f"c{n}")], "turn": n},
        {"role": "tool", "turn": n, "results": [{"id": f"c{n}", "name": tool, "args": args or {}, "archive_id": f"a{n:03d}",
                                                  "response": response}]},
    ]


def test_old_turns_are_pruned_recent_kept():
    tests_out = "\n".join(["    ✓ ok"] * 800 + ["FAIL tests/auth.test.ts", "  ● auth.refresh › concurrent", "Tests: 3 failed, 10 passed"])
    msgs = (turn(1, "run_tests", {"ok": True, "exit_code": 1, "output": tests_out})
            + turn(2, "read_file", {"ok": True, "content": BIG + "1"}, {"path": "src/auth.ts"})
            + turn(3, "read_file", {"ok": True, "content": BIG + "2"}, {"path": "src/session.ts"}))
    before = sum(estimate_message(m) for m in msgs)
    report = prune(msgs, keep_recent_steps=1)
    labels = {a.turn: a.label for a in report.actions}
    assert labels == {1: TRUNCATE, 2: DROP}
    t1 = msgs[2]["results"][0]["response"]
    assert "concurrent" in t1["summary"] and "Tests: 3 failed" in t1["summary"] and t1["archived"] == "a001"
    assert "read_file('src/auth.ts')" in msgs[5]["results"][0]["response"]["note"]
    assert msgs[8]["results"][0]["response"]["content"].startswith("x ")  # lượt gần nhất giữ nguyên
    assert all(m["text"].startswith("yêu cầu") for m in msgs if m["role"] == "user")  # user luôn KEEP
    assert sum(estimate_message(m) for m in msgs) < before / 2
    assert label_counts(msgs)[KEEP] == 1


def test_older_duplicate_dropped_as_duplicate():
    same = {"ok": True, "exit_code": 1, "output": "FAIL\n" + "line 12 ms\n" * 600}
    later = {"ok": True, "exit_code": 1, "output": "FAIL\n" + "line 99 ms\n" * 600}  # chỉ khác số đo thời gian
    msgs = turn(1, "run_tests", same) + turn(2, "run_tests", later)
    report = prune(msgs, keep_recent_steps=1)
    assert [(a.turn, a.label) for a in report.actions] == [(1, DROP)]
    assert "trùng" in msgs[2]["results"][0]["response"]["note"]


def test_small_and_error_results_kept():
    msgs = turn(1, "read_file", {"ok": False, "error": "FileNotFoundError: x" * 200}) + turn(2, "write_file", {"ok": True})
    assert prune(msgs, keep_recent_steps=0).actions == []


def test_tool_call_result_pairs_preserved():
    msgs = turn(1, "read_file", {"ok": True, "content": BIG}) + turn(2, "grep", {"ok": True, "matches": BIG + "g"})
    prune(msgs, keep_recent_steps=0)
    calls = [c.id for m in msgs if m["role"] == "assistant" for c in m["tool_calls"]]
    results = [r["id"] for m in msgs if m["role"] == "tool" for r in m["results"]]
    assert calls == results


def test_cap_at_ingestion_keeps_head_and_tail():
    text = "HEAD\n" + "mid\n" * 20000 + "Tests: 3 failed"
    out = cap_at_ingestion({"archive_id": "a007", "response": {"ok": True, "output": text}}, cap_tokens=1000)
    assert out["truncated_at_ingestion"] and out["output"].startswith("HEAD") and out["output"].endswith("Tests: 3 failed")
    assert "read_archive('a007'" in out["output"] and len(out["output"]) < 4500


def test_recent_steps_protected_even_within_one_turn():
    """Một lượt có nhiều tool call: chỉ N tool message gần nhất được bảo vệ."""
    msgs = turn(1, "read_file", {"ok": True, "content": BIG + "a"}, {"path": "a.ts"})
    for k, name in enumerate(["grep", "read_file", "read_file"], 2):
        msgs += turn(1, name, {"ok": True, "content": BIG + str(k)}, {"path": f"f{k}.ts"})[1:]
    report = prune(msgs, keep_recent_steps=2)
    assert len(report.actions) == 2  # 2 kết quả đầu bị prune, 2 kết quả cuối giữ nguyên
    assert all(a.turn == 1 for a in report.actions)
