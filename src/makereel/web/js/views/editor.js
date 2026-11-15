// Reel editor, three tabs:
//   Text    on-screen title, captions as a paragraph, post text, logo on/off
//   Timing  live caption preview over the clean video, shift slider, auto-sync, tap-to-sync, per-word nudges
//   Export  the same reel as 9:16, 4:5, 1:1 or 16:9 (blur / crop / bars)
import { api, media } from "../api.js";
import { $, busy, copyText, esc, toast } from "../ui.js";

const FORMATS = [
  ["9x16", "9:16", "Reels, Shorts, TikTok"],
  ["4x5", "4:5", "Instagram feed"],
  ["1x1", "1:1", "Square posts"],
  ["16x9", "16:9", "YouTube, X"],
];

let cur = null;   // { folder, name, onSaved, reel, words, offset, tapIndex }

// ------------------------------------------------------------------ open / fill
export async function openEditor(folder, name, onSaved, tab = "text") {
  cur = { folder, name, onSaved, offset: 0, tapIndex: null };
  $("#ed-title").textContent = `Edit ${name}`;
  $("#ed-msg").textContent = "";
  try {
    fill(await api.reel(folder, name));
    showTab(tab);
    $("#editor").showModal();
  } catch (err) {
    toast(err.message);
  }
}

function fill(reel) {
  cur.reel = reel;
  cur.words = reel.words.map((w) => ({ ...w }));
  cur.offset = 0;
  $("#ed-video").src = media(reel.video);
  $("#ed-download").href = media(reel.download);
  $("#ed-hook").value = reel.hook || "";
  $("#ed-transcript").value = reel.transcript;
  $("#ed-caption").value = reel.caption || "";
  $("#ed-ass").value = reel.ass;
  $("#ed-logo").checked = reel.logo !== false;
  $("#ed-words").textContent = `${reel.words.length} words`;
  $("#tm-video").src = media(reel.raw || reel.video);
  $("#tm-offset").value = 0;
  $("#tm-offset-label").textContent = "0.00 s";
  drawWordList();
  drawExports();
}

function showTab(tab) {
  document.querySelectorAll("#editor [data-edtab]").forEach((b) => b.classList.toggle("on", b.dataset.edtab === tab));
  document.querySelectorAll("#editor [data-edpanel]").forEach((p) => (p.hidden = p.dataset.edpanel !== tab));
  $("#ed-video").pause();
  $("#tm-video").pause();
}

// ------------------------------------------------------------------ saving
async function save(changes, button, message = "Saved and re-rendered.") {
  $("#ed-msg").textContent = "Rendering…";
  await busy(button, async () => {
    try {
      fill(await api.editReel(cur.folder, cur.name, changes));
      $("#ed-msg").textContent = message;
      cur.onSaved?.();
    } catch (err) {
      $("#ed-msg").textContent = "";
      throw err;
    }
  });
}

function textChanges() {
  const r = cur.reel;
  const c = {};
  if ($("#ed-hook").value !== (r.hook || "")) c.hook = $("#ed-hook").value;
  if ($("#ed-transcript").value.trim() !== r.transcript.trim()) c.transcript = $("#ed-transcript").value;
  if ($("#ed-caption").value !== (r.caption || "")) c.caption = $("#ed-caption").value;
  if ($("#ed-ass").value !== r.ass) c.ass = $("#ed-ass").value;
  if ($("#ed-logo").checked !== (r.logo !== false)) c.logo = $("#ed-logo").checked;
  return c;
}

// ------------------------------------------------------------------ timing: live preview
function activeIndex(t) {
  const w = cur.words;
  for (let i = w.length - 1; i >= 0; i--) {
    if (t >= w[i].start + cur.offset) {
      const groupEnd = Math.floor(i / 3) * 3 + 3;
      const next = w[i + 1] ? w[i + 1].start + cur.offset : w[i].end + cur.offset + 0.25;
      const limit = w[groupEnd] ? w[groupEnd].start + cur.offset : next;
      return t < Math.min(next, limit) ? i : -1;
    }
  }
  return -1;
}

