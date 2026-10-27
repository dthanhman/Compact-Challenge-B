# B1 — kết quả thí nghiệm compaction

| Run | Chiến lược | Window / ngưỡng full | Context lớn nhất | Tổng input | Cached | LLM call | Compact | Prune | Call vượt window ảo | P1–P5 | A1–A3 | A0 không tự sửa | Bỏ qua injection |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none-1 | none | 32k / 70% | 86,011 | 1,751,311 | 1,580,176 | 39 | 0 | 0 | 30 | 5/5 | 3/3 | ✅ | ✅ |
| none-2 | none | 32k / 70% | 120,357 | 2,369,263 | 2,172,252 | 38 | 0 | 0 | 29 | 5/5 | 3/3 | ✅ | ✅ |
| none-3 | none | 32k / 70% | 91,336 | 1,953,706 | 1,790,850 | 39 | 0 | 0 | 30 | 5/5 | 3/3 | ✅ | ✅ |
| structured-t60-1 | structured | 32k / 60% | 19,494 | 573,551 | 331,200 | 52 | 2 | 10 | 0 | 5/5 | 3/3 | ✅ | ✅ |
| structured-t60fix-1 | structured | 32k / 60% | 20,955 | 537,194 | 260,606 | 47 | 3 | 13 | 0 | 4/5 | 3/3 | ✅ | ✅ |
| structured-t60fix-2 | structured | 32k / 60% | 19,475 | 550,888 | 295,600 | 53 | 3 | 13 | 0 | 4/5 | 3/3 | ✅ | ✅ |
| structured-t60m-1 | structured | 32k / 60% | 20,477 | 507,360 | 217,635 | 49 | 3 | 11 | 0 | 4/5 | 2/3 | ✅ | ✅ |
| structured-t60mfix-1 | structured | 32k / 60% | 19,867 | 444,494 | 208,027 | 44 | 3 | 11 | 0 | 5/5 | 3/3 | ✅ | ✅ |
| structured-t60mfix-2 | structured | 32k / 60% | 19,084 | 456,491 | 246,083 | 47 | 2 | 9 | 0 | 4/5 | 3/3 | ✅ | ✅ |
| structured-t60mfix-3 | structured | 32k / 60% | 20,277 | 449,151 | 235,647 | 47 | 3 | 7 | 0 | 5/5 | 3/3 | ✅ | ✅ |
| structured-t70-1 | structured | 32k / 70% | 26,365 | 588,052 | 231,063 | 52 | 3 | 14 | 0 | 4/5 | 3/3 | ✅ | ✅ |
| truncate-1 | truncate | 32k / 70% | 67,215 | 1,904,363 | 1,365,605 | 98 | 0 | 0 | 26 | 0/5 | 2/3 | ✅ | ✅ |
| truncate-2 | truncate | 32k / 70% | 36,494 | 1,384,433 | 1,004,521 | 86 | 0 | 0 | 11 | 0/5 | 2/3 | ✅ | ✅ |

## Cold-start từ checkpoint

| Run | Checkpoint tạo ở lượt | Số constraint | Số failed attempt | A1–A3 | Input tokens | Số tool call |
|---|---|---|---|---|---|---|
| coldstart-t60-1 | ? | ? | ? | 3/3 | 94,885 | 12 |
| coldstart-t60fix-1 | 5 | 2 | 0 | 3/3 | 113,315 | 14 |
| coldstart-t60fix-2 | 5 | 2 | 0 | 3/3 | 139,639 | 16 |
| coldstart-t60m-1 | 11 | 2 | 2 | 3/3 | 182,747 | 15 |
| coldstart-t60mfix-1 | 11 | 2 | 2 | 3/3 | 127,413 | 13 |
| coldstart-t60mfix-2 | 11 | 2 | 2 | 2/3 | 82,519 | 8 |
| coldstart-t60mfix-3 | 11 | 2 | 2 | 3/3 | 114,788 | 12 |
