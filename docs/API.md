# REST API v1

Base URL: `http://localhost:8765/api/v1`. Bodies and responses are JSON.
When a password is set, send HTTP Basic auth (any username).

Errors always look like this:

```json
{ "error": { "code": "source", "message": "Private video", "hint": "The video is private, members-only or age-restricted." } }
```

| Code | Status | Meaning |
|---|---|---|
| `invalid_input` | 400 | bad link, empty transcript, bad section... |
| `config` | 400 | a setting is invalid |
| `forbidden` | 403 | path outside the library, or an origin that isn't allowed |
| `not_found` | 404 | no such job, folder or reel |
| `method_not_allowed` | 405 | wrong HTTP method for that route |
| `conflict` | 409 | e.g. too many live streams at once |
| `source` | 422 | the link couldn't be opened or downloaded |
| `media` | 500 | ffmpeg or the speech model failed |
| `dependency` | 503 | ffmpeg / libass missing |

## System

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"ok": true, "version": "0.2.0"}` |
| GET | `/system` | OS, ffmpeg path, `libass`, `encoder`, `threads`, `version` |

## Jobs

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/jobs` | | `{"jobs": [Job]}` newest first |
| POST | `/jobs` | `{"url", "section"?, "profile"?, "max_clips"?, "min_len"?, "max_len"?, "model"?, "language"?, "layout"?}` | `201 Job` |
| POST | `/jobs/upload?name=&title=&credit=&credit_url=&…` | raw file bytes (not multipart) | `201 Job` |
| GET | `/jobs/{id}` | | `Job` plus `log` (full text) |
| POST | `/jobs/{id}/stop` | | `Job`. Live: finishes any reel in progress, then stops. Queued: cancels it. |

```json
{
  "id": "a1b2c3d4e5", "kind": "link", "target": "https://youtu.be/…", "status": "live",
  "title": "GTA 6 day one", "folder": "GTA 6 day one", "reels": 3,
  "live": { "seconds": 1820, "reels": 3, "chat": 5120 },
  "error": null, "created": 1794747656.2, "finished": null, "last_line": "  spike at 1712s (chat)"
}
```

`status` is one of `queued`, `running`, `live`, `done`, `failed` or `stopped`.

## Library

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/folders` | | `{"folders": [{folder, title, channel, url, live, count, updated, cover}]}` |
| GET | `/folders/{folder}` | | `{folder, info, reels: [Reel]}` |
| DELETE | `/folders/{folder}` | | 204 |
| GET | `/folders/{folder}/reels/{name}` | | `Reel` plus `transcript` and `ass` |
| PATCH | `/folders/{folder}/reels/{name}` | any of `{"transcript", "words", "offset", "hook", "caption", "ass", "logo", "restyle", "look"}` | updated `Reel` (re-rendered, exports too) |
| POST | `/folders/{folder}/reels/{name}/sync` | | auto-sync: re-time captions from the reel's own audio, keeping corrected words |
| POST | `/folders/{folder}/reels/{name}/export` | `{"format": "9x16"\|"4x5"\|"1x1"\|"16x9", "fit": "blur"\|"crop"\|"pad"}` | updated `Reel`, with `exports[format]` holding `video` and `download` |
| DELETE | `/folders/{folder}/reels/{name}` | | 204 |

URL-encode folder names (`Me%20at%20the%20zoo`). Reel names look like `reel_01`.

PATCH rules:
- `transcript` is the caption words as one paragraph. Words you didn't change keep their exact timing.
  Edited, added or removed words are fitted between them (sequence alignment).
- `words` gives exact timings from the timing editor: `[{"start": 1.06, "end": 1.6, "word": "ALRIGHT"}, ...]` (seconds on the reel's clock).
- `offset` moves every caption earlier (negative) or later (positive), in seconds (at most ±10).
- `look` sets this reel's caption placement and background, e.g. to avoid subtitles already in the video:
  `{"vertical": 0.45, "size": 0.9, "box": true, "box_colour": "#000000", "box_opacity": 0.6}`.
  `vertical` is where the bottom of the captions sits, as a share of the height from the bottom (0.02–0.9).
  Keys you leave out keep their value. It applies to the reel and all its exports, and the GET response returns the effective `look`.
- `logo` (bool) shows or hides the brand logo on this reel. `restyle: true` re-applies the brand kit's caption style.
- `hook` changes the on-screen title, and the first line of the post text follows it.
- `caption` is the post text (credits, hashtags).
- `ass` replaces the whole caption file (styles, timing). It wins over `transcript` and `hook`.

```bash
curl -X PATCH localhost:8765/api/v1/folders/Me%20at%20the%20zoo/reels/reel_01 \
  -H 'Content-Type: application/json' -d '{"transcript": "OKAY SO HERE WE ARE…", "hook": "Meet the elephants"}'
```

Media files are served at `/media/{folder}/{file}` with HTTP range support. Add `?download=1` to download.

## Brand kit

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/brand` | | `{logo, fonts, settings}` (settings are `brand` in CONFIGURATION.md) |
| PUT | `/brand/logo` | raw PNG / WebP / JPG bytes (≤ 5 MB) | `{logo, fonts}` |
| DELETE | `/brand/logo` | | `{logo: null, fonts}` |
| PUT | `/brand/fonts/{file.ttf}` | raw font bytes (≤ 20 MB) | `{logo, fonts}` |
| DELETE | `/brand/fonts/{file.ttf}` | | `{logo, fonts}` |

Change brand settings with `PUT /settings {"brand": {...}}`. The logo is served at `/brand/logo.png`.

## Benchmarks

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/bench` | | `{device, runs, share_enabled}` |
| POST | `/bench` | `{"model"?, "video"?}` | `201 Job` (kind `bench`; its `result.id` is set when done) |
| GET | `/bench/{id}` | | the result plus `compare` (vs the previous run), `report` (Markdown) and `share_url` |

## Settings and watcher

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/settings` | | the full settings (see CONFIGURATION.md) |
| PUT | `/settings` | any subset, e.g. `{"channels": ["@a"], "poll_minutes": 5, "clip": {"max_clips": 4}}` | validated full settings |
| GET | `/watcher` | | `{"running": bool}` |
| PUT | `/watcher` | `{"running": true}` | `{"running": bool}` |

## Versioning

Breaking changes go to `/api/v2`, and `/api/v1` keeps working until clients have moved. Adding fields
to responses is not a breaking change, so clients should ignore fields they don't know.