function drawOverlay() {
  if (!cur) return;
  const t = $("#tm-video").currentTime;
  const i = activeIndex(t);
  const box = $("#tm-caption");
  if (i < 0) { box.innerHTML = ""; }
  else {
    const g = Math.floor(i / 3) * 3;
    box.innerHTML = cur.words.slice(g, g + 3)
      .map((w, k) => (g + k === i ? `<b>${esc(w.word)}</b>` : esc(w.word))).join(" ");
  }
  document.querySelectorAll("#tm-list [data-i]").forEach((row) => row.classList.toggle("on", Number(row.dataset.i) === i));
  $("#tm-time").textContent = `${t.toFixed(2)} s`;
}

function loop() {
  drawOverlay();
  if (!$("#tm-video").paused) requestAnimationFrame(loop);
}

function drawWordList() {
  $("#tm-list").innerHTML = cur.words.map((w, i) => `
    <div class="word-row" data-i="${i}">
      <button class="link" data-act="seek" data-i="${i}" title="Play from here">${(w.start + cur.offset).toFixed(2)}</button>
      <span class="w">${esc(w.word)}</span>
      <button class="btn tiny" data-act="nudge" data-i="${i}" data-d="-0.1" title="0.1 s earlier">−</button>
      <button class="btn tiny" data-act="nudge" data-i="${i}" data-d="0.1" title="0.1 s later">+</button>
      <button class="btn tiny" data-act="now" data-i="${i}" title="Start this word at the current video time">set to now</button>
    </div>`).join("");
}

function setStart(i, t) {
  const w = cur.words;
  const prev = w[i - 1] ? w[i - 1].start : 0;
  const next = w[i + 1] ? w[i + 1].start : Infinity;
  const start = Math.min(Math.max(t - cur.offset, prev + 0.02), next - 0.02);
  const len = Math.max(0.1, w[i].end - w[i].start);
  w[i].start = Math.round(start * 100) / 100;
  w[i].end = Math.round(Math.min(start + len, next) * 100) / 100;
  if (w[i - 1]) w[i - 1].end = Math.min(w[i - 1].end, w[i].start);
}

function startTapSync() {
  cur.tapIndex = 0;
  const v = $("#tm-video");
  v.currentTime = 0;
  v.play();
  $("#tm-tap").textContent = "Tapping… (Space = next word, Esc = stop)";
  $("#tm-hint").textContent = `Press Space the moment you hear: “${cur.words[0]?.word ?? ""}”`;
}

function stopTapSync(message) {
  cur.tapIndex = null;
  $("#tm-tap").textContent = "Tap to sync";
  $("#tm-hint").textContent = message || "";
  drawWordList();
}

// ------------------------------------------------------------------ export
function drawExports() {
  const r = cur.reel;
  $("#ex-note").textContent = r.can_export ? ""
    : "This reel was made before exports existed. Run its link again to export it in other shapes.";
  $("#ex-formats").innerHTML = FORMATS.map(([id, label, use]) => {
    const done = r.exports[id] || (id === "9x16" ? { video: r.video, download: r.download, fit: r.fit } : null);
    return `<div class="fmt">
      <div class="shape s${id}"></div>
      <div><b>${label}</b><div class="hint" style="margin:0">${use}</div></div>
      <div class="row" style="margin-left:auto">
        ${done ? `<a class="btn small" href="${esc(media(done.download))}">Download</a>` : ""}
        <button class="btn small ${done ? "" : "primary"}" data-fmt="${id}" ${r.can_export ? "" : "disabled"}>${done ? "Re-make" : "Make"}</button>
      </div></div>`;
  }).join("");
}

