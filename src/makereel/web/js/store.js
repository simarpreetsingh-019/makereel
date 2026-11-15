// App state in one place. Views read `store.state` and re-render when they're notified.
// Only `store.set()` changes state, so every change goes through the same path.

const listeners = new Set();

export const store = {
  state: {
    route: { view: "create" },   // create | library | folder | auto
    system: null,
    jobs: [],
    openLogs: {},                // job id -> log text (only for expanded logs)
    folders: [],
    folder: null,                // { folder, info, reels } when inside a folder
    settings: null,
    watcher: false,
  },

  set(patch) {
    this.state = { ...this.state, ...patch };
    listeners.forEach((fn) => fn(this.state));
  },

  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
