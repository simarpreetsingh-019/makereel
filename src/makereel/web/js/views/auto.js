// "24/7" tab: channel list, limits, and the watcher switch.
import { api } from "../api.js";
import { store } from "../store.js";
import { $, busy, esc, showError, toast } from "../ui.js";

const LIMITS = ["poll_minutes", "clips_per_hour", "max_parallel_live", "buffer_minutes", "keep_days"];
let filled = false;

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// a small "Saved ✓" next to the settings tabs, for any setting that saved itself
function savedTick() {
  const el = $("#st-saved");
  el.hidden = false;
  clearTimeout(savedTick.t);
  savedTick.t = setTimeout(() => (el.hidden = true), 1800);
}

const SINCE_HELP = {
  new: "Videos already on a channel are left alone; anything posted after makereel first checks it is clipped.",
  "24h": "The first check also clips what each channel posted in the last 24 hours, then every new upload.",
  "48h": "The first check also clips what each channel posted in the last 48 hours, then every new upload.",
  date: "The first check also clips what each channel posted since this date (its 15 newest videos at most), then every new upload.",
};

function drawUploads() {
  const on = $("#watch_uploads").checked, kind = $("#uploads_since_kind").value;
  $("#uploads-opts").hidden = !on;
  $("#uploads_date_field").hidden = kind !== "date";
  $("#uploads-hint").textContent = on ? SINCE_HELP[kind] : "";
}

function uploadsBody() {
  const kind = $("#uploads_since_kind").value;
  return { watch_uploads: $("#watch_uploads").checked, uploads_every: $("#uploads_every").value,
           uploads_since: kind === "date" ? $("#uploads_date").value : kind };
}

const AI_HELP = {
  off: "Off: picks come from loudness, chat and hype words. Free and fully offline.",
  local: "Runs on this computer. Install Ollama (ollama.com), run `ollama pull llama3.1:8b`, and leave Model empty. Nothing leaves your machine. Models under 7B often return broken results.",
  claude: "Uses your Anthropic API key. Put MAKEREEL_AI_KEY=... in the .env file (never in this form), then run: pip install \"makereel[ai]\". It costs a fraction of a cent per video.",
  openai: "Any OpenAI-compatible API (OpenAI, OpenRouter, Groq…). Put MAKEREEL_AI_KEY=... in .env, and set Model and, if needed, the server address.",
};

function drawAi() {
  const p = $("#ai-provider").value;
  $("#ai-help").textContent = AI_HELP[p];
  ["#ai-model", "#ai-base_url", "#ai-weight"].forEach((id) => ($(id).disabled = p === "off"));
  $("#ai-base_url").disabled = p === "off" || p === "claude";
  $("#ai-weight-v").textContent = `${Math.round(Number($("#ai-weight").value) * 100)}%`;
}

const gb = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);

function drawStorage(st) {
  $("#st-summary").textContent = `Reels: ${gb(st.reels_bytes)} · cache: ${gb(st.cache_bytes)} · ${gb(st.free_bytes)} free on this disk.`;
  if (document.activeElement !== $("#st-reels")) $("#st-reels").value = st.reels_folder;
  if (document.activeElement !== $("#st-work")) $("#st-work").value = st.work_folder;
  $("#st-reels").disabled = $("#st-reels-save").disabled = st.fixed_by_env.reels;
  $("#st-work").disabled = $("#st-work-save").disabled = st.fixed_by_env.work;
}

function drawSignIn(st) {
  $("#yt-status").innerHTML = `${st.ok ? "✅" : st.blocked ? "⛔" : "ℹ️"} ${esc(st.message)}`;
  $("#yt-remove").hidden = st.source !== "file";
}

