import * as d3 from "d3";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Document, DocumentFilters, Project } from "../api/types";
import DocumentCard from "./DocumentCard";
import DocumentDetail from "./DocumentDetail";

const SOURCE_TYPES = ["doc", "note", "webclip", "meeting", "screenshot"];

export default function TimelineView() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [filters, setFilters] = useState<DocumentFilters>({ limit: 100 });
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects);
  }, []);

  function load() {
    setLoading(true);
    api
      .listTimeline(filters)
      .then((res) => setDocs(res.items))
      .finally(() => setLoading(false));
  }

  useEffect(load, [filters]);

  // Group by calendar day (docs already sorted created_at DESC by the API).
  const groups = d3.groups(docs, (d) => d3.timeFormat("%Y-%m-%d")(new Date(d.created_at)));

  return (
    <div>
      <div className="filter-bar">
        <select
          value={filters.source_type ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, source_type: e.target.value || undefined }))}
        >
          <option value="">全部類型</option>
          {SOURCE_TYPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={filters.project_id ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, project_id: e.target.value || undefined }))}
        >
          <option value="">全部專案</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="分類 (category)"
          value={filters.category ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value || undefined }))}
          style={{ width: 120 }}
        />
        <input
          type="date"
          value={filters.start_date ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, start_date: e.target.value || undefined }))}
        />
        <span className="muted" style={{ alignSelf: "center" }}>
          至
        </span>
        <input
          type="date"
          value={filters.end_date ?? ""}
          onChange={(e) => setFilters((f) => ({ ...f, end_date: e.target.value || undefined }))}
        />
      </div>

      {loading ? (
        <p className="muted">載入中…</p>
      ) : groups.length === 0 ? (
        <p className="muted">沒有符合條件的文件。</p>
      ) : (
        groups.map(([day, items]) => (
          <div key={day} style={{ marginBottom: 24 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                marginBottom: 10,
                borderBottom: "1px solid var(--border)",
                paddingBottom: 4,
              }}
            >
              {day}
            </div>
            <div style={{ paddingLeft: 12, borderLeft: "2px solid var(--border)" }}>
              {items.map((d) => (
                <DocumentCard key={d.id} doc={d} onSelect={setSelectedDoc} />
              ))}
            </div>
          </div>
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
