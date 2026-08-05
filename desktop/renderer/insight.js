const input = document.getElementById("input");
const goBtn = document.getElementById("go");
const result = document.getElementById("result");
const resultTitle = document.getElementById("resultTitle");
const resultInsight = document.getElementById("resultInsight");
const actions = document.getElementById("actions");
const saveBtn = document.getElementById("save");
const discardBtn = document.getElementById("discard");
const status = document.getElementById("status");

let previewId = null;

input.focus();
window.api.onClipboardText((text) => {
  if (text) input.value = text;
});

function flashStatus(text) {
  status.textContent = text;
}

function resetResult() {
  previewId = null;
  result.style.display = "none";
  actions.style.display = "none";
  resultTitle.textContent = "";
  resultInsight.textContent = "";
}

function generate() {
  const url = input.value.trim();
  if (!url) return;

  resetResult();
  goBtn.disabled = true;
  input.disabled = true;
  flashStatus("🔎 分析中…");

  window.api
    .previewInsight(url)
    .then((res) => {
      previewId = res.preview_id;
      resultTitle.textContent = res.title ? `📌 ${res.title}` : "";
      resultInsight.textContent = `💡 ${res.insight}`;
      result.style.display = "block";
      actions.style.display = "flex";
      flashStatus("");
    })
    .catch((err) => flashStatus("✗ 失敗：" + err.message))
    .finally(() => {
      goBtn.disabled = false;
      input.disabled = false;
    });
}

goBtn.addEventListener("click", generate);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") generate();
  if (e.key === "Escape") window.api.closeWindow();
});

saveBtn.addEventListener("click", () => {
  if (!previewId) return;
  saveBtn.disabled = true;
  discardBtn.disabled = true;
  flashStatus("💾 收藏中…");
  window.api
    .saveInsightPreview(previewId)
    .then(() => {
      flashStatus("✓ 已收藏至知識庫");
      setTimeout(() => window.api.closeWindow(), 1200);
    })
    .catch((err) => {
      flashStatus("✗ 失敗：" + err.message);
      saveBtn.disabled = false;
      discardBtn.disabled = false;
    });
});

discardBtn.addEventListener("click", () => window.api.closeWindow());

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") window.api.closeWindow();
});
