#!/bin/bash
# Run makereel (web app + channel watcher) 24/7 as a low-priority background service (macOS launchd).
# Then open http://localhost:8765.
#   ./deploy/install-macos.sh            install + start
#   ./deploy/install-macos.sh uninstall  stop + remove
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.makereel.daemon
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; echo "removed"; exit 0
fi

[[ -f "$DIR/makereel.json" ]] || cp "$DIR/makereel.example.json" "$DIR/makereel.json"
mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <!-- caffeinate -s: keep the Mac awake only while on power (lid-open / clamshell with charger) -->
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-s</string>
    <string>$DIR/.venv/bin/makereel</string><string>web</string>
    <string>--watch</string><string>--no-browser</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>MAKEREEL_THREADS</key><string>2</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <!-- Background = runs on the efficiency cores, throttled CPU + disk: lowest power -->
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$DIR/logs/makereel.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/makereel.err</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "running. logs: $DIR/logs/makereel.log   stop: $0 uninstall"
