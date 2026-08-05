import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Document, DocumentContent } from "../api/types";
import StatusPill from "./StatusPill";

export default function DocumentDetail({
  doc,
  onClose,
  onRetried,
}: {
  doc: Document;
  onClose: () => void;
  onRetried?: () => void;
}) {
  const [content, setContent] = useState<DocumentContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [note, setNote] = useState(doc.user_note ?? "");
  const [savingNote, setSavingNote] = useState(false);
  const [noteMsg, setNoteMsg] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getDocumentContent(doc.id)
      .then((c) => {
        if (!cancelled) setContent(c);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [doc.id]);

  async function handleRetry() {
    setRetrying(true);
    try {
      await api.retryDocument(doc.id);
      onRetried?.();
    } finally {
      setRetrying(false);
    }
  }

  async function handleSaveNote() {
    setSavingNote(true);
    setNoteMsg("");
    try {
      await api.setUserNote(doc.id, note);
      setNoteMsg("✓ 已儲存");
      onRetried?.();
    } catch (err) {
      setNoteMsg(err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤");
    } finally {
      setSavingNote(false);
    }
  }

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <h2 style={{ margin: "0 0 4px", fontSize: 18 }}>{doc.title || "（尚無標題）"}</h2>
          <button onClick={onClose}>關閉</button>
        </div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          {doc.source_type} · {doc.category ?? "未分類"} · <StatusPill status={doc.processing_status} />{" "}
          · agent: {doc.agent_used ?? "—"}
        </div>

        {doc.source_url && (
          <div style={{ marginBottom: 8 }}>
            <a href={doc.source_url} target="_blank" rel="noreferrer">
              {doc.source_url}
            </a>
          </div>
        )}

        {doc.summary && (
          <>
            <h3 style={{ fontSize: 13, margin: "10px 0 4px" }}>摘要</h3>
            <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{doc.summary}</p>
          </>
        )}

        {doc.ai_insight && (
          <>
            <h3 style={{ fontSize: 13, margin: "10px 0 4px" }}>💡 核心洞察</h3>
            <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{doc.ai_insight}</p>
          </>
        )}

        <div style={{ margin: "8px 0" }}>
          {doc.tags.map((t) => (
            <span className="tag" key={t.keyword}>
              {t.keyword}
            </span>
          ))}
        </div>

        {doc.processing_status === "failed" && (
          <button onClick={handleRetry} disabled={retrying} style={{ marginBottom: 10 }}>
            {retrying ? "重試中…" : "重新處理"}
          </button>
        )}

        <h3 style={{ fontSize: 13, margin: "10px 0 4px" }}>📝 我的洞察</h3>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="寫下你自己對這篇內容的看法或註記…"
          style={{
            width: "100%",
            minHeight: 60,
            fontSize: 13,
            padding: 8,
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "var(--bg)",
            color: "inherit",
            resize: "vertical",
          }}
        />
        <div style={{ marginTop: 6, marginBottom: 10 }}>
          <button onClick={handleSaveNote} disabled={savingNote}>
            {savingNote ? "儲存中…" : "儲存我的洞察"}
          </button>
          {noteMsg && (
            <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
              {noteMsg}
            </span>
          )}
        </div>

        {content?.corrected_content && (
          <>
            <h3 style={{ fontSize: 13, margin: "10px 0 4px" }}>
              LLM 校正版{" "}
              <span className="muted" style={{ fontWeight: 400, fontSize: 11 }}>
                （實驗性，可能改錯，請對照原始內容核實）
              </span>
            </h3>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                fontSize: 12.5,
                lineHeight: 1.6,
                maxHeight: 300,
                overflowY: "auto",
                background: "var(--bg)",
                padding: 10,
                borderRadius: 6,
                border: "1px solid var(--border)",
              }}
            >
              {content.corrected_content}
            </pre>
          </>
        )}

        <h3 style={{ fontSize: 13, margin: "10px 0 4px" }}>原始內容</h3>
        {loading ? (
          <p className="muted">載入中…</p>
        ) : content?.original_content ? (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: 12.5,
              lineHeight: 1.6,
              maxHeight: 300,
              overflowY: "auto",
              background: "var(--bg)",
              padding: 10,
              borderRadius: 6,
              border: "1px solid var(--border)",
            }}
          >
            {content.original_content}
          </pre>
        ) : (
          <p className="muted">（無原始內容）</p>
        )}

        <div style={{ marginTop: 12 }}>
          <Link to={`/mindmap?doc=${doc.id}`}>在 Mindmap 中查看關聯 →</Link>
        </div>
      </div>
    </div>
  );
}
