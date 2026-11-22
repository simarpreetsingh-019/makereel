// "Create" tab: paste a link or upload a file, then follow the jobs.
import * as liveview from "./liveview.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { $, busy, esc, showError, timeAgo, toast } from "../ui.js";

const OPTION_FIELDS = "#create-layout [name], #create-options [name]";

function readOptions() {
  const out = {};
  document.querySelectorAll(OPTION_FIELDS).forEach((el) => {
    if (el.value) out[el.name] = el.type === "number" ? Number(el.value) : el.value;
  });
  return out;
}

export function mount(refreshJobs) {
  $("#link-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.target.url;
    busy(e.submitter, async () => {
      await api.createJob({ url: input.value.trim(), ...readOptions() });
      input.value = "";
      toast("Added. Follow it under Jobs.");
      refreshJobs();
    });
  });

  $("#upload-btn").addEventListener("click", (e) => {
    const file = $("#upload-file").files[0];
    if (!file) return toast("Pick a video file first");
    const { section, ...opts } = readOptions();
    const extra = { credit: $("#upload-credit").value, credit_url: $("#upload-credit-url").value,
                    title: file.name.replace(/\.[^.]+$/, ""), ...opts };
    Object.keys(extra).forEach((k) => extra[k] === "" && delete extra[k]);
    const progress = $("#upload-progress");
    busy(e.currentTarget, async () => {
      try {
        await api.upload(file, extra, (p) => (progress.textContent = `Uploading ${Math.round(p * 100)}%`));
        progress.textContent = "Uploaded. Making reels now.";
        refreshJobs();
      } catch (err) {
        progress.textContent = "";
        throw err;
      }
    });
  });

  $("#jobs-clear").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const { cleared } = await api.clearJobs();
    toast(cleared ? `Cleared ${cleared} finished job${cleared === 1 ? "" : "s"}. Their reels stay in Reels.` : "Nothing finished to clear");
    refreshJobs();
  }));

  $("#jobs").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.dataset.action === "stop") {
      busy(btn, async () => { await api.stopJob(id); toast("Stopping. A reel in progress will still finish."); refreshJobs(); });
    } else if (btn.dataset.action === "log") {
      const logs = { ...store.state.openLogs };
      if (id in logs) delete logs[id]; else logs[id] = "loading…";
      store.set({ openLogs: logs });
      refreshJobs();
    } else if (btn.dataset.action === "remove") {
      busy(btn, async () => { await api.removeJob(id); refreshJobs(); });
    } else if (btn.dataset.action === "liveview") {
      liveview.open(id, btn.dataset.title);
    } else if (btn.dataset.action === "open") {
      location.hash = `#/library/${encodeURIComponent(btn.dataset.folder)}`;
    }
  });
}

function jobRow(j, logText) {
  const live = j.live ? ` · ${Math.floor(j.live.seconds / 60)} min watched · ${j.live.chat} chat` : "";
  const reels = j.reels ? ` · ${j.reels} reel${j.reels === 1 ? "" : "s"}` : "";
  const canStop = (j.status === "live" && j.kind !== "watcher") || j.status === "queued";
  const err = j.error ? `<div class="err">${esc(j.error.message)}${j.error.hint ? ` — ${esc(j.error.hint)}` : ""}</div>` : "";
  const st = j.status === "running" && j.stage;
  const bar = st ? `<div class="stage"><div class="stage-bar"><i style="width:${Math.round((st.step - 0.5) / 3 * 100)}%"></i></div>
    <span class="hint" style="margin:0">Step ${st.step} of 3: ${esc(st.label)}</span></div>` : "";
  return `<div class="job">${bar ? "" : ""}
    <div class="row">
      <span class="pill ${j.status}">${j.status}</span>
      <span class="title" title="${esc(j.target)}">${esc(j.title)}</span>
      <span class="hint" style="margin:0">${timeAgo(j.created)}${live}${reels}</span>
      ${j.folder && j.kind !== "watcher" ? `<button class="btn small" data-action="open" data-folder="${esc(j.folder)}">Open folder</button>` : ""}
      ${j.status === "live" && j.kind !== "watcher" && j.live ? `<button class="btn small primary" data-action="liveview" data-id="${j.id}" data-title="${esc(j.title)}">Live view</button>` : ""}
      ${canStop ? `<button class="btn small" data-action="stop" data-id="${j.id}">Stop</button>` : ""}
      <button class="btn small" data-action="log" data-id="${j.id}">${logText !== undefined ? "Hide log" : "Log"}</button>
      ${["done", "failed", "stopped"].includes(j.status) && j.kind !== "watcher"
        ? `<button class="btn tiny job-x" data-action="remove" data-id="${j.id}" title="Remove from this list (reels stay)" aria-label="Remove">×</button>` : ""}
    </div>
    ${bar}
    ${err}
    ${logText !== undefined ? `<pre class="log" data-log="${j.id}">${esc(logText)}</pre>` : `<div class="tail">${esc(j.last_line)}</div>`}
  </div>`;
}

