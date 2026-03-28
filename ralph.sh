#!/usr/bin/env bash
# ralph.sh — Pipeline loop engine for auto-edit-video
# Usage: bash ralph.sh <workspace_dir>
#
# AI stages use a headless LLM CLI (stateless). Default: Claude Code (`claude -p`).
# Primary: AUTO_EDIT_LLM=claude|cursor|agent
# Fallback (optional): AUTO_EDIT_LLM_FALLBACK — if primary CLI fails or JSON stays
#   invalid after one retry, tries the fallback backend for that stage.
# Cursor requires `agent` or `cursor` on PATH (https://cursor.com/docs/cli ).
# Optional: AUTO_EDIT_CLAUDE_MODEL, AUTO_EDIT_CURSOR_MODEL (default: auto), AUTO_EDIT_CURSOR_BIN
#   (agent|cursor), AUTO_EDIT_CURSOR_NO_TRUST=1, AUTO_EDIT_CURSOR_NO_ASK=1 (disable --mode ask).
# Cursor runs via Python (stdin prompt) + --output-format json; see auto_edit/runner.py.
# Python tools (extract, execute, caption) run directly as subprocesses.
# All pipeline state lives in workspace/pipeline.json.

set -euo pipefail

WORKSPACE="${1:?Usage: ralph.sh <workspace_dir>}"
PIPELINE="$WORKSPACE/pipeline.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AUTO_EDIT_REPO_ROOT="$SCRIPT_DIR"
AGENTS_DIR="$SCRIPT_DIR/agents"
TOOLS_DIR="$SCRIPT_DIR/tools"

# Use venv python if available, fall back to system python
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi

# Ensure auto_edit module is importable regardless of cwd
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

# ── LLM backends (primary + optional fallback) ──────────────────────────────
_normalize_llm() {
    local x
    x="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "$x" in
        claude) echo "claude" ;;
        agent|cursor) echo "cursor" ;;
        *) return 1 ;;
    esac
}

LLM_BACKEND="$(_normalize_llm "${AUTO_EDIT_LLM:-claude}")" || {
    echo "[ralph] ERROR: AUTO_EDIT_LLM must be claude, cursor, or agent (got: ${AUTO_EDIT_LLM:-})" >&2
    exit 1
}

LLM_BACKEND_FALLBACK=""
if [ -n "${AUTO_EDIT_LLM_FALLBACK:-}" ]; then
    _fb="$(_normalize_llm "${AUTO_EDIT_LLM_FALLBACK}")" || {
        echo "[ralph] ERROR: AUTO_EDIT_LLM_FALLBACK must be claude, cursor, or agent (got: ${AUTO_EDIT_LLM_FALLBACK})" >&2
        exit 1
    }
    if [ "$_fb" != "$LLM_BACKEND" ]; then
        LLM_BACKEND_FALLBACK="$_fb"
    fi
fi

LLM_TIMEOUT="${AUTO_EDIT_LLM_TIMEOUT:-600}"