// ------------------------------------------------------------------ channel rows (the hidden #channels box is the source)
let chState = {};
const LANG_NAME = { en: "English", hi: "Hindi", pa: "Punjabi", ta: "Tamil", te: "Telugu", bn: "Bengali", mr: "Marathi", es: "Spanish" };
function chLines() { return $("#channels").value.split("\n").map((l) => l.trim()).filter(Boolean); }
function chParse(line) { const [name, lang] = line.split("|").map((x) => x.trim()); return { name, lang: lang || "" }; }
function drawChannels() {
  const lines = chLines();
  $("#ch-rows").innerHTML = lines.length ? lines.map((l, i) => {
    const { name, lang } = chParse(l), st = chState[name]?.state;
    const dot = st === "live" ? `<span class="ch-dot live" title="Live now"></span>`
      : st ? `<span class="ch-dot" title="Offline at last check"></span>` : `<span class="ch-dot unknown" title="Not checked yet"></span>`;
    return `<div class="ch-row">${dot}<b>${esc(name)}</b>${lang ? `<span class="chip">${esc(LANG_NAME[lang] || lang)}</span>` : ""}
      <span class="hint" style="margin:0 0 0 auto">${st === "live" ? "Live now" : st ? "Offline" : ""}</span>
      <button class="btn small ghost" type="button" data-ch-del="${i}" title="Remove" aria-label="Remove ${esc(name)}">×</button></div>`;
  }).join("") : `<p class="hint">No channels yet. Add one below.</p>`;
}
const CH_OK = /^(@[\w.-]{2,}|(https?:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.be|twitch\.tv|kick\.com)\/\S+)$/i;

export async function load() {
  const [settings, watcher, st] = await Promise.all([api.settings(), api.watcher(), api.storage()]);
  store.set({ settings, watcher: watcher.running });
  chState = watcher.channels || {};
  if (filled) drawChannels();
  drawStorage(st);
  api.ytSignIn().then(drawSignIn).catch(() => {});
  api.creators().then(({ creators }) => {
    const sel = $("#cr-channel"), keep = sel.value;
    sel.innerHTML = `<option value="">Pick a creator…</option>` + creators.map((c) => `<option>${esc(c)}</option>`).join("");
    sel.value = keep;
  }).catch(() => {});
}

export function render(state) {
  if (document.activeElement !== $("#watch")) $("#watch").checked = state.watcher;
  if (!filled && state.settings) {   // fill the form once; don't overwrite what the user is typing
    $("#channels").value = state.settings.channels.join("\n");
    drawChannels();
    $("#watch_language").value = state.settings.watch_language || "";
    LIMITS.forEach((k) => ($(`#${k}`).value = state.settings[k]));
    $("#watch_uploads").checked = state.settings.watch_uploads !== false;
    const since = state.settings.uploads_since || "new";
    $("#uploads_since_kind").value = ["new", "24h", "48h"].includes(since) ? since : "date";
    $("#uploads_date").value = /^\d{4}-/.test(since) ? since : new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    $("#uploads_every").value = state.settings.uploads_every || "5";
    $("#cookies_browser").value = state.settings.cookies_browser || "";
    $("#cpu_mode").value = state.settings.cpu_mode || "balanced";
    $("#caption_check").checked = state.settings.clip?.caption_check !== false;
    $("#youtube_captions").value = state.settings.clip?.youtube_captions || "use";
    $("#names").value = (state.settings.clip?.names || []).join("\n");
    drawUploads();
    const ai = state.settings.ai || {};
    $("#ai-provider").value = ai.provider || "off";
    $("#ai-model").value = ai.model || "";
    $("#ai-base_url").value = ai.base_url || "";
    $("#ai-weight").value = ai.weight ?? 0.5;
    drawAi();
    filled = true;
  }
}

