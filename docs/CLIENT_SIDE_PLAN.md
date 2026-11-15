# Plan: makereel as a website that runs on each visitor's own device

**Goal:** anyone can open a web page and make reels, but all the heavy work (download, speech-to-text,
rendering) runs on *their* computer. There are no servers for us to pay for or scale: every new user
brings their own processor.

## 1. What a browser can and can't do

Browsers can't run arbitrary programs, but with the user's permission they can reach most of the hardware we need:

| Pipeline step | In a plain web page? | How |
|---|---|---|
| Use all CPU cores | ✅ | Web Workers (`navigator.hardwareConcurrency` tells us how many) |
| Use the GPU | ✅ (Chrome, Edge, Safari 18+, Firefox behind a flag) | WebGPU |
| Hardware video decode/encode | ✅ | WebCodecs `VideoDecoder` / `VideoEncoder` (the same chips VideoToolbox / NVENC use) |
| Loudness, scene cuts | ✅ | WebCodecs `AudioDecoder` + a little math; frame differences on a canvas |
| Speech-to-text | ✅ on decent laptops | Whisper `tiny`/`base` via transformers.js (WebGPU) or whisper.cpp compiled to WASM |
| Burn captions, 9:16 blur layout | ✅ | Draw each frame on an `OffscreenCanvas` (blurred fill + video + our own caption text), encode with WebCodecs, mux to MP4 (e.g. mediabunny / mp4-muxer) |
| Save into folders on disk | ✅ (Chromium) / partial elsewhere | File System Access API: the user picks a folder once, and we write `Video title/reel_01.mp4`. Other browsers use OPFS plus downloads. |
| Keep the machine awake while working | ✅ | Screen Wake Lock API |
| **Download a YouTube / Twitch link** | ❌ | Blocked by cross-site rules (CORS), plus YouTube's signature and token checks. yt-dlp is Python and can't run in a page. |
| **Record a live stream for hours / 24/7** | ❌ | Background tabs get throttled or frozen, and the tab must stay open |
| Capture a stream playing in another tab | ⚠️ | `getDisplayMedia` (the user picks the tab to share). Works, but the quality is whatever is on screen, and it needs a click every time. |

**Conclusion:** a pure web page can do everything *except* fetch videos from links, and it can't run
24/7. Those two are the heart of makereel, so the plan uses two modes.

## 2. Recommended architecture: one website, two engines

```
              https://makereel.app   (static files on free hosting, no backend)
                         │
         ┌───────────────┴────────────────┐
         ▼                                ▼
  "Full" mode (recommended)         "Lite" mode (no install)
  makereel engine on the user's     everything inside the browser tab
  computer, on 127.0.0.1:8765       (WebGPU, WebCodecs, Workers)
  = this repository                 for uploaded files + tab capture
  links, live streams, 24/7         one-off reels, quick trial
```

### Full mode: hosted UI + local engine (the "companion app" pattern, as Ollama and Jupyter use)

1. The user opens the website. It checks `http://127.0.0.1:8765/api/v1/health`.
2. If no engine answers, it shows a **Get the engine** button with one installer per OS.
3. The installer sets up the engine to start at login and run in the background at low power. That part exists already in `deploy/`.
4. The website then talks to the engine with the **same `/api/v1` this repository already has**.
   The browser only shows the UI. The user's computer does the downloading, transcribing, rendering and 24/7 watching.

**Already in place:**
- The UI is static files and can point at any engine: `window.MAKEREEL_API` in `web/js/api.js`.
- Cross-site access is refused unless allowed: `MAKEREEL_ALLOWED_ORIGINS=https://makereel.app`.
- Chrome's Private Network Access preflight (`Access-Control-Allow-Private-Network`) is answered.
- The engine binds to localhost only by default, so other machines can't use it.

**Still to build:**
- **Pairing instead of a password.** On first connect the engine shows a 6-digit code (tray icon or
  terminal), the site sends it once, and the engine returns a token kept in the site's storage. Every API call
  sends `Authorization: Bearer <token>`. This stops any other website from driving the engine, even one that
  gets into the allow-list.
- **Installers.** Package the engine with PyInstaller (one binary per OS) and bundle ffmpeg with libass and a JS
  runtime, so nothing else needs installing. Sign them: Apple Developer ID plus notarisation on macOS,
  and a code-signing certificate on Windows, otherwise SmartScreen and Gatekeeper scare users away.
- **Auto-update.** The engine checks a static `latest.json` on the website and updates itself, including
  yt-dlp, which needs frequent updates.
- **Browser quirks.** Chrome and Edge allow an `https://` page to call `http://127.0.0.1`. Safari and
  Firefox are stricter about it. As a fallback, the engine serves the same UI itself (it already does at
  `http://localhost:8765`), and the website can simply send people there.

