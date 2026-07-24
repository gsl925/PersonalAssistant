import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Document, Project } from "../api/types";
import DocumentCard from "./DocumentCard";
import DocumentDetail from "./DocumentDetail";

const ALL_DOCS = "__all__";

export default function ProjectView() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<string>(ALL_DOCS);
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects);
  }, []);

  function loadDocs() {
    setLoading(true);
    const req =
      selected === ALL_DOCS
        ? api.listDocuments({ limit: 100 })
        : api.listProjectDocuments(selected, { limit: 100 });
    req.then((res) => setDocs(res.items)).finally(() => setLoading(false));
  }

  useEffect(loadDocs, [selected]);

  return (
    <div style={{ display: "flex", gap: 20, height: "100%" }}>
      <div style={{ width: 220, flexShrink: 0 }}>
        <h3 style={{ fontSize: 13, marginTop: 0 }}>專案</h3>
        <button
          onClick={() => setSelected(ALL_DOCS)}
          className={selected === ALL_DOCS ? "primary" : undefined}
          style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 6 }}
        >
          全部文件
        </button>
        {projects.map((p) => (
          <button
            key={p.id}
            onClick={() => setSelected(p.id)}
            className={selected === p.id ? "primary" : undefined}
            style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 6 }}
          >
            {p.name}
          </button>
        ))}
        {projects.length === 0 && <p className="muted" style={{ fontSize: 12 }}>尚無專案</p>}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {loading ? (
          <p className="muted">載入中…</p>
        ) : docs.length === 0 ? (
          <p className="muted">這裡沒有文件。</p>
        ) : (
          docs.map((d) => <DocumentCard key={d.id} doc={d} onSelect={setSelectedDoc} />)
        )}
      </div>

      {selectedDoc && (
        <DocumentDetail
          doc={selectedDoc}
          onClose={() => setSelectedDoc(null)}
          onRetried={() => {
            loadDocs();
            setSelectedDoc(null);
          }}
        />
      )}
    </div>
  );
}
