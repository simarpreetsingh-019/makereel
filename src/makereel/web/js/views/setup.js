// System tab: first-run setup (speech models suggested for this computer) and updates from GitHub.
// Also the notices at the top of every page: "finish setup" and "an update is available".
import { api } from "../api.js";
import { $, busy, esc, toast } from "../ui.js";

let setup = null;     // GET /setup
let update = null;    // GET /updates

const ENGLISH = ["base", "small", "medium", "distil-large-v3", "large-v3"];
const OTHER = ["small", "medium", "large-v3"];

function option(m, recommended) {
  const flag = m.state === "done" ? "downloaded" : `${m.size_gb} GB download`;
  return `<option value="${m.name}">${esc(m.label)}${m.name === recommended ? " (suggested)" : ""} · ${flag}</option>`;
}

function drawSetup() {
  const pc = setup.computer, rec = setup.recommended, byName = Object.fromEntries(setup.models.map((m) => [m.name, m]));
  const gpu = pc.gpu ? `${esc(pc.gpu.name)} (${pc.gpu.vram_gb} GB)${pc.cuda ? "" : " — its CUDA libraries aren't installed, so speech uses the CPU"}`
    : "no NVIDIA GPU";
  $("#su-pc").innerHTML = `This computer: <b>${pc.ram_gb} GB</b> memory · ${pc.cores} cores · ${gpu} · ${pc.free_disk_gb} GB free disk.`;
  $("#su-model").innerHTML = ENGLISH.map((n) => option(byName[n], rec.model)).join("");
  $("#su-model_other").innerHTML = OTHER.map((n) => option(byName[n], rec.model_other)).join("");
  $("#su-model").value = rec.model;
  $("#su-model_other").value = rec.model_other;
  $("#su-device").value = setup.current.device || "auto";
  drawWhy();
  drawModels();
  pollModels();
}

function drawModels() {
  const inUse = [setup.current.model, setup.current.model_other];
  $("#su-models").innerHTML = setup.models.map((m) => {
    const state = m.state === "downloading" ? `downloading ${m.percent ?? 0}%` : m.state === "done" ? "downloaded"
      : m.state === "failed" ? `failed: ${esc(m.error || "")}` : "not downloaded";
    const btn = m.state === "downloading" ? `<button class="btn small" data-m-cancel="${m.name}" type="button">Stop</button>`
      : m.state === "done" ? (inUse.includes(m.name) ? `<span class="hint" style="margin:0">in use</span>`
        : `<button class="btn small danger" data-m-delete="${m.name}" type="button">Delete</button>`)
      : `<button class="btn small" data-m-get="${m.name}" type="button">Download</button>`;
    return `<div class="row" style="justify-content:space-between;padding:4px 0"><span><b>${esc(m.label)}</b> ·
      ${m.size_gb} GB · <span class="hint" style="margin:0">${state}</span></span>${btn}</div>`;
  }).join("");
}

let polling = false;
async function pollModels() {
  if (polling) return;
  polling = true;
  try {
    while (setup.models.some((m) => m.state === "downloading")) {
      await new Promise((r) => setTimeout(r, 1500));
      setup = await api.setup($("#su-focus").value);
      drawModels();
    }
    drawWhy();
  } finally { polling = false; }
}

function drawWhy() {
  const rec = setup.recommended, byName = Object.fromEntries(setup.models.map((m) => [m.name, m]));
  const a = byName[$("#su-model").value], b = byName[$("#su-model_other").value];
  const need = [...new Set([a, b])].filter((m) => m.state !== "done").reduce((s, m) => s + m.size_gb, 0);
  $("#su-why").innerHTML = `Suggested because: ${esc(rec.why)}.<br>
    <b>${esc(a.label)}</b>: ${esc(a.note)}<br><b>${esc(b.label)}</b>: ${esc(b.note)}<br>
    ${need ? `Downloads ${need.toFixed(1)} GB once.` : "Both are already downloaded."}
    ${need + 2 > setup.computer.free_disk_gb ? " <b>Not enough free disk space for this.</b>" : ""}`;
}

async function waitFor(name) {
  for (;;) {
    const st = await api.downloadModel(name);
    if (st.state === "done") return;
    if (st.state === "failed") throw new Error(`Download of ${name} failed: ${st.error}`);
    if (st.state === "missing") throw new Error(`Download of ${name} was stopped`);
    $("#su-progress").textContent = `Downloading ${name}… ${st.percent ?? 0}% (stop it under "Downloaded models")`;
    await new Promise((r) => setTimeout(r, 1500));
  }
}

