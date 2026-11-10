# 本機 LLM 伺服器：llama.cpp + llama-swap

取代 Ollama 的免安裝方案。全部是解壓縮即用的 zip，沒有安裝程式、不會註冊到 Windows。

| 檔案 | 用途 |
|---|---|
| `download_binaries.ps1` | 下載 llama.cpp（CUDA 版）與 llama-swap 到 `bin/`（不進版控） |
| `link_ollama_models.ps1` | 把 Ollama 已下載的模型用硬連結接進共用資料夾（不佔空間） |
| `download_models.ps1` | 從 Hugging Face 下載 GGUF 模型 |
| `llama-swap.yaml` | 模型清單與載入規則；模型名稱與 `backend/config.py` 的 tier 一致 |
| `start_llama.bat` | 啟動 llama-swap，監聽 `127.0.0.1:8090`（`start_all.bat` 會自動帶起） |

## 使用步驟

```powershell
# 1. 執行檔（已固定版本；RTX 50 系列用 CUDA 13.5 版）
powershell -ExecutionPolicy Bypass -File tools\llama\download_binaries.ps1
tools\llama\bin\llama.cpp\llama-server.exe --list-devices   # 應該看到 RTX 5080

# 2. 模型：已在 Ollama 的先連結（免下載），其餘才下載
powershell -ExecutionPolicy Bypass -File tools\llama\link_ollama_models.ps1 -OllamaDir D:\OllamaModels
powershell -ExecutionPolicy Bypass -File tools\llama\download_models.ps1 -Only gemma4:26b,qwen3-vl:8b

# 3. 啟動
tools\llama\start_llama.bat
```

## 模型放在共用資料夾

模型檔很大，放在專案外面，路徑寫在這個專案的 `.env`（不進版控），程式碼裡不寫死：

```
LLM_MODELS_DIR=D:\llamaModels
```

- `download_models.ps1`、`link_ollama_models.ps1`、`start_llama.bat` 都會讀它。優先順序：`-Dest` 參數 > 環境變數 `LLM_MODELS_DIR` > `.env` > 專案內的 `data\llm_models\`。
- 換機器或複製專案時，只要改那一行。其他專案各自決定自己的模型路徑，不受影響；GGUF 是通用格式，要共用時指向同一個資料夾即可。

## 沿用 Ollama 已下載的模型

Ollama 的模型檔本身就是 GGUF（存在 `blobs\sha256-…`）。2026-11-10 實測用 llama-server 直接載入：

| 模型 | 結果 |
|---|---|
| `qwen3:8b`、`deepseek-r1:14b`、`bge-m3`、`minicpm-v:8b`（含 projector） | ✅ 可載入，`link_ollama_models.ps1` 會處理 |
| `qwen3-vl:8b`、`gemma4:26b` | ❌ 載入失敗：Ollama 新引擎用自己的張量格式，必須從 Hugging Face 下載 |

`link_ollama_models.ps1` 建立的是**硬連結**，不複製檔案、不佔額外空間、不會改動 Ollama 資料夾，之後 Ollama 刪掉模型也不影響這邊（資料仍由連結保留）。限制：Ollama 資料夾與共用資料夾必須在**同一個磁碟機**。這也讓 `bge-m3` 與現有向量庫用的是同一個檔案。

只需要從 Hugging Face 下載 gemma4:26b（約 17 GB）與 qwen3-vl:8b（約 6.2 GB），共約 23 GB。

## 切換引擎

`.env` 用 `LOCAL_LLM_ENGINE` 明確選擇，改完重啟 backend 即生效。**預設是 `llama`，Ollama 不會是沒設定時的退路**，要用必須明講：

```
LOCAL_LLM_ENGINE=llama     # 預設：llama.cpp（llama-swap，http://localhost:8090）
LOCAL_LLM_ENGINE=ollama    # 改用 Ollama（http://localhost:11434，位址由 OLLAMA_LOCAL_BASE_URL 決定）
```

- 位址預設值在 `LLAMA_SWAP_BASE_URL` / `OLLAMA_LOCAL_BASE_URL`；要指到別台機器才用 `LOCAL_LLM_BASE_URL` 覆寫，此時 `LOCAL_LLM_ENGINE` 要跟它實際是哪種引擎一致。
- 設定頁的 tier 清單不用動，因為模型名稱與 Ollama 一樣。
- dev_agent 會依引擎切換傳輸格式：llama 走 OpenAI 相容端點，Ollama 走原生 `/api/chat`（Ollama 的 `/v1` 會弄壞 qwen3-coder 的工具呼叫）。
- 兩邊同時載大模型會搶顯存；切換前先停掉其中一邊（llama-swap：`curl http://127.0.0.1:8090/unload`）。

