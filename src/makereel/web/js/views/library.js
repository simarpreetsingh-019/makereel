// "Reels" tab: one folder per source video; open a folder to see and edit its reels.
import { api, media } from "../api.js";
import { store } from "../store.js";
import { $, busy, copyText, esc, showError, timeAgo, toast, undoable } from "../ui.js";
import { openEditor } from "./editor.js";

let lastDrawn = "";   // avoid redrawing (and restarting videos) when nothing changed
let joining = null;   // null, or the reel names picked to join, in click order
const gone = new Set();  // folders / "folder/reel" waiting out their Undo: hidden, not yet deleted
const redraw = () => { lastDrawn = null; render(store.state); };
let sortBest = true;  // best score first, or in the order they happen in the video
try { sortBest = localStorage.getItem("mr-reel-sort") !== "time"; } catch { /* private mode */ }

export async function load(folder) {
  if (folder !== store.state.folder?.folder) joining = null;
  if (folder) store.set({ folder: await api.folder(folder) });
  else store.set({ folders: (await api.folders()).folders, folder: null });
}

function foldersHTML(folders, query) {
  const q = query.toLowerCase();
  const list = folders.filter((f) => !gone.has(f.folder)).filter((f) => !q || `${f.title} ${f.channel}`.toLowerCase().includes(q));
  if (!list.length) return `<div class="empty">${folders.length ? "No folder matches." : "No reels yet. Paste a link in Create."}</div>`;
  return `<div class="folders">${list.map((f) => `
    <div class="folder" data-folder="${esc(f.folder)}" role="link" tabindex="0">
      <button class="btn tiny folder-del" data-del-folder="${esc(f.folder)}" title="Delete this folder">Delete</button>
      <div class="cover">${f.cover ? `<video src="${esc(media(f.cover))}#t=1" preload="metadata" muted></video>` : `<span class="icon">📁</span>`}</div>
      <div class="meta">
        <div class="name">${f.live ? "🔴 " : ""}${esc(f.title)}</div>
        <div class="sub">${esc(f.channel || "")}${f.channel ? " · " : ""}${f.count} reel${f.count === 1 ? "" : "s"} · ${timeAgo(f.updated)}</div>
      </div>
    </div>`).join("")}</div>`;
}

function reelsHTML(all) {
  const data = { ...all, reels: all.reels.filter((r) => !gone.has(`${all.folder}/${r.name}`)) };
  if (!data.reels.length) return `<div class="empty">This folder has no reels yet${data.info?.live_status === "is_live" ? " (it fills up as the stream has big moments)" : ""}.</div>`;
  const bar = joining ? `<div class="joinbar"><span>${joining.length ? `Join in this order: <b>${joining.map(esc).join(" → ")}</b>`
      : "Tick the reels to join, in the order they should play."}</span>
      <button class="btn primary" data-act="join-go" ${joining.length < 2 ? "disabled" : ""}>Join ${joining.length || ""}</button>
      <button class="btn" data-act="join-cancel">Cancel</button></div>` : "";
  const best = sortBest && !joining;
  const list = best ? [...data.reels].sort((a, b) => (b.score || 0) - (a.score || 0)) : data.reels;
  const ready = data.reels.filter((r) => r.ready).length;
  const tools = `<div class="reel-tools"><div class="seg" role="group" aria-label="Order">
      <button class="${best ? "on" : ""}" data-act="sort-best">Best first</button><button class="${best ? "" : "on"}" data-act="sort-time">In order</button></div>
      <span class="hint" style="margin:0">${ready} of ${data.reels.length} ready to post</span></div>`;
  return `${tools}<div class="reels">${list.map((r, i) => `
    <div class="reel${r.ready ? " is-ready" : ""}">
      ${joining ? `<input type="checkbox" class="pick" data-pick="${r.name}" ${joining.includes(r.name) ? "checked" : ""}>` : ""}
      <video src="${esc(media(r.video))}" controls playsinline preload="metadata"></video>
      <div class="body">
        <div class="hook">${esc(r.hook)}</div>
        <div class="sub">${best && i === 0 && data.reels.length > 1 ? `<span class="chip top">★ Best</span> ` : ""}<span class="chip">${Math.round(r.end - r.start)} s</span> <span class="chip">score ${r.score}</span></div>
        ${r.caption ? `<div class="post-preview" title="Post text">${esc(r.caption)}</div>` : ""}
        <label class="switch ready-toggle"><input type="checkbox" data-ready="${r.name}" ${r.ready ? "checked" : ""}> Ready to post</label>
        ${r.ai?.reason ? `<div class="ai-why" title="AI judge">✦ ${esc(r.ai.reason)}</div>` : ""}
        <div class="acts">
          <button class="btn small primary" data-act="edit" data-name="${r.name}">Edit</button>
          <a class="btn small" href="${esc(media(r.download))}">Download</a>
          <button class="btn small" data-act="copy" data-name="${r.name}">Copy post text</button>
          <details class="menu"><summary class="btn small" aria-label="More for this reel">⋯</summary><div class="menu-list">
            <button class="btn small" data-act="export" data-name="${r.name}">Other shapes (4:5, 1:1, 16:9)</button>
            <button class="btn small danger" data-act="delete" data-name="${r.name}">Delete reel</button></div></details>
        </div>
      </div>
    </div>`).join("")}</div>${bar}`;
}

