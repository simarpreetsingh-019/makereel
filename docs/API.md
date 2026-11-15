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
| PATCH | `/folders/{folder}/reels/{name}` | any of `{"transcript", "hook", "caption", "ass"}` | updated `Reel` (re-rendered) |
| DELETE | `/folders/{folder}/reels/{name}` | | 204 |

URL-encode folder names (`Me%20at%20the%20zoo`). Reel names look like `reel_01`.

PATCH rules:
- `transcript` is the caption words as one paragraph. With the same word count, each word keeps its
  exact timing. Otherwise the words are spread evenly over the same span.
- `hook` changes the on-screen title, and the first line of the post text follows it.
- `caption` is the post text (credits, hashtags).
- `ass` replaces the whole caption file (styles, timing). It wins over `transcript` and `hook`.

```bash
curl -X PATCH localhost:8765/api/v1/folders/Me%20at%20the%20zoo/reels/reel_01 \
  -H 'Content-Type: application/json' -d '{"transcript": "OKAY SO HERE WE ARE…", "hook": "Meet the elephants"}'
```

Media files are served at `/media/{folder}/{file}` with HTTP range support. Add `?download=1` to download.

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
