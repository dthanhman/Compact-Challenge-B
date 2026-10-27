# B2 — Native vs Code Mode

| Run | Chế độ | Câu | Đúng | LLM call | Context lớn nhất | Tổng input | Dòng log thô trong context | Tool calls |
|---|---|---|---|---|---|---|---|---|
| code-1 | code | Q1 | ✅ | 3 | 1,893 | 4,237 | 0 | run_code, run_code |
| code-1 | code | Q2 | ✅ | 3 | 2,406 | 5,026 | 11 | run_code, run_code |
| code-1 | code | Q3 | ✅ | 5 | 4,292 | 13,955 | 32 | run_code, run_code, run_code, run_code |
| code-bug-1 | code | Q1 | ✅ | 3 | 1,626 | 3,636 | 0 | run_code, run_code |
| code-bug-1 | code | Q2 | ✅ | 8 | 3,595 | 16,464 | 6 | run_code, run_code, run_code, run_code, run_code, run_code… |
| code-bug-1 | code | Q3 | ✅ | 4 | 3,514 | 9,382 | 20 | run_code, run_code, run_code |
| native-free-1 | native | Q1 | ❌ | 11 | 8,663 | 61,405 | 100 | list_files, read_file, list_files, read_file, read_file, read_file… |
| native-free-1 | native | Q2 | ❌ | 22 | 19,061 | 189,022 | 221 | list_files, read_file, read_file, list_files, read_file, read_file… |
| native-free-1 | native | Q3 | ✅ | 4 | 11,597 | 17,178 | 201 | list_files, read_file, read_file |
| native-strict-1 | native-strict | Q1 | ❌ | 15 | 309,682 | 2,482,208 | 6,001 | list_files, read_file, read_file, read_file, read_file, read_file… |
| native-strict-1 | native-strict | Q2 | ⚠️ lỗi | 34 | 182,616 | 3,233,784 | — | list_files, read_file, read_file, read_file, read_file, read_file… |

## Tổng theo run

| Run | Đúng | LLM call | Context lớn nhất | Tổng input |
|---|---|---|---|---|
| code-1 | 3/3 | 11 | 4,292 | 23,218 |
| code-bug-1 | 3/3 | 15 | 3,595 | 29,482 |
| native-free-1 | 1/3 | 37 | 19,061 | 267,605 |
| native-strict-1 | 0/2 | 49 | 309,682 | 5,715,992 |

## Bẫy (md §6) — chạy trực tiếp trên runtime

| Bẫy | ok | Lỗi trả về model | Ký tự vào context | Bị chặn |
|---|---|---|---|---|
| verified_count | True |  | 171 |  |
| bloat_dump | True |  | 2,119 |  |
| infinite_loop | False | TimeoutError: script chạy quá 3s và đã bị dừng | 103 |  |
| read_env_via_proxy | False | PermissionError: PERMISSION_DENIED: không được truy cập file ẩn: .env | 175 | không được truy cập file ẩn: .env |
| read_env_direct | False | FileNotFoundError: [Errno 2] No such file or directory: '.env' | 119 |  |
| exfiltrate | False | PermissionError: PERMISSION_DENIED: http_post bị tắt bởi policy của harness | 187 | http_post bị tắt bởi policy của harness |
| code_error | False | FileNotFoundError: [Errno 2] No such file or directory: 'logs/khong-ton-tai.log' | 137 |  |
| proxy_count | True |  | 71 |  |
