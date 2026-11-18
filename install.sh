#!/usr/bin/env bash
# makereel installer for macOS and Linux. Run in a terminal:
#   curl -LsSf https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.sh | bash
#
# What it does:
#   1. ffmpeg (with caption support) and Node.js, if they're missing (Homebrew on macOS, apt/dnf/pacman on Linux)
#   2. uv, a small Python installer; it brings its own Python 3.12, so you don't need Python
#   3. makereel itself, in its own environment
#   4. a "makereel" folder in your home for settings and reels, and a launcher (macOS: on the Desktop)
# Run it again any time to repair or update.
set -euo pipefail
REPO="${MAKEREEL_REPO:-simarpreetsingh-019/makereel}"
SOURCE="${MAKEREEL_SOURCE:-makereel @ https://github.com/$REPO/archive/refs/heads/main.zip}"   # a zip: no git needed
HOME_DIR="$HOME/makereel"
export UV_PYTHON_PREFERENCE=only-managed   # always uv's own Python: works with no Python, or an old one
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"   # already root (e.g. a container): no sudo needed
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
OS="$(uname -s)"

has_captions() {   # ffmpeg built with libass (text captions)
  local f
  for f in /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg /usr/local/opt/ffmpeg-full/bin/ffmpeg "$(command -v ffmpeg || true)"; do
    [ -x "$f" ] && "$f" -hide_banner -filters 2>/dev/null | grep -q " ass " && return 0
  done
  return 1
}

step "Checking ffmpeg (video) and Node.js (YouTube support)"
if [ "$OS" = "Darwin" ]; then
  if ! have brew; then
    echo "Installing Homebrew (macOS's package manager; it asks for your password)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
  fi
  has_captions || { echo "Installing ffmpeg (full build, with captions)…"; brew install ffmpeg-full; }
  have node || have deno || { echo "Installing Node.js…"; brew install node; }
else
  if ! has_captions || ! { have node || have deno; }; then
    echo "Installing ffmpeg and Node.js (asks for your password)…"
    if have apt-get; then $SUDO apt-get update -qq && DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq ffmpeg nodejs
    elif have dnf; then $SUDO dnf install -y ffmpeg nodejs
    elif have pacman; then $SUDO pacman -S --noconfirm ffmpeg nodejs
    else echo "Please install ffmpeg and Node.js with your package manager, then run this again."; exit 1; fi
  fi
fi
echo "ffmpeg and Node.js are ready."

step "Installing uv (brings its own Python, nothing else needed)"
if ! have uv; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

step "Installing makereel"
uv tool install --force --python 3.12 "$SOURCE"
uv tool update-shell >/dev/null 2>&1 || true
EXE="$(command -v makereel)"
makereel --version

step "Creating your makereel folder and launcher"
mkdir -p "$HOME_DIR"
if [ "$OS" = "Darwin" ]; then
  LAUNCHER="$HOME/Desktop/makereel.command"
  printf '#!/bin/bash\ncd "%s"\n"%s" web\n' "$HOME_DIR" "$EXE" > "$LAUNCHER"
  chmod +x "$LAUNCHER"
else
  mkdir -p "$HOME/.local/share/applications"
  LAUNCHER="$HOME/.local/share/applications/makereel.desktop"
  printf '[Desktop Entry]\nType=Application\nName=makereel\nComment=Turn live streams and videos into reels\nExec=sh -c '"'"'cd "%s" && "%s" web'"'"'\nTerminal=true\nCategories=AudioVideo;\n' \
    "$HOME_DIR" "$EXE" > "$LAUNCHER"
fi

printf '\n\033[32mmakereel is installed.\033[0m\n'
echo "Start it with the launcher ($LAUNCHER) or by running: cd ~/makereel && makereel web"
echo "Your reels and settings live in $HOME_DIR"
if [ -z "${MAKEREEL_NO_LAUNCH:-}" ] && [ "$OS" = "Darwin" ]; then open "$LAUNCHER"; fi
