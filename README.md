# makereel

Paste any link (a live stream, a past stream, a long video or a Short; YouTube, Twitch, Kick and more)
and get captioned 9:16 reels with full creator credits, ready for Instagram, YouTube Shorts and X.

- **Any link, auto-detected.** Live streams are recorded and clipped as big moments happen. Past streams use the chat replay.
- **One folder per video.** Each folder is named after the video's title, with all its reels inside.
- **Editable, in-sync captions.** Captions are text, not images, and are timed from each reel's own audio. Fix words in a paragraph,
  auto-sync, shift them, or tap along to the audio, all with a live preview.
- **Speaker framing.** "Follow the speaker" keeps the person centred with a calm, smooth camera.
- **Caption styles.** Classic, Pop, Boxed word, Glow, Karaoke fill, One word, Minimal.
- **Trim, split, join.** Every reel keeps 6 s of extra footage on each side, so you can extend or cut it later.
- **Optional AI judge.** A local model or your own key scores moments like an editor and writes titles. Off by default.
- **Any shape.** Export each reel as 9:16, 4:5, 1:1 or 16:9 (blurred fill, crop or black bars) in seconds.
- **Brand kit.** Your logo, fonts and caption colours on every reel. The "Made with makereel" line in the post text is opt-out.
- **Benchmarks.** Measure speed, CPU, RAM and disk on any device, and compare versions.
- **Credits on every post.** Creator, channel link, original title, a link to the exact second, and their tags.
- **Runs on your own machine** (Windows, macOS, Linux or a server) at low power, 24/7 if you like.

Built first for GTA 6 streams; the `talk` profile tunes it for podcasts and talking heads.

## Quick start

```bash
# 1. tools: ffmpeg with libass (text captions), Python 3.10+, Node (yt-dlp uses it for YouTube)
brew install ffmpeg-full python@3.12 node                      # macOS
# winget install Gyan.FFmpeg Python.Python.3.12 OpenJS.NodeJS  # Windows
# sudo apt install ffmpeg python3-venv nodejs                  # Debian / Ubuntu

# 2. install
python3 -m venv .venv && .venv/bin/pip install -e .           # Windows: .venv\Scripts\pip install -e .
cp makereel.example.json makereel.json                         # optional: your channels and defaults
cp .env.example .env                                           # optional: ports, password, threads

# 3. run
.venv/bin/makereel web                                         # opens http://localhost:8765
```

From the terminal instead:

```bash
makereel run "<any link>"                         # live → clips as it streams; anything else → clips now
makereel run "<long VOD>" --section "1:00:00-2:30:00"
makereel local gameplay.mp4 --credit "Name" --credit-url "https://youtube.com/@name"
makereel rerender "Me at the zoo" reel_01 --transcript "fixed caption text…"   # or --sync / --offset -0.2
makereel export "Me at the zoo" reel_01 --format 4x5 --fit blur
makereel bench                                    # speed, CPU, RAM, disk on this device
makereel daemon                                   # 24/7 channel watcher without the web UI
```

## How it picks moments

1. **Cheap signals over the whole video.** It measures loudness every second and chat speed (from the chat replay or live chat). Chat is shifted back about 6 s because people react late. A 10-hour video uses only a few MB of memory.
2. **Candidates.** The biggest spikes become 30-second windows, 3× as many as the reels you asked for.
3. **Transcribe only those windows** (faster-whisper, int8). A 6-hour stream needs about 15 minutes of transcription, not 6 hours. Hype words and talking pace re-rank the windows.
4. **Clean edges.** Each clip starts and ends in a pause between words, and starts on a new shot (PySceneDetect).
5. **Render.** The reel is 9:16 with a blurred fill, loudness-normalised, with an on-screen title and word-by-word captions. It uses a hardware encoder when one is available.

Live streams use a rolling buffer (idea from [PeakCut](https://github.com/haziqahmedqasmi/PeakCut), MIT). The stream is copied into 6-second pieces without re-encoding, which costs almost no CPU, and old pieces are deleted. Nothing is transcribed until loudness or chat jumps 60% above the last 3 minutes.

## Documentation

| | |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Folder structure, layers, data flow, state, error handling |
| [docs/API.md](docs/API.md) | REST API v1 reference |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable and setting |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Windows, macOS, Linux, Docker, servers, 24/7 low-power setup |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setting up, tests, lint, conventions, adding a route |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | What's measured, how to share results, results table |
| [docs/CLIENT_SIDE_PLAN.md](docs/CLIENT_SIDE_PLAN.md) | Plan: offer makereel as a website that runs on each visitor's own device (no servers to pay for) |
| [CHANGELOG.md](CHANGELOG.md) | What changed |

## Credits and responsibility

Every reel's post text credits the original creator and links to the exact moment.
You are responsible for having the right to repost what you clip. Credit is not permission, so check each
platform's rules and the creator's wishes.
