# Configuration

There are two kinds of configuration, kept apart on purpose.

| | Environment (`.env` / `MAKEREEL_*`) | Settings (`makereel.json`) |
|---|---|---|
| What | how and where this install runs, plus secrets | what you tune day to day |
| Who edits | whoever deploys it | you, from the 24/7 tab or by hand |
| When read | at start-up | on every use (no restart needed) |
| Committed to Git? | `.env` never; `.env.example` yes | `makereel.json` never; `makereel.example.json` yes |

## Environment variables

Put them in `.env` (copy `.env.example`) or set them in the shell or service. Real environment
variables win over `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `MAKEREEL_CONFIG` | `makereel.json` | settings file |
| `MAKEREEL_OUTPUT_DIR` | `output` | reel library (one folder per video) |
| `MAKEREEL_WORK_DIR` | `downloads` | temporary downloads, uploads and live buffers |
| `MAKEREEL_DATA_DIR` | `data` | brand kit (logo, fonts) and benchmark history |
| `MAKEREEL_REPO_URL` | none | your repository URL; enables "Share benchmark" (a pre-filled GitHub issue) |
| `MAKEREEL_HOST` | `127.0.0.1` | `0.0.0.0` to reach it from other devices (requires a password) |
| `MAKEREEL_PORT` / `PORT` | `8765` | `PORT` wins (hosting services set it) |
| `MAKEREEL_WEB_PASSWORD` | none | HTTP Basic password; required when the host isn't local |
| `MAKEREEL_ALLOWED_ORIGINS` | none | comma-separated sites allowed to call this engine from a browser (see CLIENT_SIDE_PLAN.md) |
| `MAKEREEL_THREADS` | `2` | CPU threads for speech-to-text and x264. Fewer threads use less power. |
| `MAKEREEL_ENCODER` | auto | force `h264_videotoolbox`, `h264_nvenc`, `h264_qsv`, `h264_amf` or `libx264` |
| `MAKEREEL_FFMPEG_DIR` | auto | folder containing an ffmpeg built with libass |
| `MAKEREEL_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

The encoder is picked automatically. A hardware encoder (Apple, NVIDIA, Intel or AMD) is used if one
passes a one-frame test; otherwise it falls back to `libx264`.

## Settings (`makereel.json`)

| Key | Default | Meaning |
|---|---|---|
| `channels` | `[]` | `@handle`, channel links, `twitch.tv/name`, `kick.com/name` |
| `inbox` | `inbox.txt` | for headless use: links pasted here (one per line) get clipped |
| `poll_minutes` | 4 | how often to check if channels are live |
| `max_parallel_live` | 2 | live streams recorded at once |
| `keep_days` | 7 | folders untouched this long are deleted by the watcher |
| `keep_source` | false | keep downloaded videos after clipping |
| `buffer_minutes` | 10 | live rolling buffer (about 9 MB per minute at 720p) |
| `clips_per_hour` | 6 | reel limit per live stream |
| `max_height` | 720 | source resolution to download (720p is plenty for 1080×1920) |
| `clip.profile` | `gameplay` | `gameplay` or `talk` (weights for loudness, chat, words and speech) |
| `clip.max_clips` | 8 | reels per video (1–50) |
| `clip.min_len` / `clip.max_len` | 15 / 45 | reel length in seconds |
| `clip.model` | `base` | speech model: `tiny`, `base`, `small`, `medium` or `large-v3` |
| `clip.layout` | `blur` | `blur` (whole frame over a blurred fill), `crop`, `pad` (black bars) or `track` (follow the speaker) |
| `clip.language` | auto | e.g. `en`, `hi`, `pa`. Auto-detected once per video, so every reel of a video uses the same language and script |
| `clip.model_other` | `small` | model used for non-English speech when `clip.model` is `tiny` or `base`: `small`, `medium`, `large-v3`, or `same` to never switch |
| `clip.silence` | false | cut dead air with auto-editor (`pip install -e ".[silence]"`) |

### Brand kit (`brand`)

| Key | Default | Meaning |
|---|---|---|
| `logo_enabled` | true | show the uploaded logo on reels (also switchable per reel) |
| `logo_position` | `top-right` | `top-left`, `top-right`, `bottom-left` or `bottom-right` |
| `logo_scale` | 0.16 | logo width as a share of the video width (0.03–0.6) |
| `logo_opacity` | 0.9 | 0.05–1 |
| `font` | `Arial Black` | any installed font, or one uploaded in the Brand tab (use its family name) |
| `text_colour` / `highlight_colour` / `outline_colour` | `#FFFFFF` / `#FFDD00` / `#000000` | caption colours |
| `caption_position` | `bottom` | `bottom` (lower third), `middle` or `top` |
| `caption_size` | 1.0 | 0.5–2 × the default size |
| `caption_script` | `original` | how captions are written: `original` (the spoken language's own script, e.g. Devanagari), `roman` (the same words in English letters: "kya baat hai"), or `english` (translated). Per reel in the editor's Look tab too |
| `safe_zone` | `all` | keep captions, title and logo clear of the apps' own buttons and text on 9:16 reels: `all` (strictest of the three), `tiktok`, `reels`, `shorts`, or `off` |
| `caption_template` | `classic` | default caption style: `classic`, `pop`, `boxed`, `glow`, `karaoke`, `single` or `minimal` |
| `caption_box` | false | a background box behind captions (helps over busy video or video with its own subtitles) |
| `box_colour` / `box_opacity` | `#000000` / 0.6 | background colour, and how solid it is (0 = invisible, 1 = solid) |
| `credit_footer` | true | end the post text with "✂️ Made with makereel". It's opt-out, and is never put on the video. |

### AI judge (`ai`): optional

| Key | Default | Meaning |
|---|---|---|
| `provider` | `off` | `off`; `local` (Ollama, LM Studio or any OpenAI-compatible server on this machine; nothing leaves it); `claude` (your Anthropic key, `pip install "makereel[ai]"`); or `openai` (any OpenAI-compatible API with your key: OpenAI, OpenRouter, Groq...) |
| `model` | provider default | `llama3.1:8b` for local and `claude-opus-5-5` for claude; required for openai |
| `base_url` | provider default | `http://localhost:11434/v1` for local |
| `weight` | 0.5 | how much the AI's scores count against loudness, chat and words (0–1) |

The API key goes in `.env` as `MAKEREEL_AI_KEY` (or `ANTHROPIC_API_KEY` for Claude), never in `makereel.json`.
The judge only reads the shortlist's transcripts, a few thousand tokens per video. If anything fails, it
falls back to the signal-only ranking.

Each reel can override the height, size and background in Edit → **Look**. That's how to deal with
videos that already have subtitles burned in: move the captions above them, or cover them with a solid background.

The brand applies to new reels. For existing reels, use Edit → *Apply brand style* (captions); the logo
setting applies on any re-render.

Invalid values are rejected with a message saying what's wrong, both from the API and at start-up.
