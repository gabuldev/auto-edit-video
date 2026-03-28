"""
runner.py — Prompt builder for ralph.sh agent stages.
Called as: python auto_edit/runner.py build-prompt <stage> <workspace> <prompt_file>
Prints the full prompt to stdout (safe JSON embedding, no shell quoting issues).

Also:
  invoke-cursor — run Cursor Agent CLI with prompt on stdin (no argv size limit).
  validate-json — strip markdown fences, extract first JSON object from LLM output.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from auto_edit import pipeline as pl


def invoke_cursor(prompt_path: Path, output_path: Path, repo_root: Path) -> int:
    """Headless Cursor agent; writes CLI stdout+stderr to output_path. Prompt only via stdin + --print."""
    trust: list[str] = [] if os.environ.get("AUTO_EDIT_CURSOR_NO_TRUST") == "1" else ["--trust"]
    # Default --model auto so the CLI/router picks a model (implicit default was hitting Sonnet limits).
    _model = (os.environ.get("AUTO_EDIT_CURSOR_MODEL") or "auto").strip()
    if not _model or _model.lower() in ("none", "default"):
        _model = "auto"
    model_args: list[str] = ["--model", _model]
    # Ask = read-only; better for JSON-only agent stages. Disable with AUTO_EDIT_CURSOR_NO_ASK=1.
    ask: list[str] = (
        []
        if os.environ.get("AUTO_EDIT_CURSOR_NO_ASK") == "1"
        else ["--mode", "ask"]
    )

    # Prompt must be stdin only. Do not use `-p -` — Cursor treats `-` as the literal prompt.
    tail = ["--print", "--workspace", str(repo_root.resolve())]
    override = os.environ.get("AUTO_EDIT_CURSOR_BIN")
    if override == "cursor":
        cmd = ["cursor", "agent", "--output-format", "json", *ask, *trust, *model_args, *tail]
    elif override == "agent":
        cmd = ["agent", "--output-format", "json", *ask, *trust, *model_args, *tail]
    elif shutil.which("agent"):
        cmd = ["agent", "--output-format", "json", *ask, *trust, *model_args, *tail]
    elif shutil.which("cursor"):
        cmd = ["cursor", "agent", "--output-format", "json", *ask, *trust, *model_args, *tail]
    else:
        print("invoke-cursor: neither 'agent' nor 'cursor' on PATH", file=sys.stderr)
        return 127

    data = prompt_path.read_bytes()
    try:
        with open(output_path, "wb") as outf:
            r = subprocess.run(
                cmd,
                input=data,
                cwd=str(repo_root.resolve()),
                stdout=outf,
                stderr=subprocess.STDOUT,
            )
        return r.returncode
    except OSError as e:
        print(f"invoke-cursor: {e}", file=sys.stderr)
        return 1


def build_prompt(stage: str, workspace: Path, prompt_file: Path) -> str:
    base_prompt = prompt_file.read_text(encoding="utf-8")
    pipeline = pl.load(workspace)

    context = pipeline.get("context", "")
    video_type = pipeline.get("type", "short")
    iteration = pipeline.get("iteration", 1)
    max_iterations = pipeline.get("max_iterations", 3)
    feedback = pipeline.get("evaluator_feedback")

    sections = [base_prompt]

    # ── Per-stage context injection ───────────────────────────────────────────

    if stage == "plan":
        transcription = _read_json(workspace / "transcription.json")
        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            f"- Iteration: {iteration} of {max_iterations}",
        ]
        if feedback:
            sections += [
                "\n## Evaluator Feedback from Previous Iteration",
                "(Incorporate these notes into your cut decisions:)",
                feedback,
            ]
        if video_type == "short":
            sections.append(
                "\n## Pacing (short-form)\n"
                "- **Tight, dry cuts**: remove dead air **> ~0.75s** unless it is clearly a comedic or emotional beat.\n"
                "- Kill false starts, filler, repeated hooks, and long breaths between clauses.\n"
                "- Prefer jump-cuts / energetic rhythm over leaving “comfort pauses”."
            )
        else:
            sections.append(
                "\n## Pacing (long-form)\n"
                "- Still aim for a **dynamic** feel: trim pauses **> ~1.0s** that are not deliberate emphasis.\n"
                "- Remove redundancy and sluggish transitions; keep intentional rhetorical pauses only.\n"
                "- Avoid a “podcast slow” cadence unless the content demands it."
            )
        sections += [
            "\n## Transcription Data",
            "```json",
            json.dumps(transcription, indent=2, ensure_ascii=False),
            "```",
        ]

    elif stage == "review":
        transcription = _read_json(workspace / "transcription.json")
        cut_plan = _read_json(workspace / "cut_plan.json")
        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
        ]
        if video_type == "short":
            sections.append(
                "\n## Pacing (short-form)\n"
                "- Enforce **snappy** rhythm: approve aggressive silence trims; reject plans that leave obvious dead air.\n"
                "- Cut boundaries only need a **brief** audio buffer (~0.15–0.25s), not long padding."
            )
        else:
            sections.append(
                "\n## Pacing (long-form)\n"
                "- Prefer **tighter** plans: challenge pauses and weak segments that hurt momentum.\n"
                "- Do not undo good trims just to add “breathing room” unless the sentence would clip."
            )
        sections += [
            "\n## Proposed Cut Plan",
            "```json",
            json.dumps(cut_plan, indent=2, ensure_ascii=False),
            "```",
            "\n## Original Transcription",
            "```json",
            json.dumps(transcription, indent=2, ensure_ascii=False),
            "```",
        ]

    elif stage == "overlay":
        transcription = _read_json(workspace / "transcription.json")
        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            "\n## Transcription Data",
            "```json",
            json.dumps(transcription, indent=2, ensure_ascii=False),
            "```",
        ]

    elif stage == "evaluate":
        # Re-transcribe or use existing post-cut transcript
        post_cut_transcript = _read_json_optional(workspace / "post_cut_transcription.json")
        if post_cut_transcript is None:
            # Fallback: use original transcription with cut plan applied (approximation)
            post_cut_transcript = _read_json(workspace / "transcription.json")

        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            f"- Iteration: {iteration} of {max_iterations}",
            f"- Max iterations: {max_iterations}",
            "\n## Final Video Transcription (post-edit)",
            "```json",
            json.dumps(post_cut_transcript, indent=2, ensure_ascii=False),
            "```",
        ]

    elif stage == "metadata":
        # Use post-cut transcription if available, else original
        transcript = (
            _read_json_optional(workspace / "post_cut_transcription.json")
            or _read_json(workspace / "transcription.json")
        )
        language = pipeline.get("language", "pt")
        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            f"- Language: {language}",
            "\n## Final Video Transcription",
            "```json",
            json.dumps(transcript, indent=2, ensure_ascii=False),
            "```",
        ]

    sections.append(
        "\nRespond with ONLY valid JSON. No markdown code fences, no explanation."
    )

    return "\n".join(sections)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ── JSON validation (extracted from ralph.sh) ────────────────────────────────


def _strip_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    body = "\n".join(lines[1:])
    body = re.sub(r"\n```\s*$", "", body, count=1)
    return body.strip()


def _extract_json(raw: str) -> dict | None:
    raw = _strip_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", raw):
        try:
            obj, _end = dec.raw_decode(raw[m.start():])
            return obj
        except json.JSONDecodeError:
            continue
    return None


def validate_and_save_llm_output(raw_file: Path, out_file: Path) -> bool:
    """Strip markdown fences, extract first JSON object from LLM output.
    Handles Cursor's {"type":"result","result":"..."} wrapper.
    Returns True on success, False on failure."""
    raw = raw_file.read_text(encoding="utf-8")

    # Handle Cursor --output-format json wrapper
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            outer = json.loads(stripped)
            if (
                isinstance(outer, dict)
                and outer.get("type") == "result"
                and isinstance(outer.get("result"), str)
            ):
                if outer.get("is_error") is True:
                    return False
                raw = outer["result"]
        except json.JSONDecodeError:
            pass

    obj = _extract_json(raw)
    if obj is None:
        return False
    out_file.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "build-prompt":
        stage = sys.argv[2]
        workspace = Path(sys.argv[3])
        prompt_file = Path(sys.argv[4])
        print(build_prompt(stage, workspace, prompt_file))
    elif cmd == "invoke-cursor":
        prompt_file = Path(sys.argv[2])
        output_file = Path(sys.argv[3])
        repo_root = Path(sys.argv[4])
        sys.exit(invoke_cursor(prompt_file, output_file, repo_root))
    elif cmd == "validate-json":
        raw_file = Path(sys.argv[2])
        out_file = Path(sys.argv[3])
        if not validate_and_save_llm_output(raw_file, out_file):
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
