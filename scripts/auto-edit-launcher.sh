#!/usr/bin/env bash
# Launcher script for Nix-installed auto-edit-video.
# On first run, creates a venv and pip-installs Python deps (whisper, torch).
# Nix provides ffmpeg + python in PATH via wrapProgram.
set -euo pipefail

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/auto-edit-video"
VENV_DIR="$CACHE_DIR/venv"
PKG_DIR="$(dirname "$(dirname "$(readlink -f "$0")")")/share/auto-edit-video"

# ── First-run: create venv and install deps ──────────────────────────────────
if [ ! -f "$VENV_DIR/.installed" ]; then
  echo ""
  echo "  auto-edit-video — first-run setup"
  echo "  ──────────────────────────────────"
  echo ""

  mkdir -p "$CACHE_DIR"

  echo "  [1/3] Creating virtual environment..."
  python3 -m venv "$VENV_DIR"

  echo "  [2/3] Installing auto-edit-video..."
  "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>/dev/null
  "$VENV_DIR/bin/pip" install "$PKG_DIR" --quiet

  echo "  [3/3] Installing openai-whisper + PyTorch (~2 GB, grab a coffee)..."
  "$VENV_DIR/bin/pip" install openai-whisper --quiet

  touch "$VENV_DIR/.installed"
  echo ""
  echo "  Setup complete! Running auto-edit..."
  echo ""
fi

exec "$VENV_DIR/bin/auto-edit" "$@"
