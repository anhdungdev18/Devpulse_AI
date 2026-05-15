# 🧠 DevPulseAI - Hệ thống tình báo tín hiệu đa agent

DevPulseAI là một project mẫu minh họa cách xây dựng **pipeline multi-agent** để:

- thu thập tín hiệu kỹ thuật từ nhiều nguồn
- chuẩn hóa và khử trùng lặp dữ liệu
- chấm điểm độ liên quan
- đánh giá rủi ro
- tổng hợp thành một bản **intelligence digest** có thể hành động

Nguyên tắc thiết kế của project này:

- chỉ dùng agent ở những bước thực sự cần suy luận
- các bước tất định như thu thập, chuẩn hóa, khớp schema, dedup sẽ được viết dưới dạng utility thông thường
- điểm cuối không do LLM tự quyết định, mà được tính bằng công thức có thể giải thích

## Kiến trúc tổng quan

```text
Nguồn dữ liệu
GitHub / ArXiv / HackerNews / Medium / HuggingFace
        |
        v
SignalCollector
- Utility, không dùng LLM
- Chuẩn hóa schema
- Khử trùng lặp bằng source:id
        |
        v
RelevanceAgent
- Hybrid scoring
- Deterministic factors + LLM semantic factors
        |
        v
RiskAgent
- Hybrid scoring
- Deterministic risk factors + LLM contextual factors
        |
        v
SynthesisAgent
- Tổng hợp relevance + risk + metadata
- Tạo executive summary và recommendations
        |
        v
Intelligence Digest
```

## Vì sao SignalCollector không phải là agent

Đây là một lựa chọn có chủ đích.

Phần thu thập dữ liệu chỉ gồm:

- gọi API hoặc RSS
- chuẩn hóa field
- khử trùng lặp

Những việc này không cần suy luận, không cần phân tích ngữ nghĩa, không cần LLM. Nếu bọc nó vào `Agent` thì chỉ mang tính trang trí và làm sai lệch kiến trúc.

Quy tắc đơn giản:

- nếu có thể viết thành pure function, đó là utility
- nếu đầu ra phụ thuộc vào ngữ cảnh, phán đoán, giải thích hoặc tổng hợp ngôn ngữ, đó mới là agent

## Vai trò agent và model

| Thành phần | Loại | Model mặc định | Vai trò |
|---|---|---|---|
| `SignalCollector` | Utility | không dùng | Chuẩn hóa và dedup |
| `RelevanceAgent` | Agent | `gpt-4.1-mini` | Chấm semantic relevance |
| `RiskAgent` | Agent | `gpt-4.1-mini` | Đánh giá risk context |
| `SynthesisAgent` | Agent | `gpt-4.1` | Tổng hợp digest cuối |

Có thể override bằng biến môi trường:

```bash
export MODEL_RELEVANCE=gpt-4.1-mini
export MODEL_RISK=gpt-4.1-mini
export MODEL_SYNTHESIS=gpt-4.1
```

## Cơ chế scoring hiện tại

Project hiện dùng kiểu **hybrid deterministic + LLM**.

### Relevance

Deterministic factors:

- `popularity`
- `timeliness`
- `engagement`

LLM chỉ trả semantic factors:

- `technical_impact`
- `actionability`
- `ecosystem_relevance`

Điểm relevance cuối được tính bằng công thức cố định:

```python
final_score = (
    0.20 * popularity
    + 0.15 * timeliness
    + 0.15 * engagement
    + 0.25 * technical_impact
    + 0.15 * actionability
    + 0.10 * ecosystem_relevance
)
```

### Risk

Deterministic factors:

- `severity`
- `exploitability`
- `developer_impact`
- `migration_cost`
- `confidence`

LLM bổ sung phần contextual cho các factor trên. `risk_score` cuối được tính bằng công thức:

```python
risk_score = (
    0.30 * severity
    + 0.25 * exploitability
    + 0.25 * developer_impact
    + 0.15 * migration_cost
    + 0.05 * confidence
)
```

Map mức rủi ro:

- `0-29` -> `LOW`
- `30-59` -> `MEDIUM`
- `60-84` -> `HIGH`
- `85-100` -> `CRITICAL`

## Cách chạy local

### 1. Kiểm tra nhanh không cần API key

```bash
python verify.py
```