# ── FFmpeg auto-detection ──────────────────────────────────────────────────
# If ffmpeg isn't in PATH, try to find it via nix (cached, instant if built before)
if ! command -v ffmpeg >/dev/null 2>&1; then
    # 1. nix user profile
    if [ -f "$HOME/.nix-profile/bin/ffmpeg" ]; then
        export PATH="$HOME/.nix-profile/bin:$PATH"
    # 2. nix store (queries the already-built derivation, no rebuild needed)
    elif command -v nix >/dev/null 2>&1; then
        NIX_FFMPEG=$(nix build nixpkgs#ffmpeg-full --no-link --print-out-paths 2>/dev/null | tail -1)
        if [ -n "$NIX_FFMPEG" ] && [ -f "$NIX_FFMPEG/bin/ffmpeg" ]; then
            export PATH="$NIX_FFMPEG/bin:$PATH"
            log "Using ffmpeg from nix store: $NIX_FFMPEG"
        fi
    fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    log "ERROR: ffmpeg not found. Run 'nix develop' or 'brew install ffmpeg'."
    exit 1
fi

# ── Helpers ───────────────────────────────────────────────────────────────────

log() { echo "[ralph] $*"; }

get_stage() {
    $PYTHON -c "import json; print(json.load(open('$PIPELINE'))['current_stage'])"
}

advance_stage() {
    local stage="$1"
    $PYTHON -m auto_edit.pipeline complete "$WORKSPACE" "$stage" > /dev/null
}

fail_stage() {
    local stage="$1"
    $PYTHON -c "
import json
p = json.load(open('$PIPELINE'))
p['stages']['$stage']['status'] = 'failed'
json.dump(p, open('$PIPELINE', 'w'), indent=2, ensure_ascii=False)
"
    log "ERROR: Stage '$stage' failed."
    exit 1
}

run_python_tool() {
    local stage="$1"
    local script="$2"
    log "Running tool: $stage"
    "$PYTHON" -m auto_edit.pipeline running "$WORKSPACE" "$stage" 2>/dev/null || true

    local tool_output exit_code
    local tmp_output
    tmp_output=$(mktemp)

    # Stream output to console in real time AND capture for error persistence
    "$PYTHON" "$script" "$WORKSPACE" 2>&1 | tee "$tmp_output"
    exit_code=${PIPESTATUS[0]}
    tool_output=$(cat "$tmp_output")
    rm -f "$tmp_output"

    if [ "$exit_code" -ne 0 ]; then
        "$PYTHON" -m auto_edit.pipeline failed "$WORKSPACE" "$stage" "$tool_output" 2>/dev/null || true
        fail_stage "$stage" "$tool_output"
    fi

    advance_stage "$stage"
}

# Builds the full prompt in Python (safe JSON embedding) and calls the LLM CLI.
# Validates JSON output, retries once on failure.
run_agent() {
    local stage="$1"
    local output_file="$2"
    local prompt_file="$3"

    log "Running agent: $stage"

    # Mark as running in pipeline.json
    $PYTHON -c "
import json
p = json.load(open('$PIPELINE'))
p['stages']['$stage']['status'] = 'running'
json.dump(p, open('$PIPELINE', 'w'), indent=2, ensure_ascii=False)
"

    local tmp_prompt="$WORKSPACE/.prompt_${stage}.txt"
    local tmp_output="$WORKSPACE/.output_${stage}.txt"

    # Build prompt safely in Python (embeds JSON without shell quoting issues)
    $PYTHON "$SCRIPT_DIR/auto_edit/runner.py" build-prompt \
        "$stage" "$WORKSPACE" "$prompt_file" > "$tmp_prompt"

    _call_llm "$tmp_prompt" "$tmp_output" "$stage" "$output_file"

    rm -f "$tmp_prompt" "$tmp_output"
    advance_stage "$stage"
}

# Cursor Agent: Python wrapper feeds prompt on stdin (see invoke-cursor); avoids argv limits & empty text output.
_run_cursor_print() {
    local prompt_file="$1"
    local output_file="$2"
    $PYTHON "$SCRIPT_DIR/auto_edit/runner.py" invoke-cursor "$prompt_file" "$output_file" "$SCRIPT_DIR"
}

# Runs one LLM backend; writes combined stdout+stderr to output_file.
_run_llm_print_backend() {
    local backend="$1"
    local prompt_file="$2"
    local output_file="$3"
    local exit_code
    case "$backend" in
        claude)
            if [ -n "${AUTO_EDIT_CLAUDE_MODEL:-}" ]; then
                timeout "$LLM_TIMEOUT" claude --model "$AUTO_EDIT_CLAUDE_MODEL" \
                    -p "$(cat "$prompt_file")" >"$output_file" 2>&1
            else
                timeout "$LLM_TIMEOUT" claude -p "$(cat "$prompt_file")" >"$output_file" 2>&1
            fi
            exit_code=$?
            if [ "$exit_code" -eq 124 ]; then
                log "ERROR: LLM 'claude' timed out after ${LLM_TIMEOUT}s"
                return 1
            fi
            return "$exit_code"
            ;;
        cursor)
            timeout "$LLM_TIMEOUT" "$PYTHON" -m auto_edit.runner invoke-cursor \
                "$prompt_file" "$output_file"
            exit_code=$?
            if [ "$exit_code" -eq 124 ]; then
                log "ERROR: LLM 'cursor' timed out after ${LLM_TIMEOUT}s"
                return 1
            fi
            return "$exit_code"
            ;;
        *)
            log "ERROR: Unknown LLM backend '$backend'"
            return 1
            ;;
    esac
}

