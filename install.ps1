# makereel installer for Windows 10/11. Run in PowerShell:
#   irm https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.ps1 | iex
#
# What it does (nothing needs admin rights except winget's own prompts):
#   1. ffmpeg (with caption support) and Node.js, through winget, if they're missing
#   2. uv, a small Python installer; it brings its own Python 3.12, so you don't need Python
#   3. makereel itself, in its own environment
#   4. a "makereel" folder in your home for settings and reels, and Start menu + desktop shortcuts
# Run it again any time to repair or update.
# Everything runs inside a script block, so with `irm … | iex` none of its settings (like the strict
# error mode) stay behind in the user's PowerShell window.
& {
  $ErrorActionPreference = "Stop"
  $Repo = if ($env:MAKEREEL_REPO) { $env:MAKEREEL_REPO } else { "simarpreetsingh-019/makereel" }
  $Source = if ($env:MAKEREEL_SOURCE) { $env:MAKEREEL_SOURCE } else { "makereel @ https://github.com/$Repo/archive/refs/heads/main.zip" }   # a zip: no git needed
  $Home_ = Join-Path $env:USERPROFILE "makereel"
  $env:UV_PYTHON_PREFERENCE = "only-managed"   # always uv's own Python: works with no Python, or an old one

  function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
  function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
  function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
  }
  # Run an external program. Windows PowerShell 5.1 treats anything a program prints to stderr as an error
  # (and stops the script under "Stop"), even notes like uv's "already in PATH", so stderr is just shown and
  # only the exit code decides. -Optional: a failure is only reported, never fatal.
  function Invoke-Native([scriptblock]$cmd, [string]$what, [switch]$Optional) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $global:LASTEXITCODE = 0
    try { & $cmd 2>&1 | ForEach-Object { "$_" } | Out-Host } finally { $ErrorActionPreference = $old }
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
      if ($Optional) { Write-Host "  (note: $what returned $LASTEXITCODE; continuing)" }
      else { throw "$what failed (exit code $LASTEXITCODE). Run this installer again; if it keeps failing, share this window's text." }
    }
  }
  function Install-Tool($id, $choco) {
    if (Have winget) { Invoke-Native { winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent } "winget install $id" }
    elseif (Have choco) { Invoke-Native { choco install $choco -y } "choco install $choco" }
    else { throw "Install $id yourself (winget isn't available here), then run this again." }
    Refresh-Path
  }

  Step "Checking ffmpeg (video) and Node.js (YouTube support)"
  $needFfmpeg = -not (Have ffmpeg)
  if (-not $needFfmpeg) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $needFfmpeg = -not ((ffmpeg -hide_banner -filters 2>&1 | ForEach-Object { "$_" }) -match " ass ")
    $ErrorActionPreference = $old
  }
  if ($needFfmpeg) { Write-Host "Installing ffmpeg (full build, with captions)…"; Install-Tool "Gyan.FFmpeg" "ffmpeg-full" }
  else { Write-Host "ffmpeg is ready." }
  if (-not (Have node) -and -not (Have deno)) { Write-Host "Installing Node.js…"; Install-Tool "OpenJS.NodeJS.LTS" "nodejs-lts" }
  else { Write-Host "Node.js is ready." }

  Step "Installing uv (brings its own Python, nothing else needed)"
  if (-not (Have uv)) {
    Invoke-Native { powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex" } "installing uv"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  }

  Step "Installing makereel"
  Invoke-Native { uv tool install --force --python 3.12 $Source } "installing makereel"
  Invoke-Native { uv tool update-shell } "adding makereel to PATH" -Optional
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  $exe = (Get-Command makereel -ErrorAction Stop).Source
  Invoke-Native { makereel --version } "checking makereel"

  Step "Creating your makereel folder and shortcuts"
  New-Item -ItemType Directory -Force $Home_ | Out-Null
  $launcher = Join-Path $Home_ "Start makereel.cmd"
  Set-Content -Encoding ASCII $launcher "@echo off`r`ncd /d `"$Home_`"`r`n`"$exe`" start`r`n"
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
  Write-Host "Check on it any time with: makereel status   ·   all commands: makereel help"
  if (-not $env:MAKEREEL_NO_LAUNCH) { Start-Process $launcher -WorkingDirectory $Home_ }
}
