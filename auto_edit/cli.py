"""
auto-edit CLI — entry point for all commands.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from auto_edit import pipeline as pl
from auto_edit import plan as plan_mod
from auto_edit._version import __version__
from auto_edit.ideas import ideas_app
from auto_edit.plan import plan_app
from auto_edit.workspace import get_workspace, init_workspace, get_status_table


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"auto-edit {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="auto-edit",
    help="AI-powered video editing using Claude Code agents.",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(plan_app, name="plan")
app.add_typer(ideas_app, name="ideas")


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """AI-powered video editing using Claude Code agents."""


console = Console()

def _repo_root() -> Path:
    """Resolve the repo root. AUTO_EDIT_REPO_ROOT env var takes priority (set by install wrapper)."""
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


REPO_ROOT = _repo_root()
RALPH_SCRIPT = REPO_ROOT / "ralph.sh"

_CODEC_PREFERENCE: list[tuple[str, list[str]]] = [
    ("h264_videotoolbox", ["-q:v", "50"]),       # macOS HW
    ("h264_nvenc",        ["-cq", "23"]),         # NVIDIA HW
    ("h264_vaapi",        ["-qp", "23"]),         # Linux VA-API
    ("libx264",           ["-crf", "23", "-preset", "fast"]),
]


def _get_merge_codec() -> tuple[str, list[str]]:
    """Return (codec_name, extra_flags) for the best available H.264 encoder."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True,
    )
    for codec, flags in _CODEC_PREFERENCE:
        if codec in result.stdout:
            return codec, flags
    return "libx264", ["-crf", "23", "-preset", "fast"]
VALID_MODELS = ["tiny", "base", "small", "medium", "large"]
CLI_EPILOG = "claude, cursor, or agent (agent = Cursor)"


def _norm_cli_token(raw: str) -> str:
    x = raw.strip().lower()
    if x == "agent":
        return "cursor"
    if x not in ("claude", "cursor"):
        raise ValueError(raw)
    return x


def _resolve_llm(
    cli: Optional[str],
    cli_fallback: Optional[str],
) -> tuple[str, Optional[str]]:
    primary_raw = (cli if cli is not None else os.environ.get("AUTO_EDIT_LLM", "claude")).strip()
    if not primary_raw:
        primary_raw = "claude"
    try:
        primary = _norm_cli_token(primary_raw)
    except ValueError:
        console.print(
            f"[red]Invalid primary LLM:[/red] {primary_raw!r} — use {CLI_EPILOG}"
        )
        raise typer.Exit(1)

    fb_src = (
        cli_fallback
        if cli_fallback is not None
        else os.environ.get("AUTO_EDIT_LLM_FALLBACK")
    )
    if not fb_src or not str(fb_src).strip():
        return primary, None
    try:
        fb = _norm_cli_token(str(fb_src).strip())
    except ValueError:
        console.print(f"[red]Invalid fallback LLM:[/red] {fb_src!r} — use {CLI_EPILOG}")
        raise typer.Exit(1)
    if fb == primary:
        console.print(
            "[yellow]Note:[/yellow] primary and fallback are the same; fallback disabled."
        )
        return primary, None
    return primary, fb


def _resolve_plan(plan_id: Optional[str], no_prompt: bool, resume_from: Optional[str]) -> Optional[str]:
    """Convert raw --plan-id flag to canonical id, or interactively pick one."""
    if resume_from:
        # When resuming, plan_id is already in pipeline.json — don't override.
        return None
    if plan_id:
        return plan_mod.resolve_plan_id_arg(plan_id)
    if no_prompt:
        return None
    # No flag, no opt-out — offer interactive picker if there are pending items.
    pending = plan_mod.pending_items()
    if not pending:
        return None
    return plan_mod.prompt_for_plan_id()