export function render(state) {
  const query = $("#library-search").value;
  const inFolder = state.route.view === "folder" && state.folder;
  const key = JSON.stringify([state.route, inFolder ? state.folder : state.folders, query, joining]);
  if (key === lastDrawn) return;
  lastDrawn = key;

  $("#library-search").hidden = Boolean(inFolder);
  $("#library-crumbs").innerHTML = inFolder
    ? `<a class="btn small" href="#/library">← All folders</a><h2>${esc(state.folder.info?.title || state.folder.folder)}</h2>
       ${state.folder.info?.url ? `<a class="hint" style="margin:0" href="${esc(state.folder.info.url)}" target="_blank" rel="noopener">original video ↗</a>` : ""}
       <button class="btn small primary" id="lib-zip" style="margin-left:auto" title="All reels and their post text in one zip">Download all</button>
       ${state.folder.info?.url?.includes("youtube") ? `<button class="btn small" id="lib-ytcap" title="Use YouTube's own captions for reels you haven't edited">Get YouTube captions</button>` : ""}
       <button class="btn small" id="join-start">Join reels</button>
       <details class="menu"><summary class="btn small" aria-label="More actions">⋯</summary><div class="menu-list">
         <button class="btn small" id="lib-refresh" title="Look for new reels">↻ Refresh</button>
         <button class="btn small" id="lib-show" title="Open this folder in Finder / Explorer">Show in folder</button>
         <button class="btn small danger" id="delete-folder">Delete folder</button></div></details>`
    : `<h2>Folders</h2><button class="btn small" id="lib-refresh" style="margin-left:auto" title="Look for new reels">↻ Refresh</button>`;
  $("#library-body").innerHTML = inFolder ? reelsHTML(state.folder) : foldersHTML(state.folders, query);
}

