// "System" tab: this device, benchmark runs, history and comparisons. Nothing leaves the device
// unless the user clicks Share (which only opens a pre-filled issue for them to review).
import { api } from "../api.js";
import { store } from "../store.js";
import { $, busy, copyText, esc, timeAgo, toast } from "../ui.js";

let data = null;          // { device, runs, share_enabled }
let selected = null;      // full result with compare + report
let lastJobState = "";

export async function load() {
  data = await api.bench();
  draw();
  if (!selected && data.runs[0]) await select(data.runs[0].id);
}

async function select(id) {
  selected = await api.benchResult(id);
  drawResult();
}

const fmtPct = (v) => (v === null || v === undefined ? "—"
  : `<span class="${v <= 0 ? "good" : "bad"}">${v > 0 ? "+" : ""}${v}%</span>`);

function draw() {
  const d = data.device;
  const gpu = d.gpu && d.gpu !== "unknown" ? ` · ${esc(d.gpu)}` : "";
  const power = d.on_battery ? ` · <span class="bad">on battery (slower)</span>` : "";
  $("#sys-device").innerHTML = `<div>${esc(d.cpu)} · ${d.cores_physical} cores · ${d.ram_gb} GB memory${gpu}${power}</div>
    <div class="hint" style="margin:4px 0 0">Video ${d.encoder === "libx264" ? "made on the processor" : "uses hardware encoding"}.</div>
    <details style="margin-top:6px"><summary class="hint" style="margin:0">Technical details</summary><table class="kv">
    <tr><td>Video encoder</td><td>${esc(d.encoder)}</td></tr>
    <tr><td>System</td><td>${esc(d.os)} · ${esc(d.arch)} · Python ${esc(d.python)} · ffmpeg ${esc(d.ffmpeg)}</td></tr>
  </table></details>`;
  $("#sys-runs").innerHTML = data.runs.length ? `<table class="grid">
    <thead><tr><th>When</th><th>Version</th><th>Model</th><th>Total</th><th>Speed</th><th>CPU time</th><th>Peak RAM</th></tr></thead>
    <tbody>${data.runs.map((r) => `<tr data-id="${r.id}" class="${selected?.id === r.id ? "on" : ""}">
      <td>${timeAgo(r.time)}</td><td>${esc(r.device.makereel)}</td><td>${esc(r.model)}</td>
      <td>${r.wall_s}s</td><td>${r.speed_x}×</td><td>${r.cpu_seconds}s</td><td>${r.ram_peak_mb} MB</td></tr>`).join("")}</tbody>
  </table>` : `<div class="empty">No benchmarks yet.</div>`;
}

function drawResult() {
  const r = selected;
  if (!r) return;
  const c = r.compare;
  const stages = Object.entries(r.stages_s).filter(([, v]) => v > 0);
  const total = stages.reduce((a, [, v]) => a + v, 0) || 1;
  $("#sys-result").innerHTML = `
    <div class="stats">
      <div><b>${r.wall_s}s</b><span>total for ${r.reels} reel${r.reels === 1 ? "" : "s"}</span></div>
      <div><b>${r.speed_x}×</b><span>real time</span></div>
      <div><b>${r.cpu_seconds}s</b><span>CPU time (energy proxy)</span></div>
      <div><b>${r.cpu_avg_pct}%</b><span>avg CPU (peak ${r.cpu_peak_pct}%)</span></div>
      <div><b>${r.ram_peak_mb} MB</b><span>peak RAM</span></div>
      <div><b>${r.disk_peak_mb} MB</b><span>peak disk while working</span></div>
      <div><b>${r.gpu_avg_pct ?? "—"}${r.gpu_avg_pct !== null ? "%" : ""}</b><span>GPU load${r.gpu_avg_pct === null ? " (NVIDIA only)" : ""}</span></div>
    </div>
    <div class="bar">${stages.map(([k, v]) => `<span style="flex:${v}" title="${k}: ${v}s">${v / total > 0.09 ? `${k} ${v}s` : ""}</span>`).join("")}</div>
    <p class="hint">${c ? `Compared with the previous run (v${esc(c.against_version)}): time ${fmtPct(c.wall_pct)} · CPU ${fmtPct(c.cpu_seconds_pct)} · RAM ${fmtPct(c.ram_peak_pct)}`
      : "Run it again after an update to see what changed."}</p>
    <div class="row">
      <button class="btn small" id="sys-copy">Copy report</button>
      ${r.share_url ? `<a class="btn small" href="${r.share_url}" target="_blank" rel="noopener">Share with the project…</a>` : ""}
    </div>`;
  $("#sys-copy").onclick = () => copyText(r.report).then(() => toast("Report copied (hardware + timings only)"));
}

export function render(state) {
  // follow the benchmark job: refresh when it finishes
  const job = state.jobs.find((j) => j.kind === "bench");
  const key = job ? `${job.id}:${job.status}` : "";
  $("#sys-status").textContent = job && ["queued", "running"].includes(job.status) ? "Benchmark running… (about 30–60 s)" : "";
  if (key !== lastJobState) {
    lastJobState = key;
    if (job?.status === "done" && job.result) { select(job.result.id).then(load); }
    if (job?.status === "failed") toast(job.error?.message || "Benchmark failed");
  }
}

export function mount() {
  $("#sys-run").addEventListener("click", (e) => {
    const ok = $("#sys-consent").checked;
    if (!ok) return toast("Tick the box to allow the benchmark to run on this device");
    busy(e.currentTarget, async () => {
      await api.runBench({ model: $("#sys-model").value || undefined });
      store.set({ jobs: (await api.jobs()).jobs });
    });
  });
  $("#sys-runs").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row) select(row.dataset.id).then(draw);
  });
}
