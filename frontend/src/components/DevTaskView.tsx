import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { OllamaModel, ToolOut } from "../api/types";

const TASK_TYPE_OPTIONS = ["彙整報表", "log 解析計算數值", "修改既有工具", "建立自動化腳本", "其他"];

const INPUT_SOURCE_OPTIONS = [
  "單一指定檔案",
  "整個資料夾（可能多層）",
  "執行一個指令產生（例如跑測試程式抓 stdout）",
  "讀取別的程式已產出的 log/result",
];
const FILE_FILTER_OPTIONS = ["依副檔名", "依檔名關鍵字/pattern", "依檔案內容關鍵字", "不篩選，全都要"];
const FOLDER_DEPTH_OPTIONS = ["層級固定已知", "層級不固定"];

const EXTRACTION_METHOD_OPTIONS = ["固定欄位/行號", "關鍵字定位", "正規表達式", "講不清楚，用範例示範"];
const CALC_METHOD_OPTIONS = ["原始值直接複製，不計算", "需要換算（加總/平均/單位轉換…）", "需要比對門檻判斷 PASS/FAIL"];
const EXCEPTION_HANDLING_OPTIONS = [
  "格式不一致時容錯跳過，不中斷",
  "格式不一致時中斷並回報",
  "缺資料時用預設值/留空",
  "缺資料時視為失敗",
];
const COMPARISON_SCOPE_OPTIONS = ["單一檔案/單筆分析", "跨多個檔案比較（例如多個 SN 疊圖比較趨勢）", "跨多次執行比較（同一個 SN 的歷史趨勢）"];

const OUTPUT_FORMAT_OPTIONS = [
  "CSV",
  "Excel",
  "JSON",
  "純文字報告",
  "圖表（折線圖/圖片）",
  "執行檔本體（.bat/.cmd/.exe）",
  "原始腳本（不打包）",
];
const COMPLETION_REPORT_OPTIONS = ["獨立 result 檔案", "process exit code / errorlevel"];
const RESULT_FORMAT_OPTIONS = ["JSON", "CSV", "TXT"];

