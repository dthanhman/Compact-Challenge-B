# Mô phỏng token (md §2, §8)

## Native vs Code Mode — 100 file × 1.200 token, nền 3.000 token, $5/1M

| Kết quả | Native (1 call/lượt) | Native (8 call song song) | Code Mode |
|---|---|---|---|
| LLM call | 102 | 15 | 2 |
| Context lớn nhất | 126,830 | 126,830 | 3,320 |
| Tổng input | 6,601,330 | 947,140 | 6,320 |
| Chi phí input | $33.01 | $4.74 | $0.0316 |

Native gửi gấp **1,045 lần** Code Mode. Song song giảm số LLM call nhưng đỉnh context giữ nguyên.

## Compaction + Code Mode — 40 lượt, window 200k, compact khi > 70%

| | Native | Code Mode |
|---|---|---|
| Số lần compact | 1 | 0 |
| Context lớn nhất | 136,000 | 54,200 |
| Context cuối | 130,000 | 54,200 |
