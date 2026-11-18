// Small shared UI helpers.

export const $ = (sel, root = document) => root.querySelector(sel);

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

let toastTimer;
export function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 2600);
}

/** Show an error from the API (message + how to fix it). */
export function showError(err) {
  toast(err.hint ? `${err.message} — ${err.hint}` : err.message || String(err));
}

/** Run an async action with the button disabled; errors become toasts. */
// While `fn` runs, the button is disabled and shows a spinner (saves and renders can take a while).
export async function busy(button, fn) {
  if (button) { button.disabled = true; button.classList.add("loading"); button.setAttribute("aria-busy", "true"); }
  try {
    return await fn();
  } catch (err) {
    showError(err);
  } finally {
    if (button) { button.disabled = false; button.classList.remove("loading"); button.removeAttribute("aria-busy"); }
  }
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied post text with credits");
  } catch {
    window.prompt("Copy this:", text);
  }
}

export const timeAgo = (t) => {
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
};

// Only one video plays at a time: starting one pauses every other (captures events from all <video>s).
document.addEventListener("play", (e) => {
  document.querySelectorAll("video").forEach((v) => { if (v !== e.target && !v.paused) v.pause(); });
}, true);

/**
 * In-page confirmation (resolves true/false). Used instead of window.confirm(), which some
 * embedded browsers and webviews silently block, so the action would never happen.
 */
export function confirmDialog(message, { ok = "Delete", danger = true } = {}) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "confirm";
    d.innerHTML = `<p>${esc(message)}</p><div class="row" style="justify-content:flex-end">
      <button class="btn" value="no">Cancel</button>
      <button class="btn ${danger ? "danger-solid" : "primary"}" value="yes">${esc(ok)}</button></div>`;
    d.addEventListener("click", (e) => {
      if (e.target === d) d.close("no");                       // click outside = cancel
      const v = e.target.closest("button")?.value;
      if (v) d.close(v);
    });
    d.addEventListener("close", () => { resolve(d.returnValue === "yes"); d.remove(); });
    document.body.append(d);
    d.showModal();
    d.querySelector('[value="no"]').focus();                   // Enter won't delete by accident
  });
}

/** Shade the parts of a 9:16 stage that TikTok/Reels/Shorts cover with their own buttons and text.
 *  `zone` = {top, bottom, left, right} as shares of the frame, or null to remove the guide. */
export function drawSafeZone(stage, zone, label = "") {
  let g = stage.querySelector(".safe-guide");
  if (!zone) { g?.remove(); return; }
  if (!g) {
    g = document.createElement("div");
    g.className = "safe-guide";
    g.innerHTML = '<i class="t"></i><i class="b"></i><i class="l"></i><i class="r"></i><em></em>';
    stage.appendChild(g);
  }
  const pc = (v) => `${(v * 100).toFixed(1)}%`;
  Object.assign(g.querySelector(".t").style, { height: pc(zone.top) });
  Object.assign(g.querySelector(".b").style, { height: pc(zone.bottom) });
  Object.assign(g.querySelector(".l").style, { width: pc(zone.left), top: pc(zone.top), bottom: pc(zone.bottom) });
  Object.assign(g.querySelector(".r").style, { width: pc(zone.right), top: pc(zone.top), bottom: pc(zone.bottom) });
  g.querySelector("em").textContent = label ? `${label} buttons & text` : "";
  g.querySelector("em").style.bottom = pc(zone.bottom);
}
