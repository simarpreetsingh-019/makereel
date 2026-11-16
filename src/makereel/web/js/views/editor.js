// Reel editor, three tabs:
//   Text    on-screen title, captions as a paragraph, post text, logo on/off
//   Timing  live caption preview over the clean video, shift slider, auto-sync, tap-to-sync, per-word nudges
//   Look    caption style template, framing (incl. follow-the-speaker), height, size, background box
//   Cards   text overlays: quotes, notes, an outro over the last seconds
//   Cut     trim / extend the edges, split in two
//   Export  the same reel as 9:16, 4:5, 1:1 or 16:9 (blur / crop / bars)
import { api, media } from "../api.js";
import { $, busy, confirmDialog, copyText, drawSafeZone, esc, toast } from "../ui.js";
import { hexToRgba } from "./brand.js";

const FORMATS = [
  ["9x16", "9:16", "Reels, Shorts, TikTok"],
  ["4x5", "4:5", "Instagram feed"],
  ["1x1", "1:1", "Square posts"],
  ["16x9", "16:9", "YouTube, X"],
];

let cur = null;   // { folder, name, onSaved, reel, words, offset, tapIndex, look }
const LOOK_FIELDS = ["vertical", "size", "box", "box_colour", "box_opacity", "script"];

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
  $("#lk-video").src = media(reel.raw || reel.video);
  cur.look = { ...reel.look };
  fillLook();
  fillCut(reel);
  $("#cd-video").src = media(reel.video);
  cur.cards = (reel.cards || []).map((c) => ({ ...c }));
  drawCards();
  drawWordList();
  drawExports();
}

// ------------------------------------------------------------------ cut (trim / split)
function fillCut(reel) {
  cur.trim = { start: 0, end: 0 };
  $("#cut-video").src = media(reel.video);
  $("#cut-len").textContent = `${reel.length.toFixed(1)} s`;
  $("#cut-room").textContent = `${reel.room_before.toFixed(1)} s before and ${reel.room_after.toFixed(1)} s after`;
  $("#cut-note").textContent = reel.can_trim ? ""
    : "This reel was made before trimming existed. Run its link again to trim or split it.";
  document.querySelectorAll("[data-edpanel=cut] button").forEach((b) => (b.disabled = !reel.can_trim));
  drawCut();
}

function clampTrim() {
  const r = cur.reel;
  cur.trim.start = Math.min(Math.max(cur.trim.start, -r.room_before), r.length - 3);
  cur.trim.end = Math.max(Math.min(cur.trim.end, r.room_after), -(r.length - 3 - Math.max(0, cur.trim.start)));
  cur.trim.start = Math.round(cur.trim.start * 100) / 100;
  cur.trim.end = Math.round(cur.trim.end * 100) / 100;
}

function drawCut() {
  const f = (v) => `${v > 0 ? "+" : ""}${v.toFixed(2)} s`;
  $("#cut-start").textContent = f(cur.trim.start);
  $("#cut-end").textContent = f(cur.trim.end);
  const newLen = cur.reel.length - cur.trim.start + cur.trim.end;
  $("#cut-result").textContent = cur.trim.start || cur.trim.end ? `New length ${newLen.toFixed(1)} s` : "";
}

// ------------------------------------------------------------------ look (placement + background)
function fillLook() {
  const r = cur.reel;
  $("#lk-templates").innerHTML = Object.entries(r.templates || {}).map(([id, label]) =>
    `<button type="button" class="chip-btn ${id === cur.look.template ? "on" : ""}" data-template="${id}">${esc(label)}</button>`).join("");
  $("#lk-fit").value = r.fit || "blur";
  $("#lk-fit").disabled = !r.can_export;
  LOOK_FIELDS.forEach((k) => {
    const el = $(`#lk-${k}`);
    if (el.type === "checkbox") el.checked = cur.look[k]; else el.value = cur.look[k];
  });
  drawLook();
}

function readLook() {
  const out = {};
  LOOK_FIELDS.forEach((k) => {
    const el = $(`#lk-${k}`);
    out[k] = el.type === "checkbox" ? el.checked : el.type === "range" ? Number(el.value) : el.value;
  });
  return out;
}

const GROUP = { classic: 3, pop: 3, boxed: 3, glow: 3, karaoke: 4, single: 1, minimal: 5 };

/** Caption HTML for word `i` being spoken, in a template's grouping (mirrors captions.TEMPLATES). */
function captionHTML(words, i, template) {
  const n = GROUP[template] || 3;
  const g = Math.floor(i / n) * n;
  return words.slice(g, g + n).map((w, k) => {
    const idx = g + k;
    if (idx === i) return `<b>${esc(w.word)}</b>`;
    if (template === "karaoke" && idx < i) return `<i>${esc(w.word)}</i>`;
    return esc(w.word);
  }).join(" ");
}

