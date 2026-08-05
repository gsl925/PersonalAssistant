const { BrowserWindow, screen, clipboard } = require("electron");
const path = require("path");

let insightWin = null;

// Only auto-fill when clipboard content actually looks like a URL — the
// clipboard is just as likely to hold something unrelated, and pre-filling
// garbage is worse than leaving the input blank for the user to paste into.
function sendClipboardText() {
  const text = (clipboard.readText() || "").trim();
  insightWin.webContents.send("clipboard-text", /^https?:\/\//i.test(text) ? text : "");
}

function createInsightWindow() {
  if (insightWin) {
    insightWin.show();
    insightWin.focus();
    sendClipboardText();
    return insightWin;
  }

  const { width } = screen.getPrimaryDisplay().workAreaSize;
  insightWin = new BrowserWindow({
    // Taller than note/todo windows — needs room to show the generated
    // insight text plus a save/discard button row, not just one input line.
    width: 380,
    height: 320,
    x: width - 400,
    y: 400,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  insightWin.loadFile(path.join(__dirname, "..", "..", "renderer", "insight.html"));
  insightWin.webContents.once("did-finish-load", sendClipboardText);
  insightWin.on("closed", () => {
    insightWin = null;
  });
  return insightWin;
}

module.exports = { createInsightWindow };
