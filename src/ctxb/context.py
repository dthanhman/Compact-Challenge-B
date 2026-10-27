"""System prompt TĨNH: base prompt + AGENTS.md (slide 39–40: static prefix, dynamic suffix).

System prompt không bao giờ đổi trong một session — kể cả khi compact — để phần prefix
này luôn có thể được prompt cache dùng lại. Checkpoint đi vào ``messages`` chứ không vào system.
"""

from __future__ import annotations

from pathlib import Path

BASE_PROMPT = """Bạn là coding agent làm việc trên repo `authsvc` (TypeScript) thông qua các tool.
Workspace là thư mục gốc của repo; mọi đường dẫn đều tương đối với nó.

Cách làm việc:
1. Dùng tool để xem code, chạy test, đọc log trước khi kết luận.
2. Output tool lớn có thể bị harness lược bớt; khi cần chi tiết, đọc một khoảng dòng (read_file với start_line/end_line) hoặc read_archive(id, pattern).
3. Context có thể được harness compact. Khi đó đầu hội thoại có khối <checkpoint>: coi đó là trạng thái công việc chính thức
   (goal, constraints, failed_attempts, next_action) và tiếp tục từ đó. Yêu cầu mới của user được ưu tiên hơn
   next_action/waiting_for_user cũ; constraints vẫn luôn phải tuân thủ.
4. Khi trả lời user, nói rõ: đang điều tra gì, đã thử gì, bước tiếp theo là gì."""

CODE_MODE_NOTE = """
Code Mode: có tool `run_code` để chạy chương trình Python xử lý dữ liệu lớn (nhiều file log...).
Dữ liệu trung gian nằm lại trong runtime; CHỈ những gì script print ra mới vào context.
Hãy lọc/tổng hợp trong script và chỉ print kết quả cuối kèm số liệu kiểm chứng (số file đã quét, số dòng khớp)."""


def read_agents_md(path: str | Path) -> str:
    file = Path(path)
    return file.read_text(encoding="utf-8").strip() if file.exists() else ""


def build_system_prompt(agents_md: str, code_mode: bool = False) -> str:
    parts = [BASE_PROMPT + (CODE_MODE_NOTE if code_mode else "")]
    if agents_md:
        parts.append("# Rules của project (AGENTS.md)\n\n" + agents_md)
    return "\n\n".join(parts)