async function loadSetup() {
  setup = await api.setup($("#su-focus").value);
  drawSetup();
}

// ------------------------------------------------------------------ updates
function drawUpdate() {
  const u = update;
  let text = `You have makereel <b>${esc(u.current)}</b>.`;
  if (u.installed) text += ` Version <b>${esc(u.installed)}</b> is installed. Restart makereel to use it.`;
  else if (u.installing) text += " Installing the update…";
  else if (u.available) text += ` <b>Version ${esc(u.latest.version)} is available.</b>
    ${u.latest.url ? `<a href="${esc(u.latest.url)}" target="_blank" rel="noopener">What's new ↗</a>` : ""}`;
  else if (u.error) text += ` Couldn't check: ${esc(u.error)}.`;
  else if (u.latest) text += " It's the latest version.";
  $("#up-status").innerHTML = text;
  $("#up-install").hidden = !u.available || u.installing || !!u.installed;
  $("#up-restart").hidden = !u.installed;
  $("#up-log").hidden = !u.log?.length;
  $("#up-log").textContent = (u.log || []).join("\n");
}

async function pollInstall() {
  while (update.installing) {
    await new Promise((r) => setTimeout(r, 2000));
    update = await api.updates();
    drawUpdate();
  }
  if (update.error && !update.installed) toast(`Update failed: ${update.error}`);
  drawNotices();
}

// ------------------------------------------------------------------ notification cards (like Thermo)
// One card at a time, top right. Each new release is announced once; "what's new" once per version.
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } },
};

function bullets(notes) {
  return (notes || "").split("\n").map((l) => l.trim()).filter((l) => /^[-*•]\s+/.test(l))
    .map((l) => l.replace(/^[-*•]\s+/, "").replace(/\*\*/g, "")).slice(0, 3);
}

function card({ icon, title, subtitle, items = [], actions = [], extra = "" }) {
  const el = $("#ncard");
  el.innerHTML = `<div class="ncard-head"><span class="ncard-icon">${icon}</span>
      <div><b>${esc(title)}</b><div class="ncard-sub">${esc(subtitle)}</div></div>
      <button class="ncard-x" type="button" aria-label="Close">×</button></div>
    ${items.length ? `<ul>${items.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}${extra}
    ${actions.length ? `<div class="ncard-acts">${actions.map((a, i) =>
      `<button class="btn small${a.primary ? " primary" : ""}" data-i="${i}" type="button">${esc(a.title)}</button>`).join("")}</div>` : ""}`;
  const close = () => { el.classList.remove("in"); setTimeout(() => (el.hidden = true), 250); };
  el.querySelector(".ncard-x").onclick = close;
  el.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => {
    const a = actions[b.dataset.i];
    a.run?.();
    if (!a.keep) close();                  // "Open YouTube" keeps the card so the user can come back to it
  }));
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("in"));
}

// YouTube's "Sign in to confirm you're not a bot": there's nothing to click inside makereel, so ask the
// user to open YouTube in their own browser, sign in (and solve a check if YouTube shows one), then
// let makereel use that browser's sign-in. Paused recordings pick it up on their next retry.
let botShown = 0;

export function botCheck(jobs) {
  const hit = (jobs || []).find((j) => ["live", "running", "queued"].includes(j.status) && j.kind !== "watcher"
    && /not a bot|confirm you/i.test(j.last_line || ""));
  if (!hit || Date.now() - botShown < 10 * 60 * 1000 || !$("#ncard").hidden) return;
  botShown = Date.now();
  card({ icon: "🛑", title: "YouTube stopped makereel",
    subtitle: `It wants to know you're not a bot, so "${(hit.title || "").slice(0, 40)}" is paused and retrying.`,
    items: ["Open YouTube in your browser and make sure you're signed in",
            "Pick that browser below and press Continue: makereel checks the sign-in works",
            "If your computer blocks it, Settings has a sign-in file option that always works"],
    extra: `<label class="field" style="margin:8px 0 0 40px">Browser I'm signed in with<select id="nc-browser">
      <option value="chrome">Chrome</option><option value="safari">Safari</option><option value="firefox">Firefox</option>
      <option value="edge">Edge</option><option value="brave">Brave</option></select></label>`,
    actions: [
      { title: "Open YouTube", keep: true, run: () => api.ytOpen($("#nc-browser").value).catch((e) => toast(e.message)) },
      { title: "Continue", primary: true, run: async () => {
        const browser = $("#nc-browser").value;
        await api.saveSettings({ cookies_browser: browser });
        const st = await api.ytSignIn();
        if (st.ok) toast(`Signed in through ${browser}. Paused recordings retry within 2 minutes.`);
        else { toast(st.message); location.hash = "#/auto"; }
      } },
    ] });
}

