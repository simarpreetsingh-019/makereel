# Start makereel (web app + channel watcher) on Windows.
#   powershell -ExecutionPolicy Bypass -File deploy\start-windows.ps1
# To run it at every login: Task Scheduler -> Create Task -> Trigger "At log on" ->
#   Action: powershell.exe  Arguments: -WindowStyle Hidden -ExecutionPolicy Bypass -File "<repo>\deploy\start-windows.ps1"
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv; .\.venv\Scripts\pip install -e . }
if (-not (Test-Path "makereel.json")) { Copy-Item makereel.example.json makereel.json }
New-Item -ItemType Directory -Force logs | Out-Null
$env:PYTHONUNBUFFERED = "1"
.\.venv\Scripts\makereel.exe web --watch *>> logs\makereel.log
