# makereel installer for Windows 10/11. Run in PowerShell:
#   irm https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.ps1 | iex
#
# What it does (nothing needs admin rights except winget's own prompts):
#   1. ffmpeg (with caption support) and Node.js, through winget, if they're missing
#   2. uv, a small Python installer; it brings its own Python 3.12, so you don't need Python
#   3. makereel itself, in its own environment
#   4. a "makereel" folder in your home for settings and reels, and Start menu + desktop shortcuts
# Run it again any time to repair or update.
$ErrorActionPreference = "Stop"
$Repo = if ($env:MAKEREEL_REPO) { $env:MAKEREEL_REPO } else { "simarpreetsingh-019/makereel" }
$Source = if ($env:MAKEREEL_SOURCE) { $env:MAKEREEL_SOURCE } else { "git+https://github.com/$Repo" }
$Home_ = Join-Path $env:USERPROFILE "makereel"

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
}
function Install-Tool($id, $choco) {
  if (Have winget) { winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent | Out-Host }
  elseif (Have choco) { choco install $choco -y | Out-Host }
  else { throw "Install $id yourself (winget isn't available here), then run this again." }
  Refresh-Path
}

Step "Checking ffmpeg (video) and Node.js (YouTube support)"
$needFfmpeg = -not (Have ffmpeg)
if (-not $needFfmpeg) { $needFfmpeg = -not ((ffmpeg -hide_banner -filters 2>$null) -match " ass ") }
if ($needFfmpeg) { Write-Host "Installing ffmpeg (full build, with captions)…"; Install-Tool "Gyan.FFmpeg" "ffmpeg-full" }
else { Write-Host "ffmpeg is ready." }
if (-not (Have node) -and -not (Have deno)) { Write-Host "Installing Node.js…"; Install-Tool "OpenJS.NodeJS.LTS" "nodejs-lts" }
else { Write-Host "Node.js is ready." }

Step "Installing uv (brings its own Python, nothing else needed)"
if (-not (Have uv)) {
  powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Host
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Step "Installing makereel"
uv tool install --force --python 3.12 $Source | Out-Host
uv tool update-shell 2>$null | Out-Null
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
$exe = (Get-Command makereel -ErrorAction Stop).Source
makereel --version

Step "Creating your makereel folder and shortcuts"
New-Item -ItemType Directory -Force $Home_ | Out-Null
$launcher = Join-Path $Home_ "Start makereel.cmd"
Set-Content -Encoding ASCII $launcher "@echo off`r`ncd /d `"$Home_`"`r`n`"$exe`" web`r`n"
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
  $lnk = $shell.CreateShortcut((Join-Path $dir "makereel.lnk"))
  $lnk.TargetPath = $launcher
  $lnk.WorkingDirectory = $Home_
  $lnk.Description = "Turn live streams and videos into reels"
  $lnk.Save()
}

Write-Host "`nmakereel is installed." -ForegroundColor Green
Write-Host "Open it from the desktop or Start menu ('makereel'). Your reels and settings live in $Home_"
if (-not $env:MAKEREEL_NO_LAUNCH) { Start-Process $launcher -WorkingDirectory $Home_ }
