const { app, globalShortcut, ipcMain, BrowserWindow } = require("electron");
const { createTray } = require("./tray");
const { createNoteWindow } = require("./windows/noteWindow");
const { createTodoWindow } = require("./windows/todoWindow");
const { createInsightWindow } = require("./windows/insightWindow");
const { captureScreenshot } = require("./windows/overlayWindow");
const { ingestText, ingestUrl, ingestFilePath, createTodo, previewInsight, saveInsightPreview } = require("./api");

// Personal single-instance desktop widget — a second launch should just
// focus/reuse the running one instead of binding the hotkeys twice.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.whenReady().then(() => {
    createTray();
    const screenshotOk = globalShortcut.register("CommandOrControl+Shift+S", captureScreenshot);
    const noteOk = globalShortcut.register("CommandOrControl+Shift+N", createNoteWindow);
    const todoOk = globalShortcut.register("CommandOrControl+Shift+T", createTodoWindow);
    const insightOk = globalShortcut.register("CommandOrControl+Shift+I", createInsightWindow);
    console.log(`[main] hotkey registration — screenshot(Ctrl+Shift+S): ${screenshotOk}, note(Ctrl+Shift+N): ${noteOk}, todo(Ctrl+Shift+T): ${todoOk}, insight(Ctrl+Shift+I): ${insightOk}`);
    if (!screenshotOk || !noteOk || !todoOk || !insightOk) {
      console.warn("[main] a hotkey failed to register — likely already claimed by another app (e.g. Snipping Tool, ShareX, OneNote).");
    }
  });

  // Tray-resident app: don't quit just because every window closed.
  app.on("window-all-closed", () => {});

  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
  });

  ipcMain.handle("ingest-text", async (_event, text) => ingestText(text));
  ipcMain.handle("ingest-url", async (_event, url) => ingestUrl(url));
  ipcMain.handle("ingest-file-path", async (_event, filePath) => ingestFilePath(filePath));
  ipcMain.handle("create-todo", async (_event, text) => createTodo(text));
  ipcMain.handle("preview-insight", async (_event, url) => previewInsight(url));
  ipcMain.handle("save-insight-preview", async (_event, previewId) => saveInsightPreview(previewId));
  ipcMain.handle("close-current-window", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close();
  });
}
