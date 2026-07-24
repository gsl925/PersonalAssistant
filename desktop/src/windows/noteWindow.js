const { BrowserWindow, screen } = require("electron");
const path = require("path");

let noteWin = null;

function createNoteWindow() {
  if (noteWin) {
    noteWin.show();
    noteWin.focus();
    return noteWin;
  }

  const { width } = screen.getPrimaryDisplay().workAreaSize;
  noteWin = new BrowserWindow({
    width: 380,
    height: 150,
    x: width - 400,
    y: 60,
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
  noteWin.loadFile(path.join(__dirname, "..", "..", "renderer", "note.html"));
  noteWin.on("closed", () => {
    noteWin = null;
  });
  return noteWin;
}

module.exports = { createNoteWindow };
