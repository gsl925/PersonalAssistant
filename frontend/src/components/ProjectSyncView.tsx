import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TrackedProjectOut } from "../api/types";
import ConfirmDeleteButton from "./ConfirmDeleteButton";

export default function ProjectSyncView() {
  const [items, setItems] = useState<TrackedProjectOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sending, setSending] = useState<Record<string, boolean>>({});
  const [msgs, setMsgs] = useState<Record<string, string>>({});
  const [newPath, setNewPath] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState("");
  const [broadcastText, setBroadcastText] = useState("");
  const [broadcasting, setBroadcasting] = useState(false);
  const [broadcastMsg, setBroadcastMsg] = useState("");

  function load() {
    setLoading(true);
    api
      .listTrackedProjects()
      .then((res) => setItems(res.items))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function send(projectName: string, key: string, text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setSending((s) => ({ ...s, [key]: true }));
    setMsgs((m) => ({ ...m, [key]: "" }));
    try {
      await api.sendProjectInstruction(projectName, trimmed);
      setDrafts((d) => ({ ...d, [key]: "" }));
      setMsgs((m) => ({ ...m, [key]: "✓ 已送出" }));
      load();
    } catch (err) {
      setMsgs((m) => ({ ...m, [key]: err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤" }));
    } finally {
      setSending((s) => ({ ...s, [key]: false }));
    }
  }

  async function broadcast() {
    const trimmed = broadcastText.trim();
    if (!trimmed) return;
    setBroadcasting(true);
    setBroadcastMsg("");
    try {
      const res = await api.broadcastInstruction(trimmed);
      const parts: string[] = [];
      if (res.succeeded.length) parts.push(`✓ 已寫入：${res.succeeded.join("、")}`);
      if (res.failed.length) parts.push(`✗ 沒有 PROGRESS.md，略過：${res.failed.join("、")}`);
      setBroadcastMsg(parts.join(" ") || "沒有追蹤中的專案。");
      setBroadcastText("");
    } catch (err) {
      setBroadcastMsg(err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤");
    } finally {
      setBroadcasting(false);
    }
  }

  async function addProject() {
    const label = newLabel.trim();
    const repoPath = newPath.trim();
    if (!label || !repoPath) return;
    setAdding(true);
    setAddMsg("");
    try {
      const res = await api.addTrackedProject(label, repoPath);
      setAddMsg(`🆕 開始設定「${res.label}」，完成後會出現在下方清單並開始同步。`);
      setNewLabel("");
      setNewPath("");
      load();
    } catch (err) {
      setAddMsg(err instanceof Error ? `✗ ${err.message}` : "✗ 發生錯誤");
    } finally {
      setAdding(false);
    }
  }

  async function remove(projectName: string) {
    try {
      await api.deleteTrackedProject(projectName);
      setItems((prev) => prev.filter((p) => p.name !== projectName));
    } catch (err) {
      alert(err instanceof Error ? err.message : "刪除時發生錯誤");
    }
  }

  if (loading) return <p className="muted">載入中…</p>;

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        目前追蹤的 Repo，跟 PROGRESS.md 郵差機制同步——這裡的回覆跟 Telegram 回覆效果完全一樣。
      </p>

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>➕ 新增追蹤專案</div>
        <div className="filter-bar" style={{ marginBottom: 6 }}>
          <input
            type="text"
            placeholder="Repo 路徑，例如 D:/_SideProject/Foo"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            style={{ flex: 1 }}
          />
          <input
            type="text"
            placeholder="名稱，例如 Foo 專案"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="primary" onClick={addProject} disabled={adding}>
            {adding ? "設定中…" : "新增"}
          </button>
        </div>
        {addMsg && <p className="muted" style={{ fontSize: 12 }}>{addMsg}</p>}
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>📢 廣播指令給所有專案</div>
        <p className="muted" style={{ fontSize: 12, marginTop: 0, marginBottom: 6 }}>
          寫進每個專案的「📮 你的指示」——純寫檔，不會觸發任何 session，各專案自己判斷什麼時候處理。
        </p>
        <div className="filter-bar" style={{ marginBottom: 6 }}>
          <input
            type="text"
            placeholder="例如：明天休息一天，不用跑排程"
            value={broadcastText}
            onChange={(e) => setBroadcastText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") broadcast();
            }}
            style={{ flex: 1 }}
          />
          <button className="primary" onClick={broadcast} disabled={broadcasting}>
            {broadcasting ? "送出中…" : "廣播"}
          </button>
        </div>
        {broadcastMsg && <p className="muted" style={{ fontSize: 12 }}>{broadcastMsg}</p>}
      </div>

      {items.map((project) => (
        <div className="card" key={project.name} style={{ marginBottom: 14 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 8,
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14 }}>
              {project.label}（#{project.name}）
            </div>
            <ConfirmDeleteButton
              onConfirm={() => remove(project.name)}
              label="🗑 刪除"
              confirmLabel="確定刪除？"
              title="停止追蹤此 Repo"
            />
          </div>

          {project.pending_items.length === 0 ? (
            <p className="muted" style={{ fontSize: 12 }}>目前沒有待決策項目。</p>
          ) : (
            project.pending_items.map((item) => {
              const key = `${project.name}:${item.number}`;
              return (
                <div key={key} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 13 }}>💬 #{item.number} {item.content}</div>
                  <div className="filter-bar" style={{ marginTop: 4 }}>
                    <input
                      type="text"
                      placeholder="輸入回覆..."
                      value={drafts[key] ?? ""}
                      onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") send(project.name, key, `${item.number}. ${drafts[key] ?? ""}`);
                      }}
                      style={{ flex: 1 }}
                    />
                    <button
                      onClick={() => send(project.name, key, `${item.number}. ${drafts[key] ?? ""}`)}
                      disabled={sending[key]}
                    >
                      {sending[key] ? "送出中…" : "回覆"}
                    </button>
                  </div>
                  {msgs[key] && (
                    <p className="muted" style={{ fontSize: 12, marginTop: 2 }}>{msgs[key]}</p>
                  )}
                </div>
              );
            })
          )}

          <div style={{ marginTop: 8, borderTop: "1px solid var(--border, #333)", paddingTop: 8 }}>
            <div className="filter-bar">
              <input
                type="text"
                placeholder="傳送指令給這個專案（不限於上面的待決策項目）..."
                value={drafts[`${project.name}:general`] ?? ""}
                onChange={(e) =>
                  setDrafts((d) => ({ ...d, [`${project.name}:general`]: e.target.value }))
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    send(project.name, `${project.name}:general`, drafts[`${project.name}:general`] ?? "");
                  }
                }}
                style={{ flex: 1 }}
              />
              <button
                className="primary"
                onClick={() =>
                  send(project.name, `${project.name}:general`, drafts[`${project.name}:general`] ?? "")
                }
                disabled={sending[`${project.name}:general`]}
              >
                {sending[`${project.name}:general`] ? "送出中…" : "傳送指令"}
              </button>
            </div>
            {msgs[`${project.name}:general`] && (
              <p className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                {msgs[`${project.name}:general`]}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
