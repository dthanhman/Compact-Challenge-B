from ctxb.experiments.grading import grade_b2, grade_probe
from ctxb.experiments.simulate import compaction_sim, native_vs_code
from ctxb.tokens import TokenCounter, estimate


def test_simulation_reproduces_md_table():
    r = native_vs_code()
    assert r["native"].llm_calls == 102 and r["code"].llm_calls == 2
    assert 126_000 < r["native"].peak_context < 128_000
    assert 6_500_000 < r["native"].total_input < 6_700_000
    assert round(r["native"].cost_usd, 1) == 33.0
    assert native_vs_code(parallel=8)["native"].peak_context == r["native"].peak_context


def test_compaction_sim_code_mode_never_compacts():
    sim = compaction_sim()
    assert sim["code"]["compactions"] == 0 and 53_000 < sim["code"]["peak"] < 55_000
    assert sim["native"]["compactions"] >= 1


def test_token_counter_calibrates():
    c = TokenCounter()
    c.calibrate(1000, 1500)
    assert 1.2 < c.factor < 1.3
    c.calibrate(1000, 10)  # giá trị bất thường bị bỏ qua
    assert 1.2 < c.factor < 1.3
    assert estimate("abcd" * 10) == 10


def test_grade_probe():
    spec = {"all": [["race", "đồng thời"], ["refresh"]]}
    assert grade_probe("Lỗi race condition khi Refresh token", spec)
    assert not grade_probe("Lỗi refresh", spec)
    assert grade_probe("auth.ts và session.ts", {"min_of": 2, "any": ["auth.ts", "session.ts", "auth.test.ts"]})


def test_grade_b2(fixture_root):
    import json
    truth = json.loads((fixture_root / "ground_truth.json").read_text(encoding="utf-8"))
    top = truth["top3_error_codes"]
    ans = ", ".join(f"{c}: {truth['error_code_counts'][c]} lần" for c in top)
    assert grade_b2("top3_error_codes", ans, truth)["correct"]
    assert not grade_b2("top3_error_codes", top[0], truth)["correct"]
    ans2 = "\n".join(f"- {ep}: {n:,}" for ep, n in truth["status500_by_endpoint"].items())
    assert grade_b2("status500_by_endpoint", ans2, truth)["correct"]
