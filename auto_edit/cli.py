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
from auto_edit.workspace import get_workspace, init_workspace, get_status_table

app = typer.Typer(
    name="auto-edit",
    help="AI-powered video editing using Claude Code agents.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

RALPH_SCRIPT = Path(__file__).parent.parent / "ralph.sh"
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
) -> None:
    if not video.exists():
        console.print(f"[red]Error:[/red] File not found: {video}")
        raise typer.Exit(1)

    ws = get_workspace(video)

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
        )

    console.print(f"[cyan]Type:[/cyan] {video_type}")
    console.print(f"[cyan]Context:[/cyan] {context or '(none)'}")
    console.print(f"[cyan]Whisper model:[/cyan] {whisper_model}")
    console.print(f"[cyan]Language:[/cyan] {language}")
    console.print(f"[cyan]Workspace:[/cyan] {ws}")
    primary, fb = _resolve_llm(cli, cli_fallback)
    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(RALPH_SCRIPT.parent.resolve())
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
) -> None:
    """Edit a long-form video (no captions, generates YouTube metadata)."""
    if whisper_model not in VALID_MODELS:
        console.print(f"[red]Invalid model.[/red] Choose from: {', '.join(VALID_MODELS)}")
        raise typer.Exit(1)
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

    # Write FFmpeg concat list
    concat_list = folder / ".concat_list.txt"
    concat_list.write_text(
        "\n".join(f"file '{v.resolve()}'" for v in videos) + "\n"
    )

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(merged_path),
        ],
        capture_output=True,
        text=True,
    )
    concat_list.unlink(missing_ok=True)

    if result.returncode != 0:
        console.print(f"[red]FFmpeg merge failed:[/red]\n{result.stderr}")
        raise typer.Exit(1)

    console.print(f"[green]Merged successfully.[/green] ({merged_path.stat().st_size // 1_000_000} MB)\n")

    caption_style = {
        "border_highlight": highlight_border,
        "color_highlight": highlight_color,
        "font_size": font_size,
    } if video_type == "short" else None

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