/** Style a caption element like the rendered captions (positions/sizes relative to its stage). */
function styleCaption(el, look, stage) {
  const w = stage.clientWidth || 300;
  el.style.bottom = `${look.vertical * 100}%`;
  el.style.top = "auto";
  el.style.fontSize = `${w * 0.08 * look.size}px`;
  el.style.fontFamily = `"${look.font}", "Arial Black", system-ui, sans-serif`;
  el.style.color = look.text_colour;
  el.style.webkitTextStroke = `${Math.max(1, w * 0.004)}px ${look.outline_colour}`;
  el.dataset.tpl = look.template || "classic";
  el.style.setProperty("--hl", look.highlight_colour);
  el.style.setProperty("--outline", look.outline_colour);
  if (look.template === "minimal") el.style.fontSize = `${w * 0.08 * look.size * 0.75}px`;
  const inner = el.querySelector("span") || el;
  inner.style.background = look.box ? hexToRgba(look.box_colour, look.box_opacity) : "transparent";
}

function drawLook() {
  const look = { ...cur.reel.look, ...readLook() };
  const cap = $("#lk-caption");
  look.template = cur.look.template;
  const sample = cur.words.length ? cur.words : ["captions", "look", "like", "this"].map((word) => ({ word }));
  cap.innerHTML = `<span>${captionHTML(sample, 1, look.template)}</span>`;
  const zone = cur.reel.safe_zone;
  const lifted = zone && look.vertical < zone.bottom;
  styleCaption(cap, lifted ? { ...look, vertical: zone.bottom } : look, $("#lk-stage"));
  if (zone) { cap.style.left = `${Math.max(5.5, zone.left * 100)}%`; cap.style.right = `${Math.max(5.5, zone.right * 100)}%`; }
  drawSafeZone($("#lk-stage"), $("#lk-safe-show").checked ? zone : null, zone?.label);
  $("#lk-safe-show").closest("label").hidden = !zone;
  $("#lk-safe-hint").textContent = lifted
    ? `Lifted to ${Math.round(zone.bottom * 100)}% so ${zone.label} doesn't cover it. Turn this off in Brand → Keep clear of app buttons.` : "";
  $("#lk-vertical-v").textContent = `${Math.round(look.vertical * 100)}%`;
  $("#lk-size-v").textContent = `${Math.round(look.size * 100)}%`;
  $("#lk-box_opacity-v").textContent = `${Math.round(look.box_opacity * 100)}%`;
  $("#lk-box-opts").style.opacity = look.box ? 1 : 0.45;
  const lang = cur.reel.language;
  $("#lk-lang").textContent = lang ? `(spoken: ${LANGS[lang] || lang})` : "";
  const was = cur.reel.look.script, now = look.script;
  $("#lk-script-hint").textContent = now === was ? ""
    : now === "roman" && was === "original" ? "Your caption words are kept, just written in English letters."
    : "Saving listens to the reel again (a few seconds). Word edits you made are replaced.";
}

const LANGS = { en: "English", hi: "Hindi", pa: "Punjabi", ur: "Urdu", bn: "Bengali", gu: "Gujarati", mr: "Marathi",
  ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam", es: "Spanish", pt: "Portuguese", fr: "French",
  de: "German", it: "Italian", ar: "Arabic", ru: "Russian", tr: "Turkish", id: "Indonesian", ja: "Japanese",
  ko: "Korean", zh: "Chinese", th: "Thai", vi: "Vietnamese", nl: "Dutch", pl: "Polish" };

function showTab(tab) {
  document.querySelectorAll("#editor [data-edtab]").forEach((b) => b.classList.toggle("on", b.dataset.edtab === tab));
  document.querySelectorAll("#editor [data-edpanel]").forEach((p) => (p.hidden = p.dataset.edpanel !== tab));
  ["#ed-video", "#tm-video", "#lk-video", "#cut-video", "#cd-video"].forEach((v) => $(v).pause());
}