## 模型對照表

| tier 用的名稱 | GGUF 來源 | 檔案 | 大小 | 備註 |
|---|---|---|---|---|
| `qwen3:8b` | `Qwen/Qwen3-8B-GGUF` | `Qwen3-8B-Q4_K_M.gguf` | 5.03 GB | 官方版本 |
| `deepseek-r1:14b` | `bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF` | `…-Q4_K_M.gguf` | 8.99 GB | Ollama 的 14b 就是這個蒸餾版 |
| `gemma4:26b` | `unsloth/gemma-4-26B-A4B-it-GGUF` | `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf` | 16.95 GB | MoE（約 4B 啟用）。比 16 GB VRAM 大，由 `--fit` 自動把部分 expert 放到記憶體；Unsloth 曾更新過檔案，要用最新版 |
| `qwen3-vl:8b` | `Qwen/Qwen3-VL-8B-Instruct-GGUF` | `Qwen3VL-8B-Instruct-Q4_K_M.gguf` + `mmproj-…-F16.gguf` | 5.03 + 1.16 GB | 視覺模型必須搭配 mmproj |
| `minicpm-v:8b` | `openbmb/MiniCPM-V-2_6-gguf` | `ggml-model-Q4_K_M.gguf` + `mmproj-model-f16.gguf`（或從 Ollama 連結） | 4.68 + 1.04 GB | Ollama 的 `minicpm-v:8b` 是 2.6 版，所以選 2.6 以維持 OCR 測試結果；4.5 版較新，換之前要重測 |
| `qwen3-coder:30b` | `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` | 18.56 GB | dev_agent 專用（工具呼叫）。MoE 約 3B 啟用；llama-server 需 `--jinja` 才會回結構化 `tool_calls` |
| `bge-m3` | `lm-kit/bge-m3-gguf`（社群轉檔） | `bge-m3-F16.gguf` | 1.16 GB | 沒有官方 GGUF。用 F16 是為了貼近 Ollama 版，**切換前必須比對向量**（見下） |

沒有遷移的：

- `llava:7b`：vision tier 的第二順位。很舊，沒有對應下載；切換 vision tier 時建議改成 `minicpm-v:8b` 當 fallback。
- `gpt-oss:120b-cloud`：雲端模型，本機沒有對應物，已從預設 tier 移除。

## 切換前要驗證的事

1. **embedding 向量要和 Ollama 一致。** ✅ 2026-11-10 已驗證：6 段文字（1~1399 字，中英混合）兩邊的向量維度都是 1024、都已正規化，餘弦相似度最低 0.999994，**不需要重建向量庫**。
2. **thinking 輸出格式。** llama.cpp 預設會把思考內容拆到 `reasoning_content`，`content` 保持乾淨；確認 `insight.py`、`video_digest.py` 等後處理沒有仰賴 `<think>` 標籤。
3. **gemma4:26b 的速度與品質。** 用 2026-10-05 的 KB 測試題對比（Ollama 當時約 137 秒）。

## 注意事項

- **VRAM 共用**：llama-swap 閒置 10 分鐘會卸載模型（`globalTTL`），bge-m3 常駐。Ollama 也會把模型留在 VRAM 一段時間，兩邊同時用大模型可能會互相擠爆。
- **更新**：重新執行 `download_binaries.ps1 -LlamaCppTag <新版>`。llama.cpp 每天會發很多個 build，不需要追最新。
- llama-swap 設定檔語法驗證：`tools\llama\bin\llama-swap\llama-swap.exe -config tools\llama\llama-swap.yaml -validate`