def _run_pipeline(
    video: Path,
    video_type: str,
    context: str,
    whisper_model: str,
    max_iterations: int,
    resume_from: Optional[str],
    caption_style: Optional[dict] = None,
    cli: Optional[str] = None,
    cli_fallback: Optional[str] = None,
    dry_run: bool = False,
    language: str = "pt",
    plan_id: Optional[str] = None,
) -> None:
    if not video.exists():
        console.print(f"[red]Error:[/red] File not found: {video}")
        raise typer.Exit(1)

    ws = get_workspace(video, plan_id=plan_id)

    if resume_from:
        if not (ws / "pipeline.json").exists():
            console.print(f"[red]Error:[/red] No workspace found for {video.name}. Run without --from first.")
            raise typer.Exit(1)
        console.print(f"[cyan]Resuming from stage:[/cyan] {resume_from}")
        pl.set_stage(ws, resume_from)
    else:
        console.print(f"[cyan]Initializing workspace for:[/cyan] {video.name}")
        ws = init_workspace(
            video_path=video,
            video_type=video_type,
            context=context,
            whisper_model=whisper_model,
            max_iterations=max_iterations,
            caption_style=caption_style or {},
            language=language,
            plan_id=plan_id,
        )

    console.print(f"[cyan]Type:[/cyan] {video_type}")
    console.print(f"[cyan]Context:[/cyan] {context or '(none)'}")
    console.print(f"[cyan]Whisper model:[/cyan] {whisper_model}")
    console.print(f"[cyan]Language:[/cyan] {language}")
    console.print(f"[cyan]Workspace:[/cyan] {ws}")
    if plan_id:
        console.print(f"[cyan]Plan slot:[/cyan] {plan_id}")
    primary, fb = _resolve_llm(cli, cli_fallback)
    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(RALPH_SCRIPT.parent.resolve())
    env["PYTHON"] = sys.executable
    env["AUTO_EDIT_LANGUAGE"] = language
    env["AUTO_EDIT_LLM"] = primary
    if fb:
        env["AUTO_EDIT_LLM_FALLBACK"] = fb
    else:
        env.pop("AUTO_EDIT_LLM_FALLBACK", None)
    if dry_run:
        env["AUTO_EDIT_DRY_RUN"] = "1"
    console.print(
        f"[cyan]LLM:[/cyan] {primary}"
        + (f" [dim](fallback: {fb})[/dim]" if fb else "")
    )
    console.print()

    if not RALPH_SCRIPT.exists():
        console.print(f"[red]Error:[/red] ralph.sh not found at {RALPH_SCRIPT}")
        console.print("[dim]Set AUTO_EDIT_REPO_ROOT to the project root, or check your installation.[/dim]")
        raise typer.Exit(1)

    console.print("[bold green]Starting pipeline...[/bold green]")
    result = subprocess.run(
        ["bash", str(RALPH_SCRIPT), str(ws.resolve())],
        cwd=RALPH_SCRIPT.parent,
        env=env,
    )

    if result.returncode != 0:
        current = pl.load(ws)
        stage = current["current_stage"]
        console.print(f"\n[red]Pipeline failed at stage:[/red] {stage}")
        console.print(
            f"Run [bold]auto-edit resume {video} --from {stage}[/bold] to retry from that stage."
        )
        raise typer.Exit(result.returncode)

    console.print("\n[bold green]Done![/bold green] Output saved to [bold]output/[/bold]")


@app.command()
def short(
    video: Path = typer.Argument(..., help="Path to the video file"),
    context: str = typer.Option("", "--context", "-c", help="What the video is about"),
    whisper_model: str = typer.Option("small", "--whisper-model", "-m", help=f"Whisper model: {', '.join(VALID_MODELS)}"),
    max_iterations: int = typer.Option(3, "--max-iter", help="Max evaluator feedback loops"),
    resume_from: Optional[str] = typer.Option(None, "--from", help="Resume from a specific stage"),
    cli: Optional[str] = typer.Option(
        None,
        "--cli",
        help=f"Primary agent CLI ({CLI_EPILOG}). Default: $AUTO_EDIT_LLM or claude.",
    ),
    cli_fallback: Optional[str] = typer.Option(
        None,
        "--cli-fallback",
        help="If primary fails or returns invalid JSON after retry, try this CLI. Default: $AUTO_EDIT_LLM_FALLBACK.",
    ),
    highlight_border: float = typer.Option(2.5, "--highlight-border", help="Highlight word border thickness (default 2.5)"),
    highlight_color: str = typer.Option("&H0045FF&", "--highlight-color", help="Highlight color in ASS format &HBBGGRR& (default orange)"),
    font_size: int = typer.Option(14, "--font-size", help="Caption font size (default 14)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run only through review stage — shows cut plan without executing FFmpeg."),
    language: str = typer.Option("pt", "--language", "-l", help="Audio language (pt, en, es, etc.)"),
    plan_id: Optional[str] = typer.Option(None, "--plan-id", help="Link this video to a plan slot (e.g. 'S2' or '2026-W19/S2'). Use 'none' to skip prompt."),
    no_plan_prompt: bool = typer.Option(False, "--no-plan-prompt", help="Don't prompt for a plan slot when --plan-id is omitted."),
) -> None:
    """Edit a short-form video (adds captions, generates Reels/Shorts metadata)."""
    if whisper_model not in VALID_MODELS:
        console.print(f"[red]Invalid model.[/red] Choose from: {', '.join(VALID_MODELS)}")
        raise typer.Exit(1)
    caption_style = {
        "border_highlight": highlight_border,
        "color_highlight": highlight_color,
        "font_size": font_size,
    }
    pid = _resolve_plan(plan_id, no_plan_prompt, resume_from)
    _run_pipeline(
        video,
        "short",
        context,
        whisper_model,
        max_iterations,
        resume_from,
        caption_style,
        cli=cli,
        cli_fallback=cli_fallback,
        dry_run=dry_run,
        language=language,
        plan_id=pid,
    )


