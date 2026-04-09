"""
MCP server for auto-edit-video — exposes video editing tools to Claude Code.

Usage:
    auto-edit mcp-server          # started by Claude Code via mcpServers config
    python -m auto_edit.mcp_server  # direct invocation

Configure in Claude Code settings:
    {
      "mcpServers": {
        "auto-edit-video": {
          "command": "auto-edit",
          "args": ["mcp-server"]
        }
      }
    }
"""
from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from auto_edit import pipeline as pl
from auto_edit.workspace import get_workspace, get_status_table

mcp = FastMCP(
    "auto-edit-video",
    version=importlib.metadata.version("auto-edit-video"),
)


def _repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _ralph() -> Path:
    return _repo_root() / "ralph.sh"


def _run_pipeline(
    video_path: str,
    video_type: str,
    context: str,
    whisper_model: str = "small",
    max_iterations: int = 3,
    resume_from: str | None = None,
    language: str = "pt",
    dry_run: bool = False,
    caption_style: dict | None = None,
) -> str:
    """Internal: run the pipeline and return a status summary."""
    from auto_edit.workspace import init_workspace

    video = Path(video_path).resolve()
    if not video.exists():
        return f"Error: file not found: {video}"

    ws = get_workspace(video)
    ralph = _ralph()

    if not ralph.exists():
        return f"Error: ralph.sh not found at {ralph}"

    if resume_from:
        if not (ws / "pipeline.json").exists():
            return f"Error: no workspace found for {video.name}. Run without resume_from first."
        pl.set_stage(ws, resume_from)
    else:
        ws = init_workspace(
            video_path=video,
            video_type=video_type,
            context=context,
            whisper_model=whisper_model,
            max_iterations=max_iterations,
            caption_style=caption_style or {},
            language=language,
        )

    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(ralph.parent.resolve())
    env["AUTO_EDIT_LANGUAGE"] = language
    env["AUTO_EDIT_LLM"] = env.get("AUTO_EDIT_LLM", "claude")
    if dry_run:
        env["AUTO_EDIT_DRY_RUN"] = "1"

    result = subprocess.run(
        ["bash", str(ralph), str(ws.resolve())],
        cwd=ralph.parent,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pipeline = pl.load(ws)
        stage = pipeline["current_stage"]
        return (
            f"Pipeline failed at stage: {stage}\n"
            f"Workspace: {ws}\n"
            f"stderr: {result.stderr if result.stderr else '(empty)'}\n"
            f"Use resume_from='{stage}' to retry."
        )

    return f"Pipeline completed! Output saved to output/\nWorkspace: {ws}"


@mcp.tool()
def edit_short(
    video_path: str,
    context: str = "",
    whisper_model: str = "small",
    language: str = "pt",
    dry_run: bool = False,
    max_iterations: int = 3,
) -> str:
    """Edit a short-form video (Reels/Shorts/TikTok). Adds captions, removes silences, generates metadata.

    Args:
        video_path: Path to the video file (mp4, mov, mkv, etc.)
        context: Description of the video content (helps the AI planner make better cuts)
        whisper_model: Whisper transcription model - tiny, base, small, medium, large (default: small)
        language: Audio language code - pt, en, es, etc. (default: pt)
        dry_run: If True, only plans cuts without executing FFmpeg (preview mode)
        max_iterations: Max evaluator feedback loops before accepting result (default: 3)
    """
    return _run_pipeline(
        video_path=video_path,
        video_type="short",
        context=context,
        whisper_model=whisper_model,
        language=language,
        dry_run=dry_run,
        max_iterations=max_iterations,
    )


@mcp.tool()
def edit_long(
    video_path: str,
    context: str = "",
    whisper_model: str = "small",
    language: str = "pt",
    dry_run: bool = False,
    max_iterations: int = 3,
) -> str:
    """Edit a long-form video (YouTube). Removes silences, adds overlays, generates metadata. No captions.

    Args:
        video_path: Path to the video file (mp4, mov, mkv, etc.)
        context: Description of the video content (helps the AI planner make better cuts)
        whisper_model: Whisper transcription model - tiny, base, small, medium, large (default: small)
        language: Audio language code - pt, en, es, etc. (default: pt)
        dry_run: If True, only plans cuts without executing FFmpeg (preview mode)
        max_iterations: Max evaluator feedback loops before accepting result (default: 3)
    """
    return _run_pipeline(
        video_path=video_path,
        video_type="long",
        context=context,
        whisper_model=whisper_model,
        language=language,
        dry_run=dry_run,
        max_iterations=max_iterations,
    )


@mcp.tool()
def pipeline_status(video_path: str) -> str:
    """Show the current pipeline status for a video.

    Args:
        video_path: Path to the original video file
    """
    video = Path(video_path).resolve()
    rows = get_status_table(video)
    if not rows:
        return f"No workspace found for: {video.name}"

    lines = [f"Pipeline: {video.name}", ""]
    status_icons = {
        "complete": "✓",
        "pending": "·",
        "running": "⟳",
        "failed": "✗",
        "skip": "─",
    }

    for row in rows[:-1]:
        icon = status_icons.get(row["status"], "?")
        info = row.get("completed_at", "")
        lines.append(f"  {icon} {row['stage']:<12} {row['status']:<10} {info}")

    current = rows[-1]
    lines.append(f"\nCurrent: {current['status']} ({current['completed_at']})")

    return "\n".join(lines)


@mcp.tool()
def resume_pipeline(
    video_path: str,
    from_stage: str,
    whisper_model: str | None = None,
) -> str:
    """Resume a pipeline from a specific stage (useful after fixing errors).

    Args:
        video_path: Path to the original video file
        from_stage: Stage to resume from (extract, plan, review, execute, overlay, caption, evaluate, metadata)
        whisper_model: Override Whisper model for extract stage (tiny, base, small, medium, large)
    """
    video = Path(video_path).resolve()
    ws = get_workspace(video)
    if not (ws / "pipeline.json").exists():
        return f"No workspace found for: {video.name}"

    p = pl.load(ws)

    if whisper_model:
        p["whisper_model"] = whisper_model
        pl.save(ws, p)

    return _run_pipeline(
        video_path=video_path,
        video_type=p["type"],
        context=p["context"],
        whisper_model=p.get("whisper_model", "small"),
        max_iterations=p.get("max_iterations", 3),
        resume_from=from_stage,
        language=p.get("language", "pt"),
    )


@mcp.tool()
def doctor() -> str:
    """Check that all dependencies are installed and available. Returns a diagnostic table."""
    import shutil

    lines = ["auto-edit doctor", ""]
    checks: list[tuple[str, str]] = []

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("python", f"OK ({py_ver})"))

    # ffmpeg / ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        checks.append((tool, f"OK ({path})" if path else "MISSING"))

    # Python packages
    for pkg, import_name in [
        ("openai-whisper", "whisper"),
        ("pysubs2", "pysubs2"),
        ("typer", "typer"),
        ("rich", "rich"),
        ("mcp", "mcp"),
    ]:
        try:
            __import__(import_name)
            checks.append((pkg, "OK"))
        except ImportError:
            checks.append((pkg, "MISSING"))

    # ralph.sh
    ralph = _ralph()
    checks.append(("ralph.sh", "OK" if ralph.exists() else f"MISSING ({ralph})"))

    # agents/ and tools/
    repo = _repo_root()
    for d in ("agents", "tools"):
        p = repo / d
        checks.append((f"{d}/", "OK" if p.is_dir() else "MISSING"))

    # LLM CLI
    for cli_name in ("claude", "cursor"):
        if shutil.which(cli_name):
            checks.append((cli_name, "OK"))
            break
    else:
        checks.append(("claude/cursor", "WARN (needed for agent stages)"))

    for name, status in checks:
        lines.append(f"  {name:<16} {status}")

    lines.append(f"\nRepo root: {repo}")
    return "\n".join(lines)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
