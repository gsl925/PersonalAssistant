const { app, globalShortcut, ipcMain, BrowserWindow } = require("electron");
const { createTray } = require("./tray");
const { createNoteWindow } = require("./windows/noteWindow");
const { createTodoWindow } = require("./windows/todoWindow");
const { captureScreenshot } = require("./windows/overlayWindow");
const { ingestText, ingestUrl, ingestFilePath, createTodo } = require("./api");

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
    console.log(`[main] hotkey registration — screenshot(Ctrl+Shift+S): ${screenshotOk}, note(Ctrl+Shift+N): ${noteOk}, todo(Ctrl+Shift+T): ${todoOk}`);
    if (!screenshotOk || !noteOk || !todoOk) {
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
  ipcMain.handle("close-current-window", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close();
  });
}
