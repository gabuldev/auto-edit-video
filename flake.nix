{
  description = "auto-edit-video — AI-powered video editing CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python313;

        # ── Installable package ──────────────────────────────────────────
        # Wraps auto-edit with ffmpeg + python in PATH.
        # Python deps (whisper, torch) are pip-installed into a user-local
        # venv on first run — this avoids Nix-building PyTorch from source.
        auto-edit-pkg = pkgs.stdenv.mkDerivation {
          pname = "auto-edit-video";
          version = "0.1.0";
          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          dontBuild = true;

          installPhase = ''
            runHook preInstall

            # Copy full project (pipeline needs tools/, agents/, ralph.sh, assets/)
            mkdir -p $out/share/auto-edit-video $out/bin
            cp -r auto_edit tools agents assets $out/share/auto-edit-video/
            cp pyproject.toml ralph.sh $out/share/auto-edit-video/
            chmod +x $out/share/auto-edit-video/ralph.sh
            cp scripts/auto-edit-launcher.sh $out/bin/auto-edit
            chmod +x $out/bin/auto-edit

            # Wrap with Nix-provided ffmpeg + python in PATH
            wrapProgram $out/bin/auto-edit \
              --prefix PATH : ${pkgs.lib.makeBinPath [
                python
                pkgs.ffmpeg-full
                pkgs.git
              ]}

            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "AI-powered video editing CLI";
            license = licenses.mit;
            platforms = platforms.unix;
            mainProgram = "auto-edit";
          };
        };
      in
      {
        # nix profile install github:gabuldev/auto-edit-video
        packages.default = auto-edit-pkg;

        # nix run github:gabuldev/auto-edit-video -- short video.mp4 --context "..."
        apps.default = {
          type = "app";
          program = "${auto-edit-pkg}/bin/auto-edit";
        };

        # nix develop (for contributors)
        devShells.default = pkgs.mkShell {
          name = "auto-edit-video";

          packages = [
            python
            pkgs.uv
            pkgs.ffmpeg-full   # ffmpeg + ffprobe + all codecs
            pkgs.nodePackages.npm  # needed only if claude-code not yet installed
          ];

          shellHook = ''
            set -e

            BOLD="\033[1m"
            GREEN="\033[0;32m"
            YELLOW="\033[0;33m"
            RED="\033[0;31m"
            RESET="\033[0m"

            echo ""
            echo -e "''${BOLD}auto-edit-video — AI video editing CLI''${RESET}"
            echo "────────────────────────────────────────"

            # ── 1. Virtual environment ────────────────────────────────────────
            if [ ! -d .venv ]; then
              echo -e "''${YELLOW}[1/4] Creating virtual environment (Python 3.13)...''${RESET}"
              uv venv --python ${python}/bin/python .venv --quiet
            else
              echo -e "''${GREEN}[1/4] Virtual environment already exists''${RESET}"
            fi

            source .venv/bin/activate

            # ── 2. Python package (auto-edit + deps) ──────────────────────────
            if ! python -c "import auto_edit" 2>/dev/null; then
              echo -e "''${YELLOW}[2/4] Installing auto-edit-video and dependencies...''${RESET}"
              uv pip install -e . --quiet
            else
              echo -e "''${GREEN}[2/4] auto-edit-video already installed''${RESET}"
            fi

            # ── 3. Whisper + PyTorch (large download, only once) ──────────────
            if ! python -c "import whisper" 2>/dev/null; then
              echo -e "''${YELLOW}[3/4] Installing openai-whisper + PyTorch...''${RESET}"
              echo    "      (first time only — PyTorch is ~2GB, grab a coffee)"
              uv pip install openai-whisper
              echo -e "''${GREEN}      Whisper installed''${RESET}"
            else
              echo -e "''${GREEN}[3/4] openai-whisper already installed''${RESET}"
            fi

            # ── 4. Validate all dependencies ─────────────────────────────────
            echo -e "''${YELLOW}[4/4] Validating environment...''${RESET}"

            OK=true

            # ffmpeg
            if command -v ffmpeg >/dev/null 2>&1; then
              FFMPEG_VER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
              echo -e "  ''${GREEN}[OK]''${RESET} ffmpeg $FFMPEG_VER"
            else
              echo -e "  ''${RED}[FAIL]''${RESET} ffmpeg not found"
              OK=false
            fi

            # ffprobe
            if command -v ffprobe >/dev/null 2>&1; then
              echo -e "  ''${GREEN}[OK]''${RESET} ffprobe"
            else
              echo -e "  ''${RED}[FAIL]''${RESET} ffprobe not found"
              OK=false
            fi

            # python
            PY_VER=$(python --version 2>&1)
            echo -e "  ''${GREEN}[OK]''${RESET} $PY_VER"

            # whisper
            if python -c "import whisper" 2>/dev/null; then
              echo -e "  ''${GREEN}[OK]''${RESET} openai-whisper"
            else
              echo -e "  ''${RED}[FAIL]''${RESET} openai-whisper not installed"
              OK=false
            fi

            # pysubs2
            if python -c "import pysubs2" 2>/dev/null; then
              echo -e "  ''${GREEN}[OK]''${RESET} pysubs2"
            else
              echo -e "  ''${RED}[FAIL]''${RESET} pysubs2 not installed"
              OK=false
            fi

            # auto-edit CLI
            if command -v auto-edit >/dev/null 2>&1; then
              echo -e "  ''${GREEN}[OK]''${RESET} auto-edit CLI"
            else
              echo -e "  ''${RED}[FAIL]''${RESET} auto-edit command not found"
              OK=false
            fi

            # LLM CLI for agent stages (claude default, or AUTO_EDIT_LLM=cursor)
            if command -v claude >/dev/null 2>&1; then
              CLAUDE_VER=$(claude --version 2>/dev/null || echo "unknown")
              echo -e "  ''${GREEN}[OK]''${RESET} claude $CLAUDE_VER"
            elif command -v agent >/dev/null 2>&1 || command -v cursor >/dev/null 2>&1; then
              echo -e "  ''${GREEN}[OK]''${RESET} Cursor CLI found — use AUTO_EDIT_LLM=cursor for agents"
            else
              echo -e "  ''${YELLOW}[WARN]''${RESET} No LLM CLI for agent stages (claude or Cursor agent)"
              echo    "         claude: npm install -g @anthropic-ai/claude-code"
              echo    "         cursor: curl https://cursor.com/install -fsS | bash"
            fi

            echo ""
            if [ "$OK" = true ]; then
              echo -e "''${GREEN}''${BOLD}Environment ready!''${RESET}"
            else
              echo -e "''${RED}''${BOLD}Some dependencies failed. Check errors above.''${RESET}"
            fi
            echo ""
            echo "  auto-edit --help"
            echo "  auto-edit short video.mp4 --context \"seu video aqui\""
            echo ""

            set +e
          '';
        };
      });
}
