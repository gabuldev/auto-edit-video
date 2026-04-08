#!/usr/bin/env bash
# auto-edit-video installer
# Usage: curl -sSL https://raw.githubusercontent.com/gabuldev/auto-edit-video/main/install.sh | bash
set -euo pipefail

INSTALL_DIR="${AUTO_EDIT_HOME:-$HOME/.auto-edit-video}"
BIN_DIR="$HOME/.local/bin"
REPO_URL="https://github.com/gabuldev/auto-edit-video.git"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

# ── Colors ────────────────────────────────────────────────────────────────────
bold()   { printf '\033[1m%s\033[0m' "$*"; }
green()  { printf '\033[0;32m%s\033[0m' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m' "$*"; }
red()    { printf '\033[0;31m%s\033[0m' "$*"; }

info()  { echo "  $(green ">>") $*"; }
warn()  { echo "  $(yellow "!!") $*"; }
fail()  { echo "  $(red "ERROR") $*"; exit 1; }

echo ""
echo "  $(bold "auto-edit-video installer")"
echo "  ────────────────────────"
echo ""

# ── Detect package manager ────────────────────────────────────────────────────
install_pkg() {
    local pkg="$1"
    local pkg_apt="${2:-$1}"
    local pkg_dnf="${3:-$1}"

    if [ "$(uname)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            info "Installing $pkg via Homebrew..."
            brew install "$pkg" 2>/dev/null || true
        else
            fail "$pkg not found. Install Homebrew first: https://brew.sh"
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        info "Installing $pkg_apt via apt..."
        sudo apt-get update -qq && sudo apt-get install -y -qq "$pkg_apt"
    elif command -v dnf >/dev/null 2>&1; then
        info "Installing $pkg_dnf via dnf..."
        sudo dnf install -y "$pkg_dnf"
    elif command -v pacman >/dev/null 2>&1; then
        info "Installing $pkg via pacman..."
        sudo pacman -S --noconfirm "$pkg"
    else
        fail "$pkg not found and no supported package manager detected. Install it manually."
    fi
}

# ── 1. Check/Install git ─────────────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
    info "git not found, installing..."
    install_pkg git
fi
info "git found"

# ── 2. Check/Install Python ──────────────────────────────────────────────────
find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "${major:-0}" -ge $MIN_PYTHON_MAJOR ] && [ "${minor:-0}" -ge $MIN_PYTHON_MINOR ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON=$(find_python || true)
if [ -z "$PYTHON" ]; then
    info "Python >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} not found, installing..."
    install_pkg python3 python3 python3
    # Re-check after install
    PYTHON=$(find_python || true)
    if [ -z "$PYTHON" ]; then
        fail "Python >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} still not found after install. Install manually."
    fi
fi
ver=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python found: $PYTHON ($ver)"

# ── 3. Check/Install ffmpeg ──────────────────────────────────────────────────
if ! command -v ffmpeg >/dev/null 2>&1; then
    info "ffmpeg not found, installing..."
    install_pkg ffmpeg
fi
ffv=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
info "ffmpeg found: $ffv"

# ── 4. Clone or update repo ──────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    git -C "$INSTALL_DIR" pull --ff-only --quiet
else
    if [ -d "$INSTALL_DIR" ]; then
        fail "$INSTALL_DIR exists but is not a git repo. Remove it first: rm -rf $INSTALL_DIR"
    fi
    info "Cloning repository..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi
info "Repository ready at $INSTALL_DIR"

# ── 5. Create venv and install ────────────────────────────────────────────────
VENV="$INSTALL_DIR/.venv"
if [ ! -d "$VENV" ]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV"
fi

info "Installing dependencies (first time includes PyTorch ~2GB)..."
"$VENV/bin/pip" install --upgrade pip --quiet 2>/dev/null
"$VENV/bin/pip" install -e "$INSTALL_DIR" --quiet
# Whisper needs separate install (heavy dep, not always pulled by pip)
if ! "$VENV/bin/python" -c "import whisper" 2>/dev/null; then
    warn "Installing openai-whisper + PyTorch (~2GB download, grab a coffee)..."
    "$VENV/bin/pip" install openai-whisper --quiet
fi
info "Dependencies installed"

# ── 6. Create wrapper script ─────────────────────────────────────────────────
mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/auto-edit" << 'WRAPPER'
#!/usr/bin/env bash
export AUTO_EDIT_REPO_ROOT="$HOME/.auto-edit-video"
exec "$HOME/.auto-edit-video/.venv/bin/auto-edit" "$@"
WRAPPER
chmod +x "$BIN_DIR/auto-edit"
info "Wrapper installed at $BIN_DIR/auto-edit"

# ── 7. Check PATH ────────────────────────────────────────────────────────────
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
    echo ""
    warn "$BIN_DIR is not in your PATH. Add it:"
    echo ""
    SHELL_NAME=$(basename "${SHELL:-/bin/bash}")
    case "$SHELL_NAME" in
        zsh)  echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc" ;;
        bash) echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc" ;;
        fish) echo "    fish_add_path ~/.local/bin" ;;
        *)    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
    echo ""
fi

# ── 8. Check optional deps ───────────────────────────────────────────────────
if command -v claude >/dev/null 2>&1; then
    info "claude CLI found"
else
    warn "claude CLI not found (needed for AI agent stages)"
    warn "Install: $(bold "npm install -g @anthropic-ai/claude-code")"
fi

# ── 9. Done ──────────────────────────────────────────────────────────────────
echo ""
echo "  $(green "$(bold "Installation complete!")")"
echo ""
echo "  Usage:"
echo "    auto-edit --help"
echo "    auto-edit short video.mp4 --context \"describe your video\""
echo "    auto-edit doctor        # check all dependencies"
echo "    auto-edit update        # update to latest version"
echo ""
echo "  Uninstall:"
echo "    bash $INSTALL_DIR/uninstall.sh"
echo ""
