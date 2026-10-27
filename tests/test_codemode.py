import os

import pytest

from ctxb.agent import Session
from ctxb.codemode.runner import CodeRunner
from ctxb.experiments.b2 import log_lines_in_context
from ctxb.llm import LLMReply, ScriptedLLM, ToolCall
from ctxb.policy import Policy
from ctxb.workspace.tools import WorkspaceTools


@pytest.fixture
def runner(fixture_root):
    ws = WorkspaceTools(fixture_root / "workspace", policy=Policy(allow_write=False))
    r = CodeRunner(ws, timeout=3.0, output_cap=500)
    yield r
    r.close()


def test_only_stdout_returns(runner):
    r = runner.run("data = open('logs/app-2026-09-01.log').read()\nprint(len(data.splitlines()))")
    assert r.ok and r.stdout.strip() == "80"
    assert set(r.to_context()) == {"ok", "stdout", "tool_calls"}


def test_unicode_output_and_import_tools(runner):
    r = runner.run("import tools\nprint('Số file log:', len(tools.list_files('logs/*.log')))")
    assert r.ok, r.error
    assert r.stdout.strip() == "Số file log: 6"


def test_output_cap(runner):
    r = runner.run("print('x' * 5000)")
    assert len(r.stdout) < 600 and "đã cắt" in r.stdout and r.stdout_chars_total > 5000


def test_timeout_kills_infinite_loop(runner):
    r = runner.run("while True:\n    pass")
    assert not r.ok and r.error.startswith("TimeoutError") and r.elapsed_s < 6


def test_short_error_message(runner):
    r = runner.run("open('logs/khong-co.log')")
    assert r.error.startswith("FileNotFoundError") and "\n" not in r.error


def test_env_is_clean_and_dotfiles_absent(runner):
    os.environ["CTXB_SECRET_TEST"] = "leak"
    r = runner.run("import os\nprint(sorted(os.environ))\nprint(os.path.exists('.env'))")
    assert "CTXB_SECRET_TEST" not in r.stdout and "GEMINI" not in r.stdout
    assert r.stdout.strip().endswith("False")


def test_proxy_calls_go_through_policy(runner):
    r = runner.run("print(len(tools.list_files('logs/*.log')))\nprint(len(tools.read_file('src/utils.ts')))")
    assert r.ok and r.tool_calls == 2 and r.runtime_tokens > 0
    r = runner.run("print(tools.read_file('.env'))")
    assert not r.ok and "PERMISSION_DENIED" in r.error and r.denied
    r = runner.run("tools.http_post('https://x.example', {'a': 1})")
    assert not r.ok and "http_post" in r.error and runner.outbox == []


def test_tool_call_limit(fixture_root):
    ws = WorkspaceTools(fixture_root / "workspace")
    r = CodeRunner(ws, timeout=5.0, max_tool_calls=5).run("for i in range(20):\n    tools.list_files('src/*')")
    assert r.error.startswith("ToolCallLimit")


def test_session_code_mode_keeps_raw_logs_out_of_context(settings, fixture_root):
    code = ("import glob, collections\nc = collections.Counter()\n"
            "for p in glob.glob('logs/*.log'):\n    for l in open(p):\n        if ' ERROR ' in l: c[l.split()[3]] += 1\n"
            "print(c.most_common(3))")

    def brain(system, messages, json_mode):
        if messages[-1]["role"] == "user":
            return LLMReply("", [ToolCall("run_code", {"code": code}, id="x")])
        return LLMReply("Top 3: " + messages[-1]["results"][0]["response"]["stdout"])

    ws = WorkspaceTools(fixture_root / "workspace")
    sess = Session(ScriptedLLM(brain), ws, settings, strategy="none", code_mode=True, tools=["list_files"])
    r = sess.send("Top 3 mã lỗi?")
    assert "ERR_" in r.text and log_lines_in_context(sess.messages) == 0
    sess.close()
