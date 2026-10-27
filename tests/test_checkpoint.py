import json

import pytest

from ctxb.compaction.checkpoint import (
    Checkpoint,
    build_checkpoint_prompt,
    constraint_messages,
    parse_checkpoint,
    render_checkpoint_message,
    validate,
)

from conftest import CHECKPOINT_JSON


def test_parse_plain_and_fenced_json():
    cp = parse_checkpoint(json.dumps(CHECKPOINT_JSON))
    assert cp.next_action.startswith("thêm")
    fenced = "Đây là checkpoint:\n```json\n" + json.dumps(CHECKPOINT_JSON) + "\n```"
    assert parse_checkpoint(fenced).goal == cp.goal
    with pytest.raises(ValueError):
        parse_checkpoint("không có json")


def test_tolerates_loose_types():
    cp = Checkpoint.from_dict({"goal": "g", "next_action": "n", "constraints": "một chuỗi", "failed_attempts": ["thử A"]})
    assert cp.constraints == ["một chuỗi"]
    assert cp.failed_attempts == [{"what": "thử A", "result": ""}]


def test_validate_rejects_missing_fields_and_lost_constraints(ws):
    cp = Checkpoint(goal="", next_action="", constraints=[])
    _, errors, _ = validate(cp, ["Lưu ý: phải giữ API backward compatible"], ws.root)
    assert any("goal" in e for e in errors) and any("next_action" in e for e in errors)
    assert any("constraints rỗng" in e for e in errors)


def test_validate_drops_hallucinated_files(ws):
    cp, errors, warnings = validate(parse_checkpoint(json.dumps(CHECKPOINT_JSON)), [], ws.root)
    assert not errors
    assert cp.files == ["src/auth.ts", "tests/auth.test.ts"]
    assert any("khong_ton_tai" in w for w in warnings)


def test_constraint_detection():
    msgs = [{"role": "user", "text": "Chạy test"}, {"role": "user", "text": "Lưu ý: không được đổi signature"},
            {"role": "assistant", "text": "phải làm"}]
    assert constraint_messages(msgs) == ["Lưu ý: không được đổi signature"]


def test_prompt_and_render_contain_state():
    cp = parse_checkpoint(json.dumps(CHECKPOINT_JSON))
    prompt = build_checkpoint_prompt(cp, [{"role": "user", "text": "hello", "turn": 4}], issues=["thiếu goal"])
    assert "CHECKPOINT CŨ" in prompt and "[turn 4] USER: hello" in prompt and "thiếu goal" in prompt
    msg = render_checkpoint_message(cp, 2, (1, 5), [{"role": "user", "text": "phải giữ API", "turn": 3}])
    assert msg.startswith("<checkpoint n=2 covers_turns=1-5>") and "[turn 3] phải giữ API" in msg


def test_validate_rejects_waiting_as_next_action(ws):
    """§4.8: 'chờ user' là trạng thái tạm, không phải next_action."""
    cp = Checkpoint(goal="g", next_action="Chờ chỉ đạo từ user", constraints=["c"])
    _, errors, _ = validate(cp, [], ws.root)
    assert any("waiting_for_user" in e for e in errors)
    cp = Checkpoint(goal="g", next_action="thêm lock cho refresh() rồi chạy test", waiting_for_user="chờ user cho phép sửa",
                    constraints=["c"])
    assert not validate(cp, [], ws.root)[1]


def test_waiting_for_user_roundtrip_and_priority_in_render():
    cp = Checkpoint.from_dict({"goal": "g", "next_action": "n", "waiting_for_user": "chờ user cho phép sửa"})
    assert cp.to_dict()["waiting_for_user"] == "chờ user cho phép sửa"
    msg = render_checkpoint_message(cp, 1, (1, 3), [])
    assert "yêu cầu MỚI NHẤT của user" in msg


def test_waiting_for_tool_result_is_still_valid(ws):
    cp = Checkpoint(goal="g", next_action="Chờ kết quả run_tests sau khi tăng ttlSeconds", constraints=["c"])
    assert not validate(cp, [], ws.root)[1]


def test_waiting_prefix_with_technical_step_is_only_a_warning(ws):
    cp = Checkpoint(goal="g", constraints=["c"],
                    next_action="Đợi user chỉ đạo tiếp theo; khi được yêu cầu sẽ thêm single-flight lock cho refresh() trong src/auth.ts")
    _, errors, warnings = validate(cp, [], ws.root)
    assert not errors and any("waiting_for_user" in w for w in warnings)
