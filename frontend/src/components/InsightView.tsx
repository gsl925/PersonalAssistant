import { useState } from "react";
import { api } from "../api/client";
import type { InsightPreview } from "../api/types";

export default function InsightView() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<InsightPreview | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [errMsg, setErrMsg] = useState("");

  async function generate() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setLoading(true);
    setErrMsg("");
    setSaveMsg("");
    setPreview(null);
    try {
      const result = await api.previewInsight(trimmed);
      setPreview(result);
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "發生錯誤");
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!preview?.preview_id) return;
    setSaving(true);
    setSaveMsg("");
    try {
      await api.saveInsightPreview(preview.preview_id);
      setSaveMsg("✓ 已收藏至知識庫");
      setPreview(null);
      setUrl("");
    } catch (err) {
      setSaveMsg(err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤");
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    setPreview(null);
    setSaveMsg("");
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        貼上文章或影片連結，先看作者真正想傳達的核心觀點，覺得值得留才收藏——不會自動存進知識庫。
      </p>
      <div className="filter-bar">
        <input
          type="text"
          placeholder="貼上連結，例如 https://example.com/article"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") generate();
          }}
          style={{ flex: 1 }}
        />
        <button className="primary" onClick={generate} disabled={loading || !url.trim()}>
          {loading ? "分析中…" : "產生洞察"}
        </button>
      </div>
      {errMsg && (
        <p className="muted" style={{ fontSize: 12, color: "var(--danger, #d33)" }}>
          ✗ {errMsg}
        </p>
      )}

      {preview && preview.status === "ok" && (
        <div className="card" style={{ marginTop: 14 }}>
          {preview.title && (
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>📌 {preview.title}</div>
          )}
          <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>💡 {preview.insight}</p>
          <div style={{ marginTop: 10 }}>
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? "收藏中…" : "💾 收藏"}
            </button>
            <button onClick={discard} disabled={saving} style={{ marginLeft: 6 }}>
              不用了
            </button>
          </div>
        </div>
      )}

      {saveMsg && (
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          {saveMsg}
        </p>
      )}
    </div>
  );
}
