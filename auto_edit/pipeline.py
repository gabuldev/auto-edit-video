"""
Pipeline state machine — manages pipeline.json per video workspace.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGES = ["extract", "plan", "review", "execute", "overlay", "caption", "evaluate", "metadata", "done"]

# Stages that are skipped per video type
SKIP_FOR_LONG = {"caption"}
SKIP_FOR_SHORT = {"overlay"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(
    workspace: Path,
    video_path: Path,
    video_type: str,
    context: str,
    whisper_model: str = "base",
    max_iterations: int = 3,
    caption_style: dict | None = None,
    language: str = "pt",
) -> dict:
    """Create initial pipeline.json. Returns the pipeline dict."""
    stages = {}
    for stage in STAGES:
        if stage == "done":
            continue
        if stage in SKIP_FOR_LONG and video_type == "long":
            stages[stage] = {"status": "skip"}
        elif stage in SKIP_FOR_SHORT and video_type == "short":
            stages[stage] = {"status": "skip"}
        else:
            stages[stage] = {"status": "pending"}

    pipeline = {
        "video_path": str(video_path.resolve()),
        "video_name": video_path.stem,
        "type": video_type,
        "context": context,
        "whisper_model": whisper_model,
        "language": language,
        "iteration": 1,
        "max_iterations": max_iterations,
        "current_stage": "extract",
        "evaluator_feedback": None,
        "caption_style": caption_style or {},
        "stages": stages,
        "created_at": _now(),
    }

    save(workspace, pipeline)
    return pipeline


def load(workspace: Path) -> dict:
    path = workspace / "pipeline.json"
    if not path.exists():
        raise FileNotFoundError(f"No pipeline.json found in {workspace}")
    return json.loads(path.read_text())


def save(workspace: Path, pipeline: dict) -> None:
    (workspace / "pipeline.json").write_text(
        json.dumps(pipeline, indent=2, ensure_ascii=False)
    )


def set_stage_status(workspace: Path, stage: str, status: str, error: str | None = None) -> dict:
    """Mark a stage as running/complete/failed and update current_stage."""
    pipeline = load(workspace)
    pipeline["stages"][stage]["status"] = status

    if status == "complete":
        pipeline["stages"][stage]["completed_at"] = _now()
        # Advance to next non-skip stage
        current_idx = STAGES.index(stage)
        for next_stage in STAGES[current_idx + 1 :]:
            if next_stage == "done":
                pipeline["current_stage"] = "done"
                break
            if pipeline["stages"].get(next_stage, {}).get("status") != "skip":
                pipeline["current_stage"] = next_stage
                break

    elif status == "failed":
        pipeline["stages"][stage]["failed_at"] = _now()
        if error:
            pipeline["stages"][stage]["error"] = error[:2000]

    save(workspace, pipeline)
    return pipeline


def loop_back(workspace: Path) -> dict:
    """Evaluator rejected: increment iteration and return to plan stage."""
    pipeline = load(workspace)

    assessment_path = workspace / "assessment.json"
    if assessment_path.exists():
        assessment = json.loads(assessment_path.read_text())
        pipeline["evaluator_feedback"] = assessment.get("feedback_for_planner", "")

    pipeline["iteration"] += 1

    # Reset plan, review, execute, overlay, caption, evaluate to pending
    for stage in ["plan", "review", "execute", "overlay", "caption", "evaluate"]:
        if pipeline["stages"].get(stage, {}).get("status") != "skip":
            pipeline["stages"][stage] = {"status": "pending"}

    pipeline["current_stage"] = "plan"
    save(workspace, pipeline)
    return pipeline


def set_stage(workspace: Path, stage: str) -> dict:
    """Force current_stage to a specific stage (used by resume command)."""
    pipeline = load(workspace)
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}. Valid: {STAGES}")

    pipeline["current_stage"] = stage
    # Reset that stage and everything after it
    idx = STAGES.index(stage)
    for s in STAGES[idx:]:
        if s == "done":
            continue
        if pipeline["stages"].get(s, {}).get("status") != "skip":
            pipeline["stages"][s] = {"status": "pending"}

    save(workspace, pipeline)
    return pipeline


def finalize(workspace: Path) -> Path:
    """Copy final video + write metadata txt to output/. Cleans up temp files."""
    import shutil

    pipeline = load(workspace)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # Determine final video file
    if pipeline["type"] == "short" and (workspace / "captioned_video.mp4").exists():
        video_src = workspace / "captioned_video.mp4"
    elif (workspace / "overlaid_video.mp4").exists():
        video_src = workspace / "overlaid_video.mp4"
    elif (workspace / "edited_video.mp4").exists():
        video_src = workspace / "edited_video.mp4"
    else:
        raise FileNotFoundError("No edited video found in workspace")

    video_name = pipeline["video_name"]
    video_dst = output_dir / f"{video_name}_final.mp4"
    shutil.copy2(video_src, video_dst)

    # Copy SRT if available
    srt_src = workspace / "captions.srt"
    if srt_src.exists():
        srt_dst = output_dir / f"{video_name}.srt"
        shutil.copy2(srt_src, srt_dst)
        print(f"[finalize] SRT → {srt_dst}")

    # Write metadata txt
    metadata_path = workspace / "metadata.json"
    txt_dst = output_dir / f"{video_name}.txt"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        _write_metadata_txt(txt_dst, metadata, pipeline["type"])

    # Clean up large intermediate files — keep JSONs for debugging/resume
    _cleanup_workspace(workspace, pipeline["type"])

    return video_dst


def _cleanup_workspace(workspace: Path, video_type: str) -> None:
    """Remove large temp files after successful pipeline completion."""
    # Always remove extracted audio (no longer needed)
    _remove_if_exists(workspace / "audio.wav")

    # For shorts: remove edited_video (captioned_video is the final)
    if video_type == "short":
        _remove_if_exists(workspace / "edited_video.mp4")
        _remove_if_exists(workspace / "overlaid_video.mp4")

    # Remove any leftover claude prompt/output temp files
    for f in workspace.glob(".prompt_*.txt"):
        f.unlink(missing_ok=True)
    for f in workspace.glob(".output_*.txt"):
        f.unlink(missing_ok=True)


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()
        print(f"[finalize] Removed: {path.name}")


def _write_metadata_txt(path: Path, metadata: dict, video_type: str) -> None:
    lines = []
    if video_type in ("short", "reels"):
        lines += [
            "=== SHORT / REELS ===",
            "",
            f"TÍTULO: {metadata.get('short_title', '')}",
            "",
            f"HOOK: {metadata.get('hook', '')}",
            "",
            "HASHTAGS:",
            " ".join(metadata.get("hashtags", [])),
        ]
    else:
        lines += [
            "=== YOUTUBE ===",
            "",
            f"TÍTULO: {metadata.get('youtube_title', '')}",
            "",
            "DESCRIÇÃO:",
            metadata.get("youtube_description", ""),
            "",
            "TAGS:",
            ", ".join(metadata.get("tags", [])),
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ── CLI subcommand mode (called from ralph.sh) ───────────────────────────────
# Usage: python -m auto_edit.pipeline <command> <workspace>

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    ws = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if cmd == "loop-back" and ws:
        p = loop_back(ws)
        print(f"Looped back to plan (iteration {p['iteration']})")

    elif cmd == "set-stage" and ws and len(sys.argv) > 3:
        stage = sys.argv[3]
        set_stage(ws, stage)
        print(f"Stage set to: {stage}")

    elif cmd == "running" and ws and len(sys.argv) > 3:
        stage = sys.argv[3]
        set_stage_status(ws, stage, "running")

    elif cmd == "failed" and ws and len(sys.argv) > 3:
        stage = sys.argv[3]
        error = sys.argv[4] if len(sys.argv) > 4 else None
        set_stage_status(ws, stage, "failed", error=error)

    elif cmd == "complete" and ws and len(sys.argv) > 3:
        stage = sys.argv[3]
        set_stage_status(ws, stage, "complete")
        p = load(ws)
        print(p["current_stage"])

    elif cmd == "get-stage" and ws:
        p = load(ws)
        print(p["current_stage"])

    elif cmd == "finalize" and ws:
        out = finalize(ws)
        print(f"Output: {out}")

    elif cmd == "eval-result" and ws:
        pipeline = load(ws)
        assessment_path = ws / "assessment.json"
        if not assessment_path.exists():
            print("ERROR: assessment.json not found", file=sys.stderr)
            sys.exit(1)
        assessment = json.loads(assessment_path.read_text())
        approved = assessment.get("approved", False)
        iteration = pipeline["iteration"]
        max_iter = pipeline["max_iterations"]

        if approved or iteration >= max_iter:
            set_stage_status(ws, "evaluate", "complete")
            p = load(ws)
            print(f"next:{p['current_stage']}")
        else:
            loop_back(ws)
            print("next:plan")

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
