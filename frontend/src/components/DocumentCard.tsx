import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Document } from "../api/types";
import ConfirmDeleteButton from "./ConfirmDeleteButton";
import StatusPill from "./StatusPill";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("zh-TW", { dateStyle: "medium", timeStyle: "short" });
}

export default function DocumentCard({
  doc,
  onSelect,
  onDeleted,
}: {
  doc: Document;
  onSelect?: (doc: Document) => void;
  onDeleted?: (docId: string) => void;
}) {
  async function handleDelete() {
    try {
      await api.deleteDocument(doc.id);
      onDeleted?.(doc.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "刪除時發生錯誤");
    }
  }

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <button
          onClick={() => onSelect?.(doc)}
          style={{
            border: "none",
            background: "none",
            padding: 0,
            textAlign: "left",
            fontWeight: 600,
            fontSize: 14,
            color: "var(--text)",
            cursor: onSelect ? "pointer" : "default",
          }}
        >
          {doc.title || "（尚無標題）"}
        </button>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
          <StatusPill status={doc.processing_status} />
          <ConfirmDeleteButton onConfirm={handleDelete} />
        </div>
      </div>
      <div className="muted" style={{ fontSize: 12, margin: "4px 0" }}>
        {doc.source_type} · {doc.category ?? "未分類"} · {formatDate(doc.created_at)}
      </div>
      {doc.summary && (
        <p style={{ margin: "6px 0", fontSize: 13, lineHeight: 1.5 }}>
          {doc.summary.length > 200 ? doc.summary.slice(0, 200) + "…" : doc.summary}
        </p>
      )}
      <div>
        {doc.tags.map((t) => (
          <span className="tag" key={t.keyword}>
            {t.keyword}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 6 }}>
        <Link to={`/mindmap?doc=${doc.id}`} style={{ fontSize: 12 }}>
          查看關聯 →
        </Link>
      </div>
    </div>
  );
}
