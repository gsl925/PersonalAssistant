const { BrowserWindow, screen } = require("electron");
const path = require("path");

let todoWin = null;

function createTodoWindow() {
  if (todoWin) {
    todoWin.show();
    todoWin.focus();
    return todoWin;
  }

  const { width } = screen.getPrimaryDisplay().workAreaSize;
  todoWin = new BrowserWindow({
    width: 380,
    height: 150,
    x: width - 400,
    y: 230,
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
  todoWin.loadFile(path.join(__dirname, "..", "..", "renderer", "todo.html"));
  todoWin.on("closed", () => {
    todoWin = null;
  });
  return todoWin;
}

module.exports = { createTodoWindow };
