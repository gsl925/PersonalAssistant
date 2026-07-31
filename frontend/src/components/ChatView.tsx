import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Document } from "../api/types";
import DocumentCard from "./DocumentCard";
import DocumentDetail from "./DocumentDetail";

// Same underlying Document rows as the knowledge base (source_type="chat")
// — searchable/deletable the same way — just listed on its own tab instead
// of mixed into the general note browser. See Orchestrator.ask_claude().
export default function ChatView() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);

  function load() {
    setLoading(true);
    api
      .listDocuments({ source_type: "chat", limit: 100 })
      .then((res) => setDocs(res.items))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        透過 Telegram /ask 問過的問答記錄，跟知識庫共用同一份資料（可搜尋、可刪除），只是不跟一般筆記混在一起列。
      </p>

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
