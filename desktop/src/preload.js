const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("api", {
  ingestText: (text) => ipcRenderer.invoke("ingest-text", text),
  ingestUrl: (url) => ipcRenderer.invoke("ingest-url", url),
  ingestFilePath: (filePath) => ipcRenderer.invoke("ingest-file-path", filePath),
  getPathForFile: (file) => webUtils.getPathForFile(file),
  closeWindow: () => ipcRenderer.invoke("close-current-window"),
  // Screenshot overlay only:
  onCaptureImage: (cb) => ipcRenderer.on("capture-image", (_event, dataUrl) => cb(dataUrl)),
  submitRegion: (rect) => ipcRenderer.send("screenshot-region", rect),
});
