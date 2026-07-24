import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Agent } from "../api/types";

export default function AgentsView() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    setLoading(true);
    api
      .listAgents()
      .then(setAgents)
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function toggle(name: string) {
    setBusy(name);
    try {
      await api.toggleAgent(name);
      load();
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <p className="muted">載入中…</p>;

  return (
    <div>
      {agents.map((a) => (
        <div className="card" key={a.name} style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>
                {a.name} <span className="muted" style={{ fontSize: 12 }}>v{a.version}</span>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                model tier: {a.model}
              </div>
            </div>
            <button onClick={() => toggle(a.name)} disabled={busy === a.name}>
              {a.enabled ? "停用" : "啟用"}
            </button>
          </div>
          <p style={{ fontSize: 13, margin: "8px 0" }}>{a.description}</p>
          <div className="muted" style={{ fontSize: 11 }}>
            工具：{a.tools.join(", ") || "—"}
          </div>
        </div>
      ))}
    </div>
  );
}
