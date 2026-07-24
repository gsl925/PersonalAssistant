import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SearchResult } from "../api/types";

export default function SearchBox() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    const handle = setTimeout(() => {
      api
        .search(q.trim(), 8)
        .then((res) => {
          setResults(res.results);
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 300);
    return () => clearTimeout(handle);
  }, [q]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div ref={boxRef} style={{ position: "relative", flex: 1, maxWidth: 420 }}>
      <input
        type="search"
        placeholder="語意搜尋知識庫…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        style={{ width: "100%" }}
      />
      {open && results.length > 0 && (
        <div
          className="card"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 40,
            maxHeight: 360,
            overflowY: "auto",
            padding: 6,
          }}
        >
          {results.map((r) => {
            const title = (r.payload.title as string) || "（尚無標題）";
            const summary = (r.payload.summary as string) || "";
            const category = (r.payload.category as string) || "";
            return (
              <button
                key={r.id}
                onClick={() => {
                  setOpen(false);
                  navigate(`/mindmap?doc=${r.id}`);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  border: "none",
                  background: "none",
                  padding: "8px 8px",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 13 }}>{title}</div>
                <div className="muted" style={{ fontSize: 11 }}>
                  {category} · score {r.score.toFixed(3)}
                </div>
                {summary && (
                  <div style={{ fontSize: 12, marginTop: 2 }}>
                    {summary.length > 120 ? summary.slice(0, 120) + "…" : summary}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