// ------------------------------------------------------------------ subtitles out (mirrors core/subtitles.to_srt)
function toSrt(words, perLine = 7, maxGap = 0.8) {
  const ts = (t) => {
    let ms = Math.round(Math.max(0, t) * 1000);
    const h = Math.floor(ms / 3600000); ms %= 3600000;
    const m = Math.floor(ms / 60000); ms %= 60000;
    const s = Math.floor(ms / 1000); ms %= 1000;
    const p = (n, k = 2) => String(n).padStart(k, "0");
    return `${p(h)}:${p(m)}:${p(s)},${p(ms, 3)}`;
  };
  const lines = [];
  let line = [];
  for (const w of words) {
    if (line.length && (line.length >= perLine || w.start - line[line.length - 1].end > maxGap)) { lines.push(line); line = []; }
    line.push(w);
  }
  if (line.length) lines.push(line);
  return lines.map((l, i) => `${i + 1}\n${ts(l[0].start)} --> ${ts(l[l.length - 1].end)}\n${l.map((w) => w.word).join(" ")}\n`).join("\n");
}

// ------------------------------------------------------------------ cards (text overlays)
function wordsNear(t, secs = 2.5) {
  return cur.words.filter((w) => w.start >= t - 0.3 && w.start < t + secs).map((w) => w.word).join(" ");
}

function addCard(kind) {
  const t = Math.round($("#cd-video").currentTime * 10) / 10;
  const len = cur.reel.length || $("#cd-video").duration || 30;
  if (kind === "outro") {
    if (cur.cards.some((c) => c.kind === "outro")) return toast("This reel already has an outro card");
    cur.cards.push({ kind, text: "Follow for more", position: "middle", secs: 3 });
  } else {
    const start = Math.min(t, Math.max(0, len - 1));
    cur.cards.push({ kind, text: kind === "quote" ? wordsNear(t) || "Your quote" : "", position: "top",
                     start, end: Math.min(len, start + 3) });
  }
  drawCards();
}

function drawCards() {
  const pos = (c) => ["top", "middle", "bottom"].map((p) => `<option ${c.position === p ? "selected" : ""}>${p}</option>`).join("");
  $("#cd-list").innerHTML = cur.cards.length ? cur.cards.map((c, i) => `
    <div class="card-row" data-i="${i}">
      <span class="kind">${esc(c.kind)}</span>
      <button class="link" data-act="del" type="button">remove</button>
      <textarea data-k="text" maxlength="200" placeholder="Card text">${esc(c.text)}</textarea>
      <div class="row" style="grid-column:1/-1">
        ${c.kind === "outro"
          ? `<label>last <input type="number" data-k="secs" min="1" max="10" step="0.5" value="${c.secs}"> s</label>`
          : `<label>from <input type="number" data-k="start" min="0" step="0.1" value="${c.start}"></label>
             <button class="btn tiny" data-act="start" type="button">at playhead</button>
             <label>to <input type="number" data-k="end" min="0" step="0.1" value="${c.end}"></label>
             <button class="btn tiny" data-act="end" type="button">at playhead</button>`}
        <label>at <select data-k="position">${pos(c)}</select></label>
      </div>
    </div>`).join("") : `<p class="hint" style="margin:0">No cards on this reel yet.</p>`;
}

