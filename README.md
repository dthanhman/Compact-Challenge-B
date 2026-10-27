# Challenge B: Context Management

Bài tập SE373, Buổi 7: *Memory, Context Engineering & Prompt Caching*.

- **B1 Compact (bắt buộc):** session dài được compact; agent vẫn nhớ lỗi đang điều tra, cách đã thử và bước tiếp theo.
- **B2 Code Mode (điểm cộng):** agent trả lời câu hỏi trên nhiều file log; raw log không đi vào context.

Kế hoạch: [Plan.md](Plan.md) · Báo cáo nháp: [docs/BaoCao_ChallengeB.md](docs/BaoCao_ChallengeB.md)

## Cài đặt

```bat
conda activate se373
cd Chanllenge_B
copy .env.example .env      :: điền GEMINI_API_KEY (hoặc GOOGLE_API_KEY), GEMINI_MODEL
set PYTHONPATH=src           :: PowerShell: $env:PYTHONPATH="src"
```

Nếu tạo env mới: `pip install -r requirements.txt` (Python 3.11+).

## Chạy

```bat
python -m pytest                                   :: test offline, không cần API key
python -m ctxb simulate                            :: mô phỏng token theo md §2, §8
python -m ctxb traps                               :: các bẫy Code Mode (không cần API)

python -m ctxb run-b1 --strategy all --window 48000 --cold-start   :: B1: none / truncate / structured + cold-start
python -m ctxb run-b2 --mode both --traps                          :: B2: native vs Code Mode
python -m ctxb summary                                             :: tổng hợp lại reports/

python -m ctxb chat --strategy structured --window 48000           :: chat tương tác (/compact, /stats, /quit)
streamlit run app/streamlit_app.py                                 :: web UI
```

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
