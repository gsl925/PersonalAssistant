const { BrowserWindow, screen, desktopCapturer, ipcMain, Notification, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { ingestFilePath } = require("../api");

// Only ONE overlay window at a time, on whichever display the mouse cursor
// is on when the hotkey fires — NOT all displays at once. An earlier
// version tried to open one overlay per display simultaneously (so the
// user wouldn't need to move the mouse first), but on this machine's
// mixed-DPI setup (one display at 175%, one at 100%) Electron/Windows
// would not reliably size or fullscreen a window to match a *secondary*
// display's actual bounds — it kept rendering confined to the top-left,
// leaving most of that monitor outside the window and unselectable. Both
// explicit width/height and setFullScreen(true) hit the same problem.
// Targeting a single display the user is already looking at sidesteps
// this entirely: it's simpler, and cross-monitor DPI weirdness never
// comes into play for the one display actually being captured.
let overlayWin = null;
let overlayState = null; // { image, scaleX, scaleY }

// Single flag covering the ENTIRE lifecycle, from hotkey press through the
// backend upload finishing — see prior history in git blame / conversation
// for why this replaced two separate flags: pressing the hotkey again
// while a previous upload was still in flight used to open a second,
// unclosable overlay and could leave the screen stuck.
let busy = false;

async function captureScreenshot() {
  console.log("[screenshot] hotkey triggered");
  if (busy) {
    console.log("[screenshot] a previous capture/upload is still in progress, ignoring hotkey");
    new Notification({ title: "截圖處理中", body: "上一張還在處理，請稍候再試一次" }).show();
    return;
  }
  busy = true;

  try {
    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    const scaleFactor = display.scaleFactor || 1;

    const sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: {
        width: Math.round(display.size.width * scaleFactor),
        height: Math.round(display.size.height * scaleFactor),
      },
    });
    const source =
      sources.find((s) => s.display_id && String(s.display_id) === String(display.id)) || sources[0];
    console.log(
      `[screenshot] target display=${display.id} bounds=${JSON.stringify(display.bounds)} scaleFactor=${scaleFactor}, ${sources.length} source(s) found, using ${source ? source.id : "none"}`
    );
    if (!source) {
      new Notification({ title: "截圖失敗", body: "找不到可用的螢幕來源" }).show();
      busy = false;
      return;
    }

    createOverlay(display, source.thumbnail);
    // NOTE: `busy` stays true — it's only cleared once the user actually
    // finishes (cancel or a completed/failed upload), in the ipcMain
    // handler below, not here.
  } catch (err) {
    console.error("[screenshot] error setting up capture:", err);
    busy = false;
  }
}

function createOverlay(display, image) {
  const capturedSize = image.getSize();

  overlayWin = new BrowserWindow({
    x: display.bounds.x,
    y: display.bounds.y,
    width: display.bounds.width,
    height: display.bounds.height,
    show: false,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    movable: false,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  overlayWin.setAlwaysOnTop(true, "screen-saver");

  overlayWin.once("show", () => {
    // Measure the window's REAL rendered content size rather than trusting
    // display.bounds/scaleFactor — on this machine those didn't always
    // match what Windows actually gave the window on a given monitor.
    const [cw, ch] = overlayWin.getContentSize();
    const scaleX = capturedSize.width / cw;
    const scaleY = capturedSize.height / ch;
    console.log(
      `[screenshot] actual window content size=${cw}x${ch} capturedImageSize=${JSON.stringify(
        capturedSize
      )} measuredScale=(${scaleX.toFixed(3)},${scaleY.toFixed(3)})`
    );
    overlayState = { image, scaleX, scaleY };
  });

  overlayWin.webContents.on("console-message", (_event, _level, message) => {
    console.log("[overlay renderer]", message);
  });
  overlayWin.webContents.on("preload-error", (_event, preloadPath, error) => {
    console.error("[overlay preload error]", preloadPath, error);
  });

  overlayWin.loadFile(path.join(__dirname, "..", "..", "renderer", "overlay.html"));
  overlayWin.webContents.once("did-finish-load", () => {
    console.log("[screenshot] overlay loaded, sending capture-image");
    overlayWin.webContents.send("capture-image", image.toDataURL());
    overlayWin.show();
  });
  overlayWin.on("closed", () => {
    overlayWin = null;
    overlayState = null;
  });
}

function closeOverlay() {
  if (overlayWin && !overlayWin.isDestroyed()) overlayWin.close();
  overlayWin = null;
  overlayState = null;
}

ipcMain.on("screenshot-region", async (_event, rect) => {
  console.log("[screenshot] received region:", JSON.stringify(rect));

  // An explicit cancel (Escape → rect is null) must ALWAYS be able to close
  // the overlay and clear `busy`, no matter what else is going on — this is
  // the user's only way to back out, so nothing should ever be able to
  // swallow it.
  if (rect === null) {
    console.log("[screenshot] explicit cancel — closing overlay");
    closeOverlay();
    busy = false;
    return;
  }

  // A too-small rect (an accidental click, or a stray extra mousedown before
  // the real drag) is NOT a cancel — leave the overlay open so the user can
  // just try dragging again, don't make them re-press the hotkey.
  if (rect.width <= 2 && rect.height <= 2) {
    console.log("[screenshot] selection too small (stray click?) — leaving overlay open to retry");
    return;
  }

  if (!overlayState) {
    console.log("[screenshot] no active overlay state, ignoring");
    return;
  }

  // Close the overlay right away, before the (potentially slow, local-
  // vision-model-bound) crop+upload even starts. The captured `image` is
  // already an in-memory NativeImage, so cropping/uploading never needed
  // the window to stay open.
  const { image, scaleX, scaleY } = overlayState;
  closeOverlay();

  try {
    console.log("[screenshot] full captured image size:", JSON.stringify(image.getSize()), "measuredScale:", scaleX, scaleY, "rect (logical):", JSON.stringify(rect));
    const cropRect = {
      x: Math.round(rect.x * scaleX),
      y: Math.round(rect.y * scaleY),
      width: Math.round(rect.width * scaleX),
      height: Math.round(rect.height * scaleY),
    };
    console.log("[screenshot] cropping at", JSON.stringify(cropRect));
    const cropped = image.crop(cropRect);
    const tmpPath = path.join(os.tmpdir(), `screenshot-${Date.now()}.png`);
    fs.writeFileSync(tmpPath, cropped.toPNG());
    console.log("[screenshot] saved crop to", tmpPath, "- uploading...");

    // Open the exact cropped image in the OS's default viewer right away —
    // lets the user immediately eyeball whether the captured region matches
    // what they actually meant to select, instead of only finding out once
    // the (possibly slow) backend processing finishes.
    shell.openPath(tmpPath).then((err) => {
      if (err) console.error("[screenshot] failed to open preview:", err);
    });

    new Notification({ title: "截圖處理中", body: "已送出，本地模型分析可能需要數十秒到數分鐘" }).show();
    try {
      const result = await ingestFilePath(tmpPath, "screenshot");
      console.log("[screenshot] upload result:", JSON.stringify(result));
      new Notification({ title: "截圖已送出", body: result.message || "已加入處理佇列" }).show();
    } finally {
      // Give the preview viewer time to actually load the file before it
      // gets deleted from disk.
      setTimeout(() => fs.unlink(tmpPath, () => {}), 60_000);
    }
  } catch (err) {
    console.error("[screenshot] error:", err);
    new Notification({ title: "截圖上傳失敗", body: err.message }).show();
  } finally {
    busy = false;
  }
});

module.exports = { captureScreenshot };