@app.command()
def long(
    video: Path = typer.Argument(..., help="Path to the video file"),
    context: str = typer.Option("", "--context", "-c", help="What the video is about"),
    whisper_model: str = typer.Option("small", "--whisper-model", "-m", help=f"Whisper model: {', '.join(VALID_MODELS)}"),
    max_iterations: int = typer.Option(3, "--max-iter", help="Max evaluator feedback loops"),
    resume_from: Optional[str] = typer.Option(None, "--from", help="Resume from a specific stage"),
    cli: Optional[str] = typer.Option(
        None,
        "--cli",
        help=f"Primary agent CLI ({CLI_EPILOG}). Default: $AUTO_EDIT_LLM or claude.",
    ),
    cli_fallback: Optional[str] = typer.Option(
        None,
        "--cli-fallback",
        help="If primary fails or returns invalid JSON after retry, try this CLI. Default: $AUTO_EDIT_LLM_FALLBACK.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run only through review stage — shows cut plan without executing FFmpeg."),
    language: str = typer.Option("pt", "--language", "-l", help="Audio language (pt, en, es, etc.)"),
    plan_id: Optional[str] = typer.Option(None, "--plan-id", help="Link this video to a plan slot (e.g. 'L1' or '2026-W19/L1'). Use 'none' to skip prompt."),
    no_plan_prompt: bool = typer.Option(False, "--no-plan-prompt", help="Don't prompt for a plan slot when --plan-id is omitted."),
) -> None:
    """Edit a long-form video (no captions, generates YouTube metadata)."""
    if whisper_model not in VALID_MODELS:
        console.print(f"[red]Invalid model.[/red] Choose from: {', '.join(VALID_MODELS)}")
        raise typer.Exit(1)
    pid = _resolve_plan(plan_id, no_plan_prompt, resume_from)
    _run_pipeline(
        video,
        "long",
        context,
        whisper_model,
        max_iterations,
        resume_from,
        cli=cli,
        cli_fallback=cli_fallback,
        dry_run=dry_run,
        language=language,
        plan_id=pid,
    )


@app.command()
def batch(
    folder: Path = typer.Argument(..., help="Folder containing video files"),
    video_type: str = typer.Option(..., "--type", "-t", help="short or long"),
    context: str = typer.Option("", "--context", "-c", help="What the videos are about"),
    whisper_model: str = typer.Option("small", "--whisper-model", "-m"),
    max_iterations: int = typer.Option(3, "--max-iter"),
    cli: Optional[str] = typer.Option(
        None,
        "--cli",
        help=f"Primary agent CLI ({CLI_EPILOG}). Default: $AUTO_EDIT_LLM or claude.",
    ),
    cli_fallback: Optional[str] = typer.Option(
        None,
        "--cli-fallback",
        help="Fallback CLI if primary fails. Default: $AUTO_EDIT_LLM_FALLBACK.",
    ),
    language: str = typer.Option("pt", "--language", "-l", help="Audio language (pt, en, es, etc.)"),
) -> None:
    """Process all videos in a folder sequentially."""
    if video_type not in ("short", "long"):
        console.print("[red]--type must be 'short' or 'long'[/red]")
        raise typer.Exit(1)

    extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    videos = sorted(p for p in folder.iterdir() if p.suffix.lower() in extensions)

    if not videos:
        console.print(f"[yellow]No video files found in {folder}[/yellow]")
        raise typer.Exit(0)

    console.print(f"Found [bold]{len(videos)}[/bold] video(s) to process.\n")

    failed = []
    for i, video in enumerate(videos, 1):
        console.rule(f"[{i}/{len(videos)}] {video.name}")
        try:
            _run_pipeline(
                video,
                video_type,
                context,
                whisper_model,
                max_iterations,
                None,
                cli=cli,
                cli_fallback=cli_fallback,
                language=language,
            )
        except SystemExit:
            failed.append(video.name)
            console.print(f"[red]Failed:[/red] {video.name} — continuing with next.\n")

    if failed:
        console.print(f"\n[red]Failed videos:[/red] {', '.join(failed)}")
    else:
        console.print("\n[bold green]All videos processed successfully.[/bold green]")


