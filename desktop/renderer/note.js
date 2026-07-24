const input = document.getElementById("input");
const status = document.getElementById("status");
const drop = document.getElementById("drop");

input.focus();

function flashStatus(text) {
  status.textContent = text;
  setTimeout(() => {
    status.textContent = "";
  }, 2500);
}

input.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    window.api.closeWindow();
    return;
  }
  if (e.key !== "Enter") return;

  const text = input.value.trim();
  if (!text) return;

  // Deliberately don't await this or disable the input — the backend can
  // take anywhere from seconds (a note) to minutes (a URL needing
  // transcript fetch + summarization) to finish processing. Clearing the
  // input immediately lets the user keep typing/submitting further notes
  // right away instead of the whole window locking up until one submission
  // completes (each ingest call is independent on the backend, so several
  // in flight at once is fine).
  input.value = "";
  const isUrl = text.startsWith("http://") || text.startsWith("https://");
  status.textContent = isUrl ? "🔗 已送出，處理中…" : "📝 已送出，處理中…";

  const promise = isUrl ? window.api.ingestUrl(text) : window.api.ingestText(text);
  promise
    .then(() => flashStatus("✓ 完成：" + (text.length > 30 ? text.slice(0, 30) + "…" : text)))
    .catch((err) => flashStatus("✗ 失敗：" + err.message));
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") window.api.closeWindow();
});

["dragenter", "dragover"].forEach((evt) =>
  document.addEventListener(evt, (e) => {
    e.preventDefault();
    drop.classList.add("hover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  document.addEventListener(evt, (e) => {
    e.preventDefault();
    drop.classList.remove("hover");
  })
);

document.addEventListener("drop", async (e) => {
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files);
  for (const file of files) {
    const filePath = window.api.getPathForFile(file);
    status.textContent = `上傳中：${file.name}`;
    try {
      await window.api.ingestFilePath(filePath);
      flashStatus(`已上傳：${file.name} ✓`);
    } catch (err) {
      flashStatus(`上傳失敗：${file.name}（${err.message}）`);
    }
  }
});
