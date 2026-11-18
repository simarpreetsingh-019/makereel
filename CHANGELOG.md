# Changelog

## Unreleased

- **Speech model setup** (System tab, with a reminder on first run): reads memory, disk and NVIDIA GPU,
  asks whether you clip English or Indian streamers, suggests a model for English and one for Hindi,
  downloads them with progress. New English-only model: distil-large-v3.
- **NVIDIA GPU for speech**: used automatically when available (`speech_device`), falling back to the CPU.
- **Updates from GitHub**: a banner when a new release is out, one-click install and restart
  (System → Updates; see docs/RELEASING.md).
- **Creator badge**: the creator's profile picture and @handle in a corner of every reel (Brand → Creator
  credit; top left by default, moves aside if it would cover your logo, keeps clear of app buttons).
- **Caption language moved to the Text tab** (first thing you see when editing): original script, English
  letters or Translate to English, with the detected language shown. It applies right away, and asks first
  when unsaved word edits would be lost.
- **Loading spinners**: every save, render and export button shows a spinner while it works, and the editor's
  status line spins during a re-render.
- **Camera tab without Follow the speaker**: offers a "Use Follow the speaker" button instead of a dead end,
  and no longer shows video controls with nothing to play.
- **One recording per live stream**: a pasted live link and the 24/7 watcher no longer record the same stream
  twice ("already recording this stream"), and a video always reuses its folder even when YouTube changes the
  time in a live title.
- **Refresh button in Reels** (folder list and inside a folder): shows how many new reels arrived.
- **24/7 watches new uploads too** (YouTube): new videos and premieres that have aired are clipped as
  they appear, not only live streams. A channel's older videos are skipped the first time it's checked.
  Switch: Settings → "Also clip new uploads and premieres" (`watch_uploads`, on by default).
- **Upload window and check interval**: clip uploads from now on, the last 24 or 48 hours, or since a date
  (`uploads_since`), and check every 4, 5, 10, 15, 30 or 60 minutes or at random 4–30 minutes (`uploads_every`).
- **Show everyone** shots in the Camera tab: pick a shot and the reel zooms out smoothly to the whole frame
  (both people over a blurred fill), then zooms back in to the speaker at the next cut.
- **Auto layout** (new default): split screen for two people or a webcam over gameplay, follow the speaker for one
  steady face, otherwise blur. The Layout choice now sits above both the link box and the upload box.
- **Follow the speaker follows who is talking**: mouth movement decides who is on screen (it used to lock on the
  biggest face in the first frame). Cuts land near when the person starts talking, and a quick "yeah" doesn't move it.
- **Camera tab** in the editor: the wide video with the reel's frame drawn on it, and a timeline of shots. Drag a
  cut, add or remove cuts, click a person to point a shot at them, or find the shots again automatically.

## 0.6.0 (2026-11-16)

### Added
- **Safe zones** (Brand → Keep clear of app buttons: All apps, TikTok, Reels, Shorts or Off). On 9:16 reels,
  captions stay above the account name and description, clear of the like/share column, and the title and logo
  stay below the top tabs. The Look editor and Brand preview shade the covered areas. Default: All apps.
- **Split screen layout** (`split`, in Look → Framing and the Layout option): two people side by side
  (podcasts, interviews) are stacked one above the other, each framed head and shoulders; a streamer's webcam
  over gameplay becomes webcam on top (40%) and the game below. Falls back to the blurred layout when it finds
  neither. Webcam faces are small, so this looks at frames at 640 px instead of 320. Both people must be on
  screen together, so a podcast that cuts between single shots isn't split. Captions sit on the seam. In the
  editor, choosing split (or follow the speaker) on a reel with nobody suitable says so and keeps the layout.
- **Cards** (editor → Cards): text boxes over the video. A **quote** (pre-filled with the words at the playhead),
  a **note**, or an **outro** over the last seconds ("Follow for more"). Kept through caption edits, trims,
  splits, joins and exports.
- **Import subtitles** (editor → Text): an SRT or WebVTT of the reel, or of the whole video it came from
  (moved to the reel's clock automatically; YouTube's repeating auto-captions are cleaned up), or a plain
  transcript (fitted to the current timing). **Download .srt** gives the reel's captions as a subtitle file.
- **60 fps** (`clip.fps`, Create → Frame rate, `--fps 60`): reels from 50/60 fps sources (gameplay, Twitch
  720p60) keep their smooth motion; 30 fps sources stay 30 rather than repeating frames. Trims, layouts,
  exports and joins follow the reel's own rate.

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
