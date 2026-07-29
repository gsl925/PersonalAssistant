import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Todo } from "../api/types";

export default function TodosView() {
  const [items, setItems] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [snoozeMsg, setSnoozeMsg] = useState<Record<string, string>>({});

  function load() {
    setLoading(true);
    api
      .listTodos({ status: "pending" })
      .then((res) => setItems(res.items))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function addTodo() {
    const trimmed = text.trim();
    if (!trimmed) return;
    setSaving(true);
    setSaveMsg("");
    try {
      await api.createTodo(trimmed, "dashboard");
      setText("");
      setSaveMsg("✓ 已記下");
      load();
    } catch (err) {
      setSaveMsg(err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤");
    } finally {
      setSaving(false);
    }
  }

  async function updateStatus(id: string, status: string) {
    await api.updateTodoStatus(id, status);
    load();
  }

  async function snooze(id: string) {
    const res = await api.snoozeTodo(id);
    const when = res.remind_at.slice(0, 16).replace("T", " ");
    setSnoozeMsg((m) => ({ ...m, [id]: `😴 已加一筆提醒：${when}` }));
  }

  const sorted = [...items].sort((a, b) =>
    (a.due_date ?? "9999-99-99").localeCompare(b.due_date ?? "9999-99-99")
  );

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        快速記一筆代辦，AI 會自動判斷內容跟日期，時間到會透過 Telegram 提醒。
      </p>
      <div className="filter-bar">
        <input
          type="text"
          placeholder="例如：Google Cloud 認證課程，8/16~8/30 開放申請"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") addTodo();
          }}
          style={{ flex: 1 }}
        />
        <button className="primary" onClick={addTodo} disabled={saving}>
          {saving ? "新增中…" : "+ 新增代辦"}
        </button>
      </div>
      {saveMsg && (
        <p className="muted" style={{ fontSize: 12 }}>
          {saveMsg}
        </p>
      )}

      {loading ? (
        <p className="muted">載入中…</p>
      ) : sorted.length === 0 ? (
        <p className="muted">目前沒有代辦事項。</p>
      ) : (
        sorted.map((item) => (
          <div className="card" key={item.id} style={{ marginBottom: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{item.content}</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              {item.start_date && <>🗓️ {item.start_date} </>}
              {item.due_date && <>⏰ {item.due_date} </>}
              · 來源：{item.source}
            </div>
            {item.reminders && item.reminders.length > 0 && (
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                🔔 下次提醒：{item.reminders[0].remind_at.slice(0, 16).replace("T", " ")}
              </div>
            )}
            {item.source_url && (
              <div style={{ fontSize: 12, marginTop: 2 }}>
                <a href={item.source_url} target="_blank" rel="noreferrer">
                  🔗 {item.source_url}
                </a>
              </div>
            )}
            <div style={{ marginTop: 8 }}>
              <button onClick={() => updateStatus(item.id, "done")}>完成</button>
              <button onClick={() => snooze(item.id)} style={{ marginLeft: 6 }}>
                😴 延後
              </button>
              <button onClick={() => updateStatus(item.id, "cancelled")} style={{ marginLeft: 6 }}>
                取消
              </button>
            </div>
            {snoozeMsg[item.id] && (
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                {snoozeMsg[item.id]}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