export function mount() {
  ["#ai-provider", "#ai-weight"].forEach((id) => $(id).addEventListener("input", drawAi));
  // AI settings save on their own (typing: after a pause; choices: right away)
  const saveAi = async () => {
    const ai = { provider: $("#ai-provider").value, model: $("#ai-model").value.trim(),
                 base_url: $("#ai-base_url").value.trim(), weight: Number($("#ai-weight").value) };
    try { store.set({ settings: await api.saveSettings({ ai }) }); savedTick(); } catch (err) { showError(err); }
  };
  ["#ai-provider", "#ai-weight"].forEach((id) => $(id).addEventListener("change", saveAi));
  ["#ai-model", "#ai-base_url"].forEach((id) => $(id).addEventListener("input", debounce(saveAi, 800)));
  $("#watch").addEventListener("change", async (e) => {
    try {
      const { running } = await api.setWatcher(e.target.checked);
      store.set({ watcher: running });
      toast(running ? "Watching your channels" : "Stopped watching");
    } catch (err) {
      e.target.checked = !e.target.checked;
      showError(err);
    }
  });

  $("#yt-open").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const browser = $("#cookies_browser").value || "chrome";
    await api.ytOpen(browser);
    toast(`Opened YouTube in ${$("#cookies_browser").selectedOptions[0]?.text || browser}. Sign in there, then press Test sign-in.`);
  }));
  $("#yt-test").addEventListener("click", (e) => busy(e.currentTarget, async () => drawSignIn(await api.ytSignIn())));
  $("#yt-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    busy(null, async () => { drawSignIn(await api.putFile("/youtube/cookies", file)); toast("Sign-in file saved"); });
    e.target.value = "";
  });
  $("#yt-remove").addEventListener("click", (e) => busy(e.currentTarget, async () => drawSignIn(await api.ytRemoveCookies())));
  $("#caption_check").addEventListener("change", async (e) => {
    try {
      store.set({ settings: await api.saveSettings({ clip: { caption_check: e.target.checked } }) });
      savedTick();
    } catch (err) { showError(err); }
  });
  $("#youtube_captions").addEventListener("change", async (e) => {
    try {
      store.set({ settings: await api.saveSettings({ clip: { youtube_captions: e.target.value } }) });
      savedTick();
    } catch (err) { showError(err); }
  });
  const bulkWatch = (st) => {
    const msg = $("#bulk-msg");
    msg.textContent = st.running ? `Updating reels… ${st.done} of ${st.total}` : st.message;
    $("#bulk-hinglish").disabled = $("#bulk-convert").disabled = st.running;
    if (st.running) setTimeout(async () => bulkWatch(await api.bulkLettersStatus()), 2000);
  };
  [["#bulk-hinglish", "hinglish"], ["#bulk-convert", "convert"]].forEach(([id, src]) =>
    $(id).addEventListener("click", async () => {
      try { bulkWatch(await api.bulkLetters(src)); } catch (err) { showError(err); }
    }));
  const showCreator = (c) => {
    $("#cr-names").value = (c.names || []).join("\n");
    $("#cr-notes").value = c.notes || "";
    $("#cr-suggest").innerHTML = c.suggested?.length
      ? `Often in their reels (click to add): ${c.suggested.map((w) => `<button type="button" class="btn tiny cr-add">${esc(w)}</button>`).join(" ")}`
      : "";
  };
  $("#cr-channel").addEventListener("change", async (e) => {
    if (e.target.value) showCreator(await api.creator(e.target.value));
  });
  $("#cr-find").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    if (!$("#cr-channel").value) return toast("Pick a creator first");
    const c = await api.creator($("#cr-channel").value, true);
    showCreator({ ...c, names: $("#cr-names").value.split("\n"), notes: $("#cr-notes").value });
    if (!c.suggested.length) toast("Nothing new keeps coming up in their reels yet");
  }));
  $("#cr-suggest").addEventListener("click", (e) => {
    const b = e.target.closest(".cr-add");
    if (!b) return;
    $("#cr-names").value = ($("#cr-names").value.trim() + "\n" + b.textContent).trim();
    b.remove();
  });
  $("#cr-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const ch = $("#cr-channel").value;
    if (!ch) return toast("Pick a creator first");
    await api.saveCreator(ch, $("#cr-names").value.split("\n"), $("#cr-notes").value);
    toast(`Saved. ${ch}'s new reels use these names.`);
  }));
  $("#cpu_mode").addEventListener("change", async (e) => {
    try {
      store.set({ settings: await api.saveSettings({ cpu_mode: e.target.value }) });
      toast({ quiet: "Cool and quiet: gentler on the CPU from the next reel", balanced: "Balanced processing",
              fast: "Fast processing: uses most cores" }[e.target.value]);
    } catch (err) { showError(err); }
  });
  $("#cookies_browser").addEventListener("change", async (e) => {
    try {
      store.set({ settings: await api.saveSettings({ cookies_browser: e.target.value }) });
      toast(e.target.value ? `Using your ${e.target.selectedOptions[0].text} YouTube sign-in for new checks` : "Not using a YouTube sign-in");
    } catch (err) { showError(err); }
  });
  // upload watching saves as soon as it changes
  ["#watch_uploads", "#uploads_since_kind", "#uploads_date", "#uploads_every"].forEach((id) =>
    $(id).addEventListener("change", async () => {
      drawUploads();
      const body = uploadsBody();
      if ($("#uploads_since_kind").value === "date" && !body.uploads_since) return;
      try {
        store.set({ settings: await api.saveSettings(body) });
        toast(body.watch_uploads ? "Upload watching saved. It applies on the next check." : "Only live streams will be clipped");
      } catch (err) {
        showError(err);
      }
    }));

  $("#st-reels-open").addEventListener("click", (e) => busy(e.currentTarget, () => api.openFolder("reels")));
  $("#st-work-open").addEventListener("click", (e) => busy(e.currentTarget, () => api.openFolder("work")));
  $("#st-reels-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const res = await api.setReelsFolder($("#st-reels").value.trim(), $("#st-move").checked);
    drawStorage(res);
    toast(res.moved ? `Saving reels in the new folder; moved ${res.moved} video folder${res.moved === 1 ? "" : "s"} there`
                    : "New reels are saved in this folder");
  }));
  $("#st-work-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    await api.saveSettings({ work_folder: $("#st-work").value.trim() });
    drawStorage(await api.storage());
    toast("Cache folder changed (used by new jobs)");
  }));
  $("#st-clear").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const res = await api.clearCache();
    drawStorage(res);
    toast(`Freed ${gb(res.freed_bytes)}${res.kept.length ? ` (kept ${res.kept.length} live recording${res.kept.length === 1 ? "" : "s"})` : ""}`);
  }));

  // channels, limits and names save on their own, a moment after you stop typing
  const saveGeneral = async () => {
    const body = { channels: $("#channels").value.split("\n"), watch_language: $("#watch_language").value,
                   clip: { names: $("#names").value.split("\n") } };
    LIMITS.forEach((k) => (body[k] = $(`#${k}`).value));
    try { store.set({ settings: await api.saveSettings(body) }); savedTick(); } catch (err) { showError(err); }
  };
  const later = debounce(saveGeneral, 900);
  $("#ch-rows").addEventListener("click", (e) => {
    const i = e.target.closest("[data-ch-del]")?.dataset.chDel;
    if (i === undefined) return;
    const lines = chLines(); lines.splice(+i, 1);
    $("#channels").value = lines.join("\n"); drawChannels(); saveGeneral();
  });
  $("#ch-add").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("#ch-new").value.trim(), lang = $("#ch-new-lang").value, msg = $("#ch-add-msg");
    if (!CH_OK.test(name)) { msg.textContent = "That doesn't look like a channel. Try @name or a YouTube, Twitch or Kick link."; return; }
    if (chLines().some((l) => chParse(l).name.toLowerCase() === name.toLowerCase())) { msg.textContent = "Already in the list."; return; }
    $("#channels").value = [...chLines(), lang ? `${name} | ${lang}` : name].join("\n");
    $("#ch-new").value = ""; $("#ch-new-lang").value = ""; msg.textContent = "";
    drawChannels(); saveGeneral();
  });
  ["#names", ...LIMITS.map((k) => `#${k}`)].forEach((id) => $(id).addEventListener("input", later));
  $("#watch_language").addEventListener("change", saveGeneral);

  // settings tabs
  document.querySelectorAll("#tab-auto [data-st]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#tab-auto [data-st]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    document.querySelectorAll("#tab-auto [data-stpane]").forEach((p) => (p.hidden = p.dataset.stpane !== b.dataset.st));
    try { localStorage.setItem("mr-settings-tab", b.dataset.st); } catch { /* private window */ }
  }));
  let tab = null;
  try { tab = localStorage.getItem("mr-settings-tab"); } catch { /* private window */ }
  document.querySelector(`#tab-auto [data-st="${tab || "channels"}"]`)?.click();;
}
