// Entry point: hash routing, polling, and wiring views to the store.
//   #/create · #/library · #/library/<folder> · #/auto
import { api } from "./api.js";
import { store } from "./store.js";
import { $, esc, showError } from "./ui.js";
import * as auto from "./views/auto.js";
import * as create from "./views/create.js";
import * as editor from "./views/editor.js";
import * as library from "./views/library.js";

const POLL_MS = 2500;

function parseRoute() {
  const [, view = "create", folder] = location.hash.split("/");
  if (view === "library" && folder) return { view: "folder", folder: decodeURIComponent(folder) };
  return { view: ["create", "library", "auto"].includes(view) ? view : "create" };
}

async function refreshJobs() {
  try {
    store.set({ jobs: (await api.jobs()).jobs });
    await create.refreshLogs();
  } catch (err) { showError(err); }
}

async function refreshView() {
  const { route } = store.state;
  try {
    if (route.view === "library") await library.load();
    if (route.view === "folder") await library.load(route.folder);
    if (route.view === "auto") await auto.load();
  } catch (err) {
    showError(err);
    if (route.view === "folder") location.hash = "#/library";
  }
}

function render(state) {
  const tab = state.route.view === "folder" ? "library" : state.route.view;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== `tab-${tab}`));
  const sys = state.system;
  if (sys) {
    $("#sys").textContent = `${sys.os} · encoder ${(sys.encoder || "none").replace("h264_", "")} · v${sys.version}`;
    $("#banner").innerHTML = sys.libass ? "" : `<div class="banner">This ffmpeg can't draw text captions, so reels will fail.
      Install a full build: macOS <code>brew install ffmpeg-full</code> · Windows <code>winget install Gyan.FFmpeg</code> · Linux <code>sudo apt install ffmpeg</code>.</div>`;
  }
  create.render(state);
  if (tab === "library") library.render(state);
  if (tab === "auto") auto.render(state);
}

async function start() {
  create.mount(refreshJobs);
  library.mount();
  editor.mount();
  auto.mount();
  store.subscribe(render);

  window.addEventListener("hashchange", () => { store.set({ route: parseRoute() }); refreshView(); });
  store.set({ route: parseRoute() });

  try { store.set({ system: await api.system() }); }
  catch (err) { $("#banner").innerHTML = `<div class="banner">${esc(err.message)}</div>`; }

  await Promise.all([refreshJobs(), refreshView()]);
  setInterval(() => {
    if (document.hidden) return;              // save power when the tab is in the background
    refreshJobs();
    if (store.state.route.view !== "auto") refreshView();
  }, POLL_MS);
}

start();
