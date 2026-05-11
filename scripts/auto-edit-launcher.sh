#!/usr/bin/env bash
# Launcher script for Nix-installed auto-edit-video.
# On first run, creates a venv and pip-installs Python deps (whisper, torch).
# Nix provides ffmpeg + python in PATH via wrapProgram.
set -euo pipefail

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/auto-edit-video"
VENV_DIR="$CACHE_DIR/venv"
PKG_DIR="$(dirname "$(dirname "$(readlink -f "$0")")")/share/auto-edit-video"

# ── Staleness check: rebuild venv when package changes or venv is broken ─────
CURRENT_HASH="$(md5sum "$PKG_DIR/pyproject.toml" 2>/dev/null | cut -d' ' -f1 || md5 -q "$PKG_DIR/pyproject.toml" 2>/dev/null)"
STORED_HASH="$(cat "$VENV_DIR/.pkg_hash" 2>/dev/null || true)"
NEEDS_SETUP=false

if [ ! -d "$VENV_DIR" ] || [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
  NEEDS_SETUP=true
elif ! "$VENV_DIR/bin/python" -c "import auto_edit" 2>/dev/null; then
  NEEDS_SETUP=true
fi

if [ "$NEEDS_SETUP" = true ]; then
  echo ""
  echo "  auto-edit-video — setup/update"
  echo "  ──────────────────────────────────"
  echo ""

  mkdir -p "$CACHE_DIR"

  # Recreate venv if python binary is missing or broken
  if [ ! -x "$VENV_DIR/bin/python" ] || ! "$VENV_DIR/bin/python" -c "pass" 2>/dev/null; then
    rm -rf "$VENV_DIR"
    echo "  [1/3] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>/dev/null
  else
    echo "  [1/3] Virtual environment OK"
  fi

  echo "  [2/3] Installing/Updating auto-edit-video..."
  "$VENV_DIR/bin/pip" install "$PKG_DIR" --quiet --upgrade

  if ! "$VENV_DIR/bin/python" -c "import whisper" 2>/dev/null; then
    echo "  [3/3] Installing openai-whisper + PyTorch (~2 GB, grab a coffee)..."
    "$VENV_DIR/bin/pip" install openai-whisper --quiet
  else
    echo "  [3/3] openai-whisper already installed"
  fi

  echo "$CURRENT_HASH" > "$VENV_DIR/.pkg_hash"
  echo "$PKG_DIR" > "$VENV_DIR/.pkg_path"
  echo ""
  echo "  Setup complete! Running auto-edit..."
  echo ""
fi

export AUTO_EDIT_REPO_ROOT="${AUTO_EDIT_REPO_ROOT:-$PKG_DIR}"
exec "$VENV_DIR/bin/auto-edit" "$@"
