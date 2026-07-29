const input = document.getElementById("input");
const status = document.getElementById("status");

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

  // Same "don't await/lock the input" reasoning as the note window — the
  // backend LLM extraction call takes a couple seconds, and the user should
  // be able to fire off another todo immediately.
  input.value = "";
  status.textContent = "📌 已送出，處理中…";

  window.api
    .createTodo(text)
    .then(() => flashStatus("✓ 已記下：" + (text.length > 30 ? text.slice(0, 30) + "…" : text)))
    .catch((err) => flashStatus("✗ 失敗：" + err.message));
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") window.api.closeWindow();
});
