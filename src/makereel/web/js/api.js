// Thin client for /api/v1. Every call resolves to JSON or throws an ApiError with a readable message.
// API_BASE can point at another machine running makereel (see docs/CLIENT_SIDE_PLAN.md).

export const API_BASE = (window.MAKEREEL_API || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(status, body) {
    const e = body?.error || {};
    super(e.message || `Request failed (${status})`);
    this.status = status;
    this.code = e.code;
    this.hint = e.hint;
  }
}

async function request(method, path, body) {
  const opts = { method, headers: {}, credentials: "include" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, opts);
  } catch {
    throw new ApiError(0, { error: { message: "Can't reach makereel. Is it still running?" } });
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

const enc = encodeURIComponent;
const reelPath = (folder, name) => `/folders/${enc(folder)}/reels/${enc(name)}`;

export const api = {
  system: () => request("GET", "/system"),
  jobs: () => request("GET", "/jobs"),
  job: (id) => request("GET", `/jobs/${id}`),
  createJob: (body) => request("POST", "/jobs", body),
  stopJob: (id) => request("POST", `/jobs/${id}/stop`),
  folders: () => request("GET", "/folders"),
  folder: (folder) => request("GET", `/folders/${enc(folder)}`),
  deleteFolder: (folder) => request("DELETE", `/folders/${enc(folder)}`),
  folderZip: (folder) => request("POST", `/folders/${enc(folder)}/zip`),
  folderYoutubeCaptions: (folder) => request("POST", `/folders/${enc(folder)}/youtube-captions`),
  reel: (folder, name) => request("GET", reelPath(folder, name)),
  editReel: (folder, name, changes) => request("PATCH", reelPath(folder, name), changes),
  deleteReel: (folder, name) => request("DELETE", reelPath(folder, name)),
  syncReel: (folder, name) => request("POST", `${reelPath(folder, name)}/sync`),
  importCaptions: (folder, name, text) => request("POST", `${reelPath(folder, name)}/import`, { text }),
  trimReel: (folder, name, start, end) => request("POST", `${reelPath(folder, name)}/trim`, { start, end }),
  splitReel: (folder, name, at) => request("POST", `${reelPath(folder, name)}/split`, { at }),
  shortVersions: (folder, name, length, count) => request("POST", `${reelPath(folder, name)}/shorts`, { length, count }),
  mergeReels: (folder, reels) => request("POST", `/folders/${enc(folder)}/merge`, { reels }),
  exportReel: (folder, name, format, fit) => request("POST", `${reelPath(folder, name)}/export`, { format, fit }),
  bench: () => request("GET", "/bench"),
  benchResult: (id) => request("GET", `/bench/${id}`),
  runBench: (body = {}) => request("POST", "/bench", body),
  brand: () => request("GET", "/brand"),
  deleteLogo: () => request("DELETE", "/brand/logo"),
  deleteFont: (name) => request("DELETE", `/brand/fonts/${enc(name)}`),
  settings: () => request("GET", "/settings"),
  saveSettings: (body) => request("PUT", "/settings", body),
  watcher: () => request("GET", "/watcher"),
  setWatcher: (running) => request("PUT", "/watcher", { running }),
  setup: (focus = "both") => request("GET", `/setup?focus=${enc(focus)}`),
  downloadModel: (name) => request("POST", `/setup/models/${enc(name)}`),
  cancelModel: (name) => request("POST", `/setup/models/${enc(name)}/cancel`),
  deleteModel: (name) => request("DELETE", `/setup/models/${enc(name)}`),
  removeJob: (id) => request("DELETE", `/jobs/${id}`),
  clearJobs: () => request("POST", "/jobs/clear"),
  storage: () => request("GET", "/storage"),
  load: () => request("GET", "/system/load"),
  ytSignIn: () => request("GET", "/youtube/sign-in"),
  ytOpen: (browser) => request("POST", "/youtube/open", { browser }),
  ytRemoveCookies: () => request("DELETE", "/youtube/cookies"),
  openFolder: (which, folder) => request("POST", "/storage/open", { which, folder }),
  clearCache: () => request("POST", "/storage/clear-cache"),
  setReelsFolder: (path, move) => request("PUT", "/storage/reels-folder", { path, move }),
  updates: (force = false) => request("GET", `/updates${force ? "?force=1" : ""}`),
  installUpdate: () => request("POST", "/updates/install"),
  restartApp: () => request("POST", "/updates/restart"),

  /** PUT a file as the raw body (logo, fonts). */
  async putFile(path, file) {
    const res = await fetch(`${API_BASE}/api/v1${path}`, { method: "PUT", body: file, credentials: "include" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, data);
    return data;
  },

  /** Raw-body upload with progress (no multipart). */
  upload(file, options, onProgress) {
    return new Promise((resolve, reject) => {
      const q = new URLSearchParams({ name: file.name, ...options });
      const x = new XMLHttpRequest();
      x.open("POST", `${API_BASE}/api/v1/jobs/upload?${q}`);
      x.withCredentials = true;
      x.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      x.onload = () => {
        const data = JSON.parse(x.responseText || "{}");
        x.status < 300 ? resolve(data) : reject(new ApiError(x.status, data));
      };
      x.onerror = () => reject(new ApiError(0, { error: { message: "Upload failed: connection lost" } }));
      x.send(file);
    });
  },
};

export const media = (url) => (url?.startsWith("/") ? API_BASE + url : url);
