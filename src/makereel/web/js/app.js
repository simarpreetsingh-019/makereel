// Entry point: hash routing, polling, and wiring views to the store.
//   #/create · #/library · #/library/<folder> · #/auto · #/brand · #/system
import { api } from "./api.js";
import { store } from "./store.js";
import { $, esc, showError } from "./ui.js";
import * as auto from "./views/auto.js";
import * as brand from "./views/brand.js";
import * as create from "./views/create.js";
import * as editor from "./views/editor.js";
import * as library from "./views/library.js";
import * as setup from "./views/setup.js";
import * as system from "./views/system.js";
import * as wizard from "./views/wizard.js";
import * as liveview from "./views/liveview.js";

const POLL_MS = 2500;

function parseRoute() {
  const [, view = "create", folder] = location.hash.split("/");
  if (view === "library" && folder) return { view: "folder", folder: decodeURIComponent(folder) };
  return { view: ["create", "library", "auto", "brand", "system"].includes(view) ? view : "create" };
}

async function refreshJobs() {
  try {
    store.set({ jobs: (await api.jobs()).jobs });
    const live = store.state.jobs.filter((j) => j.status === "live" && j.kind !== "watcher").length;
    const busy = store.state.jobs.filter((j) => ["running", "queued"].includes(j.status)).length;
    const nb = $("#nb-create");
    nb.hidden = !(live || busy);
    nb.textContent = live ? `● ${live} live` : `${busy}`;
    nb.title = live ? `${live} live stream${live === 1 ? "" : "s"} recording` : `${busy} job${busy === 1 ? "" : "s"} running`;
    setup.botCheck(store.state.jobs);
    if (store.state.route.view === "create") create.refreshLoad(store.state.jobs);
    await create.refreshLogs();
  } catch (err) { showError(err); }
}

async function refreshView() {
  const { route } = store.state;
  try {
    if (route.view === "library") await library.load();
    if (route.view === "folder") await library.load(route.folder);
    if (route.view === "auto") await auto.load();
    if (route.view === "brand") await brand.load();
    if (route.view === "system") await Promise.all([system.load(), setup.load()]);
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
    $("#sys").textContent = `makereel v${sys.version}`;
    $("#sys").title = `${sys.os} · video encoder ${sys.encoder || "none"}`;
    $("#banner").innerHTML = sys.libass ? "" : `<div class="banner">This ffmpeg can't draw text captions, so reels will fail.
      Install a full build: macOS <code>brew install ffmpeg-full</code> · Windows <code>winget install Gyan.FFmpeg</code> · Linux <code>sudo apt install ffmpeg</code>.</div>`;
  }
  create.render(state);
  if (tab === "library") library.render(state);
  if (tab === "auto") auto.render(state);
  if (tab === "system") system.render(state);
}

// ⋯ menus close when you pick something or click elsewhere
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.menu[open]").forEach((m) => {
    if (!m.contains(e.target) || e.target.closest(".menu-list button, .menu-list a")) m.open = false;
  });
});

async function start() {
  create.mount(refreshJobs);
  library.mount();
  editor.mount();
  auto.mount();
  brand.mount();
  system.mount();
  setup.mount();
  wizard.mount();
  liveview.mount();
  store.subscribe(render);

  window.addEventListener("hashchange", () => { store.set({ route: parseRoute() }); refreshView(); });
  store.set({ route: parseRoute() });

  try { store.set({ system: await api.system() }); }
  catch (err) { $("#banner").innerHTML = `<div class="banner">${esc(err.message)}</div>`; }

  await Promise.all([refreshJobs(), refreshView()]);
  api.settings().then((s) => { setup.drawNotices(s); wizard.maybeOpen(s); }).catch(() => {});
  setInterval(() => {
    if (document.hidden) return;              // save power when the tab is in the background
    refreshJobs();
    if (["library", "folder"].includes(store.state.route.view)) refreshView();
  }, POLL_MS);
}

start();
