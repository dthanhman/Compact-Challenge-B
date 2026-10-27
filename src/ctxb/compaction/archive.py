"""Archive raw tool output ra đĩa (slide 19: raw output được archive, không nằm mãi trong context)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class Archive:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._n = len(list(self.dir.glob("a*.txt")))

    def put(self, tool: str, args: dict[str, Any], text: str) -> str:
        self._n += 1
        aid = f"a{self._n:03d}"
        (self.dir / f"{aid}.txt").write_text(text, encoding="utf-8")
        (self.dir / f"{aid}.meta.json").write_text(
            json.dumps({"id": aid, "tool": tool, "args": args, "chars": len(text)}, ensure_ascii=False), encoding="utf-8"
        )
        return aid

    def get(self, aid: str) -> str:
        if not re.fullmatch(r"a\d{3,}", aid or ""):
            raise ValueError(f"archive id không hợp lệ: {aid}")
        path = self.dir / f"{aid}.txt"
        if not path.exists():
            raise FileNotFoundError(f"không có archive {aid}")
        return path.read_text(encoding="utf-8")


READ_ARCHIVE_SPEC = {
    "name": "read_archive",
    "description": (
        "Đọc lại raw output đã được harness archive khi compact context (id dạng a012). "
        "Nên truyền pattern (regex) để chỉ lấy các dòng liên quan, tránh đưa lại toàn bộ vào context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "pattern": {"type": "string", "description": "Regex lọc dòng (tuỳ chọn)"},
            "max_lines": {"type": "integer", "description": "Mặc định 80"},
        },
        "required": ["id"],
    },
}


def read_archive(archive: Archive, id: str, pattern: str = "", max_lines: int = 80) -> dict[str, Any]:
    lines = archive.get(id).splitlines()
    if pattern:
        rx = re.compile(pattern)
        lines = [l for l in lines if rx.search(l)]
    total = len(lines)
    return {"ok": True, "id": id, "matched_lines": total, "content": "\n".join(lines[: int(max_lines)]),
            "truncated": total > int(max_lines)}
