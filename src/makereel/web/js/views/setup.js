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
    $("#su-progress").textContent = `Downloading ${name}… ${st.percent ?? 0}%`;
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
  $("#up-repo").value = u.repo || "";
  let text = `You have makereel <b>${esc(u.current)}</b>.`;
  if (!u.repo) text += " Add the GitHub repository that publishes makereel releases to get updates.";
  else if (u.installed) text += ` Version <b>${esc(u.installed)}</b> is installed. Restart makereel to use it.`;
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

// ------------------------------------------------------------------ notices on every page
export async function drawNotices(settings) {
  const parts = [];
  try { update = update || (await api.updates()); } catch { /* offline: no notice */ }
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
    await api.saveSettings({ update_repo: $("#up-repo").value });
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
