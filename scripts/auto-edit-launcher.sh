#!/usr/bin/env bash
# Launcher script for Nix-installed auto-edit-video.
# On first run, creates a venv and pip-installs Python deps (whisper, torch).
# Nix provides ffmpeg + python in PATH via wrapProgram.
set -euo pipefail

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/auto-edit-video"
VENV_DIR="$CACHE_DIR/venv"
PKG_DIR="$(dirname "$(dirname "$(readlink -f "$0")")")/share/auto-edit-video"

# ── Staleness check ─────────────────────────────────────────────────────────
# Rebuild when: store path changed (nix upgrade), pyproject changed, or venv broken.
CURRENT_PKG="$PKG_DIR"
STORED_PKG="$(cat "$VENV_DIR/.pkg_path" 2>/dev/null || true)"
NEEDS_SETUP=false

if [ ! -d "$VENV_DIR" ] || [ "$CURRENT_PKG" != "$STORED_PKG" ]; then
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

  # Nuke venv if store path changed (python binary points to old nix store)
  # or if python is broken
  if [ -d "$VENV_DIR" ]; then
    if [ "$CURRENT_PKG" != "$STORED_PKG" ] || ! "$VENV_DIR/bin/python" -c "pass" 2>/dev/null; then
      echo "  [0/3] Cleaning stale virtual environment..."
      rm -rf "$VENV_DIR"
    fi
  fi

  if [ ! -d "$VENV_DIR" ]; then
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

  echo "$CURRENT_PKG" > "$VENV_DIR/.pkg_path"
  echo ""
  echo "  Setup complete! Running auto-edit..."
  echo ""
fi

export AUTO_EDIT_REPO_ROOT="${AUTO_EDIT_REPO_ROOT:-$PKG_DIR}"
exec "$VENV_DIR/bin/auto-edit" "$@"
