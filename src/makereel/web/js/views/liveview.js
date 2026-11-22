// Live dashboard for a recording: loudness, chat and excited words over time, with the moments found.
import { api } from "../api.js";
import { $, esc, showError } from "../ui.js";

let jobId = null, timer = null;
const W = 860, H = 220, PAD = 28;

const clock = (s) => `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)}:` : ""}${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function line(points, key, max, cls) {
  const pts = points.filter((p) => p[key] !== null);
  if (!pts.length) return "";
  return `<polyline class="${cls}" fill="none" points="${pts.map((p) => `${p.x.toFixed(1)},${(H - PAD - (p[key] / max) * (H - 2 * PAD)).toFixed(1)}`).join(" ")}"/>`;
}

function draw(d) {
  const b = d.buckets, t0 = d.from, t1 = Math.max(d.seconds, t0 + 60);
  const x = (t) => PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD);
  const louds = b.map((v) => v.loud).filter((v) => v !== null);
  const lo = louds.length ? Math.min(...louds) : -60, hi = louds.length ? Math.max(...louds) : 0;
  const pts = b.map((v) => ({ x: x(v.t), loud: v.loud === null ? null : v.loud - lo, chat: v.chat, hype: v.hype }));
  const maxChat = Math.max(1, ...b.map((v) => v.chat)), maxHype = Math.max(1, ...b.map((v) => v.hype));
  const ticks = [];
  for (let k = 0; k <= 4; k++) { const t = t0 + ((t1 - t0) * k) / 4; ticks.push(`<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${clock(t)}</text>`); }
  const marks = d.moments.map((m) => `<g class="${m.reel ? "lv-m reel" : "lv-m"}"><line x1="${x(m.t)}" x2="${x(m.t)}" y1="${PAD}" y2="${H - PAD}"/>
    <text x="${x(m.t)}" y="${PAD - 6}" text-anchor="middle">▲</text><title>${clock(m.t)}: ${esc(m.why.join(", "))}</title></g>`).join("");
  $("#lv-chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="lv-svg" role="img" aria-label="Loudness, chat and excited words over time">
    <line class="lv-axis" x1="${PAD}" x2="${W - PAD}" y1="${H - PAD}" y2="${H - PAD}"/>${ticks.join("")}
    ${line(pts, "loud", Math.max(1, hi - lo), "lv-loud")}${line(pts, "chat", maxChat, "lv-chat")}${line(pts, "hype", maxHype, "lv-hype")}${marks}</svg>`;
  const made = d.moments.filter((m) => m.reel).length;
  $("#lv-sum").textContent = `${clock(d.seconds)} recorded · ${d.moments.length} moment${d.moments.length === 1 ? "" : "s"} shown · ${d.reels} reel${d.reels === 1 ? "" : "s"} this hour (limit ${d.per_hour})`;
  $("#lv-moments").innerHTML = d.moments.length ? d.moments.slice().sort((p, q) => q.t - p.t).map((m) => `<div class="ch-row">
    <b>${clock(m.t)}</b><span class="chip">${esc(m.why.join(" + "))}</span>
    <span class="hint" style="margin:0 0 0 auto">${m.reel === undefined ? "still going…" : m.reel === null ? "making a reel…" : m.reel ? "reel made" : "no reel (hourly limit or nothing usable)"}</span></div>`).join("")
    : `<p class="hint">No moments yet. They show up when loudness, chat or excited words jump above the last few minutes${made ? "" : " (the first 90 seconds only learn what normal sounds like)"}.</p>`;
}

async function refresh() {
  if (!jobId) return;
  try { draw(await api.jobLive(jobId, $("#lv-min").value)); }
  catch (err) { stop(); showError(err); }
}

function stop() { clearInterval(timer); timer = null; jobId = null; }

export function open(id, title) {
  jobId = id;
  $("#lv-title").textContent = title ? `Live: ${title}` : "Live";
  $("#liveview").showModal();
  refresh();
  clearInterval(timer);
  timer = setInterval(refresh, 5000);
}

export function mount() {
  $("#lv-close").addEventListener("click", () => $("#liveview").close());
  $("#liveview").addEventListener("close", stop);
  $("#lv-min").addEventListener("change", refresh);
}
