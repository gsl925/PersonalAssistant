// All backend HTTP calls happen here, in the Electron main process — Node's
// fetch is not subject to browser CORS, so this sidesteps the whole
// renderer-origin/CORS question entirely instead of touching backend/main.py's
// CORS allowlist.
const fs = require("fs");
const path = require("path");

const BASE_URL = "http://localhost:8000";

async function parseOrThrow(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || res.statusText);
  }
  return data;
}

async function ingestText(text) {
  const res = await fetch(`${BASE_URL}/api/ingest/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return parseOrThrow(res);
}

async function ingestUrl(url) {
  const res = await fetch(`${BASE_URL}/api/ingest/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  return parseOrThrow(res);
}

async function ingestFilePath(filePath, inputType) {
  const buffer = fs.readFileSync(filePath);
  const form = new FormData();
  form.append("file", new Blob([buffer]), path.basename(filePath));
  if (inputType) form.append("input_type", inputType);
  const res = await fetch(`${BASE_URL}/api/ingest/file`, { method: "POST", body: form });
  return parseOrThrow(res);
}

async function createTodo(text) {
  // Explicit-intent path — the backend skips the ambient is-this-a-todo
  // classification the Telegram bot uses, since pressing this hotkey already
  // says "this is a todo".
  const res = await fetch(`${BASE_URL}/api/todos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source: "desktop" }),
  });
  return parseOrThrow(res);
}

module.exports = { ingestText, ingestUrl, ingestFilePath, createTodo, BASE_URL };
