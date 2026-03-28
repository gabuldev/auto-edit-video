"""
Workspace management — one directory per video under workspace/.
"""
from __future__ import annotations

from pathlib import Path

from auto_edit import pipeline as pl


def get_workspace(video_path: Path) -> Path:
    """Return workspace path for a video (may not exist yet)."""
    root = Path("workspace")
    return root / video_path.stem


def init_workspace(
    video_path: Path,
    video_type: str,
    context: str,
    whisper_model: str = "base",
    max_iterations: int = 3,
    caption_style: dict | None = None,
    language: str = "pt",
) -> Path:
    """Create workspace directory and initial pipeline.json. Returns workspace path."""
    ws = get_workspace(video_path)
    ws.mkdir(parents=True, exist_ok=True)

    pl.init(
        workspace=ws,
        video_path=video_path,
        video_type=video_type,
        context=context,
        whisper_model=whisper_model,
        max_iterations=max_iterations,
        caption_style=caption_style or {},
        language=language,
    )
    return ws


def get_status_table(video_path: Path) -> list[dict]:
    """Return stage statuses for display."""
    ws = get_workspace(video_path)
    if not (ws / "pipeline.json").exists():
        return []

    p = pl.load(ws)
    rows = []
    for stage in pl.STAGES:
        if stage == "done":
            continue
        info = p["stages"].get(stage, {})
        rows.append(
            {
                "stage": stage,
                "status": info.get("status", "pending"),
                "completed_at": info.get("completed_at", ""),
            }
        )
    rows.append(
        {
            "stage": "current",
            "status": p["current_stage"],
            "completed_at": f"iteration {p['iteration']}/{p['max_iterations']}",
        }
    )
    return rows