export function mount() {
  $("#library-search").addEventListener("input", () => render(store.state));

  $("#library-body").addEventListener("keydown", (e) => {
    const card = e.target.closest(".folder");
    if (card && e.target === card && e.key === "Enter") location.hash = `#/library/${encodeURIComponent(card.dataset.folder)}`;
  });

  $("#library-body").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del-folder]");
    if (del) {
      const f = store.state.folders.find((x) => x.folder === del.dataset.delFolder);
      undoable(`Deleted "${f.title}" (${f.count} reel${f.count === 1 ? "" : "s"})`, {
        hide: () => { gone.add(f.folder); redraw(); }, restore: () => { gone.delete(f.folder); redraw(); },
        commit: async () => { try { await api.deleteFolder(f.folder); } finally { gone.delete(f.folder); } await load(); },
      });
      return;
    }
    const folderBtn = e.target.closest(".folder");
    if (folderBtn) { location.hash = `#/library/${encodeURIComponent(folderBtn.dataset.folder)}`; return; }
    const rd = e.target.closest("[data-ready]");
    if (rd) {
      const { folder, reels } = store.state.folder, reel = reels.find((r) => r.name === rd.dataset.ready);
      try { await api.setReady(folder, reel.name, rd.checked); reel.ready = rd.checked; lastDrawn = null; render(store.state); }
      catch (err) { rd.checked = !rd.checked; showError(err); }
      return;
    }
    const pick = e.target.closest("[data-pick]");
    if (pick) {
      const n = pick.dataset.pick;
      joining = pick.checked ? [...joining, n] : joining.filter((x) => x !== n);
      render(store.state);
      return;
    }
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const { folder, reels } = store.state.folder;
    if (btn.dataset.act === "sort-best" || btn.dataset.act === "sort-time") {
      sortBest = btn.dataset.act === "sort-best";
      try { localStorage.setItem("mr-reel-sort", sortBest ? "best" : "time"); } catch { /* private mode */ }
      lastDrawn = null; render(store.state); return;
    }
    if (btn.dataset.act === "join-cancel") { joining = null; render(store.state); return; }
    if (btn.dataset.act === "join-go") {
      busy(btn, async () => {
        const made = await api.mergeReels(folder, joining);
        joining = null;
        toast(`Joined into ${made.name}`);
        await load(folder);
      });
      return;
    }
    const reel = reels.find((r) => r.name === btn.dataset.name);
    if (btn.dataset.act === "edit") openEditor(folder, reel.name, () => load(folder));
    if (btn.dataset.act === "export") openEditor(folder, reel.name, () => load(folder), "export");
    if (btn.dataset.act === "copy") copyText(reel.caption);
    if (btn.dataset.act === "delete") {
      const key = `${folder}/${reel.name}`;
      undoable(`Deleted "${reel.hook || reel.name}"`, {
        hide: () => { gone.add(key); redraw(); }, restore: () => { gone.delete(key); redraw(); },
        commit: async () => { try { await api.deleteReel(folder, reel.name); } finally { gone.delete(key); } await load(folder); },
      });
    }
  });

  $("#library-crumbs").addEventListener("click", async (e) => {
    if (e.target.id === "lib-refresh") {
      const inFolder = store.state.route.view === "folder" ? store.state.folder?.folder : null;
      const before = inFolder ? store.state.folder.reels.length : (store.state.folders || []).reduce((n, f) => n + f.count, 0);
      await busy(e.target, () => load(inFolder || undefined));
      const after = inFolder ? store.state.folder.reels.length : (store.state.folders || []).reduce((n, f) => n + f.count, 0);
      toast(after > before ? `${after - before} new reel${after - before === 1 ? "" : "s"}` : "No new reels yet");
      return;
    }
    if (e.target.id === "lib-ytcap") {
      await busy(e.target, async () => {
        const r = await api.folderYoutubeCaptions(store.state.folder.folder);
        toast(r.status);
        load(store.state.folder.folder);
      });
      return;
    }
    if (e.target.id === "lib-zip") {
      await busy(e.target, async () => {
        const z = await api.folderZip(store.state.folder.folder);
        location.href = z.download;
        toast(`Downloading ${z.count} reels with their post text`);
      });
      return;
    }
    if (e.target.id === "lib-show") {
      await busy(e.target, () => api.openFolder("reels", store.state.folder.folder));
      return;
    }
    if (e.target.id === "join-start") { joining = joining ? null : []; render(store.state); return; }
    if (e.target.id !== "delete-folder") return;
    const { folder, reels } = store.state.folder;
    const n = reels.length;
    location.hash = "#/library";
    undoable(`Deleted "${folder}" (${n} reel${n === 1 ? "" : "s"})`, {
      hide: () => { gone.add(folder); redraw(); }, restore: () => { gone.delete(folder); redraw(); },
      commit: async () => { try { await api.deleteFolder(folder); } finally { gone.delete(folder); } await load(); },
    });
  });
}