@app.command()
def merge(
    folder: Path = typer.Argument(..., help="Folder containing video files to merge and edit"),
    output_name: str = typer.Option(..., "--name", "-n", help="Output name (without extension)"),
    video_type: str = typer.Option(..., "--type", "-t", help="short or long"),
    context: str = typer.Option("", "--context", "-c", help="What the videos are about"),
    whisper_model: str = typer.Option("small", "--whisper-model", "-m"),
    max_iterations: int = typer.Option(3, "--max-iter"),
    cli: Optional[str] = typer.Option(
        None,
        "--cli",
        help=f"Primary agent CLI ({CLI_EPILOG}). Default: $AUTO_EDIT_LLM or claude.",
    ),
    cli_fallback: Optional[str] = typer.Option(
        None,
        "--cli-fallback",
        help="Fallback CLI if primary fails. Default: $AUTO_EDIT_LLM_FALLBACK.",
    ),
    highlight_border: float = typer.Option(2.5, "--highlight-border"),
    highlight_color: str = typer.Option("&H0045FF&", "--highlight-color"),
    font_size: int = typer.Option(14, "--font-size"),
    language: str = typer.Option("pt", "--language", "-l", help="Audio language (pt, en, es, etc.)"),
    plan_id: Optional[str] = typer.Option(None, "--plan-id", help="Link merged video to a plan slot (e.g. 'S2' or '2026-W19/S2')."),
    no_plan_prompt: bool = typer.Option(False, "--no-plan-prompt", help="Don't prompt for a plan slot when --plan-id is omitted."),
) -> None:
    """Concatenate all videos in a folder into one, then run the pipeline."""
    if video_type not in ("short", "long"):
        console.print("[red]--type must be 'short' or 'long'[/red]")
        raise typer.Exit(1)

    extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    videos = sorted(p for p in folder.iterdir() if p.suffix.lower() in extensions)

    if not videos:
        console.print(f"[yellow]No video files found in {folder}[/yellow]")
        raise typer.Exit(0)

    console.print(f"Found [bold]{len(videos)}[/bold] video(s) to merge:")
    for v in videos:
        console.print(f"  • {v.name}")

    merged_path = folder / f"{output_name}.mp4"
    console.print(f"\n[cyan]Merging into:[/cyan] {merged_path}")

    # Probe each video's resolution to decide merge strategy
    resolutions: list[tuple[int, int]] = []
    for v in videos:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(v)],
            capture_output=True, text=True,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            console.print(f"[red]Error probing {v.name}:[/red] {probe.stderr}")
            raise typer.Exit(1)
        w, h = (int(x) for x in probe.stdout.strip().split("x"))
        resolutions.append((w, h))
        aspect = f"{w/h:.2f}"
        console.print(f"  {v.name}: {w}x{h} (aspect {aspect})")

    needs_normalize = len(set(resolutions)) > 1
    if needs_normalize:
        console.print("\n[yellow]Mixed resolutions detected — normalizing with crop+scale[/yellow]")

    if not needs_normalize:
        # Fast path: all same resolution, use concat demuxer (stream copy)
        concat_list = folder / ".concat_list.txt"
        concat_list.write_text(
            "\n".join(f"file '{v.resolve()}'" for v in videos) + "\n"
        )
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(merged_path)],
            capture_output=True, text=True,
        )
        concat_list.unlink(missing_ok=True)
    else:
        # Slow path: mixed resolutions — use concat filter with crop+scale
        # Target: largest 16:9 resolution present, or 1920x1080 default
        target_w, target_h = 1920, 1080
        for w, h in resolutions:
            ar = w / h
            if 1.7 < ar < 1.8 and w > target_w:  # ~16:9
                target_w, target_h = w, h
        console.print(f"  Target resolution: [bold]{target_w}x{target_h}[/bold]")

        inputs = []
        filters = []
        for i, v in enumerate(videos):
            inputs.extend(["-i", str(v)])
            w, h = resolutions[i]
            ar = w / h
            target_ar = target_w / target_h
            if abs(ar - target_ar) < 0.05:
                # Same aspect ratio — just scale
                filters.append(
                    f"[{i}:v]scale={target_w}:{target_h},setsar=1[v{i}]"
                )
            else:
                # Different aspect — crop to target AR then scale
                if ar < target_ar:
                    # Taller than target (e.g. vertical) — crop top/bottom
                    crop_h = int(w / target_ar) // 2 * 2
                    filters.append(
                        f"[{i}:v]crop={w}:{crop_h}:{0}:(ih-{crop_h})/2,"
                        f"scale={target_w}:{target_h},setsar=1[v{i}]"
                    )
                else:
                    # Wider than target — crop left/right
                    crop_w = int(h * target_ar) // 2 * 2
                    filters.append(
                        f"[{i}:v]crop={crop_w}:{h}:(iw-{crop_w})/2:{0},"
                        f"scale={target_w}:{target_h},setsar=1[v{i}]"
                    )
            filters.append(f"[{i}:a]aresample=44100[a{i}]")

        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(videos)))
        filters.append(f"{concat_inputs}concat=n={len(videos)}:v=1:a=1[outv][outa]")
        filter_complex = ";\n".join(filters)

        # Auto-select best available encoder (same logic as executor.py)
        codec, codec_flags = _get_merge_codec()
        cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex,
               "-map", "[outv]", "-map", "[outa]",
               "-c:v", codec, *codec_flags,
               "-c:a", "aac", "-b:a", "192k",
               str(merged_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        console.print(f"[red]FFmpeg merge failed:[/red]\n{result.stderr}")
        raise typer.Exit(1)

    console.print(f"[green]Merged successfully.[/green] ({merged_path.stat().st_size // 1_000_000} MB)\n")

    caption_style = {
        "border_highlight": highlight_border,
        "color_highlight": highlight_color,
        "font_size": font_size,
    } if video_type == "short" else None

    pid = _resolve_plan(plan_id, no_plan_prompt, None)
    _run_pipeline(
        merged_path,
        video_type,
        context,
        whisper_model,
        max_iterations,
        None,
        caption_style,
        cli=cli,
        cli_fallback=cli_fallback,
        language=language,
        plan_id=pid,
    )


@app.command()
def status(
    video: Path = typer.Argument(..., help="Path to the original video file"),
) -> None:
    """Show pipeline status for a video."""
    rows = get_status_table(video)
    if not rows:
        console.print(f"[yellow]No workspace found for:[/yellow] {video.name}")
        raise typer.Exit(0)

    table = Table(title=f"Pipeline: {video.name}", show_lines=True)
    table.add_column("Stage", style="bold")
    table.add_column("Status")
    table.add_column("Info")

    status_style = {
        "complete": "[green]✓ complete[/green]",
        "pending": "[dim]pending[/dim]",
        "running": "[yellow]⟳ running[/yellow]",
        "failed": "[red]✗ failed[/red]",
        "skip": "[dim]─ skip[/dim]",
    }

    for row in rows[:-1]:  # all except the "current" summary row
        style = status_style.get(row["status"], row["status"])
        table.add_row(row["stage"], style, row.get("completed_at", ""))

    console.print(table)

    # Print current stage summary
    current_row = rows[-1]
    console.print(
        f"\nCurrent stage: [bold cyan]{current_row['status']}[/bold cyan]  "
        f"({current_row['completed_at']})"
    )


@app.command("apply-overlays")
def apply_overlays(
    video: Path = typer.Argument(..., help="Original video file (same stem as workspace/<name>/)"),
) -> None:
    """Run only tools/overlayer.py: uses existing overlay_plan.json + edited_video.mp4 (no LLM)."""
    ws = get_workspace(video)
    if not ws.is_dir():
        console.print(f"[red]Workspace not found:[/red] {ws}")
        raise typer.Exit(1)

    edited = ws / "edited_video.mp4"
    plan = ws / "overlay_plan.json"
    reviewed = ws / "reviewed_plan.json"
    pipeline = ws / "pipeline.json"

    if not edited.exists():
        console.print(f"[red]Missing edited video:[/red] {edited}")
        raise typer.Exit(1)
    if not plan.exists():
        console.print(f"[red]Missing overlay plan:[/red] {plan}")
        raise typer.Exit(1)
    if not reviewed.exists():
        console.print(f"[red]Missing (needed for time remap):[/red] {reviewed}")
        raise typer.Exit(1)
    if not pipeline.exists():
        console.print(f"[red]Missing:[/red] {pipeline}")
        raise typer.Exit(1)

    overlayer = RALPH_SCRIPT.parent / "tools" / "overlayer.py"
    if not overlayer.exists():
        console.print(f"[red]overlayer.py not found:[/red] {overlayer}")
        raise typer.Exit(1)

    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(RALPH_SCRIPT.parent.resolve())

    console.print(f"[cyan]Workspace:[/cyan] {ws.resolve()}")
    console.print("[dim]Applying overlays only (FFmpeg + assets)…[/dim]\n")

    result = subprocess.run(
        [sys.executable, str(overlayer), str(ws.resolve())],
        cwd=str(RALPH_SCRIPT.parent),
        env=env,
    )
    if result.returncode != 0:
        raise typer.Exit(result.returncode)

    out = ws / "overlaid_video.mp4"
    if out.exists():
        console.print(f"\n[green]Written:[/green] {out.resolve()}")
    else:
        console.print(
            '\n[yellow]No overlaid_video.mp4[/yellow] (empty plan or all overlays skipped).'
        )


@app.command("smoke-overlay")
def smoke_overlay(
    out_dir: Path = typer.Option(
        Path("output/overlay_smoke"),
        "--out",
        "-o",
        help="Directory for synthetic clips + smoke_overlaid.mp4",
    ),
) -> None:
    """Generate tiny test clips and run the same chroma+overlay FFmpeg path as the overlayer (no workspace)."""
    script = RALPH_SCRIPT.parent / "tools" / "overlay_smoke_test.py"
    if not script.is_file():
        console.print(f"[red]Not found:[/red] {script}")
        raise typer.Exit(1)
    r = subprocess.run(
        [sys.executable, str(script), "-o", str(out_dir.resolve())],
        cwd=str(RALPH_SCRIPT.parent),
    )
    raise typer.Exit(r.returncode)


@app.command("sync-overlays")
def sync_overlays() -> None:
    """Copy *.mp4 from <repo>/overlays/ into assets/overlays/ (canonical location for tools and git)."""
    from auto_edit.overlay_assets import sync_overlay_assets

    repo = RALPH_SCRIPT.parent.resolve()
    src = repo / "overlays"
    if not src.is_dir():
        console.print(
            f"[yellow]Skip:[/yellow] no folder {src} — put ctas.mp4 etc. in "
            f"[cyan]assets/overlays/[/cyan] or create [cyan]overlays/[/cyan] and run again."
        )
        raise typer.Exit(0)

    copied = sync_overlay_assets(repo)
    if not copied:
        console.print(f"[dim]No .mp4 files in {src}[/dim]")
        raise typer.Exit(0)

    for p in copied:
        console.print(f"[green]Copied[/green] {p}")
    console.print(
        f"\n[dim]Canonical dir:[/dim] {repo / 'assets' / 'overlays'} "
        "(overlayer searches assets/overlays first, then overlays/)"
    )


@app.command()
def resume(
    video: Path = typer.Argument(..., help="Path to the original video file"),
    from_stage: str = typer.Option(..., "--from", help=f"Stage to resume from: {', '.join(pl.STAGES[:-1])}"),
    whisper_model: Optional[str] = typer.Option(None, "--whisper-model", "-m", help=f"Override Whisper model: {', '.join(VALID_MODELS)}"),
    cli: Optional[str] = typer.Option(
        None,
        "--cli",
        help=f"Primary agent CLI ({CLI_EPILOG}). Default: $AUTO_EDIT_LLM or claude.",
    ),
    cli_fallback: Optional[str] = typer.Option(
        None,
        "--cli-fallback",
        help="Fallback CLI if primary fails. Default: $AUTO_EDIT_LLM_FALLBACK.",
    ),
) -> None:
    """Resume a pipeline from a specific stage."""
    ws = get_workspace(video)
    if not (ws / "pipeline.json").exists():
        console.print(f"[red]No workspace found for:[/red] {video.name}")
        raise typer.Exit(1)

    p = pl.load(ws)

    # Update whisper model if explicitly set or if resuming extract with outdated default
    if whisper_model:
        if whisper_model not in VALID_MODELS:
            console.print(f"[red]Invalid whisper model:[/red] {whisper_model}")
            raise typer.Exit(1)
        if p.get("whisper_model") != whisper_model:
            console.print(f"[cyan]Updating whisper_model:[/cyan] {p.get('whisper_model')} → {whisper_model}")
            p["whisper_model"] = whisper_model
            pl.save(ws, p)

    _run_pipeline(
        video=video,
        video_type=p["type"],
        context=p["context"],
        whisper_model=p["whisper_model"],
        max_iterations=p["max_iterations"],
        resume_from=from_stage,
        cli=cli,
        cli_fallback=cli_fallback,
        language=p.get("language", "pt"),
    )


# ── Maintenance commands ─────────────────────────────────────────────────────


@app.command()
def doctor() -> None:
    """Check that all dependencies are installed and available."""
    import shutil

    checks = [
        ("python", sys.executable, f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
    ]

    # ffmpeg / ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            checks.append((tool, path, "[green]OK[/green]"))
        else:
            checks.append((tool, "NOT FOUND", "[red]MISSING[/red]"))

    # Python packages
    for pkg, import_name in [("openai-whisper", "whisper"), ("pysubs2", "pysubs2"), ("typer", "typer"), ("rich", "rich")]:
        try:
            __import__(import_name)
            checks.append((pkg, "", "[green]OK[/green]"))
        except ImportError:
            checks.append((pkg, "", "[red]MISSING[/red]"))

    # ralph.sh
    if RALPH_SCRIPT.exists():
        checks.append(("ralph.sh", str(RALPH_SCRIPT), "[green]OK[/green]"))
    else:
        checks.append(("ralph.sh", str(RALPH_SCRIPT), "[red]MISSING[/red]"))

    # agents/ and tools/ dirs
    for d in ("agents", "tools"):
        p = REPO_ROOT / d
        checks.append((f"{d}/", str(p), "[green]OK[/green]" if p.is_dir() else "[red]MISSING[/red]"))

    # LLM CLI
    for cli_name in ("claude", "cursor"):
        path = shutil.which(cli_name)
        if path:
            checks.append((cli_name, path, "[green]OK[/green]"))
            break
    else:
        checks.append(("claude/cursor", "NOT FOUND", "[yellow]WARN[/yellow] (needed for agent stages)"))

    table = Table(title="auto-edit doctor", show_header=True)
    table.add_column("Component", style="bold")
    table.add_column("Path / Info")
    table.add_column("Status")
    for name, info, status in checks:
        table.add_row(name, info, status)

    console.print(table)
    console.print(f"\n[dim]Repo root:[/dim] {REPO_ROOT}")


_VALID_TARGETS = ("claude", "gemini", "cursor")


@app.command()
def setup(
    target: str = typer.Argument(
        None,
        help=f"Which AI CLI to configure: {', '.join(_VALID_TARGETS)}, or omit for --all.",
    ),
    all_targets: bool = typer.Option(False, "--all", help="Configure all supported AI CLIs."),
) -> None:
    """Configure AI coding assistants to understand auto-edit commands."""
    if all_targets or target is None:
        targets = list(_VALID_TARGETS)
    else:
        t = target.lower().strip()
        if t not in _VALID_TARGETS:
            console.print(f"[red]Unknown target:[/red] {t}. Choose from: {', '.join(_VALID_TARGETS)}")
            raise typer.Exit(1)
        targets = [t]

    for t in targets:
        console.rule(f"[bold]{t}[/bold]")
        _SETUP_HANDLERS[t]()
        console.print()

    console.print("[bold green]Done![/bold green] Restart your AI CLI for changes to take effect.")


def _setup_claude() -> None:
    import json
    import shutil

    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # 1. Write AUTO_EDIT.md instructions
    instructions_file = claude_dir / "AUTO_EDIT.md"
    instructions_file.write_text(_AUTO_EDIT_INSTRUCTIONS)
    console.print(f"[green]✓[/green] Wrote {instructions_file}")

    # 2. Add @AUTO_EDIT.md to CLAUDE.md if not present
    claude_md = claude_dir / "CLAUDE.md"
    tag = "@AUTO_EDIT.md"
    if claude_md.exists():
        content = claude_md.read_text()
        if tag not in content:
            claude_md.write_text(content.rstrip() + f"\n{tag}\n")
            console.print(f"[green]✓[/green] Added {tag} to {claude_md}")
        else:
            console.print(f"[dim]✓ {tag} already in {claude_md}[/dim]")
    else:
        claude_md.write_text(f"{tag}\n")
        console.print(f"[green]✓[/green] Created {claude_md} with {tag}")

    # 3. Configure MCP server if auto-edit is in PATH
    auto_edit_path = shutil.which("auto-edit")
    if auto_edit_path:
        settings_file = claude_dir / "settings.json"
        settings: dict = {}
        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                pass

        mcp_servers = settings.setdefault("mcpServers", {})
        if "auto-edit-video" not in mcp_servers:
            mcp_servers["auto-edit-video"] = {
                "command": "auto-edit",
                "args": ["mcp-server"],
            }
            settings_file.write_text(json.dumps(settings, indent=2) + "\n")
            console.print(f"[green]✓[/green] Added MCP server to {settings_file}")
        else:
            console.print(f"[dim]✓ MCP server already configured in {settings_file}[/dim]")
    else:
        console.print(
            "[yellow]⚠[/yellow] auto-edit not in PATH — skipping MCP server. "
            "Add to PATH and re-run [bold]auto-edit setup claude[/bold]."
        )


def _setup_gemini() -> None:
    gemini_dir = Path.home() / ".gemini"
    gemini_dir.mkdir(exist_ok=True)

    gemini_md = gemini_dir / "GEMINI.md"
    begin = "<!-- BEGIN auto-edit -->"
    end = "<!-- END auto-edit -->"
    block = f"{begin}\n{_AUTO_EDIT_INSTRUCTIONS}{end}\n"

    if gemini_md.exists():
        content = gemini_md.read_text()
        if begin in content and end in content:
            before = content.split(begin)[0].rstrip()
            after = content.split(end)[1]
            gemini_md.write_text((before + "\n\n" if before else "") + block + after.lstrip("\n"))
            console.print(f"[green]✓[/green] Updated auto-edit section in {gemini_md}")
        elif begin not in content:
            gemini_md.write_text(content.rstrip() + "\n\n" + block)
            console.print(f"[green]✓[/green] Appended auto-edit instructions to {gemini_md}")
        else:
            console.print(f"[yellow]⚠[/yellow] Found {begin} but no {end} in {gemini_md} — please fix manually")
    else:
        gemini_md.write_text(block)
        console.print(f"[green]✓[/green] Created {gemini_md}")


def _setup_cursor() -> None:
    cursor_rules_dir = Path.home() / ".cursor" / "rules"
    cursor_rules_dir.mkdir(parents=True, exist_ok=True)

    rules_file = cursor_rules_dir / "auto-edit.mdc"
    frontmatter = (
        "---\n"
        "description: auto-edit-video CLI for AI-powered video editing\n"
        "globs:\n"
        "alwaysApply: true\n"
        "---\n\n"
    )
    rules_file.write_text(frontmatter + _AUTO_EDIT_INSTRUCTIONS)
    console.print(f"[green]✓[/green] Wrote {rules_file}")
    console.print("[dim]Cursor loads .mdc rules globally from ~/.cursor/rules/[/dim]")


_SETUP_HANDLERS = {
    "claude": _setup_claude,
    "gemini": _setup_gemini,
    "cursor": _setup_cursor,
}


_AUTO_EDIT_INSTRUCTIONS = """\
# auto-edit — AI Video Editing CLI

**What it does**: Automated video editing pipeline — transcribes, plans cuts, executes via FFmpeg, adds captions, and generates metadata. All powered by AI agents.

## Commands

```bash
# Edit a short (vertical, with captions — Reels/Shorts)
auto-edit short video.mp4 --context "review de produto tech"

# Edit a long (horizontal, no captions — YouTube)
auto-edit long video.mp4 --context "tutorial de Python"

# Merge multiple clips into one, then edit
auto-edit merge folder/ --name "final" --type short --context "vlogs"

# Batch process all videos in a folder
auto-edit batch folder/ --type short --context "vlogs de viagem"

# Check pipeline status
auto-edit status video.mp4

# Resume from a specific stage
auto-edit resume video.mp4 --from plan

# Health check
auto-edit doctor
```

## Common Options

| Flag | Short | Description |
|------|-------|-------------|
| `--context` | `-c` | What the video is about (helps AI plan cuts) |
| `--whisper-model` | `-m` | Whisper model: tiny, base, small, medium, large (default: small) |
| `--language` | `-l` | Audio language: pt, en, es, etc. (default: pt) |
| `--max-iter` | | Max evaluator feedback loops (default: 3) |
| `--dry-run` | | Preview cut plan without running FFmpeg |
| `--cli` | | Agent CLI: claude, cursor, agent (default: $AUTO_EDIT_LLM or claude) |
| `--cli-fallback` | | Fallback CLI if primary fails |

## Caption Options (short only)

| Flag | Default | Description |
|------|---------|-------------|
| `--font-size` | 14 | Caption font size |
| `--highlight-color` | `&H0045FF&` | Highlight color in ASS `&HBBGGRR&` format |
| `--highlight-border` | 2.5 | Highlight word border thickness |

## Pipeline Stages

```
extract → plan → review → execute → overlay → caption → evaluate → metadata → done
Whisper   Claude  Claude   FFmpeg   FFmpeg    FFmpeg    Claude     Claude
```

- **short**: skips overlay, runs caption (CapCut-style subtitles)
- **long**: runs overlay, skips caption
- If evaluator rejects, pipeline loops back to `plan` with feedback (up to max-iter)

## Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| `AUTO_EDIT_LLM` | `claude` | Primary CLI for agent stages |
| `AUTO_EDIT_LLM_FALLBACK` | — | Fallback CLI if primary fails |
| `AUTO_EDIT_END_PADDING` | `0.2` | Seconds added to end of each kept segment |
| `AUTO_EDIT_LANGUAGE` | `pt` | Audio language for transcription |
| `GEMINI_API_KEY` | — | API key for Gemini text correction |

## Troubleshooting

- Run `auto-edit doctor` to check all dependencies
- If a stage fails: `auto-edit resume video.mp4 --from <stage>`
- Use `--dry-run` to preview cuts before executing
- Check status: `auto-edit status video.mp4`
"""


@app.command("mcp-server")
def mcp_server() -> None:
    """Start the MCP server for Claude Code integration (stdio transport)."""
    from auto_edit.mcp_server import main as run_mcp
    run_mcp()


@app.command()
def update() -> None:
    """Update auto-edit-video to the latest version."""
    import shutil

    # Nix install: REPO_ROOT is in /nix/store (read-only, no .git)
    if "/nix/store" in str(REPO_ROOT):
        if not shutil.which("nix"):
            console.print("[red]Nix installation detected but 'nix' command not found.[/red]")
            raise typer.Exit(1)

        console.print("[cyan]Nix installation detected — upgrading via nix profile...[/cyan]")
        result = subprocess.run(
            ["nix", "profile", "upgrade", "--refresh", "auto-edit-video"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]nix profile upgrade failed:[/red]\n{result.stderr}")
            console.print("[dim]Try manually: nix profile upgrade auto-edit-video[/dim]")
            raise typer.Exit(1)
        console.print("[green]Updated successfully via Nix.[/green]")
        return

    if not (REPO_ROOT / ".git").is_dir():
        console.print("[red]Not a git repo — cannot auto-update.[/red]")
        console.print("[dim]Set AUTO_EDIT_REPO_ROOT to the project root, or check your installation.[/dim]")
        raise typer.Exit(1)

    console.print("[cyan]Pulling latest changes...[/cyan]")
    result = subprocess.run(["git", "-C", str(REPO_ROOT), "pull", "--ff-only"], capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]git pull failed:[/red]\n{result.stderr}")
        raise typer.Exit(1)
    console.print(result.stdout.strip())

    console.print("[cyan]Reinstalling package...[/cyan]")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(REPO_ROOT), "-q"], check=True)
    console.print("[green]Updated successfully.[/green]")
