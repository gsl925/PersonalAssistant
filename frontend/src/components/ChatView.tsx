import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AskKnowledgeBaseResponse, Document } from "../api/types";
import DocumentCard from "./DocumentCard";
import DocumentDetail from "./DocumentDetail";

// Same underlying Document rows as the knowledge base (source_type="chat")
// — searchable/deletable the same way — just listed on its own tab instead
// of mixed into the general note browser. See Orchestrator.ask_claude().
export default function ChatView() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  const [kbQuestion, setKbQuestion] = useState("");
  const [kbIncludeCloud, setKbIncludeCloud] = useState(false);
  const [kbAsking, setKbAsking] = useState(false);
  const [kbError, setKbError] = useState<string | null>(null);
  const [kbResult, setKbResult] = useState<AskKnowledgeBaseResponse | null>(null);

  function load() {
    setLoading(true);
    api
      .listDocuments({ source_type: "chat", limit: 100 })
      .then((res) => setDocs(res.items))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleAsk() {
    const q = question.trim();
    if (!q || asking) return;
    setAsking(true);
    setAskError(null);
    try {
      await api.askChat(q);
      setQuestion("");
      load();
    } catch (err) {
      setAskError(err instanceof Error ? err.message : "發生錯誤");
    } finally {
      setAsking(false);
    }
  }

  async function handleKbAsk() {
    const q = kbQuestion.trim();
    if (!q || kbAsking) return;
    setKbAsking(true);
    setKbError(null);
    setKbResult(null);
    try {
      const res = await api.askKnowledgeBase(q, kbIncludeCloud);
      setKbResult(res);
    } catch (err) {
      setKbError(err instanceof Error ? err.message : "發生錯誤");
    } finally {
      setKbAsking(false);
    }
  }

  function renderKbAnswer(label: string, answer: AskKnowledgeBaseResponse["local"]) {
    return (
      <div style={{ flex: 1, border: "1px solid var(--border, #ddd)", borderRadius: 6, padding: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }} className="muted">
          <span>{label}{answer.model ? `（${answer.model}）` : ""}</span>
          {answer.latency_ms != null && <span>{(answer.latency_ms / 1000).toFixed(1)}s</span>}
        </div>
        {answer.error ? (
          <p style={{ fontSize: 13, color: "var(--danger, #d33)" }}>❌ {answer.error}</p>
        ) : (
          <p style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{answer.answer}</p>
        )}
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 16, borderBottom: "1px solid var(--border, #ddd)" }}>
        <h3 style={{ fontSize: 14, marginTop: 0 }}>知識庫問答</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          只根據你存進知識庫的內容回答，不會上網查。預設只問 local（Ollama，目前是 gemma4:26b），勾選下面的選項才會同時問 cloud（Claude）方便比較。不會存成問答記錄。
        </p>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <input
            type="text"
            value={kbQuestion}
            onChange={(e) => setKbQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleKbAsk();
              }
            }}
            placeholder="針對你知識庫裡的內容提問"
            disabled={kbAsking}
            style={{ flex: 1 }}
          />
          <button onClick={handleKbAsk} disabled={kbAsking || !kbQuestion.trim()}>
            {kbAsking ? "查詢中…" : "問知識庫"}
          </button>
        </div>
        <label className="muted" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4, marginBottom: 12 }}>
          <input
            type="checkbox"
            checked={kbIncludeCloud}
            onChange={(e) => setKbIncludeCloud(e.target.checked)}
            disabled={kbAsking}
          />
          同時問 Cloud（比較用，local 已經夠用的話不用勾）
        </label>
        {kbError && (
          <p className="muted" style={{ fontSize: 12, color: "var(--danger, #d33)" }}>
            ❌ {kbError}
          </p>
        )}
        {kbResult && (
          <>
            <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
              {renderKbAnswer("Local", kbResult.local)}
              {kbResult.cloud && renderKbAnswer("Cloud", kbResult.cloud)}
            </div>
            {kbResult.sources.length > 0 && (
              <div style={{ fontSize: 12 }} className="muted">
                參考來源：
                {kbResult.sources.map((s, i) => (
                  <span key={s.doc_id} style={{ marginRight: 8 }}>
                    [{i + 1}] {s.title ?? "(未命名)"}（{s.score.toFixed(2)}）
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12 }}>
        透過 Telegram /ask 問過的問答記錄，跟知識庫共用同一份資料（可搜尋、可刪除），只是不跟一般筆記混在一起列。也可以直接在這裡發起新的問答。
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleAsk();
            }
          }}
          placeholder="輸入問題，跟 /ask 一樣是單次問答，不是連續對話"
          disabled={asking}
          style={{ flex: 1 }}
        />
        <button onClick={handleAsk} disabled={asking || !question.trim()}>
          {asking ? "發問中…" : "發問"}
        </button>
      </div>
      {askError && (
        <p className="muted" style={{ fontSize: 12, color: "var(--danger, #d33)" }}>
          ❌ {askError}
        </p>
      )}

      {loading ? (
        <p className="muted">載入中…</p>
      ) : docs.length === 0 ? (
        <p className="muted">還沒有問答記錄。</p>
      ) : (
        docs.map((d) => (
          <DocumentCard
            key={d.id}
            doc={d}
            onSelect={setSelectedDoc}
            onDeleted={(id) => setDocs((prev) => prev.filter((x) => x.id !== id))}
          />
        ))
      )}

      {selectedDoc && (
        <DocumentDetail
          doc={selectedDoc}
          onClose={() => setSelectedDoc(null)}
          onRetried={() => {
            load();
            setSelectedDoc(null);
          }}
        />
      )}
    </div>
  );
}
