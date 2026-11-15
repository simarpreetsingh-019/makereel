# Architecture

makereel is one Python package with four layers. Each layer only imports the layers below it.

```
web/  (browser UI: HTML, CSS, ES modules)            ← talks to the API over HTTP only
  │
api/  (HTTP server, router, /api/v1 routes)          ← translates HTTP ⇄ service calls and errors
  │
services/  (jobs, library, runner, watcher)          ← state, orchestration, folders on disk
  │
core/  (sources, signals, highlights, transcribe,    ← pure "video in, reels out" logic,
        captions, render, pipeline, live, media)        no knowledge of HTTP, jobs or the UI
  │
config.py · errors.py · logs.py                      ← shared foundations
```

`cli.py` sits beside `api/`: it is a second front end over the same `services/`.

## Folder structure

```
makereel/
├── src/makereel/
│   ├── __init__.py          version
│   ├── __main__.py          `python -m makereel`
│   ├── cli.py               command line (web, run, local, rerender, daemon)
│   ├── config.py            environment (.env / MAKEREEL_*) + user settings (makereel.json)
│   ├── errors.py            MakereelError hierarchy (code, HTTP status, hint)
│   ├── logs.py              logging setup + per-job log capture
│   ├── core/
│   │   ├── media.py         find ffmpeg, pick encoder, run commands with clear errors
│   │   ├── sources.py       yt-dlp: probe, download, live chat command, link parsing
│   │   ├── signals.py       loudness, chat activity, scene cuts
│   │   ├── highlights.py    scoring curve, candidates, rescoring, edge snapping
│   │   ├── transcribe.py    faster-whisper on candidate windows only
│   │   ├── captions.py      build / parse / align / shift / restyle .ass files; 7 caption templates
│   │   ├── branding.py      brand kit → caption Style + logo overlay + template
│   │   ├── framing.py       speaker tracking (YuNet faces → calm camera path → ffmpeg crop)
│   │   ├── judge.py         optional AI judge (local / Claude / OpenAI-compatible)
│   │   ├── metrics.py       stage timers for benchmarks
│   │   ├── render.py        master clip, any format (9:16, 4:5, 1:1, 16:9) × fit, captions, logo
│   │   ├── pipeline.py      video → reels (+ credits, hook, folder.json)
│   │   └── live.py          LiveSession: rolling buffer + spike detection
│   ├── services/
│   │   ├── library.py       folders and reels on disk: list, read, edit, delete, safe paths
│   │   ├── runner.py        one link / one file → reels or a LiveSession
│   │   ├── jobs.py          JobManager: queue, live sessions, status, per-job logs
│   │   └── watcher.py       24/7 channel polling, inbox.txt, cleanup
│   ├── api/
│   │   ├── router.py        method + path router, Request/Response
│   │   ├── routes.py        /api/v1 endpoints
│   │   └── server.py        HTTP server: static files, /media streaming, auth, CORS
│   └── web/
│       ├── index.html
│       ├── css/app.css
│       └── js/
│           ├── app.js       routing, polling, wiring
│           ├── api.js       API client (ApiError with message + hint)
│           ├── store.js     single app state + subscribe
│           ├── ui.js        helpers (toast, busy buttons, one-video-at-a-time)
│           └── views/       create · library · editor (text/timing/export) · auto · brand · system
├── tests/                   pytest unit tests (no network, no ffmpeg needed)
├── docs/
├── deploy/                  macOS launchd, Linux systemd, Windows PowerShell
├── Dockerfile
├── .env.example             deployment settings (copy to .env)
└── makereel.example.json    user settings (copy to makereel.json)
```

## Data flow

```
link ──► sources.probe ──► live? ──yes──► LiveSession (rolling buffer)
                             │                 │ spike
                             no                ▼
                             ▼            joined window
                    sources.download           │
                             └──────► pipeline.process ──► library folder
                                        1 signals (whole file)       "Me at the zoo/"
                                        2 transcribe candidates       folder.json
                                        3 snap + render               reel_01.{mp4,raw.mp4,ass,json}
```

## On-disk library

One folder per source video, named after its title (made safe for Windows, macOS and Linux;
two different videos with the same title get the video id appended). Inside it:

| File | Purpose |
|---|---|
| `folder.json` | source video: id, title, channel, link, live status |
| `reel_NN.mp4` | the reel (9:16), captions and logo burned in |
| `reel_NN.src.mp4` | the moment in its original shape **plus 6 s either side**: the master for every format, trim and split. The reel is `[src_offset, src_offset + length]` inside it |
| `reel_NN.raw.mp4` | the 9:16 version without captions, so caption edits only re-burn (seconds) |
| `reel_NN.<fmt>.mp4` / `.ass` | exports in other formats (`4x5`, `1x1`, `16x9`), made on demand |
| `reel_NN.ass` | the captions as text (styles, timing, one highlighted word per line) |
| `reel_NN.json` | post text with credits, on-screen title, score, why it was picked, timing |

