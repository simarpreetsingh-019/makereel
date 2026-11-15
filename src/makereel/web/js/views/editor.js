// Reel editor: edit the caption text as a paragraph, the on-screen title and the post text, then re-render.
import { api, media } from "../api.js";
import { $, busy, copyText, toast } from "../ui.js";

let current = null;      // { folder, name, onSaved, original }

function fill(reel) {
  $("#ed-video").src = media(reel.video);
  $("#ed-download").href = media(reel.download);
  $("#ed-hook").value = reel.hook || "";
  $("#ed-transcript").value = reel.transcript;
  $("#ed-caption").value = reel.caption || "";
  $("#ed-ass").value = reel.ass;
  $("#ed-words").textContent = `${reel.transcript.split(/\s+/).filter(Boolean).length} words`;
  current.original = { hook: reel.hook || "", transcript: reel.transcript, caption: reel.caption || "", ass: reel.ass };
}

export async function openEditor(folder, name, onSaved) {
  current = { folder, name, onSaved };
  $("#ed-title").textContent = `Edit ${name}`;
  $("#ed-msg").textContent = "";
  try {
    fill(await api.reel(folder, name));
    $("#editor").showModal();
  } catch (err) {
    toast(err.message);
  }
}

export function mount() {
  const dialog = $("#editor");
  $("#ed-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => $("#ed-video").pause());
  $("#ed-copy").addEventListener("click", () => copyText($("#ed-caption").value));
  $("#ed-transcript").addEventListener("input", (e) => {
    $("#ed-words").textContent = `${e.target.value.split(/\s+/).filter(Boolean).length} words (was ${current.original.transcript.split(/\s+/).length})`;
  });

  $("#ed-save").addEventListener("click", (e) => {
    const o = current.original;
    const changes = {};
    if ($("#ed-hook").value !== o.hook) changes.hook = $("#ed-hook").value;
    if ($("#ed-transcript").value.trim() !== o.transcript.trim()) changes.transcript = $("#ed-transcript").value;
    if ($("#ed-caption").value !== o.caption) changes.caption = $("#ed-caption").value;
    if ($("#ed-ass").value !== o.ass) changes.ass = $("#ed-ass").value;
    if (!Object.keys(changes).length) return toast("Nothing changed");
    $("#ed-msg").textContent = "Rendering…";
    busy(e.currentTarget, async () => {
      try {
        const reel = await api.editReel(current.folder, current.name, changes);
        fill(reel);
        $("#ed-msg").textContent = "Saved and re-rendered.";
        current.onSaved?.();
      } catch (err) {
        $("#ed-msg").textContent = "";
        throw err;
      }
    });
  });
}
