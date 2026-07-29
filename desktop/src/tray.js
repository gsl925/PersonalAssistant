const { app, Tray, Menu, BrowserWindow } = require("electron");
const path = require("path");
const { createNoteWindow } = require("./windows/noteWindow");
const { createTodoWindow } = require("./windows/todoWindow");
const { captureScreenshot } = require("./windows/overlayWindow");

const DASHBOARD_URL = "http://localhost:8000/dashboard";

function openDashboard() {
  const win = new BrowserWindow({ width: 1280, height: 820, title: "個人知識助理 Dashboard" });
  win.loadURL(DASHBOARD_URL);
}

function createTray() {
  const iconPath = path.join(__dirname, "..", "assets", "icon.png");
  const tray = new Tray(iconPath);
  tray.setToolTip("個人知識助理");

  function buildMenu() {
    return Menu.buildFromTemplate([
      { label: "開啟儀表板", click: openDashboard },
      { label: "快速筆記 (Ctrl+Shift+N)", click: createNoteWindow },
      { label: "快速代辦 (Ctrl+Shift+T)", click: createTodoWindow },
      { label: "截圖 (Ctrl+Shift+S)", click: captureScreenshot },
      { type: "separator" },
      {
        label: "開機自動啟動",
        type: "checkbox",
        checked: app.getLoginItemSettings().openAtLogin,
        click: (menuItem) => {
          app.setLoginItemSettings({ openAtLogin: menuItem.checked });
        },
      },
      { type: "separator" },
      { label: "結束", click: () => app.quit() },
    ]);
  }

  tray.setContextMenu(buildMenu());
  tray.on("click", createNoteWindow);
  return tray;
}

module.exports = { createTray, openDashboard };
