import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CapabilityTiers, DigestStatusResponse, OllamaModel } from "../api/types";

const OCR_ENGINES: { value: string; label: string }[] = [
  { value: "tesseract", label: "Tesseract（本地、確定性、無 LLM 呼叫）" },
  { value: "vlm", label: "VLM（生成式，密集文字仍可能幻覺）" },
];

const PROVIDERS = ["ollama_local", "ollama_cloud"];

export default function SettingsView() {
  const [tiers, setTiers] = useState<CapabilityTiers>({});
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, string>>({});
  const [digestMsg, setDigestMsg] = useState<string | null>(null);
  const [digestStatus, setDigestStatus] = useState<DigestStatusResponse | null>(null);
  const [ocrEngine, setOcrEngine] = useState<string>("tesseract");
  const [ocrMsg, setOcrMsg] = useState<string | null>(null);

  function loadDigestStatus() {
    api.getDigestStatus().then(setDigestStatus).catch(() => setDigestStatus(null));
  }

  useEffect(() => {
    Promise.all([api.getCapabilityTiers(), api.getOllamaModels().catch(() => ({ models: [] }))]).then(
      ([tiersRes, modelsRes]) => {
        setTiers(tiersRes.tiers);
        setOllamaModels(modelsRes.models);
        setLoading(false);
      }
    );
    loadDigestStatus();
    api.getOcrEngine().then((res) => setOcrEngine(res.engine)).catch(() => {});
  }, []);

  async function changeOcrEngine(engine: string) {
    setOcrMsg("切換中…");
    try {
      const res = await api.updateOcrEngine(engine);
      setOcrEngine(res.engine);
      setOcrMsg("已切換（僅在記憶體中生效，重啟後會還原成 .env 設定）");
    } catch (e) {
      setOcrMsg("切換失敗：" + (e as Error).message);
    }
  }

  function updateEntry(tier: string, idx: number, field: "provider" | "model", value: string) {
    setTiers((t) => {
      const next = { ...t };
      next[tier] = next[tier].map((e, i) => (i === idx ? { ...e, [field]: value } : e));
      return next;
    });
  }

  function addEntry(tier: string) {
    setTiers((t) => ({ ...t, [tier]: [...t[tier], { provider: "ollama_local", model: "" }] }));
  }

  function removeEntry(tier: string, idx: number) {
    setTiers((t) => ({ ...t, [tier]: t[tier].filter((_, i) => i !== idx) }));
  }

  async function save() {
    setSaving(true);
    setSaveMsg(null);
    try {
      await api.updateCapabilityTiers(tiers);
      setSaveMsg("已儲存（僅在記憶體中生效，重啟後會還原——要永久生效需同步更新 .env）");
    } catch (e) {
      setSaveMsg("儲存失敗：" + (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function testEntry(tier: string, idx: number) {
    const entry = tiers[tier][idx];
    const key = `${tier}-${idx}`;
    setTestResults((r) => ({ ...r, [key]: "測試中…" }));
    try {
      const res = await api.testModel(entry.provider, entry.model);
      setTestResults((r) => ({ ...r, [key]: res.reachable ? `✅ ${res.detail}` : `❌ ${res.detail}` }));
    } catch (e) {
      setTestResults((r) => ({ ...r, [key]: "❌ " + (e as Error).message }));
    }
  }

  async function triggerDigest() {
    setDigestMsg("觸發中…");
    try {
      const res = await api.triggerDigest();
      setDigestMsg(res.message);
    } catch (e) {
      setDigestMsg("失敗：" + (e as Error).message);
    } finally {
      loadDigestStatus();
    }
  }

  if (loading) return <p className="muted">載入中…</p>;

  return (
    <div>
      <div className="card" style={{ marginBottom: 20 }}>
        <h3 style={{ marginTop: 0, fontSize: 14 }}>每日彙整</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          不是固定 08:00 觸發才算——後端每次啟動時，只要當天還沒發過就會自動補發一次，
          比較適合不是隨時開機的機器。
        </p>
        {digestStatus && (
          <p className="muted" style={{ fontSize: 12 }}>
            {digestStatus.sent_today
              ? `✅ 今天 (${digestStatus.today}) 已發送`
              : `⏳ 今天 (${digestStatus.today}) 還沒發送`}
            {digestStatus.last_sent_date && ` · 最近一次：${digestStatus.last_sent_date}`}
          </p>
        )}
        <button onClick={triggerDigest}>立即觸發每日摘要</button>
        {digestMsg && <p className="muted" style={{ fontSize: 12 }}>{digestMsg}</p>}
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <h3 style={{ marginTop: 0, fontSize: 14 }}>截圖 OCR 引擎</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          Tesseract 較穩定不易幻覺，但排版理解較弱；VLM 較會理解版面但密集文字仍可能編造內容。
        </p>
        <select value={ocrEngine} onChange={(e) => changeOcrEngine(e.target.value)}>
          {OCR_ENGINES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {ocrMsg && <p className="muted" style={{ fontSize: 12 }}>{ocrMsg}</p>}
      </div>

      <h3 style={{ fontSize: 14 }}>Capability Tiers</h3>
      {Object.entries(tiers).map(([tier, entries]) => (
        <div className="card" key={tier} style={{ marginBottom: 14 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{tier}</div>
          {entries.map((entry, idx) => {
            const key = `${tier}-${idx}`;
            return (
              <div key={idx} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                <select value={entry.provider} onChange={(e) => updateEntry(tier, idx, "provider", e.target.value)}>
                  {PROVIDERS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <input
                  list={`ollama-models-${tier}-${idx}`}
                  value={entry.model}
                  onChange={(e) => updateEntry(tier, idx, "model", e.target.value)}
                  style={{ flex: 1 }}
                />
                <datalist id={`ollama-models-${tier}-${idx}`}>
                  {ollamaModels.map((m) => (
                    <option key={m.name} value={m.name} />
                  ))}
                </datalist>
                <button onClick={() => testEntry(tier, idx)}>測試</button>
                <button onClick={() => removeEntry(tier, idx)}>移除</button>
                {testResults[key] && <span className="muted" style={{ fontSize: 11 }}>{testResults[key]}</span>}
              </div>
            );
          })}
          <button onClick={() => addEntry(tier)}>+ 新增 fallback</button>
        </div>
      ))}

      <button className="primary" onClick={save} disabled={saving}>
        {saving ? "儲存中…" : "儲存設定"}
      </button>
      {saveMsg && <p className="muted" style={{ fontSize: 12 }}>{saveMsg}</p>}
    </div>
  );
}
