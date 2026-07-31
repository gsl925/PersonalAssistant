# 設計文件：每日跨專案進度確認機制（Claude Code Daily Check-in）

> 狀態：**設計階段，尚未實作**。這份文件是在 `GenAI_News` 專案的 Claude Code session 裡，跟使用者討論後寫的，目的是交給正在處理 `PersonalContent_Assistant` 其他項目的 Claude Code 實作。實作前建議先跟使用者確認「待決事項」章節裡列的幾點。

## 1. 目標

使用者想要每天固定時間，由這個 Assistant（常駐 process）自動「叫醒」Claude Code，去檢查使用者手上每個專案（目前至少 `GenAI_News`，未來會加更多）的待辦/進度，並透過 Telegram 回報。使用者確認後，才讓 Claude Code 實際動手處理。

三個已經跟使用者對齊的決策：

1. **不做雙向同步**：不要讓 Assistant 自己解析各專案格式不一的 `TODO.md`／筆記去判斷「有沒有 todo 需要叫醒」。改成**單向、由 Claude 主導**——每天無條件叫醒一次，讀該專案的實際狀態（TODO.md、git log 等），由 Claude 自己判斷、整理成結構化摘要，再把結果寫回 Assistant 的 DB。這樣 Assistant 一樣會有可查詢的狀態（滿足使用者想要的「每天都知道各專案進度」），但不用維護一套跟 Claude 判斷能力重疊、又更脆弱的 parser。
2. **先報告，不先動手**：每天的自動 check-in 一律是唯讀模式（只讀取、不修改任何檔案、不執行指令），整理報告送出後就結束。要「真的動手做」永遠需要使用者在 Telegram 上明確回覆確認，才會觸發第二次、有執行權限的呼叫。
3. **同一個 Telegram 窗口**：不新增另一個 bot，沿用這個 Assistant 現有的 `backend/bot/telegram_bot.py`（`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`），跟其他知識庫功能共用同一個對話。

## 2. 現有可重用的基礎設施（已確認存在，不用重造）

- `backend/tasks/scheduler.py` — `AsyncIOScheduler`（Asia/Taipei 時區），已有 `setup_jobs()` 註冊 `daily_digest`（08:00）跟 per-todo 的 `DateTrigger` 提醒 job，`replace_existing=True` + `misfire_grace_time` 的模式可以直接照抄。
- `backend/tasks/processing.py` — `send_daily_digest()` 是現有每日摘要的實作範例（讀 DB → 組訊息 → 發送），新的 check-in job 可以放在同一個檔案，或新開 `backend/tasks/claude_checkin.py`（比較不會讓這個檔案愈長愈亂，建議後者）。
- `backend/bot/telegram_bot.py` — `CommandHandler` 註冊模式（`/start`、`/status`、`/todo`），新增指令照同樣寫法加。這支檔案裡應該已經有「主動發訊息給使用者」的方法（daily digest 也是靠它送出的），新機制直接重用，不用重新兜 `python-telegram-bot` 的 API。
- `backend/api/todos.py` + `Orchestrator.create_todo_from_text()` / `get_todos()` — 現有的 todo CRUD，`source` 欄位可以拿來標記來源（例如 `source="claude:genai-news"`），區分「使用者自己加的」跟「Claude 每日回報同步進來的」。
- `.env` 裡已有 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`，不用新增設定。

## 3. 新增元件

### 3.1 專案清單設定 `projects.yaml`（新檔案，放在 repo 根目錄）

```yaml
projects:
  - name: genai-news
    label: "GenAI News"
    repo_path: "D:/_SideProject/GenAI_News"
    todo_source: "TODO.md"          # 相對 repo_path
    enabled: true
  - name: personal-assistant
    label: "Personal Assistant"
    repo_path: "D:/_SideProject/PersonalContent_Assistant"
    todo_source: "README.md"        # 這個專案目前沒有獨立 TODO.md，先讀 README + git log；之後可以補一份
    enabled: true
```

- `backend/config.py` 加一個 loader（例如 `load_tracked_projects()`），啟動時讀一次，供 scheduler job 使用。
- 之後要追蹤新專案，只要加一行，不用改程式碼。

### 3.2 每日 check-in job（新檔案 `backend/tasks/claude_checkin.py`）

```
async def run_daily_project_checkins() -> None:
    for project in load_tracked_projects():
        if not project.enabled:
            continue
        report = await _checkin_one_project(project)
        await _sync_report_to_todos(project, report)
        await _send_report_to_telegram(project, report)