The caption text shown in the editor is read back from the `.ass` file itself (`captions.parse_words`),
so there is a single source of truth.

## Speaker framing

`fit: "track"` samples the reel at 3 fps, finds faces with OpenCV's YuNet (a 230 KB model, downloaded and
checksum-verified on first use), and follows one person. It prefers the face nearest the previous one, so it
doesn't jump to people in the background. A virtual camera with a dead zone holds still until the
speaker moves 7% off-centre, then glides there in 0.6 s. The path becomes a piecewise-linear ffmpeg
`crop` expression of `t`. If fewer than 40% of samples have a face (gameplay, screen recordings), it uses
the blurred layout instead.

## AI judge (optional)

After the signal stage has shortlisted 3× as many moments as wanted, `judge.py` can send their transcripts to an
LLM. It scores hook, engagement, value and shareability (0–10), and writes a title and a reason. The scores
are blended with the signal score (`ai.weight`). The provider can be a local model (Ollama / LM Studio;
nothing leaves the machine), Claude via the official SDK (structured JSON output, low effort, server-side
refusal fallback), or any OpenAI-compatible API. Every failure falls back to signal-only ranking, so a job never fails because of it.

## Caption sync

Captions drift when word timings are measured on one piece of audio and shown on another. makereel avoids that in three ways:

1. **Automatic, at creation.** Candidate moments are first found with a fast transcription of the long
   source. After a reel is cut, its own audio (`reel_NN.src.mp4`) is transcribed again with precise
   settings (beam 5, tighter voice detection). The captions are timed from that, so they match exactly
   what viewers hear (`pipeline.synced_words`).
2. **Auto-sync button (and `makereel rerender --sync`).** Re-times an existing reel from its own audio.
   The user's corrected words are kept, because `captions.align` maps them onto the fresh timings.
3. **Manual tools in the editor (Timing tab).** The clean video plays with a live caption overlay, so
   there's no re-render while adjusting. You can:
   - shift every caption earlier or later with a slider
   - nudge single words by ±0.1 s
   - "set to now" at the playhead
   - use **tap to sync**: play the reel and press Space as each word is spoken

   Then save to re-render. Edits also update any exports.

Text edits use the same alignment. Words you didn't touch keep their timing, and changed, added or removed
words are fitted between them.

## State

- **Server:** `JobManager` (services/jobs.py) owns all job state behind one lock. Jobs are `queued →
  running → done/failed`, or `live → done/stopped`. One worker thread handles downloads and files one at
  a time, which keeps memory and power low. Each live stream runs in its own thread, up to `max_parallel_live`.
  Finished jobs are pruned after 200. The reel library is the files on disk, so nothing is lost on restart.
- **Settings:** `makereel.json`, validated by `config.save_settings`, re-read on every use.
- **Browser:** `store.js` holds the whole UI state in one object. Only `store.set()` changes it, and views
  re-render from it. The library view redraws only when its data changes, so polling never restarts a
  playing video. Starting a video pauses every other video (`ui.js`).

## Error handling

- Every expected failure raises a `MakereelError` subclass (`errors.py`) with a message and an optional
  hint. Each subclass has a code and an HTTP status: `invalid_input` 400, `forbidden` 403,
  `not_found` 404, `conflict` 409, `source` 422, `media` 500, `dependency` 503.
- `media.run()` wraps every ffmpeg call and turns failures into `MediaError` with ffmpeg's own last lines.
- yt-dlp errors become `SourceError` with a human hint (private video, update yt-dlp, not live...).
- The API returns `{"error": {"code", "message", "hint"}}`. Unexpected exceptions are logged with a
  traceback and returned as a generic 500, so the server never crashes on one request.
- Jobs record their error, and one failed reel never loses the others from the same video.
- The CLI prints `✗ message` and `→ hint` and exits 1, without a traceback.
- The browser shows the message and hint in a toast. Buttons are disabled while their request runs.

## Logging

Modules log with `logging.getLogger(__name__)`. A context variable carries the current job id, and
`JobLogHandler` copies each record into that job's log for the web app. Threads started with
`logs.spawn()` inherit the job. Set the level with `MAKEREEL_LOG_LEVEL`.

## Security

- The server binds to `127.0.0.1` by default. Binding anywhere else requires a password (HTTP Basic).
- Requests from other sites are refused unless their origin is listed in `MAKEREEL_ALLOWED_ORIGINS`.
- Every file path from a request is resolved and must stay inside the output folder (or the web folder).
- Uploads are streamed to disk with a size cap, and other request bodies are capped at 2 MB.
