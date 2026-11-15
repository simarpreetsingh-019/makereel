// "24/7" tab: channel list, limits, and the watcher switch.
import { api } from "../api.js";
import { store } from "../store.js";
import { $, busy, showError, toast } from "../ui.js";

const LIMITS = ["poll_minutes", "clips_per_hour", "max_parallel_live", "buffer_minutes", "keep_days"];
let filled = false;

export async function load() {
  const [settings, watcher] = await Promise.all([api.settings(), api.watcher()]);
  store.set({ settings, watcher: watcher.running });
}

export function render(state) {
  if (document.activeElement !== $("#watch")) $("#watch").checked = state.watcher;
  if (!filled && state.settings) {   // fill the form once; don't overwrite what the user is typing
    $("#channels").value = state.settings.channels.join("\n");
    LIMITS.forEach((k) => ($(`#${k}`).value = state.settings[k]));
    filled = true;
  }
}

export function mount() {
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

  $("#save-settings").addEventListener("click", (e) => {
    const body = { channels: $("#channels").value.split("\n") };
    LIMITS.forEach((k) => (body[k] = $(`#${k}`).value));
    busy(e.currentTarget, async () => {
      store.set({ settings: await api.saveSettings(body) });
      toast("Saved. The watcher uses it on its next check.");
    });
  });
}