export function render(state) {
  const box = $("#jobs");
  // keep open logs scrolled to the bottom if they were already there
  const stick = {};
  box.querySelectorAll("pre.log").forEach((p) => (stick[p.dataset.log] = p.scrollTop + p.clientHeight >= p.scrollHeight - 20));
  box.innerHTML = state.jobs.length
    ? state.jobs.map((j) => jobRow(j, state.openLogs[j.id])).join("")
    : `<div class="empty">Nothing yet. Paste a link above.</div>`;
  box.querySelectorAll("pre.log").forEach((p) => { if (stick[p.dataset.log] !== false) p.scrollTop = p.scrollHeight; });
}

// Live load card (CPU, makereel's own use, Mac CPU temperature), refreshed with the jobs.
export async function refreshLoad(jobs) {
  let l;
  try { l = await api.load(); } catch { return; }
  $("#load").hidden = false;
  const cpu = Math.round(l.cpu), own = Math.round(l.makereel_cpu / l.cores);
  $("#ld-cpu").textContent = `${cpu}%`;
  $("#ld-cpu-bar").style.width = `${Math.min(100, cpu)}%`;
  $("#ld-cpu-bar").className = cpu > 80 ? "hi" : cpu > 50 ? "mid" : "";
  $("#ld-own").textContent = `${own}% of the computer`;
  $("#ld-mem").textContent = `${Math.round(l.makereel_mem / 1e6)} MB memory`;
  $("#ld-temp-box").hidden = l.temp == null;
  if (l.temp != null) {
    $("#ld-temp").textContent = `${Math.round(l.temp)} °C`;
    $("#ld-heat").textContent = l.heat;
    $("#ld-heat").className = `load-sub heat-${l.heat}`;
  }
  const work = (jobs || []).find((j) => /transcribing|rendering|framing|speech model/i.test(j.last_line || "")
                                         && ["live", "running"].includes(j.status));
  $("#ld-note").textContent = work
    ? `Busy: ${/transcrib|speech/i.test(work.last_line) ? "listening to the audio" : "rendering a reel"} for "${work.title.slice(0, 40)}". Spikes like this are normal and pass in about a minute.`
    : own > 5 ? "Recording and watching for moments." : "Idle.";
  if (l.heat === "hot") $("#ld-note").textContent += " Running hot: Settings → Processing → Cool and quiet, or fewer reels per hour.";
}

export async function refreshLogs() {
  const ids = Object.keys(store.state.openLogs);
  if (!ids.length) return;
  const logs = { ...store.state.openLogs };
  await Promise.all(ids.map(async (id) => {
    try { logs[id] = (await api.job(id)).log || "(no output yet)"; } catch (err) { delete logs[id]; showError(err); }
  }));
  store.set({ openLogs: logs });
}
