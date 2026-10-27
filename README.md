# Challenge B: Context Management

Bài tập SE373, Buổi 7: *Memory, Context Engineering & Prompt Caching*.

- **B1 Compact (bắt buộc):** session dài được compact; agent vẫn nhớ lỗi đang điều tra, cách đã thử và bước tiếp theo.
- **B2 Code Mode (điểm cộng):** agent trả lời câu hỏi trên nhiều file log; raw log không đi vào context.

Báo cáo: [docs/final/Group44_SE373.R11_BTVN7_ChallengeB.pdf](docs/final/Group44_SE373.R11_BTVN7_ChallengeB.pdf) · Kế hoạch: [Plan.md](Plan.md)

## Cài đặt

Yêu cầu **Python 3.11+**. Các lệnh chạy tại thư mục gốc của repo.

```bash
git clone https://github.com/dthanhman/Compact-Challenge-B.git
cd Compact-Challenge-B
```

Tạo môi trường riêng (chọn **một** trong hai cách):

```bash
# Cách 1: venv
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# Cách 2: conda (tên env tuỳ ý)
conda create -n ctxb python=3.11 -y
conda activate ctxb
```

Cài package kèm giao diện web và pytest:

```bash
pip install -e ".[ui,dev]"
```

Nếu không muốn cài dạng package: `pip install -r requirements.txt` (bản đã kiểm thử), rồi đặt `PYTHONPATH=src` trước khi chạy
(`set PYTHONPATH=src` trên cmd, `$env:PYTHONPATH="src"` trên PowerShell, `export PYTHONPATH=src` trên macOS/Linux).

Cấu hình API key (chỉ cần cho thí nghiệm gọi Gemini; test, `simulate`, `traps` và xem kết quả trên web không cần):

```bash
copy .env.example .env          # Windows  (macOS/Linux: cp .env.example .env)
# mở .env, điền GEMINI_API_KEY (lấy tại https://aistudio.google.com/apikey)
```

Nếu API báo `403 free tier is not available for this project`, tạo key trong một project mới trên Google AI Studio.
Free tier giới hạn số request mỗi ngày, nên chạy các thí nghiệm lần lượt, không song song.

## Chạy

Không cần API key:

```bash
python -m pytest                        # 46 test offline (model giả)
python -m ctxb simulate                 # mô phỏng token native vs Code Mode
python -m ctxb traps                    # các bẫy an toàn của runtime Code Mode
python -m ctxb summary                  # tổng hợp lại reports/
streamlit run app/streamlit_app.py      # web UI: xem kết quả đã lưu trong reports/
```

Cần `GEMINI_API_KEY` (cấu hình giống báo cáo: window ảo 32k):

```bash
# B1: none / truncate / structured (ngưỡng 70%) + cold-start
python -m ctxb run-b1 --strategy all --window 32000 --cold-start

# B1: cấu hình tốt nhất trong báo cáo (ngưỡng 60%, checkpoint milestone), chạy 3 lần
python -m ctxb run-b1 --strategy structured --window 32000 --full-threshold 0.6 --tag t60mfix --checkpoint-after-probe --cold-start --runs 3

# B2: native vs Code Mode + bẫy
python -m ctxb run-b2 --mode all --traps

# Chat tương tác (/compact, /stats, /quit)
python -m ctxb chat --strategy structured --window 32000
```

Lưu ý: chạy lại cùng tên run sẽ **ghi đè** kết quả cũ trong `reports/`. Muốn giữ kết quả cũ, đổi `--tag` hoặc dùng `--start N` để đánh số tiếp.
Gộp các lần chạy lặp: `python docs/aggregate_b1.py` → `reports/b1/repeat.md`.

## Cấu trúc

```
src/ctxb/
├── config.py            cấu hình (.env): window ảo, ngưỡng compact, giới hạn Code Mode
├── llm.py               GeminiLLM + ScriptedLLM (model giả cho test)
├── tokens.py            ước lượng token + hiệu chỉnh theo usage
├── context.py           system prompt tĩnh (base + AGENTS.md)
├── agent.py             Session: agent loop, hook compaction trước mỗi lần gọi model
├── policy.py            permission check cho từng lời gọi tool
├── recorder.py          JSONL mỗi request, snapshot context, checkpoint
├── workspace/           repo giả `authsvc` (fixtures.py) + tool (tools.py)
├── compaction/          archive, prune (KEEP/TRUNCATE/DROP), checkpoint, compactor (pipeline 5 bước)
├── codemode/runner.py   run_code: subprocess, timeout, output cap, tools.* proxy (JSON-RPC)
└── experiments/         b1.py, b2.py, simulate.py, grading.py
scenarios/               kịch bản B1 và câu hỏi B2 (YAML)
app/streamlit_app.py     web UI
reports/                 kết quả thí nghiệm (JSONL, result.json, summary.md)
runs/                    workspace giả và dữ liệu tạm (không commit)
```
