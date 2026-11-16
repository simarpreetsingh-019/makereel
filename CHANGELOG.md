# Changelog

## Unreleased

### Added
- **Safe zones** (Brand → Keep clear of app buttons: All apps, TikTok, Reels, Shorts or Off). On 9:16 reels,
  captions stay above the account name and description, clear of the like/share column, and the title and logo
  stay below the top tabs. The Look editor and Brand preview shade the covered areas. Default: All apps.

## 0.5.0 (2026-11-16)

### Added: other languages
- **Language detected once per video** (from three moments together), and reused by every reel and every chunk
  of a live stream, so mixed speech like Hinglish stays in one script. Set `clip.language` to force one.
- **Bigger speech model outside English:** with `base` or `tiny`, non-English videos use `small` automatically
  (`clip.model_other`: `small`, `medium`, `large-v3` or `same`).
- **Caption letters** (Brand default, and per reel in Look): own script (हिंदी, ਪੰਜਾਬੀ), **English letters**
  (Hinglish-style "kya baat hai", our own rules for all Indian scripts, `anyascii` for others), or
  **Translate to English**. Own script → English letters keeps your edits; other switches listen to the reel again.
- **Fonts per script:** captions in Devanagari, Gurmukhi, Bengali, Tamil, Arabic, Thai and more get a matching
  Noto font (downloaded once, ~250 KB), or a system font offline. Chinese, Japanese and Korean use system fonts.
- **Hype words in more languages:** Hindi/Hinglish, Punjabi, Spanish, Portuguese, French, German, Arabic,
  Russian, Turkish, Indonesian, Japanese, Chinese, Korean; chat laughs like "jaja", "kkkk", "mdr", "ㅋㅋ".

### Fixed
- Word matching dropped Hindi vowel signs (so "की" and "का" looked the same), which hurt caption editing
  and auto-sync in Indian languages.
- Titles now split sentences on "।" and full-width punctuation.

## 0.4.1 (2026-11-16)

### Fixed
- Caption styles: **Glow** blurred the word itself (unreadable); it's now a sharp white word with a coloured halo.
  **Boxed word** had white text on a yellow box; the text is now dark. **Pop** and **One word** are much bigger,
  so they're clearly different from Classic. **Minimal** is smaller and in normal case.
- The Look tab preview (and the Timing preview) now show the selected caption style straight away. Before, clicking
  a style changed nothing until you saved.
- Reels saved with the old Glow or Boxed style: open Look and save again to re-render.

## 0.4.0 (2026-11-16)

### Added
- **Follow the speaker** framing (`fit: track`): YuNet face detection, single-person tracking, a calm
  dead-zone camera, and a fallback to blur when there's no steady face. Works for every export shape.
- **Caption templates:** Classic, Pop, Boxed word, Glow, Karaoke fill, One word, Minimal (per reel, plus a brand default).
- **Trim / extend, split, join** (editor Cut tab; Join in the folder view). Masters keep 6 s either side.
  Trimming keeps corrected captions and transcribes newly revealed audio.
- **Optional AI judge:** local (Ollama / LM Studio), Claude (`makereel[ai]`) or any OpenAI-compatible
  API. Four scores plus a title and reason, blended with signals, shown on reel cards. Off by default.
- Docs: COMPETITORS.md (gap analysis vs PeakCut, OpenShorts, SupoClip, ClipStudio) and MONETIZATION.md.

### Changed
- The 24/7 tab is now **Settings** and holds the AI judge settings.
- Benchmarks include a `judge` stage.

## 0.3.1 (2026-11-15)

### Added
- **Caption look per reel** (Edit → Look): height from the bottom (with quick presets), size, and a
  background box with colour and opacity, previewed live. Use it to avoid or cover subtitles already in
  the video. It applies to the reel and all its exports. Brand defaults for the background box are in the Brand tab.
- The Timing preview shows captions with the reel's real look and position.

### Fixed
- Delete (folders and reels) did nothing in embedded browsers, because `window.confirm` was blocked. It
  now uses an in-page confirmation, and folders can be deleted straight from their card.

## 0.3.0 (2026-11-15)

### Added
- **Caption sync.** Each reel's captions are timed from its own audio (a precise second transcription
  pass). The editor has a Timing tab with a live preview, an auto-sync button, a shift slider, per-word
  nudges, "set to now" and tap-to-sync.
- **Smarter text edits.** Unchanged words keep their timing; changed, added or removed words are aligned around them.
- **Export formats.** 9:16, 4:5, 1:1 and 16:9, each with a blurred fill, crop or black bars. Exports stay in step with later edits.
- **Brand kit.** Logo (position, size, opacity), fonts, caption colours, position and size, a live preview,
  per-reel logo switch and "Apply brand style". The "Made with makereel" post-text line is opt-out.
- **Benchmarks.** `makereel bench` and the System tab measure time per stage, CPU time, CPU %, peak RAM,
  disk and GPU (NVIDIA). They keep a history with comparisons, and a report can be shared by the user.
- `makereel export`, plus `makereel rerender --sync / --offset`.
- New settings: `MAKEREEL_DATA_DIR` and `MAKEREEL_REPO_URL`. Dependency: `psutil`.

### Changed
- Every reel keeps a master clip (`reel_NN.src.mp4`) in the original shape, used for exports.
  Reels made before 0.3.0 can still be edited, but need re-making to export other shapes.

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