### Lite mode: everything in the tab

For people who won't install anything: drop in a video file, or share a browser tab that's playing a stream.

- **Signals:** WebCodecs audio decode → loudness per second (same algorithm as `core/signals.py`).
- **Speech:** Whisper `base` on WebGPU (transformers.js), on candidate windows only (same two-stage idea).
- **Render:** OffscreenCanvas per frame (blurred fill, video, captions drawn with canvas text, no libass
  needed) → WebCodecs H.264 → MP4.
- **Storage:** the user picks an output folder once (File System Access) and gets the same layout:
  `Video title/reel_01.mp4`, `reel_01.json`.
- **Limits to state in the UI:** no YouTube links, the tab must stay open, and speed depends on the device. Before starting,
  we run a 3-second benchmark and suggest `tiny` vs `base` and how many reels are realistic.

Port the logic, not the code: `highlights.py`, `captions.py` and `pipeline.credits` are small and
pure, so they can be rewritten in TypeScript or compiled with Pyodide. Both modes must produce identical folders.

### Later: desktop app

Wrap the engine and UI in **Tauri** (a small download, using the system webview). This gives a tray icon,
start-at-login, notifications when a reel is ready and auto-update, and it removes the browser quirks above.
It's the friendliest option for non-technical users and reuses everything.

## 3. Permissions we ask for, and why (shown to the user in plain words)

| Permission | Mode | Why |
|---|---|---|
| Install the engine | Full | to download videos from links and record live streams |
| Choose an output folder | Lite (Full uses its own folder) | to save reels in folders named after each video |
| Share a tab or screen | Lite | to clip a live stream that's playing in another tab |
| Keep the screen awake | both | so a long render isn't paused by sleep |
| Notifications | both | "3 new reels from the stream" |
| Persistent storage | Lite | so the browser doesn't clear models and drafts |

We never ask for more than the step in front of the user needs, and everything stays on their device.

## 4. Cost and scaling

| | Server-side SaaS | This plan |
|---|---|---|
| Compute per user | ours (GPU or CPU minutes) | theirs |
| Hosting | servers, queues, storage | static files (free tier: Cloudflare Pages, GitHub Pages, Netlify) |
| Bandwidth for video | ours (expensive) | theirs, straight from the source |
| YouTube blocking datacenter IPs | constant problem | not an issue: home IPs |
| Privacy | uploads to us | nothing leaves their device |
| Scales to 1 or 1,000,000 users | linear cost | the same cost: about $0 |

Optional small, cheap services later: the update feed (a static file), anonymous crash reports, and
OAuth for auto-posting (see below).

## 5. Auto-posting on the user's device

Instagram (Graph API, Business or Creator accounts) and X both use OAuth. With PKCE, the sign-in happens in
the user's browser and the tokens are stored by *their* engine. The website never sees them. Posting runs
from the engine on their machine, with a review queue, spacing and daily caps. Meta requires app review for
publishing permissions, so plan for that lead time.

## 6. Risks to settle before a public launch

- **Platform terms.** YouTube's terms of service restrict downloading, and reposting needs the rights holder's
  permission. Credits don't replace permission. Running on the user's device moves the action to the user, but a
  public product that makes this easy still carries risk. Get legal advice, and consider leading with
  "your own streams and videos" and creator opt-in.
- **Installer trust.** Unsigned binaries look like malware to users. Code signing costs about $100–400 a year.
- **Low-end devices.** Lite mode on a phone or old laptop will be slow. Detect it and say so up front.
- **yt-dlp breakage.** YouTube changes often, so auto-update must be reliable (Full mode).

## 7. Roadmap

| Phase | Deliverable | Rough effort |
|---|---|---|
| 0 ✅ | Engine with versioned API, CORS allow-list, static UI (this repo) | done |
| 1 | Hosted UI on free static hosting; engine detection and an "install the engine" page | 2–3 days |
| 2 | Pairing tokens; signed installers for macOS, Windows and Linux with bundled ffmpeg; auto-update | 1–2 weeks |
| 3 | Lite mode: file upload → reels fully in the browser (WebCodecs + WebGPU Whisper + canvas captions) | 2–3 weeks |
| 4 | Lite mode: tab-capture live clipping with an in-memory rolling buffer | 1 week |
| 5 | Tauri desktop app (tray, notifications, start at login) | 1–2 weeks |
| 6 | Auto-posting (Instagram, X, Shorts) from the engine | 1–2 weeks + Meta review |

Start with phases 1 and 2. They turn what already works into something anyone can use, at no running cost.
