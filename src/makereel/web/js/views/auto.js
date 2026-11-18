// "24/7" tab: channel list, limits, and the watcher switch.
import { api } from "../api.js";
import { store } from "../store.js";
import { $, busy, showError, toast } from "../ui.js";

const LIMITS = ["poll_minutes", "clips_per_hour", "max_parallel_live", "buffer_minutes", "keep_days"];
let filled = false;

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

export async function load() {
  const [settings, watcher, st] = await Promise.all([api.settings(), api.watcher(), api.storage()]);
  store.set({ settings, watcher: watcher.running });
  drawStorage(st);
}

export function render(state) {
  if (document.activeElement !== $("#watch")) $("#watch").checked = state.watcher;
  if (!filled && state.settings) {   // fill the form once; don't overwrite what the user is typing
    $("#channels").value = state.settings.channels.join("\n");
    LIMITS.forEach((k) => ($(`#${k}`).value = state.settings[k]));
    $("#watch_uploads").checked = state.settings.watch_uploads !== false;
    const since = state.settings.uploads_since || "new";
    $("#uploads_since_kind").value = ["new", "24h", "48h"].includes(since) ? since : "date";
    $("#uploads_date").value = /^\d{4}-/.test(since) ? since : new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    $("#uploads_every").value = state.settings.uploads_every || "5";
    $("#cookies_browser").value = state.settings.cookies_browser || "";
    $("#cpu_mode").value = state.settings.cpu_mode || "balanced";
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
  $("#ai-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const ai = { provider: $("#ai-provider").value, model: $("#ai-model").value.trim(),
                 base_url: $("#ai-base_url").value.trim(), weight: Number($("#ai-weight").value) };
    store.set({ settings: await api.saveSettings({ ai }) });
    toast(ai.provider === "off" ? "AI judge off" : "AI judge saved. It's used for the next videos you clip.");
  }));
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

  $("#save-settings").addEventListener("click", (e) => {
    const body = { channels: $("#channels").value.split("\n") };
    LIMITS.forEach((k) => (body[k] = $(`#${k}`).value));
    busy(e.currentTarget, async () => {
      store.set({ settings: await api.saveSettings(body) });
      toast("Saved. The watcher uses it on its next check.");
    });
  });
}
