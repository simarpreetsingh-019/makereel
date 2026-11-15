# Deployment

makereel runs wherever Python 3.10+ and an ffmpeg with libass run. Pick one of the setups below.

## Requirements

| | macOS | Windows | Debian / Ubuntu |
|---|---|---|---|
| ffmpeg with libass | `brew install ffmpeg-full` | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |
| Python | `brew install python@3.12` | `winget install Python.Python.3.12` | `sudo apt install python3-venv` |
| Node (for YouTube) | `brew install node` | `winget install OpenJS.NodeJS` | `sudo apt install nodejs` |

Homebrew's `ffmpeg-full` installs next to the normal `ffmpeg` and is found automatically.
Keep yt-dlp current, because YouTube changes often: `pip install -U "yt-dlp[default]"`.

## On your own computer

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/makereel web
```

### Keep it running 24/7 at low power

| OS | How |
|---|---|
| macOS | `./deploy/install-macos.sh` (launchd; `./deploy/install-macos.sh uninstall` to remove) |
| Windows | Task Scheduler "At log on" running `deploy\start-windows.ps1` (instructions inside the file) |
| Linux | `cp deploy/makereel.service ~/.config/systemd/user/ && systemctl --user enable --now makereel`, then `loginctl enable-linger $USER` |

All of them run `makereel web --watch`, so you get the web app and the channel watcher together.

What keeps it light (measured on an Apple-silicon laptop):

| State | CPU | Memory |
|---|---|---|
| Idle, watching channels | ~0% | ~120 MB |
| Recording a live stream | ~0% (stream copy) | ~310 MB in total (Python, chat reader, ffmpeg) |
| Making a reel | short bursts of 15–30 s | up to ~700 MB with the `base` model |

- macOS `ProcessType=Background` runs it on the efficiency cores. Linux uses `Nice`, idle IO and a `CPUQuota` / `MemoryMax`.
- 2 transcription threads, a small speech model that is unloaded between streams, and 720p sources.
- A hardware video encoder where available.
- Downloaded videos are deleted after clipping, and old folders after `keep_days`.
- On macOS, `caffeinate -s` keeps the machine awake only while it's on the charger.

## On a server (VPS, NAS, home server)

```bash
docker build -t makereel .
docker run -d --name makereel --restart unless-stopped -p 8765:8765 \
  -e MAKEREEL_WEB_PASSWORD='something long' -v "$PWD/data:/data" makereel
```

`/data` holds `makereel.json`, `output/` and `downloads/`. The container has a health check on `/api/v1/health`.

Without Docker: `makereel web --host 0.0.0.0 --password '…' --no-browser` (or set the `MAKEREEL_*`
variables) under systemd.

**If it faces the internet, put HTTPS in front of it.** Caddy is the shortest option:

```
reels.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

Cloudflare Tunnel works too, and needs no open port.

### Scaling notes

- One instance processes one video at a time on purpose (low memory). For more throughput, run several
  instances, each with its own `MAKEREEL_OUTPUT_DIR`, behind a proxy, or raise the worker count in
  `services/jobs.py` on a machine with enough RAM (about 700 MB per worker with the `base` model).
- YouTube rate-limits datacenter IPs. A home connection is often more reliable for downloading than a cloud VM.
- For a public multi-user service, see [CLIENT_SIDE_PLAN.md](CLIENT_SIDE_PLAN.md). Running the work on
  each user's own device avoids compute costs and most of the download blocking.

## Platform notes

- **Windows:** folder names are made Windows-safe automatically. NVIDIA, Intel and AMD GPUs are used for encoding.
- **Linux without a GPU:** x264 is used, with `MAKEREEL_THREADS` threads.
- **Raspberry Pi 5:** works. Use the `tiny` or `base` model and `max_height: 720`.
