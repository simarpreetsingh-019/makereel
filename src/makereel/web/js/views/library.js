// "Reels" tab: one folder per source video; open a folder to see and edit its reels.
import { api, media } from "../api.js";
import { store } from "../store.js";
import { $, busy, confirmDialog, copyText, esc, timeAgo, toast } from "../ui.js";
import { openEditor } from "./editor.js";

let lastDrawn = "";   // avoid redrawing (and restarting videos) when nothing changed
let joining = null;   // null, or the reel names picked to join, in click order

export async function load(folder) {
  if (folder !== store.state.folder?.folder) joining = null;
  if (folder) store.set({ folder: await api.folder(folder) });
  else store.set({ folders: (await api.folders()).folders, folder: null });
}

function foldersHTML(folders, query) {
  const q = query.toLowerCase();
  const list = folders.filter((f) => !q || `${f.title} ${f.channel}`.toLowerCase().includes(q));
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

function reelsHTML(data) {
  if (!data.reels.length) return `<div class="empty">This folder has no reels yet${data.info?.live_status === "is_live" ? " (it fills up as the stream has big moments)" : ""}.</div>`;
  const bar = joining ? `<div class="joinbar"><span>${joining.length ? `Join in this order: <b>${joining.map(esc).join(" → ")}</b>`
      : "Tick the reels to join, in the order they should play."}</span>
      <button class="btn primary" data-act="join-go" ${joining.length < 2 ? "disabled" : ""}>Join ${joining.length || ""}</button>
      <button class="btn" data-act="join-cancel">Cancel</button></div>` : "";
  return `<div class="reels">${data.reels.map((r) => `
    <div class="reel">
      ${joining ? `<input type="checkbox" class="pick" data-pick="${r.name}" ${joining.includes(r.name) ? "checked" : ""}>` : ""}
      <video src="${esc(media(r.video))}" controls playsinline preload="metadata"></video>
      <div class="body">
        <div class="hook">${esc(r.hook)}</div>
        <div class="sub">${esc(r.name)} · ${Math.round(r.end - r.start)}s · score ${r.score}</div>
        ${r.ai?.reason ? `<div class="ai-why" title="AI judge">✦ ${esc(r.ai.reason)}</div>` : ""}
        <div class="acts">
          <button class="btn small" data-act="edit" data-name="${r.name}">Edit</button>
          <button class="btn small" data-act="copy" data-name="${r.name}">Copy post text</button>
          <a class="btn small" href="${esc(media(r.download))}">Download</a>
          <button class="btn small" data-act="export" data-name="${r.name}">Formats</button>
          <button class="btn small danger" data-act="delete" data-name="${r.name}">Delete</button>
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
       <button class="btn small" id="join-start" style="margin-left:auto">Join reels</button>
       <button class="btn small danger" id="delete-folder">Delete folder</button>`
    : `<h2>Folders</h2>`;
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
      if (await confirmDialog(`Delete "${f.title}" and its ${f.count} reel${f.count === 1 ? "" : "s"}? This can't be undone.`)) {
        busy(del, async () => { await api.deleteFolder(f.folder); toast("Folder deleted"); await load(); });
      }
      return;
    }
    const folderBtn = e.target.closest(".folder");
    if (folderBtn) { location.hash = `#/library/${encodeURIComponent(folderBtn.dataset.folder)}`; return; }
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
    if (btn.dataset.act === "delete" && await confirmDialog(`Delete ${reel.name} and its exports? This can't be undone.`)) {
      busy(btn, async () => { await api.deleteReel(folder, reel.name); toast("Reel deleted"); await load(folder); });
    }
  });

  $("#library-crumbs").addEventListener("click", async (e) => {
    if (e.target.id === "join-start") { joining = joining ? null : []; render(store.state); return; }
    if (e.target.id !== "delete-folder") return;
    const { folder, reels } = store.state.folder;
    const n = reels.length;
    if (!await confirmDialog(`Delete "${folder}" and its ${n} reel${n === 1 ? "" : "s"}? This can't be undone.`)) return;
    busy(e.target, async () => { await api.deleteFolder(folder); toast("Folder deleted"); location.hash = "#/library"; });
  });
}
