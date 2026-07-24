const bg = document.getElementById("bg");
const sel = document.getElementById("sel");
const hint = document.getElementById("hint");

console.log("overlay.js loaded, window.api =", typeof window.api);

let start = null;
let submitted = false; // true once a valid region is sent — blocks further interaction

window.api.onCaptureImage((dataUrl) => {
  console.log("received capture-image, length =", dataUrl.length);
  bg.src = dataUrl;
});

document.addEventListener("mousedown", (e) => {
  if (submitted) return;
  if (start) {
    // A second mousedown before any mouseup shouldn't happen for a normal
    // press-drag-release, but if it does (stray event, focus quirk), don't
    // silently discard the drag's real origin — keep it and ignore this one.
    console.log("mousedown at", e.clientX, e.clientY, "ignored — drag already in progress from", start);
    return;
  }
  console.log("mousedown at", e.clientX, e.clientY);
  start = { x: e.clientX, y: e.clientY };
  sel.style.left = start.x + "px";
  sel.style.top = start.y + "px";
  sel.style.width = "0px";
  sel.style.height = "0px";
  sel.style.display = "block";
});

document.addEventListener("mousemove", (e) => {
  if (!start || submitted) return;
  const x = Math.min(start.x, e.clientX);
  const y = Math.min(start.y, e.clientY);
  const w = Math.abs(e.clientX - start.x);
  const h = Math.abs(e.clientY - start.y);
  sel.style.left = x + "px";
  sel.style.top = y + "px";
  sel.style.width = w + "px";
  sel.style.height = h + "px";
});

document.addEventListener("mouseup", (e) => {
  if (!start || submitted) return;
  const x = Math.min(start.x, e.clientX);
  const y = Math.min(start.y, e.clientY);
  const width = Math.abs(e.clientX - start.x);
  const height = Math.abs(e.clientY - start.y);
  start = null;

  if (width <= 2 || height <= 2) {
    console.log("mouseup, selection too small, staying open to retry", x, y, width, height);
    return;
  }

  // Lock the overlay immediately — no more mousedown/mousemove/mouseup is
  // processed until this window closes. Without this, the overlay stayed
  // fully interactive while the (potentially slow, local-vision-model-bound)
  // upload was in flight, so a user who didn't see instant feedback would
  // just select again — firing multiple concurrent uploads that then queue
  // up behind each other and make everything even slower.
  submitted = true;
  sel.style.borderColor = "#888";
  sel.style.background = "rgba(136,136,136,0.15)";
  hint.textContent = "上傳中，請稍候…";
  document.body.style.cursor = "wait";

  console.log("mouseup, submitting region", x, y, width, height);
  window.api.submitRegion({ x, y, width, height });
});

document.addEventListener("keydown", (e) => {
  if (submitted) return;
  if (e.key === "Escape") {
    start = null;
    console.log("Escape pressed, cancelling");
    window.api.submitRegion(null);
  }
});
