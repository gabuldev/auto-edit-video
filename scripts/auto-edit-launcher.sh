#!/usr/bin/env bash
# Launcher script for Nix-installed auto-edit-video.
# On first run, creates a venv and pip-installs Python deps (whisper, torch).
# Nix provides ffmpeg + python in PATH via wrapProgram.
set -euo pipefail

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/auto-edit-video"
VENV_DIR="$CACHE_DIR/venv"
PKG_DIR="$(dirname "$(dirname "$(readlink -f "$0")")")/share/auto-edit-video"

# ── Setup/update: create venv and install deps when PKG_DIR changes ──────────
if [ ! -f "$VENV_DIR/.pkg_path" ] || [ "$(cat "$VENV_DIR/.pkg_path" 2>/dev/null)" != "$PKG_DIR" ]; then
  echo ""
  echo "  auto-edit-video — setup/update"
  echo "  ──────────────────────────────────"
  echo ""

  mkdir -p "$CACHE_DIR"

  if [ ! -d "$VENV_DIR" ]; then
    echo "  [1/3] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>/dev/null
  fi

  echo "  [2/3] Installing/Updating auto-edit-video..."
  "$VENV_DIR/bin/pip" install "$PKG_DIR" --quiet --upgrade

  if ! "$VENV_DIR/bin/python" -c "import whisper" 2>/dev/null; then
    echo "  [3/3] Installing openai-whisper + PyTorch (~2 GB, grab a coffee)..."
    "$VENV_DIR/bin/pip" install openai-whisper --quiet
  fi

  echo "$PKG_DIR" > "$VENV_DIR/.pkg_path"
  echo ""
  echo "  Setup complete! Running auto-edit..."
  echo ""
fi

export AUTO_EDIT_REPO_ROOT="$PKG_DIR"
exec "$VENV_DIR/bin/auto-edit" "$@"
