"""
runner.py -- Prompt builder for ralph.sh agent stages.
Called as: python auto_edit/runner.py build-prompt <stage> <workspace> <prompt_file>
Prints the full prompt to stdout (safe JSON embedding, no shell quoting issues).

Also:
  invoke-cursor -- run Cursor Agent CLI with prompt on stdin (no argv size limit).
  validate-json -- strip markdown fences, extract first JSON object from LLM output.
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
from auto_edit import snap


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

    # Prompt must be stdin only. Do not use `-p -` -- Cursor treats `-` as the literal prompt.
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


def _resolve_prompt_file(stage: str, video_type: str, prompt_file: Path) -> Path:
    """Long-form planning uses a dedicated curation prompt when available.

    ralph.sh always passes agents/planner.md; for `long` we swap in
    agents/planner_long.md (editorial curation + dropped_blocks) if present.
    """
    if stage == "plan" and video_type == "long":
        long_prompt = prompt_file.parent / "planner_long.md"
        if long_prompt.exists():
            return long_prompt
    return prompt_file


def build_prompt(stage: str, workspace: Path, prompt_file: Path) -> str:
    pipeline = pl.load(workspace)

    context = pipeline.get("context", "")
    video_type = pipeline.get("type", "short")

    prompt_file = _resolve_prompt_file(stage, video_type, prompt_file)
    base_prompt = prompt_file.read_text(encoding="utf-8")
    uses_long_planner = prompt_file.name == "planner_long.md"
    iteration = pipeline.get("iteration", 1)
    max_iterations = pipeline.get("max_iterations", 3)
    feedback = pipeline.get("evaluator_feedback")

    sections = [base_prompt]

    # -- Per-stage context injection -------------------------------------------

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
                '\n## Pacing (short-form)\n'
                '- **Tight, dry cuts**: remove dead air **> ~0.75s** unless it is clearly a comedic or emotional beat.\n'
                '- Kill false starts, filler, repeated hooks, and long breaths between clauses.\n'
                '- Prefer jump-cuts / energetic rhythm over leaving “comfort pauses”.'
            )
        elif not uses_long_planner:
            # Generic planner running on a long video — the dedicated
            # planner_long.md already carries its own pacing rules.
            sections.append(
                '\n## Pacing (long-form)\n'
                '- Still aim for a **dynamic** feel: trim pauses **> ~1.0s** that are not deliberate emphasis.\n'
                '- Remove redundancy and sluggish transitions; keep intentional rhetorical pauses only.\n'
                '- Avoid a “podcast slow” cadence unless the content demands it.'
            )
        levels = _audio_levels_brief(transcription)
        if levels:
            sections.append(levels)
        sections += [
            "\n## Transcription Data",
            _compact_json(_slim_for_plan(transcription)),
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
                '\n## Pacing (short-form)\n'
                '- Enforce **snappy** rhythm: approve aggressive silence trims; reject plans that leave obvious dead air.\n'
                '- Cut boundaries only need a **brief** audio buffer (~0.15-0.25s), not long padding.'
            )
        else:
            sections.append(
                '\n## Pacing (long-form)\n'
                '- Prefer **tighter** plans: challenge pauses and weak segments that hurt momentum.\n'
                '- Do not undo good trims just to add “breathing room” unless the sentence would clip.'
            )
            if cut_plan.get("dropped_blocks"):
                sections.append(
                    '\n## Curation Review (long-form)\n'
                    '- The plan dropped whole thematic blocks (see `dropped_blocks`). Judge each one: '
                    'restore it **only** if it carries information, proof, or story found nowhere else in the video.\n'
                    '- A block being slow or low-energy is not grounds for restoring or dropping it — that is a trimming call.\n'
                    '- Carry `dropped_blocks` and `target_rationale` through to your output, '
                    'updated to match your decisions (drop the entry when you restore a block).'
                )
        sections += [
            "\n## Proposed Cut Plan",
            _compact_json(cut_plan),
            "\n## Original Transcription (segments only)",
            _compact_json(_slim_for_review(transcription)),
        ]

    elif stage == "overlay":
        transcription = _read_json(workspace / "transcription.json")
        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            "\n## Transcription Data (word timestamps)",
            _compact_json(_slim_for_overlay(transcription)),
        ]

    elif stage == "evaluate":
        post_cut_transcript = _read_json_optional(workspace / "post_cut_transcription.json")
        is_post_cut = post_cut_transcript is not None
        if not is_post_cut:
            # No post-cut transcript: the only thing left is the raw footage,
            # which does NOT reflect the edit. Say so, loudly -- a silent
            # fallback here means grading a video that was never produced.
            post_cut_transcript = _read_json(workspace / "transcription.json")

        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            f"- Iteration: {iteration} of {max_iterations}",
            f"- Max iterations: {max_iterations}",
        ]
        if is_post_cut:
            sections += [
                "\n## Final Video Transcription (post-edit, segments only)",
                "Timestamps are on the FINAL timeline. A segment marked "
                '`"partial": true` was cut through by the edit — judge whether it still reads whole.',
                _compact_json(_slim_for_review(post_cut_transcript)),
            ]
        else:
            sections += [
                "\n## ⚠ ORIGINAL Transcription — NOT the edited video",
                "The post-cut transcript is missing, so this is the RAW footage: it still contains "
                "everything the edit removed, and its timestamps do not exist in the final video. "
                "Judge only what you can tell from content, never report a timestamp from it, and "
                "say in your feedback that the edited transcript was unavailable.",
                _compact_json(_slim_for_review(post_cut_transcript)),
            ]

    elif stage == "clip":
        post_cut = _read_json(workspace / "post_cut_transcription.json")
        # O teto vem do `--max-dur` da CLI: sem ele no prompt o agente devolve
        # clipes de até 90s que a validação depois descarta em massa.
        raw_cap = os.environ.get("AUTO_EDIT_CLIP_MAX_DUR", "").strip()
        try:
            max_dur = float(raw_cap) if raw_cap else 90.0
        except ValueError:
            max_dur = 90.0
        sections += [
            "\n## Video Information",
            f"- Context: {context or '(no context provided)'}",
            f"- Source duration: {post_cut.get('duration')}s (vídeo já editado)",
            f"- **Duração máxima de um clipe: {max_dur:g} segundos.** "
            "Nunca proponha um candidato mais longo que isso.",
        ]
        long_metadata = _read_json_optional(workspace / "metadata.json")
        if long_metadata:
            sections += [
                "\n## Metadata do Long (título, descrição, tags já gerados)",
                _compact_json(long_metadata),
            ]
        sections += [
            "\n## Post-Cut Transcription",
            _compact_json(_slim_for_plan(post_cut)),
        ]

    elif stage == "metadata":
        # Use post-cut transcription if available, else original
        transcript = (
            _read_json_optional(workspace / "post_cut_transcription.json")
            or _read_json(workspace / "transcription.json")
        )
        language = pipeline.get("language", "pt")
        text = _slim_for_metadata(transcript)
        sections += [
            "\n## Video Information",
            f"- Type: {video_type}",
            f"- Context: {context or '(no context provided)'}",
            f"- Language: {language}",
            "\n## Final Video Transcription (text only)",
            text,
        ]
        brief = _performance_section(video_type)
        if brief:
            sections += [
                "\n## O que retém no teu canal (sinal, não regra)",
                brief,
                "Imita o padrão de TEMA e GANCHO dos de maior retenção e evita o "
                "dos de menor — sem copiar títulos, priorizando o que é fiel a "
                "ESTE vídeo.",
            ]

    sections.append(
        "\nRespond with ONLY valid JSON. No markdown code fences, no explanation."
    )

    prompt = "\n".join(sections)
    _record_token_stats(workspace, stage, prompt)
    return prompt


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _performance_section(video_type: str) -> str:
    """Resumo de retenção do canal (do insights.db) pro tipo do vídeo.

    Degrada pra "" se o insights não estiver disponível — nunca quebra a edição.
    """
    kind = "short" if video_type == "short" else "long"
    try:
        from auto_edit import config as cfg
        from auto_edit.insights import service as isvc
        from auto_edit.insights import store as ist

        db_path = cfg.insights_db_path()
        if not db_path.exists():
            return ""
        conn = ist.connect(db_path)
        return isvc.performance_brief(conn, kind=kind)
    except Exception:
        return ""


# -- Transcription slimming ---------------------------------------------------


def _slim_for_plan(t: dict) -> dict:
    """Everything except the fine energy map, which is for `snap`, not the agent.

    At 0.1s a 20-minute recording is 12k numbers of prompt for a judgement the
    agent makes from the 0.5s map just as well.
    """
    return {k: v for k, v in t.items() if k not in ("energy_db_fine", "fine_resolution_seconds")}


def _audio_levels_brief(t: dict) -> str:
    """Tell the planner where silence actually sits in *this* recording.

    The noise floor is a property of the mic, its gain and the room: a treated
    room tones out near -45dB, a camera mic with the gain up near -30dB. A fixed
    number in the prompt makes the agent call every pause in the second
    recording "speech" and leave the scene changes uncut.
    """
    energy = t.get("energy_db_fine") or t.get("energy_db") or []
    audible = sorted(v for v in energy if v > snap.DIGITAL_SILENCE_DB)
    if not audible:
        return ""
    floor = audible[min(len(audible) - 1, len(audible) // 20)]
    speech = audible[min(len(audible) - 1, len(audible) * 9 // 10)]
    threshold = snap.silence_threshold_db(energy)
    return (
        "\n## Audio Levels (measured on this recording)\n"
        f"- Noise floor: **{floor:.1f}dB** — this is what silence sounds like here.\n"
        f"- Speech level: **{speech:.1f}dB**.\n"
        f"- Silence threshold: **{threshold:.1f}dB** — treat any interval at or below "
        "this as silence, and anything above it as speech. Use these numbers, not "
        "textbook ones: room tone varies by mic and gain."
    )


def _slim_for_review(t: dict) -> dict:
    """Segments with text + timestamps only (no words, energy, confidence)."""
    segments = []
    for s in t.get("segments", []):
        slim = {"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")}
        if s.get("partial"):
            slim["partial"] = True  # the edit cut through this sentence
        segments.append(slim)
    return {"duration": t.get("duration", 0), "segments": segments}


def _slim_for_overlay(t: dict) -> dict:
    """Word-level timestamps only (no confidence, energy, segments)."""
    return {
        "duration": t.get("duration", 0),
        "words": [
            {"word": w.get("word", ""), "start": w.get("start", 0), "end": w.get("end", 0)}
            for w in t.get("words", [])
        ],
    }


def _slim_for_metadata(t: dict) -> str:
    """Plain text transcript -- no timestamps, no JSON."""
    return " ".join(s["text"].strip() for s in t.get("segments", []) if s.get("text"))


# -- Compact JSON serialization ------------------------------------------------


def _truncate_floats(obj, decimals=2):
    """Recursively round floats to save tokens on serialized JSON."""
    if isinstance(obj, float):
        return round(obj, decimals)
    if isinstance(obj, dict):
        return {k: _truncate_floats(v, decimals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate_floats(x, decimals) for x in obj]
    return obj


def _compact_json(obj) -> str:
    """Serialize to compact JSON (no indent, minimal separators)."""
    return json.dumps(_truncate_floats(obj), ensure_ascii=False, separators=(",", ":"))


# -- Token stats ---------------------------------------------------------------


def _record_token_stats(workspace: Path, stage: str, prompt: str) -> None:
    """Append token usage estimate for this stage to .token_stats.jsonl."""
    stats_file = workspace / ".token_stats.jsonl"
    entry = {"stage": stage, "chars": len(prompt), "estimated_tokens": len(prompt) // 4}
    with open(stats_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# -- JSON validation (extracted from ralph.sh) ---------------------------------


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