# Calls LLM CLI(s): up to 2 attempts per backend; then optional fallback backend.
_call_llm() {
    local prompt_file="$1"
    local output_file="$2"
    local stage="$3"
    local final_output="$4"

    local backends="$LLM_BACKEND"
    [ -n "$LLM_BACKEND_FALLBACK" ] && backends="$LLM_BACKEND $LLM_BACKEND_FALLBACK"

    local be idx=0 attempt
    for be in $backends; do
        idx=$((idx + 1))
        if [ "$idx" -gt 1 ]; then
            log "Trying LLM fallback: $be (stage $stage)"
        fi
        attempt=0
        while [ "$attempt" -lt 2 ]; do
            attempt=$((attempt + 1))
            if ! _run_llm_print_backend "$be" "$prompt_file" "$output_file"; then
                log "WARNING: LLM CLI '$be' failed for stage $stage (attempt $attempt)"
                cat "$output_file" >&2
                break
            fi
            if _validate_and_save_json "$output_file" "$final_output"; then
                return 0
            fi
            if [ "$attempt" -lt 2 ]; then
                log "WARNING: Invalid JSON from LLM ($be) for $stage — retrying"
            fi
        done
    done

    log "ERROR: All LLM backends exhausted for stage $stage"
    cat "$output_file" >&2
    fail_stage "$stage"
}

# Strips markdown fences, extracts first JSON object if LLM added preamble (Cursor, etc.).
_validate_and_save_json() {
    local raw_file="$1"
    local out_file="$2"
    "$PYTHON" -m auto_edit.runner validate-json "$raw_file" "$out_file"
}

# ── Main Loop ─────────────────────────────────────────────────────────────────

log "Starting pipeline: $WORKSPACE"
if [ -n "$LLM_BACKEND_FALLBACK" ]; then
    log "LLM backend: $LLM_BACKEND (fallback: $LLM_BACKEND_FALLBACK)"
else
    log "LLM backend: $LLM_BACKEND"
fi
MAX_LOOP=25  # safety ceiling: stages(7) × max_iterations(3) + buffer
LOOP_COUNT=0

while true; do
    LOOP_COUNT=$((LOOP_COUNT + 1))
    if [ "$LOOP_COUNT" -gt "$MAX_LOOP" ]; then
        log "ERROR: Safety limit of $MAX_LOOP loop iterations reached. Aborting."
        exit 1
    fi

    STAGE=$(get_stage)
    log "Stage: $STAGE  (loop $LOOP_COUNT)"

    case "$STAGE" in

        extract)
            run_python_tool "extract" "$TOOLS_DIR/extract.py"
            ;;

        plan)
            run_agent "plan" "$WORKSPACE/cut_plan.json" "$AGENTS_DIR/planner.md"
            ;;

        review)
            run_agent "review" "$WORKSPACE/reviewed_plan.json" "$AGENTS_DIR/reviewer.md"
            ;;

        execute)
            run_python_tool "execute" "$TOOLS_DIR/executor.py"
            ;;

        overlay)
            run_agent "overlay" "$WORKSPACE/overlay_plan.json" "$AGENTS_DIR/overlayer.md"
            $PYTHON "$TOOLS_DIR/overlayer.py" "$WORKSPACE" || { log "ERROR: overlay tool failed"; exit 1; }
            ;;

        caption)
            run_python_tool "caption" "$TOOLS_DIR/captioner.py"
            ;;

        evaluate)
            run_agent "evaluate" "$WORKSPACE/assessment.json" "$AGENTS_DIR/evaluator.md"
            # eval-result handles approved/reject + loop-back logic, prints "next:<stage>"
            NEXT=$($PYTHON -m auto_edit.pipeline eval-result "$WORKSPACE")
            NEXT="${NEXT#next:}"
            log "Evaluator → next: $NEXT"
            ;;

        metadata)
            run_agent "metadata" "$WORKSPACE/metadata.json" "$AGENTS_DIR/metadata.md"
            ;;

        done)
            log "Pipeline complete. Writing output..."
            $PYTHON -m auto_edit.pipeline finalize "$WORKSPACE"
            log "Done."
            break
            ;;

        *)
            log "ERROR: Unknown stage '$STAGE'"
            exit 1
            ;;
    esac
done
