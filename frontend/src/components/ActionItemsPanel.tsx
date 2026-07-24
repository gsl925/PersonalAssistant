import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ActionItem } from "../api/types";

export default function ActionItemsPanel() {
  const [items, setItems] = useState<ActionItem[]>([]);
  const [dueBefore, setDueBefore] = useState("");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    api
      .listActionItems(dueBefore || undefined)
      .then((res) => setItems(res.items))
      .finally(() => setLoading(false));
  }

  useEffect(load, [dueBefore]);

  const sorted = [...items].sort((a, b) => (a.due_date ?? "9999-99-99").localeCompare(b.due_date ?? "9999-99-99"));

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        彙整所有已完成會議文件的 action_items。資料模型沒有「已完成」旗標，所有項目一律列出。
      </p>
      <div className="filter-bar">
        <label className="muted" style={{ fontSize: 12, alignSelf: "center" }}>
          期限早於：
        </label>
        <input type="date" value={dueBefore} onChange={(e) => setDueBefore(e.target.value)} />
        {dueBefore && <button onClick={() => setDueBefore("")}>清除</button>}
      </div>

      {loading ? (
        <p className="muted">載入中…</p>
      ) : sorted.length === 0 ? (
        <p className="muted">目前沒有代辦事項。</p>
      ) : (
        sorted.map((item, i) => (
          <div className="card" key={i} style={{ marginBottom: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{item.task}</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              {item.due_date && <>📅 {item.due_date} </>}
              {item.owner && <>· @{item.owner} </>}
            </div>
            {item.source_title && (
              <div className="muted" style={{ fontSize: 12 }}>
                來自：{item.source_title}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
