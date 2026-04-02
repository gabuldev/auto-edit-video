#!/usr/bin/env bash
# Uninstall auto-edit-video
set -euo pipefail

INSTALL_DIR="${AUTO_EDIT_HOME:-$HOME/.auto-edit-video}"
BIN_LINK="$HOME/.local/bin/auto-edit"

echo ""
echo "  Removing auto-edit-video..."

if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "  Removed $INSTALL_DIR"
fi

if [ -f "$BIN_LINK" ]; then
    rm -f "$BIN_LINK"
    echo "  Removed $BIN_LINK"
fi

echo ""
echo "  auto-edit-video uninstalled."
echo ""
