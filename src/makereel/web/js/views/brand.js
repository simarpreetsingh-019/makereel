// "Brand" tab: logo, caption font and colours, credit line. Applies to new reels; existing reels
// pick it up via Edit → "Apply brand style" (captions) or any re-render (logo).
import { api, media } from "../api.js";
import { $, busy, esc, toast } from "../ui.js";

const FIELDS = ["logo_enabled", "logo_position", "logo_scale", "logo_opacity", "font", "text_colour",
  "highlight_colour", "outline_colour", "caption_position", "caption_size", "caption_template", "caption_script", "caption_box", "box_colour",
  "box_opacity", "credit_footer"];
const COMMON_FONTS = ["Arial Black", "Impact", "Montserrat", "Bebas Neue", "Anton", "Poppins", "Inter"];

let state = null;   // { logo, fonts, settings }

export async function load() {
  state = await api.brand();
  fillForm();
  preview();
}

function fillForm() {
  const s = state.settings;
  FIELDS.forEach((k) => {
    const el = $(`#br-${k}`);
    if (el.type === "checkbox") el.checked = s[k]; else el.value = s[k];
  });
  const fonts = [...new Set([...state.fonts.map((f) => f.replace(/\.(ttf|otf)$/i, "")), ...COMMON_FONTS])];
  $("#br-font-list").innerHTML = fonts.map((f) => `<option value="${esc(f)}">`).join("");
  $("#br-fonts").innerHTML = state.fonts.length
    ? state.fonts.map((f) => `<span class="chip">${esc(f)} <button class="link" data-font="${esc(f)}">remove</button></span>`).join(" ")
    : `<span class="hint" style="margin:0">No uploaded fonts. Installed fonts work by name.</span>`;
  $("#br-logo-img").src = state.logo ? media(state.logo) : "";
  $("#br-logo-img").hidden = !state.logo;
  $("#br-logo-none").hidden = Boolean(state.logo);
  $("#br-logo-remove").hidden = !state.logo;
}

function values() {
  const out = {};
  FIELDS.forEach((k) => {
    const el = $(`#br-${k}`);
    out[k] = el.type === "checkbox" ? el.checked : el.type === "range" || el.type === "number" ? Number(el.value) : el.value;
  });
  return out;
}

/** Live mock-up of a reel with the current settings (no render needed). */
function preview() {
  const v = values();
  const phone = $("#br-preview");
  const cap = $("#br-prev-caption");
  cap.style.fontFamily = `"${v.font}", system-ui, sans-serif`;
  cap.style.color = v.text_colour;
  cap.style.fontSize = `${18 * v.caption_size}px`;
  cap.style.webkitTextStroke = `1px ${v.outline_colour}`;
  cap.style.top = { top: "22%", middle: "47%", bottom: "68%" }[v.caption_position];
  cap.querySelector("b").style.color = v.highlight_colour;
  cap.style.background = v.caption_box ? hexToRgba(v.box_colour, v.box_opacity) : "transparent";
  cap.style.padding = v.caption_box ? "4px 6px" : "0";
  $("#br-box_opacity-v").textContent = `${Math.round(v.box_opacity * 100)}%`;
  const logo = $("#br-prev-logo");
  logo.hidden = !(state.logo && v.logo_enabled);
  if (state.logo) logo.src = media(state.logo);
  logo.style.width = `${v.logo_scale * 100}%`;
  logo.style.opacity = v.logo_opacity;
  const [vert, horiz] = v.logo_position.split("-");
  Object.assign(logo.style, { top: vert === "top" ? "4%" : "", bottom: vert === "bottom" ? "4%" : "",
                               left: horiz === "left" ? "4%" : "", right: horiz === "right" ? "4%" : "" });
  $("#br-prev-footer").hidden = !v.credit_footer;
  $("#br-logo_scale-v").textContent = `${Math.round(v.logo_scale * 100)}%`;
  $("#br-logo_opacity-v").textContent = `${Math.round(v.logo_opacity * 100)}%`;
  $("#br-caption_size-v").textContent = `${Math.round(v.caption_size * 100)}%`;
  phone.dataset.ready = "1";
}

export function mount() {
  $("#tab-brand").addEventListener("input", (e) => { if (e.target.id?.startsWith("br-")) preview(); });
  $("#br-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    await api.saveSettings({ brand: values() });
    state.settings = values();
    toast("Brand saved. New reels use it; use Edit → Apply brand style for existing ones.");
  }));
  $("#br-logo-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    busy(null, async () => { Object.assign(state, await api.putFile("/brand/logo", file)); fillForm(); preview(); toast("Logo uploaded"); });
    e.target.value = "";
  });
  $("#br-logo-remove").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    Object.assign(state, await api.deleteLogo()); fillForm(); preview();
  }));
  $("#br-font-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    busy(null, async () => {
      Object.assign(state, await api.putFile(`/brand/fonts/${encodeURIComponent(file.name)}`, file));
      fillForm();
      toast("Font added. Type its name in Font (as it appears when installed).");
    });
    e.target.value = "";
  });
  $("#br-fonts").addEventListener("click", (e) => {
    const name = e.target.dataset.font;
    if (name) busy(e.target, async () => { Object.assign(state, await api.deleteFont(name)); fillForm(); });
  });
}

export function hexToRgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
