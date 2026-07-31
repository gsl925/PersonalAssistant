import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Document, Project } from "../api/types";
import ConfirmDeleteButton from "./ConfirmDeleteButton";
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

  async function removeProject(p: Project) {
    try {
      await api.deleteProject(p.id);
      setProjects((prev) => prev.filter((x) => x.id !== p.id));
      if (selected === p.id) setSelected(ALL_DOCS);
    } catch (err) {
      alert(err instanceof Error ? err.message : "刪除時發生錯誤");
    }
  }

  function loadDocs() {
    setLoading(true);
    const req =
      selected === ALL_DOCS
        ? api.listDocuments({ limit: 100 })
        : api.listProjectDocuments(selected, { limit: 100 });
    req
      // Chat Q&A lives on its own "問答記錄" tab, not mixed into general notes.
      .then((res) => setDocs(
        selected === ALL_DOCS ? res.items.filter((d) => d.source_type !== "chat") : res.items
      ))
      .finally(() => setLoading(false));
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
          <div key={p.id} style={{ display: "flex", gap: 4, marginBottom: 6 }}>
            <button
              onClick={() => setSelected(p.id)}
              className={selected === p.id ? "primary" : undefined}
              style={{ display: "block", flex: 1, textAlign: "left", minWidth: 0 }}
            >
              {p.name}
            </button>
            <ConfirmDeleteButton
              onConfirm={() => removeProject(p)}
              title="刪除此專案標籤"
              style={{ flexShrink: 0 }}
            />
          </div>
        ))}
        {projects.length === 0 && <p className="muted" style={{ fontSize: 12 }}>尚無專案</p>}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {loading ? (
          <p className="muted">載入中…</p>
        ) : docs.length === 0 ? (
          <p className="muted">這裡沒有文件。</p>
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