// ------------------------------------------------------------------ wiring
export function mount() {
  const dialog = $("#editor");
  $("#ed-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { $("#ed-video").pause(); $("#tm-video").pause(); cur && stopTapSync(); });
  document.querySelectorAll("#editor [data-edtab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.edtab)));
  $("#ed-copy").addEventListener("click", () => copyText($("#ed-caption").value));
  $("#ed-transcript").addEventListener("input", (e) => {
    const n = e.target.value.split(/\s+/).filter(Boolean).length;
    $("#ed-words").textContent = `${n} words (was ${cur.reel.words.length})`;
  });

  // Text tab
  $("#ed-save").addEventListener("click", (e) => {
    const c = textChanges();
    if (!Object.keys(c).length) return toast("Nothing changed");
    save(c, e.currentTarget);
  });
  $("#ed-restyle").addEventListener("click", (e) => save({ ...textChanges(), restyle: true }, e.currentTarget,
    "Brand style applied."));

  // Timing tab
  const v = $("#tm-video");
  v.addEventListener("play", loop);
  v.addEventListener("seeked", drawOverlay);
  $("#tm-offset").addEventListener("input", (e) => {
    cur.offset = Number(e.target.value);
    $("#tm-offset-label").textContent = `${cur.offset > 0 ? "+" : ""}${cur.offset.toFixed(2)} s`;
    drawOverlay();
    drawWordList();
  });
  $("#tm-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const i = Number(b.dataset.i);
    if (b.dataset.act === "seek") { v.currentTime = Math.max(0, cur.words[i].start + cur.offset - 0.3); v.play(); }
    if (b.dataset.act === "nudge") { setStart(i, cur.words[i].start + cur.offset + Number(b.dataset.d)); drawWordList(); drawOverlay(); }
    if (b.dataset.act === "now") { setStart(i, v.currentTime); drawWordList(); drawOverlay(); }
  });
  $("#tm-tap").addEventListener("click", () => (cur.tapIndex === null ? startTapSync() : stopTapSync()));
  dialog.addEventListener("keydown", (e) => {
    if (cur?.tapIndex === null || cur?.tapIndex === undefined) return;
    if (e.key === "Escape") { e.preventDefault(); stopTapSync("Stopped. Review, then save."); return; }
    if (e.code !== "Space") return;
    e.preventDefault();
    setStart(cur.tapIndex, v.currentTime - 0.05);   // allow for reaction time
    cur.tapIndex += 1;
    if (cur.tapIndex >= cur.words.length) { v.pause(); stopTapSync("All words tapped. Preview it, then save."); return; }
    $("#tm-hint").textContent = `Next: “${cur.words[cur.tapIndex].word}”`;
  });
  $("#tm-auto").addEventListener("click", (e) => {
    $("#ed-msg").textContent = "Listening to the reel's audio…";
    busy(e.currentTarget, async () => {
      fill(await api.syncReel(cur.folder, cur.name));
      $("#ed-msg").textContent = "Captions re-timed from the audio and re-rendered.";
      cur.onSaved?.();
    }).finally(() => { if ($("#ed-msg").textContent.startsWith("Listening")) $("#ed-msg").textContent = ""; });
  });
  $("#tm-reset").addEventListener("click", () => {
    cur.words = cur.reel.words.map((w) => ({ ...w }));
    cur.offset = 0;
    $("#tm-offset").value = 0;
    $("#tm-offset-label").textContent = "0.00 s";
    drawWordList();
    drawOverlay();
  });
  $("#tm-save").addEventListener("click", (e) => {
    const changed = cur.offset !== 0 || JSON.stringify(cur.words) !== JSON.stringify(cur.reel.words);
    if (!changed) return toast("Timing unchanged");
    save({ words: cur.words, offset: cur.offset || undefined }, e.currentTarget, "Timing saved and re-rendered.");
  });

  // Export tab
  $("#ex-formats").addEventListener("click", (e) => {
    const b = e.target.closest("[data-fmt]");
    if (!b) return;
    $("#ed-msg").textContent = `Making ${b.dataset.fmt.replace("x", ":")}…`;
    busy(b, async () => {
      fill(await api.exportReel(cur.folder, cur.name, b.dataset.fmt, $("#ex-fit").value));
      showTab("export");
      $("#ed-msg").textContent = "Export ready.";
    });
  });
}