Lệnh này dùng mock data để xác nhận pipeline vẫn chạy.

### 2. Chạy full pipeline

```bash
pip install -r requirements.txt
python main.py
```

Nếu không có `OPENAI_API_KEY`, hệ thống sẽ fallback sang heuristic scoring.

### 3. Chạy backend riêng

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 4. Chạy frontend local

Frontend là static HTML/CSS/JS, bạn có thể phục vụ nó bằng bất kỳ static server nào.

Ví dụ:

```bash
cd frontend
python -m http.server 4173
```

Mở:

```text
http://127.0.0.1:4173
```

Lưu ý:

- `frontend/config.js` phải trỏ đúng `API_BASE_URL`
- backend và frontend đã được tách riêng để deploy

## Deploy khuyến nghị

### Backend trên Render

Cấu hình:

- Root Directory: để trống
- Build Command:

```bash
pip install -r backend/requirements.txt
```

- Start Command:

```bash
uvicorn backend.app:app --host 0.0.0.0 --port $PORT
```

Environment Variables cần thêm:

- `OPENAI_API_KEY`
- `MODEL_RELEVANCE=gpt-4.1-mini`
- `MODEL_RISK=gpt-4.1-mini`
- `MODEL_SYNTHESIS=gpt-4.1`

Sau khi deploy, test:

```text
https://your-render-url/api/health
```

### Frontend trên Vercel

Trước khi deploy, sửa:

`frontend/config.js`

```js
window.DEVPULSE_CONFIG = {
  API_BASE_URL: "https://your-render-backend.onrender.com",
};
```

Cấu hình Vercel:

- Root Directory: `frontend`
- Framework Preset: `Other`
- Build Command: để trống
- Output Directory: `.`
- Install Command: để trống

## Cấu trúc thư mục

```text
devpulse_ai/
├── adapters/                 # Adapter nguồn dữ liệu gốc
├── agents/                   # Agent gốc của project
├── backend/
│   ├── app.py                # FastAPI backend
│   ├── requirements.txt      # Dependency cho backend deploy
│   ├── .env                  # Biến môi trường local cho backend
│   └── core/                 # Backend self-contained
│       ├── adapters/         # Adapter copy vào backend để deploy riêng
│       ├── agents/           # Agent copy vào backend để deploy riêng
│       ├── scoring/          # Scoring copy vào backend để deploy riêng
│       └── dashboard_service.py
├── frontend/
│   ├── index.html            # Dashboard giao diện
│   ├── styles.css            # Giao diện
│   ├── app.js                # Logic frontend
│   ├── config.js             # URL backend
│   └── vercel.json           # Cấu hình Vercel
├── scoring/                  # Công thức scoring gốc
├── workflows/
├── dashboard_service.py      # Service layer gốc
├── main.py                   # Chạy full pipeline
├── verify.py                 # Kiểm tra mock pipeline
├── render.yaml               # Gợi ý cấu hình Render
├── streamlit_app.py          # Dashboard cũ, giữ lại để tham khảo
└── requirements.txt          # Dependency gốc của project
```

## Mở rộng thêm

Một số hướng có thể mở rộng sau:

1. Bổ sung thêm provider model ngoài OpenAI
2. Thêm vector search để truy vấn signal theo ngữ nghĩa
3. Lưu feedback người dùng để cải thiện scoring
4. Thêm adapter mới cho Reddit, X, YouTube, Papers with Code
5. Chuyển pipeline sang background jobs hoặc queue để scale tốt hơn

## Dependency chính

```text
agno
openai
httpx
feedparser
fastapi
uvicorn[standard]
python-dotenv
```

## Đánh đổi thiết kế

| Lựa chọn | Đánh đổi |
|---|---|
| Một provider mặc định | Đơn giản hơn, ít linh hoạt hơn |
| Utility cho collection | Trung thực kiến trúc, ít "agentic demo" hơn |
| Fallback heuristic | Chất lượng thấp hơn khi không có API key |
| Frontend static | Dễ deploy, nhưng không có build system phức tạp |
| Backend self-contained | Dễ deploy Render, nhưng có sự lặp lại code với root project |

Project này phù hợp để học kiến trúc multi-agent có thể giải thích, để demo dashboard, và để mở rộng thành một sản phẩm thử nghiệm có backend/frontend tách riêng.
