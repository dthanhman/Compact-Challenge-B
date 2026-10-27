"""Permission check cho từng lời gọi tool (md §3, §6.4).

Dùng chung cho tool native và cho ``tools.*`` proxy của Code Mode: mọi lời gọi
đi qua harness đều được kiểm tra theo tên tool và tham số.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

PATH_ARGS = ("path", "glob")


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


@dataclass
class Policy:
    allow_dotfiles: bool = False  # .env, .git, ... (secret thường nằm ở đây)
    allow_http_post: bool = False
    allow_write: bool = True
    denied: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def is_dotfile(path: str) -> bool:
        return any(part.startswith(".") and part not in (".", "..") for part in PurePosixPath(path.replace("\\", "/")).parts)

    def check(self, tool: str, args: dict[str, Any]) -> Decision:
        decision = self._check(tool, args)
        if not decision.allowed:
            self.denied.append({"tool": tool, "args": args, "reason": decision.reason})
        return decision

    def _check(self, tool: str, args: dict[str, Any]) -> Decision:
        if tool == "http_post" and not self.allow_http_post:
            return Decision(False, "http_post bị tắt bởi policy của harness")
        if tool in ("write_file", "replace_in_file") and not self.allow_write:
            return Decision(False, "ghi file bị tắt bởi policy của harness")
        if not self.allow_dotfiles:
            for key in PATH_ARGS:
                value = args.get(key)
                if isinstance(value, str) and tool != "list_files" and self.is_dotfile(value):
                    return Decision(False, f"không được truy cập file ẩn: {value}")
        return Decision(True)