function CheckboxGroup({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  function toggle(opt: string) {
    onChange(selected.includes(opt) ? selected.filter((o) => o !== opt) : [...selected, opt]);
  }
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>{label}</label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 14px" }}>
        {options.map((opt) => (
          <label key={opt} style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={selected.includes(opt)} onChange={() => toggle(opt)} />
            {opt}
          </label>
        ))}
      </div>
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

export default function DevTaskView() {
  const [tools, setTools] = useState<ToolOut[]>([]);
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [localModel, setLocalModel] = useState("");
  const [description, setDescription] = useState("");
  const [referencePath, setReferencePath] = useState("");
  const [targetTool, setTargetTool] = useState("");
  const [newToolName, setNewToolName] = useState("");
  const [notify, setNotify] = useState<"default" | "none">("default");

  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [attachmentPath, setAttachmentPath] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const [taskType, setTaskType] = useState("");
  const [exampleInput, setExampleInput] = useState("");
  const [exampleOutput, setExampleOutput] = useState("");

  const [inputSource, setInputSource] = useState<string[]>([]);
  const [fileFilter, setFileFilter] = useState<string[]>([]);
  const [filterDetail, setFilterDetail] = useState("");
  const [folderDepth, setFolderDepth] = useState("");

  const [extractionMethod, setExtractionMethod] = useState<string[]>([]);
  const [calcMethod, setCalcMethod] = useState<string[]>([]);
  const [exceptionHandling, setExceptionHandling] = useState<string[]>([]);
  const [comparisonScope, setComparisonScope] = useState<string[]>([]);

  const [outputFormat, setOutputFormat] = useState<string[]>([]);
  const [completionReport, setCompletionReport] = useState<string[]>([]);
  const [resultFormat, setResultFormat] = useState("");
  const [keepFullLog, setKeepFullLog] = useState(true);

  const [additionalNotes, setAdditionalNotes] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [resultMsg, setResultMsg] = useState("");

  useEffect(() => {
    api.listDevTaskTools().then((res) => setTools(res.items)).catch(() => setTools([]));
    api.getOllamaModels().then((res) => setOllamaModels(res.models)).catch(() => setOllamaModels([]));
  }, []);

  async function uploadFile(file: File) {
    setAttachmentFile(file);
    setUploading(true);
    setResultMsg("");
    try {
      const res = await api.uploadDevTaskAttachment(file);
      setAttachmentPath(res.relative_path);
    } catch (err) {
      setResultMsg(err instanceof Error ? `✗ 附件上傳失敗：${err.message}` : "✗ 附件上傳失敗");
      setAttachmentFile(null);
    } finally {
      setUploading(false);
    }
  }

  function clearAttachment() {
    setAttachmentFile(null);
    setAttachmentPath(null);
  }

  async function submit() {
    const trimmed = description.trim();
    if (!trimmed) {
      setResultMsg("✗ 請先填需求描述");
      return;
    }
    setSubmitting(true);
    setResultMsg("");
    try {
      await api.submitDevTask({
        description: trimmed,
        reference_path: referencePath.trim() || undefined,
        attachment_path: attachmentPath ?? undefined,
        target_tool: targetTool || undefined,
        new_tool_name: newToolName.trim() || undefined,
        notify,
        task_type: taskType || undefined,
        example_input: exampleInput.trim() || undefined,
        example_output: exampleOutput.trim() || undefined,
        input_source: inputSource.length ? inputSource : undefined,
        file_filter: fileFilter.length ? fileFilter : undefined,
        filter_detail: filterDetail.trim() || undefined,
        folder_depth: folderDepth || undefined,
        extraction_method: extractionMethod.length ? extractionMethod : undefined,
        calc_method: calcMethod.length ? calcMethod : undefined,
        exception_handling: exceptionHandling.length ? exceptionHandling : undefined,
        comparison_scope: comparisonScope.length ? comparisonScope : undefined,
        output_format: outputFormat.length ? outputFormat : undefined,
        completion_report: completionReport.length ? completionReport : undefined,
        result_format: resultFormat || undefined,
        keep_full_log: keepFullLog,
        additional_notes: additionalNotes.trim() || undefined,
        local_model: localModel || undefined,
      });
      setResultMsg("✓ 已送出，寫入 factory-tools 的「📮 你的指示」，下次開互動 session 或巡邏時會處理。");
      setDescription("");
      setReferencePath("");
      setTargetTool("");
      setNewToolName("");
      setNotify("default");
      setTaskType("");
      setExampleInput("");
      setExampleOutput("");
      setInputSource([]);
      setFileFilter([]);
      setFilterDetail("");
      setFolderDepth("");
      setExtractionMethod([]);
      setCalcMethod([]);
      setExceptionHandling([]);
      setComparisonScope([]);
      setOutputFormat([]);
      setCompletionReport([]);
      setResultFormat("");
      setKeepFullLog(true);
      setAdditionalNotes("");
      clearAttachment();
    } catch (err) {
      setResultMsg(err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        這裡只是「開場」——送出後會寫進 factory-tools 的 📮 你的指示，實際開發還是要開互動 session 或等巡邏處理，不是即時聊天室。下面的選項沒勾就代表不需要，盡量用選的，講不清楚才用文字欄位。
      </p>

      <SectionCard title="🛠️ 新開發任務">
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>需求描述</label>
          <textarea
            rows={4}
            placeholder="描述想要的功能或改動…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ width: "100%", resize: "vertical" }}
          />
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>任務類型（選填，只影響提示文字）</label>
          <select value={taskType} onChange={(e) => setTaskType(e.target.value)} style={{ width: "100%" }}>
            <option value="">— 未指定 —</option>
            {TASK_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>參考路徑（選填）</label>
          <input
            type="text"
            placeholder="例如既有範例程式碼或資料的路徑"
            value={referencePath}
            onChange={(e) => setReferencePath(e.target.value)}
            style={{ width: "100%" }}
          />
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>附件（選填）</label>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const file = e.dataTransfer.files?.[0];
              if (file) uploadFile(file);
            }}
            style={{
              border: `1px dashed ${dragOver ? "var(--accent, #4a9eff)" : "var(--border, #444)"}`,
              borderRadius: 6,
              padding: 14,
              textAlign: "center",
              fontSize: 12,
            }}
          >
            {attachmentFile ? (
              <div>
                📎 {attachmentFile.name}{" "}
                {uploading ? "（上傳中…）" : attachmentPath ? "（已上傳）" : ""}
                <button style={{ marginLeft: 8 }} onClick={clearAttachment}>
                  移除
                </button>
              </div>
            ) : (
              <label style={{ cursor: "pointer" }}>
                拖曳檔案到這裡，或
                <input
                  type="file"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadFile(file);
                  }}
                />
                <span style={{ textDecoration: "underline", marginLeft: 4 }}>點此選擇檔案</span>
              </label>
            )}
          </div>
        </div>

        <div className="filter-bar" style={{ marginBottom: 10 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>目標工具</label>
            <select
              value={targetTool}
              onChange={(e) => setTargetTool(e.target.value)}
              style={{ width: "100%" }}
            >
              <option value="">— 未指定，交給分類判斷 —</option>
              {tools.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.display_name}
                </option>
              ))}
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              或新工具名稱（未選現有工具時）
            </label>
            <input
              type="text"
              placeholder="例如：log_checker_b"
              value={newToolName}
              onChange={(e) => setNewToolName(e.target.value)}
              disabled={!!targetTool}
              style={{ width: "100%" }}
            />
          </div>
        </div>

        <div style={{ marginBottom: 0 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
            本次使用的 local 模型（測效能用，留空 = 預設 qwen3-coder:30b）
          </label>
          <select value={localModel} onChange={(e) => setLocalModel(e.target.value)} style={{ width: "100%" }}>
            <option value="">— 預設 —</option>
            {ollamaModels.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
      </SectionCard>

      <SectionCard title="📎 範例配對（最強的溝通方式——講不清楚的邏輯，示範一次比描述準確）">
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>範例輸入 / 現況</label>
          <textarea
            rows={3}
            placeholder="貼一段真實 log 文字，或彙整類的一列真實原始資料…"
            value={exampleInput}
            onChange={(e) => setExampleInput(e.target.value)}
            style={{ width: "100%", resize: "vertical" }}
          />
        </div>
        <div style={{ marginBottom: 0 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>範例輸出 / 期望結果</label>
          <textarea
            rows={3}
            placeholder="這段輸入應該被解析/彙整出的具體數值或格式…"
            value={exampleOutput}
            onChange={(e) => setExampleOutput(e.target.value)}
            style={{ width: "100%", resize: "vertical" }}
          />
        </div>
      </SectionCard>

      <SectionCard title="📥 INPUT">
        <CheckboxGroup label="來源型態" options={INPUT_SOURCE_OPTIONS} selected={inputSource} onChange={setInputSource} />
        <CheckboxGroup label="檔案篩選" options={FILE_FILTER_OPTIONS} selected={fileFilter} onChange={setFileFilter} />
        {fileFilter.some((f) => f !== "不篩選，全都要") && fileFilter.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>篩選細節（副檔名/關鍵字內容）</label>
            <input
              type="text"
              placeholder="例如：.csv，或關鍵字「Result」"
              value={filterDetail}
              onChange={(e) => setFilterDetail(e.target.value)}
              style={{ width: "100%" }}
            />
          </div>
        )}
        <div style={{ marginBottom: 0 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>資料夾層級</label>
          <select value={folderDepth} onChange={(e) => setFolderDepth(e.target.value)} style={{ width: "100%" }}>
            <option value="">— 未指定 —</option>
            {FOLDER_DEPTH_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
      </SectionCard>

      <SectionCard title="🧩 邏輯">
        <CheckboxGroup
          label="抓取方式"
          options={EXTRACTION_METHOD_OPTIONS}
          selected={extractionMethod}
          onChange={setExtractionMethod}
        />
        <CheckboxGroup label="判斷/計算" options={CALC_METHOD_OPTIONS} selected={calcMethod} onChange={setCalcMethod} />
        <CheckboxGroup
          label="例外狀況處理"
          options={EXCEPTION_HANDLING_OPTIONS}
          selected={exceptionHandling}
          onChange={setExceptionHandling}
        />
        <CheckboxGroup
          label="比較範圍（沒勾 = 各自獨立分析，不用比較）"
          options={COMPARISON_SCOPE_OPTIONS}
          selected={comparisonScope}
          onChange={setComparisonScope}
        />
      </SectionCard>

      <SectionCard title="📤 OUTPUT">
        <CheckboxGroup label="交付格式" options={OUTPUT_FORMAT_OPTIONS} selected={outputFormat} onChange={setOutputFormat} />
        <CheckboxGroup
          label="完成狀態回報"
          options={COMPLETION_REPORT_OPTIONS}
          selected={completionReport}
          onChange={setCompletionReport}
        />
        {completionReport.includes("獨立 result 檔案") && (
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>result 檔案格式</label>
            <select value={resultFormat} onChange={(e) => setResultFormat(e.target.value)} style={{ width: "100%" }}>
              <option value="">— 未指定 —</option>
              {RESULT_FORMAT_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
        )}
        <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4, marginBottom: 0 }}>
          <input type="checkbox" checked={keepFullLog} onChange={(e) => setKeepFullLog(e.target.checked)} />
          保留完整執行過程 log（預設開啟——出問題時要能直接貼給人看，取消才會改成只在出錯時保留）
        </label>
      </SectionCard>

      <SectionCard title="✍️ 補充說明（選項涵蓋不到的細節，其他都用選的）">
        <textarea
          rows={2}
          placeholder="任何上面選項表達不到的補充…"
          value={additionalNotes}
          onChange={(e) => setAdditionalNotes(e.target.value)}
          style={{ width: "100%", resize: "vertical" }}
        />
      </SectionCard>

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 4 }}>結果通知方式</label>
          <select
            value={notify}
            onChange={(e) => setNotify(e.target.value as "default" | "none")}
            style={{ width: "100%" }}
          >
            <option value="default">預設（Telegram）</option>
            <option value="none">不需要通知我</option>
          </select>
        </div>

        <button className="primary" onClick={submit} disabled={submitting || uploading}>
          {submitting ? "送出中…" : "送出"}
        </button>

        {resultMsg && (
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            {resultMsg}
          </p>
        )}
      </div>
    </div>
  );
}
