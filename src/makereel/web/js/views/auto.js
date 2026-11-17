// "24/7" tab: channel list, limits, and the watcher switch.
import { api } from "../api.js";
import { store } from "../store.js";
import { $, busy, showError, toast } from "../ui.js";

const LIMITS = ["poll_minutes", "clips_per_hour", "max_parallel_live", "buffer_minutes", "keep_days"];
let filled = false;

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

export async function load() {
  const [settings, watcher] = await Promise.all([api.settings(), api.watcher()]);
  store.set({ settings, watcher: watcher.running });
}

export function render(state) {
  if (document.activeElement !== $("#watch")) $("#watch").checked = state.watcher;
  if (!filled && state.settings) {   // fill the form once; don't overwrite what the user is typing
    $("#channels").value = state.settings.channels.join("\n");
    LIMITS.forEach((k) => ($(`#${k}`).value = state.settings[k]));
    $("#watch_uploads").checked = state.settings.watch_uploads !== false;
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

  $("#watch_uploads").addEventListener("change", async (e) => {
    try {
      store.set({ settings: await api.saveSettings({ watch_uploads: e.target.checked }) });
      toast(e.target.checked ? "New uploads will be clipped too" : "Only live streams will be clipped");
    } catch (err) {
      e.target.checked = !e.target.checked;
      showError(err);
    }
  });

  $("#save-settings").addEventListener("click", (e) => {
    const body = { channels: $("#channels").value.split("\n") };
    LIMITS.forEach((k) => (body[k] = $(`#${k}`).value));
    busy(e.currentTarget, async () => {
      store.set({ settings: await api.saveSettings(body) });
      toast("Saved. The watcher uses it on its next check.");
    });
  });
}
