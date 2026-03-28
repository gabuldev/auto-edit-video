.PHONY: setup shell test clean clean-workspace help

# ── Setup ──────────────────────────────────────────────────────────────────

## setup: Setup full environment via Nix (installs ffmpeg, python, whisper, validates)
setup:
	@echo "Entering Nix dev shell — this will install everything on first run..."
	nix develop

## shell: Enter the development shell (alias for setup)
shell:
	nix develop

# ── Testing ────────────────────────────────────────────────────────────────

## test: Test CLI entry point (run inside nix shell)
test:
	auto-edit --help

# ── Cleanup ────────────────────────────────────────────────────────────────

## clean: Remove virtual environment and build artifacts
clean:
	rm -rf .venv dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."

## clean-workspace: Remove all per-video workspaces (keeps output/)
clean-workspace:
	rm -rf workspace/*/
	@echo "Workspaces cleared."

# ── Help ──────────────────────────────────────────────────────────────────

## help: Show available commands
help:
	@echo ""
	@echo "auto-edit-video — available make targets:"
	@echo ""
	@grep -E '^## ' Makefile | sed 's/## /  /' | column -t -s ':'
	@echo ""
	@echo "  LLM: --cli / --cli-fallback or AUTO_EDIT_LLM + AUTO_EDIT_LLM_FALLBACK — see ralph.sh."
	@echo "  Cuts: AUTO_EDIT_END_PADDING (default 0.2) — tail padding per kept segment in executor."
	@echo "  Test overlays only: auto-edit apply-overlays path/to/original.mp4"
	@echo ""
