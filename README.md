# makereel

**Turn live streams and long videos into captioned vertical reels, automatically, on your own computer.**

makereel watches a YouTube, Twitch or Kick stream (or any video link or file), finds the big moments as
they happen, and makes 9:16 reels with word-by-word captions, smart framing and full credit to the
creator. Ready for YouTube Shorts, Instagram Reels and TikTok. It runs on Windows, macOS and Linux, needs
no account and no API key, and nothing is uploaded anywhere.

[Website](https://simarpreetsingh-019.github.io/makereel/) · [Getting started](docs/GETTING_STARTED.md) ·
[For AI assistants: llms.txt](llms.txt)

```text
live stream ──▶ big moment (loud + chat spike) ──▶ reel: 9:16, captions, framing, creator credit
```

## Why makereel

Most "long video to shorts" tools work on finished videos, in the cloud, with an AI key. makereel is built
for streamers and clippers:

| | makereel |
|---|---|
| **Clips live streams while they're live** | A rolling buffer records the stream; a reel is made each time something big happens. |
| **Watches channels 24/7** | Clips your channels when they go live, plus new uploads and premieres. |
| **Reads the chat** | Moments are found from chat activity *and* loudness, not just the transcript. |
| **Credits every creator** | Channel badge on the video; creator, link and exact timestamp in the post text. |
| **Hindi, English and Hinglish** | Language per sentence, a Hinglish model, YouTube's own captions for past videos, and a second model that double-checks every caption. |
| **Free and private** | Runs on your computer. Optional AI only with your own key. |
| **Low power** | Stream copying uses almost no CPU; a "Cool and quiet" mode keeps laptops calm. |

## Install (one command)

No Python needed first: the installer gets ffmpeg, Node.js and its own Python if they're missing.

**Windows 10/11** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.ps1 | iex
```

**macOS / Linux** (Terminal):

```bash
curl -LsSf https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.sh | bash
```

Then open **makereel** from the shortcut, or run `makereel start`. Check on it with `makereel status`;
update with `makereel update`; all commands: `makereel help`.

## Features

**Finding moments**
- Live clipping with a rolling 10-minute buffer; past streams use the chat replay.
- Each reel is as long as its moment (a quick reaction ≈ 30 s, a long bit up to your limit, max 5 min).
- Optional AI judge (a local model, Claude, or any OpenAI-compatible API) scores hook, engagement, value
  and shareability, and writes titles.

**Captions**
- Word-by-word captions, 7 styles, kept clear of TikTok/Reels/Shorts buttons.
- Hindi, English and mixed speech: language per sentence; a **Hinglish** model (Hindi and English in
  English letters); YouTube's own captions for finished videos; captions in the original script, in
  English letters, or translated to English.
- A **second model double-checks** captions; disagreements show in yellow side by side, one click to fix.
- Edit any word (timing kept), shift or tap-to-sync, import SRT/VTT.

**Framing and look**
- Auto layout: split screen (two people, or webcam over gameplay), follow the speaker, or blurred fill.
- Follow the speaker by who is talking; edit the camera cuts on a timeline; "show everyone" zoom-outs.
- Brand kit (logo, fonts, colours) and a creator badge (channel picture + @handle).

**Editing and export**
- Trim, split, join, and "make short versions" of a long reel.
- Quote and note cards, outros. Export as 9:16, 4:5, 1:1 or 16:9.

**Automation and setup**
- Channel watcher for live streams and new uploads; start-date window and check interval.
- Speech models suggested for your computer (RAM, disk, NVIDIA GPU); NVIDIA GPU speech with CPU fallback.
- Live CPU/temperature card, processing modes, choose where files are saved, clear cache.
- YouTube "are you a bot?" checks: retries other clients first, then a sign-in file or browser sign-in.
- Updates from GitHub with checksum verification; `makereel update`.

## How it works

1. **yt-dlp** asks the site where the stream is; **ffmpeg** copies it (no re-encoding) into 6-second
   pieces in a rolling buffer and reads the loudness every second; a second yt-dlp process counts chat.
2. A jump in loudness or chat opens a **moment**; it stays open while the moment lasts.
3. The moment is cut, **transcribed** (faster-whisper, or YouTube's captions for past videos) and checked
   by a second model, **framed** (face and speaker detection) and **rendered** with a hardware encoder.
4. Post text with full credits is written next to each reel. Everything stays on your computer.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## From the terminal

```bash
makereel start                                   # first-run setup, then open the app
makereel run "<any link>"                        # live: clips as it streams; anything else: clips now
makereel run "<long video>" --section "1:00:00-2:30:00" --language hi
makereel local gameplay.mp4 --credit "Name" --credit-url "https://youtube.com/@name"
makereel status                                  # what's installed, running, recording
makereel signin cookies.txt                      # a YouTube sign-in file, if YouTube asks
makereel daemon                                  # 24/7 channel watcher without the app
```

## FAQ

**Is it free?** Yes. It runs on your computer; there's nothing to pay for. AI features are optional and use
your own key.

**Does it upload my videos?** No. Everything is processed locally. The only network use is downloading the
stream or video, checking channels, and checking for updates.

**Which sites?** YouTube, Twitch and Kick, and any site yt-dlp supports, plus local video files.

**Which languages?** Any language Whisper supports; extra care for Hindi, English and Hinglish.

**Do I need a GPU?** No. An NVIDIA GPU makes speech faster; Apple Silicon Macs run well on the CPU.

**Can I repost other people's streams?** Credit is not permission. You're responsible for having the right
to repost what you clip; check each platform's rules and the creator's wishes.

## Documentation

| | |
|---|---|
| [Getting started](docs/GETTING_STARTED.md) | Install, speech models, your first reels, editing, 24/7 |
| [Architecture](docs/ARCHITECTURE.md) | Folder structure, layers, data flow |
| [Configuration](docs/CONFIGURATION.md) | Every setting and environment variable |
| [API](docs/API.md) | Local REST API |
| [Deployment](docs/DEPLOYMENT.md) | Windows, macOS, Linux, Docker, 24/7 setups |
| [Development](docs/DEVELOPMENT.md) | Tests, lint, conventions |
| [Benchmarks](docs/BENCHMARKS.md) | Speed, CPU, memory measurements |
| [Releasing](docs/RELEASING.md) | Publishing updates |
| [Changelog](CHANGELOG.md) | What changed |

## Credits

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), OpenCV, PySceneDetect and
[uv](https://github.com/astral-sh/uv). The live rolling-buffer idea comes from
[PeakCut](https://github.com/haziqahmedqasmi/PeakCut) (MIT). Hinglish speech models by
[Oriserve](https://huggingface.co/Oriserve) (Apache-2.0).
