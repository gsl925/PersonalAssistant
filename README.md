# Personal AI Assistant

個人多 agent 知識助理系統 — 把日常收到的文件、截圖、筆記、網頁連結、會議錄音/影片，自動分類、摘要、打標籤，存進可搜尋的知識庫。透過 Telegram bot 或 REST API 輸入內容，全部用本機 LLM（Ollama）處理，不需要付費 API。

## 架構總覽

- **Backend**: Python 3.14 + FastAPI，APScheduler 跑在同一個 process 裡做每日摘要排程（不需要 Celery/Redis）
- **資料庫**: PostgreSQL 16（結構化資料）+ Qdrant（向量檢索）
- **Bot**: python-telegram-bot（long polling，不需要公開 IP），跟 FastAPI 共用同一個 event loop
- **LLM**: Ollama 本機 + Ollama cloud bridge（模型名稱有 `-cloud` 後綴的會走雲端算力，其餘都是純本機推理）
- **語音轉文字**: faster-whisper（CPU）
- **6 個 agent**（`skills/*/SKILL.md`）：document / note / meeting / screenshot / webclip / dev（dev-agent 預設關閉）

每個 agent 各自宣告自己要用哪個 capability tier（`fast_text` / `complex_reasoning` / `vision` / `embedding`），實際對應到哪個模型由 `backend/config.py` 的 `DEFAULT_CAPABILITY_TIERS` 決定，並支援 fallback chain。

## 前置需求

- Python 3.14
- PostgreSQL 16（或相容版本）
- Qdrant（本機執行檔或 Docker）
- [Ollama](https://ollama.com)，並先 pull 好要用的模型（預設用 `qwen3:8b`、`deepseek-r1:14b`、`qwen3-vl:8b`、`bge-m3`，可在 `backend/config.py` 調整）
- （可選）Telegram Bot Token — 從 [@BotFather](https://t.me/BotFather) 取得
- （可選）Gmail App Password — 若要用每日摘要寄信功能

## 安裝

```bash
# 1. 建立虛擬環境
setup_venv.bat
# 或手動：python -m venv venv

# 2. 啟用虛擬環境 —— 之後所有指令都要在啟用狀態下執行
venv\Scripts\activate.bat

# 3. 安裝相依套件（若用 setup_venv.bat 這步已經做過）
pip install -r requirements.txt

# 4. 設定環境變數
copy .env.example .env
# 打開 .env 填入 PostgreSQL 連線資訊、SECRET_KEY，以及（可選的）Telegram/Email 設定

# 5. 建立資料庫（若尚未建立 assistant role / knowledge_db）
python init_db.py
```

> **務必透過已啟用的虛擬環境執行所有指令**（`venv\Scripts\activate.bat` 之後，或直接呼叫 `venv\Scripts\python.exe`），不要用系統全域的 Python — 專案的相依套件（faster-whisper、qdrant-client、torch 等）都只裝在 `venv/` 裡。

## 啟動

先確認 PostgreSQL 服務已啟動（通常隨開機自動啟動）、Ollama 已啟動（通常隨登入自動啟動），然後：

```bash
start_all.bat
```

這會另外開兩個視窗：
- Qdrant（`http://localhost:6333`）
- FastAPI + Telegram bot（`http://localhost:8000`，API 文件在 `/api/docs`）

只想手動啟動 app（Qdrant 已經在跑的情況）：

```bash
venv\Scripts\python.exe start.py
```

## 使用方式

**Telegram**：直接傳文字、網址、截圖、文件（PDF/DOCX）、語音、影片給你的 bot，會自動分類處理並回覆標題/摘要/分類/標籤。

**REST API**（`http://localhost:8000/api/docs`）：
- `POST /api/ingest/text` / `/api/ingest/url` / `/api/ingest/file` — 輸入內容
- `GET /api/knowledge/documents` — 列表查詢（分頁、篩選）
- `GET /api/knowledge/documents/{id}` — 單筆詳情
- `GET /api/knowledge/documents/{id}/content` — 完整原文/逐字稿
- `GET /api/knowledge/search?q=...` — 語意搜尋（Qdrant）
- `GET /api/knowledge/mindmap/{id}` — 關聯文件圖

## 已知限制

- Telegram Bot API 下載檔案上限 20MB（Telegram 官方限制）— 大檔案請直接用 `/api/ingest/file` 上傳
- 尚無前端 dashboard，`/dashboard` 會優雅跳過
- 音訊/影片轉錄（whisper）在 CPU 上跑，大檔案會需要較長時間，處理中會顯示 `processing_status: "processing"`，可持續輪詢確認進度
