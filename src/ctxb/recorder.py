"""Ghi bằng chứng của một run: JSONL mỗi request/sự kiện, snapshot context, checkpoint.

    <run_dir>/requests.jsonl       một dòng cho mỗi lần gọi model + mỗi sự kiện compaction
    <run_dir>/snapshots/NNN_before.json / NNN_after.json   context trước/sau compact
    <run_dir>/checkpoints/checkpoint_N.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tokens import estimate_message, render_message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def summarize_messages(messages: list[dict]) -> list[dict[str, Any]]:
    """Dạng rút gọn của context để hiển thị (Context inspector)."""
    out = []
    for i, m in enumerate(messages):
        item = {"i": i, "role": m["role"], "turn": m.get("turn", 0), "tokens": estimate_message(m),
                "checkpoint": bool(m.get("checkpoint"))}
        if m["role"] == "tool":
            item["results"] = [
                {"name": r["name"], "label": r.get("label", "KEEP"), "archive_id": r.get("archive_id"),
                 "args": r.get("args")}
                for r in m["results"]
            ]
        if m["role"] == "assistant" and m.get("tool_calls"):
            item["tool_calls"] = [{"name": c.name, "args": c.args} for c in m["tool_calls"]]
        item["preview"] = render_message(m)[:1500]
        out.append(item)
    return out


class Recorder:
    def __init__(self, run_dir: str | Path, run_id: str = "") -> None:
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or self.dir.name
        self._snap = 0
        self._ckpt = 0

    def log(self, record: dict[str, Any]) -> None:
        record = {"ts": _now(), "run": self.run_id, **record}
        with (self.dir / "requests.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def snapshot(self, tag: str, messages: list[dict]) -> str:
        if tag == "before":
            self._snap += 1
        path = self.dir / "snapshots" / f"{self._snap:03d}_{tag}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summarize_messages(messages), ensure_ascii=False, indent=1), encoding="utf-8")
        return str(path.relative_to(self.dir))

    def save_checkpoint(self, cp, meta: dict[str, Any]) -> str:
        self._ckpt += 1
        path = self.dir / "checkpoints" / f"checkpoint_{self._ckpt}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**meta, "checkpoint": cp.to_dict()}, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.relative_to(self.dir))

    def write_json(self, name: str, data: Any) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path


def load_records(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "requests.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