```

- 排程：`scheduler.py` 的 `setup_jobs()` 裡加一個新的 `CronTrigger`（建議時間待決，見第 5 章），`id="daily_project_checkin"`，`replace_existing=True`。
- `_checkin_one_project()`：用 `asyncio.create_subprocess_exec` 呼叫 Claude Code CLI headless 模式：
  ```
  claude -p "<prompt，見 3.3>" --output-format text
  ```
  在 `cwd=project.repo_path` 底下執行（讓 Claude Code 用該專案自己的 `CLAUDE.md`/context，而不是在 Assistant 目錄下執行）。**這一步一定不能帶任何跳過權限確認的旗標**（例如不要用 `--dangerously-skip-permissions`）——唯讀分析理論上不會觸發寫入確認，但保留預設的權限行為是最後一道保險。
  - 需要 timeout（建議 3–5 分鐘），逾時視為失敗，記 log、照樣送一則「今天 XXX 專案檢查失敗」的 Telegram 通知，不要讓整個排程 job 掛掉（同一個 process 裡還有其他專案跟其他 job 要跑，錯誤要隔離，仿照 `run_daily.py` 裡各步驟都包 try/except 的做法）。
- `_sync_report_to_todos()`：把 Claude 回報裡的「待辦項目」清單，用現有 `POST /api/todos`（或直接呼叫 `orchestrator.create_todo_from_text()`）寫進 DB，`source="claude:{project.name}"`。**需要去重**：同一個待辦項目不該每天都新增一筆——用內容 hash 或先查詢當天/該 source 是否已存在再決定 create/skip（`todos.py` 目前的 `list_todos()` 可以查 `status=pending` 來做這個判斷，但要留意目前 schema 有沒有存 project/source 的查詢介面，可能要補一個 `GET /api/todos?source=...`）。
- `_send_report_to_telegram()`：組一則訊息（開頭標明專案名稱，例如 `📋 [GenAI News] 每日進度確認`），呼叫 telegram bot 現有的送訊息方法送出。**這則訊息的 `message_id` 要能之後被回覆比對到是哪個專案**——最簡單的做法是把專案 slug 塞進訊息文字裡（例如 hashtag `#genai-news`），不用依賴 Telegram 的 reply chain 也能比對，見 3.4。

### 3.3 Prompt 樣板

```
你正在檢查「{project.label}」這個專案的每日進度。這是唯讀檢查，不要修改任何檔案、不要執行任何會改變狀態的指令。

請做以下事：
1. 讀 {project.todo_source}（如果存在）跟最近的 git log，了解目前有哪些還沒做完的事、有沒有新發現的問題。
2. 用繁體中文整理成適合直接發 Telegram 的摘要（3-8 條，每條一行，不需要的細節不要寫）。
3. 最後另外輸出一個 fenced ```json 區塊，格式如下，列出摘要裡值得放進待辦清單追蹤的項目（如果沒有就給空陣列，不要硬湊）：
{
  "pending_items": [
    {"content": "一句話描述這件事要做什麼", "due_date": "YYYY-MM-DD 或 null"}
  ]
}
```

呼叫端解析輸出時：JSON 區塊之前的文字整段當作 Telegram 訊息內容；```json 區塊用正規表達式抓出來 parse，餵給 `_sync_report_to_todos()`。

### 3.4 Telegram 「回覆確認」路由（`backend/bot/telegram_bot.py` 新增）

- 新增一個訊息 handler（非 command，監聽一般文字訊息），檢查 `update.message.text` 或它 `reply_to_message.text` 裡有沒有 `#<project-slug>` hashtag：
  - 有 → 判斷是哪個專案，記下使用者這句話的內容（例如「好，去做」或更明確的指示）。
  - 沒有、又不是在回覆任何已知的每日報告 → 照現有邏輯處理（一般 ingest 或問使用者是指哪個專案）。
- 比對到專案後，用**同樣的 subprocess 呼叫模式**，但這次：
  - `cwd` 還是該專案的 `repo_path`。
  - prompt 改成「使用者確認要處理以下事項：{使用者這句話原文 / 或今天報告裡的待辦清單}，請實際執行。」
  - **這次才可以視情況帶執行權限**（例如允許寫檔、跑指令），但仍建議維持 Claude Code 預設的互動式權限確認行為，除非使用者之後明確要求要能無人值守執行——目前的決策是「使用者確認後才做」，不代表「使用者確認後就可以完全不受限亂做」，這兩件事要分開看。
  - 執行完的結果一樣發回 Telegram（同一個 hashtag，方便使用者知道是哪個專案的後續）。

## 4. 錯誤處理 / 韌性

- Claude CLI 不存在、逾時、非零 exit code → 都要被單獨 catch，不能讓整個 `run_daily_project_checkins()` 因為某一個專案失敗就中斷其他專案；每個專案的例外都要各自記 log + 送一則簡短失敗通知。
- 每個專案一次呼叫（sequential 或加簡單並行都可以，但**不要在同一時間對同一個專案重複跑**——可以用 job id 或簡單 in-memory lock 防止同一天重複觸發，尤其如果之後又加了手動觸發的 API）。
- 這個 process 若重啟，`MemoryJobStore`（沒有持久化）會遺失當天是否已經跑過的狀態——如果需要「同一天不要重複跑兩次」的保證,要另外记录（例如寫一個本地 state 檔或 DB flag，仿照 `GenAI_News` 專案裡 `scraper/state/*.json` 的做法)。

## 5. 待決事項（實作前建議跟使用者確認）

1. **每天觸發時間**：跟現有 08:00 的 `daily_digest` 錯開多久比較好？（例如 08:30）需要使用者決定。
2. **`projects.yaml` 的正式清單**：目前先放 `genai-news` 跟這個 Assistant 自己兩筆當範例，實際要追蹤哪些專案、`todo_source` 該指向哪個檔案，需要使用者確認。
3. **todos schema 是否要加 `project`/`source` 的查詢欄位**：如果 `backend/knowledge` 目前的 todo 資料表沒有方便依 source 查詢/去重的欄位，可能需要一個小 migration。
4. **Claude Code CLI 的呼叫方式**：現在的 headless 用法用 `claude -p "..."`，實際旗標（`--output-format`、逾時、是否需要 `--permission-mode` 相關設定）要在實作時對照當時安裝的 Claude Code 版本文件確認一次，這份文件裡的旗標名稱僅供參考方向。
5. **確認執行那一步的權限邊界**：3.4 提到「使用者確認後才執行」跟「執行時要不要繞過互動確認」是兩個獨立問題，建議實作前跟使用者再次明確拍板，避免無人值守情境下誤觸高風險操作。