function readCards() {
  return cur.cards.map((c) => ({ ...c, text: c.text.trim() }));
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
      const n = GROUP[cur.reel.look.template] || 3;
      const groupEnd = Math.floor(i / n) * n + n;
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
    box.innerHTML = `<span>${captionHTML(cur.words, i, cur.reel.look.template)}</span>`;
    styleCaption(box, cur.reel.look, box.parentElement);
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
  dialog.addEventListener("close", () => {
    ["#ed-video", "#tm-video", "#lk-video", "#cut-video", "#cd-video"].forEach((v) => $(v).pause());
    if (cur) stopTapSync();
  });
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

  // Look tab
  $("[data-edpanel=look]").addEventListener("input", (e) => { if (e.target.id?.startsWith("lk-")) drawLook(); });
  $("[data-edpanel=look]").addEventListener("click", (e) => {
    const b = e.target.closest("[data-preset]");
    if (b) { $("#lk-vertical").value = b.dataset.preset; drawLook(); }
    const t = e.target.closest("[data-template]");
    if (t) {
      cur.look.template = t.dataset.template;
      document.querySelectorAll("#lk-templates .chip-btn").forEach((x) => x.classList.toggle("on", x === t));
      drawLook();
    }
  });

  // Cut tab
  const cv = $("#cut-video");
  cv.addEventListener("timeupdate", () => ($("#cut-time").textContent = `${cv.currentTime.toFixed(1)} s`));
  $("[data-edpanel=cut]").addEventListener("click", (e) => {
    const b = e.target.closest("[data-trim], [data-trim-now]");
    if (!b || !cur.reel.can_trim) return;
    const edge = b.dataset.trim || b.dataset.trimNow;
    if (b.dataset.trimNow) cur.trim[edge] = edge === "start" ? cv.currentTime : cv.currentTime - cur.reel.length;
    else cur.trim[edge] += Number(b.dataset.d);
    clampTrim();
    drawCut();
  });
  $("#cut-apply").addEventListener("click", (e) => {
    if (!cur.trim.start && !cur.trim.end) return toast("Move an edge first");
    $("#ed-msg").textContent = "Trimming and re-rendering…";
    busy(e.currentTarget, async () => {
      fill(await api.trimReel(cur.folder, cur.name, cur.trim.start, cur.trim.end));
      showTab("cut");
      $("#ed-msg").textContent = "Trimmed. New audio at the edges was transcribed.";
      cur.onSaved?.();
    });
  });
  $("#cut-split").addEventListener("click", async (e) => {
    const at = cv.currentTime;
    if (at < 2 || at > cur.reel.length - 2) return toast("Pause at least 2 seconds from either end");
    if (!(await confirmDialog(`Split ${cur.name} at ${at.toFixed(1)} s? The second part becomes a new reel.`, { ok: "Split", danger: false }))) return;
    $("#ed-msg").textContent = "Splitting…";
    busy(e.currentTarget, async () => {
      await api.splitReel(cur.folder, cur.name, at);
      toast("Split into two reels");
      $("#editor").close();
      cur.onSaved?.();
    });
  });
  $("#lk-video").addEventListener("loadedmetadata", drawLook);
  window.addEventListener("resize", () => cur && drawLook());
  $("#lk-reset").addEventListener("click", () => { cur.look = { ...cur.reel.look }; fillLook(); });
  $("#lk-save").addEventListener("click", (e) => {
    const look = readLook();
      look.template = cur.look.template;
    const changed = [...LOOK_FIELDS, "template"].some((k) => String(look[k]) !== String(cur.reel.look[k]));
    const fit = $("#lk-fit").value;
    const fitChanged = fit !== (cur.reel.fit || "blur");
    if (!changed && !fitChanged) return toast("Look unchanged");
    const body = {};
    if (changed) body.look = look;
    if (fitChanged) body.fit = fit;
    $("#ed-msg").textContent = ["track", "split", "auto"].includes(fit) && fitChanged ? "Finding the speaker and re-rendering…" : "Rendering…";
    save(body, e.currentTarget, look.script !== cur.reel.look.script ? "Captions rewritten and re-rendered." : "Look saved and re-rendered.");
  });

  // Text tab: subtitles in and out
  $("#ed-import").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 5e6) return toast("Subtitle files must be under 5 MB");
    const text = await file.text();
    if (!await confirmDialog(`Replace this reel's captions with ${file.name}?`, { ok: "Replace", danger: false })) return;
    $("#ed-msg").textContent = "Importing and re-rendering…";
    await busy(null, async () => {
      try {
        fill(await api.importCaptions(cur.folder, cur.name, text));
        $("#ed-msg").textContent = `Captions from ${file.name}.`;
        cur.onSaved?.();
      } catch (err) { $("#ed-msg").textContent = ""; throw err; }
    });
  });
  $("#ed-srt").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([toSrt(cur.words)], { type: "application/x-subrip" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${cur.name}.srt` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  // Cards tab
  $("#cd-video").addEventListener("timeupdate", () => { $("#cd-time").textContent = `${$("#cd-video").currentTime.toFixed(1)} s`; });
  $("#cd-add-quote").addEventListener("click", () => addCard("quote"));
  $("#cd-add-note").addEventListener("click", () => addCard("note"));
  $("#cd-add-outro").addEventListener("click", () => addCard("outro"));
  $("#cd-list").addEventListener("input", (e) => {
    const row = e.target.closest("[data-i]"), k = e.target.dataset.k;
    if (!row || !k) return;
    const c = cur.cards[row.dataset.i];
    c[k] = e.target.type === "number" ? Number(e.target.value) : e.target.value;
  });
  $("#cd-list").addEventListener("click", (e) => {
    const row = e.target.closest("[data-i]"), act = e.target.dataset.act;
    if (!row || !act) return;
    const i = Number(row.dataset.i);
    if (act === "del") cur.cards.splice(i, 1);
    else cur.cards[i][act] = Math.round($("#cd-video").currentTime * 10) / 10;
    drawCards();
  });
  $("#cd-save").addEventListener("click", (e) => {
    if (cur.cards.some((c) => !c.text.trim())) return toast("Give every card some text, or remove it");
    save({ cards: readCards() }, e.currentTarget, "Cards saved and re-rendered.");
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
