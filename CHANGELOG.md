# Changelog

## 0.2.0 (2026-11-15)

Restructure into a documented, layered project, plus web app improvements.

### Added
- Web app: reels are grouped in **one folder per video**, named after the video's title.
- Web app: **edit captions as a paragraph** and re-render, keeping word timings.
- Web app: only one video plays at a time.
- REST API v1 (`/api/v1/...`) with consistent JSON errors (`code`, `message`, `hint`). See docs/API.md.
- `.env` / `MAKEREEL_*` environment configuration, separate from `makereel.json` user settings.
- CORS allow-list and Private Network Access preflight, so a hosted UI can drive a local engine.
- Unit tests (pytest) and lint (ruff).
- Docs: architecture, API, configuration, deployment, development, client-side plan.
- Windows start script, Docker health check, folder and reel delete.

### Changed
- `src/` layout: `core` (video logic), `services` (jobs, library, watcher), `api`, `web`, `cli`.
- `makereel rerender <folder> <reel> [--transcript] [--hook]` replaces `rerender <clip.json>`.
- 24/7 services run `makereel web --watch` (web app and watcher together).
- Live chat runs yt-dlp through the current Python, so it works on Windows too.
- Every ffmpeg call goes through one wrapper that turns failures into readable errors.
- Re-renders write to a temp file first, so a failure never leaves a broken reel.

### Removed
- Old `clip` / `watch` command aliases, the per-folder `manifest.json`, and the word find-and-replace
  editor (superseded by paragraph editing).

## 0.1.0

First version: CLI, highlight detection, live rolling buffer, libass captions, 24/7 daemon, first web UI.
