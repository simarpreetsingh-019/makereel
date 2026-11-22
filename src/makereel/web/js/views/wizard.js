// First-run setup, 3 steps: who you clip → speech models → your first link. Skippable; shown until setup_done.
import { api } from "../api.js";
import { $, busy, esc, showError, toast } from "../ui.js";
import { drawNotices } from "./setup.js";

const CH_OK = /^(@[\w.-]{2,}|(https?:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.be|twitch\.tv|kick\.com)\/\S+)$/i;
let step = 1, channels = [], setup = null, opened = false;

function draw() {
  document.querySelectorAll("#wizard [data-wz]").forEach((s) => (s.hidden = Number(s.dataset.wz) !== step));
  $("#wz-step").textContent = `Step ${step} of 3`;
  $("#wz-back").hidden = step === 1;
  $("#wz-next").textContent = step === 1 ? (channels.length ? "Next" : "Skip this step")
    : step === 2 ? "Use these models" : "Make reels";
  $("#wz-ch-list").innerHTML = channels.map((c, i) => `<div class="ch-row"><b>${esc(c)}</b>
    <button class="btn small" type="button" data-wz-del="${i}" style="margin-left:auto" aria-label="Remove ${esc(c)}">×</button></div>`).join("");
}

async function drawModels() {
  try { setup = setup || await api.setup(); } catch (err) { $("#wz-pc").textContent = "Couldn't check this computer."; return; }
  const pc = setup.computer, rec = setup.recommended, by = Object.fromEntries(setup.models.map((m) => [m.name, m]));
  $("#wz-pc").innerHTML = `This computer: <b>${pc.ram_gb} GB</b> memory · ${pc.cores} cores${pc.gpu ? ` · ${esc(pc.gpu.name)}` : ""}. Suggested:`;
  const row = (what, m) => `<div class="ch-row"><span>${what}</span><b>${esc(m.label)}</b>
    <span class="hint" style="margin:0 0 0 auto">${m.state === "done" ? "downloaded" : `${m.size_gb} GB download`}</span></div>`;
  $("#wz-models").innerHTML = row("English", by[rec.model]) + (rec.model_other !== rec.model ? row("Hindi and others", by[rec.model_other]) : "");
}

function addChannel() {
  const name = $("#wz-ch").value.trim(), lang = $("#wz-ch-lang").value;
  if (!CH_OK.test(name)) { $("#wz-ch-msg").textContent = "Try @name or a YouTube, Twitch or Kick link."; return; }
  channels.push(lang ? `${name} | ${lang}` : name);
  $("#wz-ch").value = ""; $("#wz-ch-msg").textContent = "";
  draw();
}

async function finish(save = {}) {
  drawNotices(await api.saveSettings({ ...save, setup_done: true }));
  $("#wizard").close();
}

async function next() {
  if (step === 1) {
    if (channels.length) {
      const cur = await api.settings();
      await api.saveSettings({ channels: [...cur.channels, ...channels] });
      if ($("#wz-watch").checked) await api.setWatcher(true);
    }
    step = 2; draw(); drawModels(); return;
  }
  if (step === 2) {
    if (setup) {
      const { model, model_other } = setup.recommended;
      for (const n of new Set([model, model_other])) {
        const m = setup.models.find((x) => x.name === n);
        if (m && m.state !== "done") await api.downloadModel(n);     // downloads carry on in the background
      }
      await api.saveSettings({ clip: { model, model_other } });
      $("#wz-dl").textContent = "Downloading in the background; System shows progress.";
    }
    step = 3; draw(); return;
  }
  const url = $("#wz-url").value.trim();
  await finish();
  if (url) {
    location.hash = "#/create";
    const box = document.querySelector("#link-form input[name=url]");
    box.value = url;
    document.querySelector("#link-form").requestSubmit();
  }
  toast("You're set. Settings and System let you change anything later.");
}

export function maybeOpen(settings) {
  if (opened || !settings || settings.setup_done) return;
  opened = true;
  draw();
  $("#wizard").showModal();
}

export function mount() {
  $("#wz-ch-add").addEventListener("click", addChannel);
  $("#wz-ch").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addChannel(); } });
  $("#wz-ch-list").addEventListener("click", (e) => {
    const i = e.target.closest("[data-wz-del]")?.dataset.wzDel;
    if (i !== undefined) { channels.splice(+i, 1); draw(); }
  });
  $("#wz-back").addEventListener("click", () => { step = Math.max(1, step - 1); draw(); });
  $("#wz-next").addEventListener("click", (e) => busy(e.currentTarget, () => next().catch(showError)));
  $("#wz-skip").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    await finish();
    toast("Setup skipped. System → Speech models has the model picks.");
  }));
  $("#wizard").addEventListener("cancel", (e) => e.preventDefault());   // Esc doesn't half-close it
}
