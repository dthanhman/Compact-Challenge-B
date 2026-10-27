import json

from ctxb.workspace.fixtures import REFRESH_SIGNATURE, generate, load_ground_truth
from ctxb.workspace.tools import WorkspaceTools


def test_fixture_is_deterministic(tmp_path):
    a = generate(tmp_path / "a", log_files=4, log_lines=50)
    b = generate(tmp_path / "b", log_files=4, log_lines=50)
    assert load_ground_truth(a.root) == load_ground_truth(b.root)
    assert (a.workspace / "src/auth.ts").read_text(encoding="utf-8") == (b.workspace / "src/auth.ts").read_text(encoding="utf-8")


def test_ground_truth_outside_workspace(ws):
    assert not (ws.root / "ground_truth.json").exists()
    assert ws.dispatch("read_file", {"path": "../ground_truth.json"})["ok"] is False


def test_run_tests_fails_until_lock_is_added(ws):
    r = ws.dispatch("run_tests", {})
    assert r["exit_code"] == 1 and "3 failed" in r["output"]
    ws.dispatch("replace_in_file", {"path": "src/auth.ts", "old": "  // rotate:",
                                    "new": "  const inflight = new Map<string, Promise<TokenPair>>();\n  // rotate:"})
    r = ws.dispatch("run_tests", {})
    assert r["exit_code"] == 0
    assert [t["passed"] for t in ws.test_runs] == [False, True]


def test_changing_signature_breaks_compat_test(ws):
    ws.dispatch("replace_in_file", {"path": "src/auth.ts", "old": REFRESH_SIGNATURE,
                                    "new": "export async function refresh(refreshToken: string, force = false): Promise<TokenPair>"})
    assert any("backward compatible" in f for f in ws.failing_tests())


def test_ttl_change_does_not_fix(ws):
    ws.dispatch("write_file", {"path": "config/token.json", "content": json.dumps({"ttlSeconds": 1800})})
    assert ws.dispatch("run_tests", {})["exit_code"] == 1
    assert ws.writes[-1]["path"] == "config/token.json"


def test_policy_blocks_dotfiles_but_grep_skips_them(ws):
    assert "PERMISSION_DENIED" in ws.dispatch("read_file", {"path": ".env"})["error"]
    g = ws.dispatch("grep", {"pattern": "PAYMENT_API_KEY"})
    assert g["count"] == 0
    assert ws.dispatch("list_files", {})["ok"]


def test_run_tests_output_is_large(tmp_path):
    fp = generate(tmp_path, scale=1.0, log_files=1, log_lines=10)
    out = WorkspaceTools(fp.workspace).dispatch("run_tests", {})["output"]
    assert out.count("\n") > 6500
    assert out.rstrip().endswith("Ran all test suites.")