export function announce(u) {
  if (!u) return;
  const seen = store.get("mr-last-version");
  store.set("mr-last-version", u.current);
  if (u.available && !u.installed && store.get("mr-notified-version") !== u.latest.version) {
    store.set("mr-notified-version", u.latest.version);
    return card({ icon: "⬆", title: `makereel ${u.latest.version} is available`, subtitle: `You have ${u.current}.`,
      items: bullets(u.latest.notes),
      actions: [
        { title: "Later" },
        ...(u.latest.url ? [{ title: "What's new", run: () => window.open(u.latest.url, "_blank", "noopener") }] : []),
        { title: "Update now", primary: true, run: () => { location.hash = "#/system"; setTimeout(() => $("#up-install").click(), 600); } },
      ] });
  }
  if (!seen) {
    return card({ icon: "👋", title: "Welcome to makereel", subtitle: "Turn live streams and videos into captioned reels.",
      items: ["Paste a live stream or video link on Create", "Add channels in Settings to clip them 24/7",
              "Pick speech models for this computer under System"],
      actions: [{ title: "Set up models", primary: true, run: () => (location.hash = "#/system") }] });
  }
  if (seen !== u.current && u.latest?.version === u.current) {
    return card({ icon: "✨", title: `What's new in ${u.current}`, subtitle: "makereel was updated.",
      items: bullets(u.latest.notes), actions: [{ title: "Got it", primary: true }] });
  }
}

// ------------------------------------------------------------------ notices on every page
export async function drawNotices(settings) {
  const parts = [];
  const first = !update;
  try { update = update || (await api.updates()); } catch { /* offline: no notice */ }
  if (first) announce(update);
  if (update?.available && !update.installed) {
    parts.push(`<div class="banner notice">makereel <b>${esc(update.latest.version)}</b> is available.
      <a href="#/system">See what's new and update →</a></div>`);
  }
  if (update?.installed) parts.push(`<div class="banner notice">Update installed. <a href="#/system">Restart makereel →</a></div>`);
  if (settings && !settings.setup_done) {
    parts.push(`<div class="banner notice">Pick speech models that suit this computer.
      <a href="#/system">Set up →</a></div>`);
  }
  $("#notices").innerHTML = parts.join("");
}

export async function load() {
  await loadSetup();
  update = await api.updates();
  drawUpdate();
  $("#up-auto").checked = (await api.settings()).update_check !== false;
}

export function mount() {
  $("#su-focus").addEventListener("change", () => loadSetup());
  $("#su-models").addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    await busy(b, async () => {
      if (b.dataset.mCancel) { await api.cancelModel(b.dataset.mCancel); toast("Download stopped and its files removed"); }
      if (b.dataset.mDelete) { await api.deleteModel(b.dataset.mDelete); toast(`${b.dataset.mDelete} deleted`); }
      if (b.dataset.mGet) await api.downloadModel(b.dataset.mGet);
      await loadSetup();
    });
  });
  ["#su-model", "#su-model_other"].forEach((id) => $(id).addEventListener("change", drawWhy));
  $("#su-apply").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const model = $("#su-model").value, other = $("#su-model_other").value;
    for (const name of new Set([model, other])) await waitFor(name);
    const settings = await api.saveSettings({ clip: { model, model_other: other },
                                              speech_device: $("#su-device").value, setup_done: true });
    $("#su-progress").textContent = "Ready. New reels use these models.";
    toast("Speech models set up");
    await loadSetup();
    drawNotices(settings);
  }));
  $("#su-skip").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    drawNotices(await api.saveSettings({ setup_done: true }));
    toast("Keeping the current models. You can change them here any time.");
  }));

  $("#up-check").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    update = await api.updates(true);
    drawUpdate();
    drawNotices();
  }));
  $("#up-auto").addEventListener("change", (e) => api.saveSettings({ update_check: e.target.checked }));
  $("#up-install").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    update = await api.installUpdate();
    drawUpdate();
    await pollInstall();
  }));
  $("#up-restart").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    await api.restartApp();
    $("#up-status").textContent = "Restarting… this page reloads in a few seconds.";
    setTimeout(() => location.reload(), 6000);
  }));
}
