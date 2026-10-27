# B1 — gộp các lần chạy lặp

Trung bình ± độ lệch chuẩn (n ≥ 2). Điểm ghi dạng tổng số đạt / tổng số tối đa qua các lần chạy.

| Cấu hình | n | Context lớn nhất | Tổng input | LLM call | Call vượt window | P1–P5 | A1–A3 | Probe trượt |
|---|---|---|---|---|---|---|---|---|
| none | 3 | 99,235 ± 18,485 | 2,024,760 ± 315,044 | 38.7 ± 0.6 | 29.7 ± 0.6 | 15/15 | 9/9 | — |
| structured-t60 | 1 | 19,494 | 573,551 | 52.0 | 0.0 | 5/5 | 3/3 | — |
| structured-t60fix | 2 | 20,215 ± 1,047 | 544,041 ± 9,683 | 50.0 ± 4.2 | 0.0 ± 0.0 | 8/10 | 6/6 | P5×2 |
| structured-t60m | 1 | 20,477 | 507,360 | 49.0 | 0.0 | 4/5 | 2/3 | P5×1 |
| structured-t60mfix | 3 | 19,743 ± 606 | 450,045 ± 6,048 | 46.0 ± 1.7 | 0.0 ± 0.0 | 14/15 | 9/9 | P5×1 |
| structured-t70 | 1 | 26,365 | 588,052 | 52.0 | 0.0 | 4/5 | 3/3 | P5×1 |
| truncate | 2 | 51,854 ± 21,723 | 1,644,398 ± 367,646 | 92.0 ± 8.5 | 18.5 ± 10.6 | 0/10 | 4/6 | P1×2, P2×2, P3×2, P4×2, P5×2 |

## Cold-start

| Cấu hình | n | A1–A3 | Input tokens |
|---|---|---|---|
| coldstart-t60 | 1 | 3/3 | 94,885 |
| coldstart-t60fix | 2 | 6/6 | 126,477 ± 18,614 |
| coldstart-t60m | 1 | 3/3 | 182,747 |
| coldstart-t60mfix | 3 | 8/9 | 108,240 ± 23,152 |
