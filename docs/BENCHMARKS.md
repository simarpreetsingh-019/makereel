# Benchmarks

Measure how fast makereel is on a device and what it costs, and compare versions.

## Running one

- **Web app:** System tab → tick *Allow the benchmark to run on this device* → **Run benchmark**.
- **Terminal:** `makereel bench` (options: `--model tiny|base|small`, `--video <link or file>`).

By default it makes reels from a fixed 19-second public test video, which is downloaded once and
cached in `data/bench/`. The reels go to a temporary folder that is deleted afterwards, so your
library isn't touched.

## What is measured

| Metric | How |
|---|---|
| Total time, speed (× real time), time per reel | wall clock around the whole pipeline |
| Time per stage | `probe`, `signals` (loudness + chat), `transcribe`, `scenes`, `render`, `sync` (`core/metrics.py`) |
| CPU time | user + system seconds of makereel **and** every ffmpeg / yt-dlp process it starts. The best cross-platform stand-in for energy use. |
| Avg CPU | CPU time ÷ wall time ÷ cores, as a share of the whole machine |
| Peak CPU, peak RAM | sampled every 0.25 s over the whole process tree (psutil) |
| Disk | peak size of the working folder, and size of the finished reels |
| GPU load | NVIDIA only (`nvidia-smi`). Apple and Intel GPUs don't expose this without admin rights. The *encoder* row shows whether the hardware video encoder was used. |
| Power | not measured directly (needs admin rights on macOS). CPU time is the proxy. The report notes if the laptop was on battery, which slows things down. |

Results are appended to `data/benchmarks.jsonl`. Each new run is compared with the previous run on
the same CPU, model and input, so you can see whether a change made makereel faster or slower:
`time −12% · CPU −8% · RAM +3%` (negative is better).

## Sharing results (opt-in)

Nothing is ever sent automatically. There's no server. The report contains only hardware and
timings: CPU, cores, RAM, GPU name, OS, versions and the numbers above. It has no user names, paths,
links or video titles.

- **Copy report** puts a Markdown table on the clipboard.
- **Share with the project…** appears when `MAKEREEL_REPO_URL` is set (e.g. `https://github.com/you/makereel`).
  It opens a pre-filled GitHub issue labelled `benchmark` that the user reviews and submits themselves.
- Maintainers add good results to the table below with a pull request.

## Results

| Version | Device | OS | Model | Input | Total | Speed | CPU time | Peak RAM | Encoder |
|---|---|---|---|---|---|---|---|---|---|
| 0.3.0 | Apple M5, 10 cores, 16 GB (on battery) | macOS 27 | base | test video 19 s → 1 reel | 8.9 s | 2.2× | 13.2 s | 642 MB | VideoToolbox |

The 0.3.0 run includes the new caption auto-sync pass (1.4 s) and keeping the master clip for exports.
Rendering is the largest stage (5.6 s of 8.9 s).
