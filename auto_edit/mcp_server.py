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
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from auto_edit import engine
from auto_edit import pipeline as pl
from auto_edit import retention as ret
from auto_edit import shell
from auto_edit.publish import youtube as yt
from auto_edit.workspace import get_workspace, get_status_table

mcp = FastMCP(
    "auto-edit-video",
    instructions=(
        "Motor de edição do auto-edit: edita (edit_short/edit_long), ajusta pela "
        "conversa (get_plan, cut_section, add_zoom, add_broll, adjust_captions, "
        "rerender), publica (publish_info, publish_youtube) e mede (retention, "
        "retention_trend). `video` é o id de list_videos ou o caminho do original; "
        "tempos em segundos, no vídeo editado por padrão."
    ),
)
# FastMCP takes no version; the low-level server reports it to the client.
try:
    mcp._mcp_server.version = importlib.metadata.version("auto-edit-video")
except Exception:  # noqa: BLE001 — not installed as a package (checkout)
    pass


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

    return _run_ralph(ws, language=language, dry_run=dry_run)


def _run_ralph(ws: Path, *, language: str = "pt", dry_run: bool = False) -> str:
    """Run ralph.sh over a workspace already set to its starting stage."""
    ralph = _ralph()
    if not ralph.exists():
        return f"Error: ralph.sh not found at {ralph}"
    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(ralph.parent.resolve())
    env["AUTO_EDIT_LANGUAGE"] = language
    env["AUTO_EDIT_LLM"] = env.get("AUTO_EDIT_LLM", "claude")
    if dry_run:
        env["AUTO_EDIT_DRY_RUN"] = "1"

    result = subprocess.run(
        [shell.bash(env), str(ralph), shell.native_path(ws.resolve())],
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


# ── Conversa → motor: plano, efeitos, legenda, publicação, retenção ──────────
#
# Every tool below takes `video` as the workspace id (see list_videos) or the
# path of the original file. Times are in seconds; `timeline="edited"` means
# the video the person watched (the final cut), "original" the raw recording.


def _id(video: str) -> str:
    vid = engine.resolve_video(video)
    if vid is None:
        raise ValueError(f"nenhuma edição encontrada para: {video} (veja list_videos)")
    return vid


def _ws_of(video_id: str) -> Path:
    return engine.library_root() / video_id


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _mmss(t: float | None) -> str:
    if t is None:
        return "?"
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _rerender(video_id: str, from_stage: str = "execute") -> str:
    ws = _ws_of(video_id)
    p = pl.load(ws)
    pl.set_stage(ws, from_stage)
    return _run_ralph(ws, language=p.get("language", "pt"))


def _guard(fn):
    """Errors the person has to fix come back as text, not a crash."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (FileNotFoundError, ValueError) as exc:
            return f"Erro: {exc}"
        except yt.PublishError as exc:
            return f"Erro ao publicar: {exc}"
        except ret.RetentionError as exc:
            return f"Retenção: {exc}"
    return wrapper


@mcp.tool()
@_guard
def list_videos(limit: int = 20) -> str:
    """List the edits in the library (newest first): id, type, status, title.

    Use the id as `video` in the other tools.

    Args:
        limit: How many to show (default 20)
    """
    items = engine.list_library()[: max(1, limit)]
    if not items:
        return "Nenhuma edição na biblioteca."
    lines = []
    for v in items:
        title = v.get("title") or v.get("name") or v.get("video_name")
        pub = " · publicado" if v.get("published") else ""
        lines.append(f"- {v['id']}  [{v.get('type')}] {v.get('status')}{pub}  {title}")
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_plan(video: str) -> str:
    """Show the cut plan: every kept segment with what is said in it, in the
    original timeline and where it lands in the edited video.

    Args:
        video: Workspace id or original video path
    """
    from auto_edit import effects as fx

    vid = _id(video)
    plan = engine.read_plan(vid)
    if not plan:
        return f"{vid} ainda não tem plano de cortes."
    play = fx.playback(_ws_of(vid))
    lines = [
        f"Plano de {vid} ({plan['source']}): {len(plan['kept_segments'])} trechos, "
        f"{_mmss(plan['kept_total'])} mantidos de {_mmss(plan.get('duration'))}.",
        "Tempos: original → no vídeo editado.",
    ]
    for k in plan["kept_segments"]:
        where = fx.place({"start": k["start"], "end": k["end"]}, play)
        edited = ", ".join(f"{_mmss(w['t0'])}–{_mmss(w['t1'])}" for w in where) or "—"
        lines.append(f"[{k['index']}] {_mmss(k['start'])}–{_mmss(k['end'])} → {edited}: {k.get('text') or ''}")
    if plan.get("dropped_blocks"):
        lines.append("")
        lines.append("Blocos descartados pela curadoria: " + _json(plan["dropped_blocks"]))
    return "\n".join(lines)


@mcp.tool()
@_guard
def cut_section(video: str, start: float, end: float, timeline: str = "edited", rerender: bool = False) -> str:
    """Remove a stretch from the edit ("tira de 2:10 a 2:25").

    Args:
        video: Workspace id or original video path
        start: Start of the stretch, in seconds
        end: End of the stretch, in seconds
        timeline: "edited" (default: the final video the person watched) or "original"
        rerender: If True, re-render now (resume from execute); otherwise call rerender later
    """
    vid = _id(video)
    data = engine.cut_range(vid, start, end, timeline=timeline)
    removed = ", ".join(f"{_mmss(w['start'])}–{_mmss(w['end'])}" for w in data["removed_windows"])
    msg = (f"Cortado (original {removed}). Agora {len(data['kept_segments'])} trechos, "
           f"{_mmss(data['kept_total'])} no total.")
    if rerender:
        return msg + "\n" + _rerender(vid)
    return msg + " Rode rerender pra gerar o vídeo novo."


@mcp.tool()
@_guard
def update_plan(video: str, kept_segments: list[dict], rerender: bool = False) -> str:
    """Replace the kept segments of the plan (original timeline). The agent's
    version is backed up once as reviewed_plan.agent.json.

    Args:
        video: Workspace id or original video path
        kept_segments: [{"start": s, "end": e, "summary": "..."}] in seconds of the original
        rerender: If True, re-render now (resume from execute)
    """
    vid = _id(video)
    data = engine.write_plan(vid, kept_segments)
    msg = f"Plano salvo: {len(data['kept_segments'])} trechos, {_mmss(data['kept_total'])}."
    return msg + ("\n" + _rerender(vid) if rerender else " Rode rerender pra gerar o vídeo novo.")


@mcp.tool()
@_guard
def rerender(video: str, from_stage: str = "execute") -> str:
    """Re-render after changing the plan or the effects (runs from `from_stage`
    to the end: cut, overlays/captions, metadata, thumbnail).

    Args:
        video: Workspace id or original video path
        from_stage: Stage to start from (default execute)
    """
    if from_stage not in pl.STAGES:
        return f"Erro: stage desconhecido: {from_stage}"
    return _rerender(_id(video), from_stage)


def _effects_text(data: dict) -> str:
    lines = []
    for e in data["effects"]:
        what = f"zoom {e['scale']}x" if e["type"] == "zoom" else f"broll {Path(e['file']).name}"
        where = ", ".join(f"{_mmss(w['t0'])}–{_mmss(w['t1'])}" for w in e["windows"])
        lines.append(f"[{e['index']}] {what} · no editado {where} (original {_mmss(e['start'])}–{_mmss(e['end'])})")
    if not lines:
        lines.append("Nenhum efeito.")
    for n in data["notes"]:
        lines.append(f"aviso: {n}")
    return "\n".join(lines)


@mcp.tool()
@_guard
def list_effects(video: str) -> str:
    """List the zoom / b-roll effects of an edit and where they play.

    Args:
        video: Workspace id or original video path
    """
    return _effects_text(engine.read_effects(_id(video)))


@mcp.tool()
@_guard
def add_zoom(video: str, start: float, end: float, scale: float = 1.2, timeline: str = "edited") -> str:
    """Punch-in zoom (centered) on a stretch. Validated: 0.5–30s, scale 1.05–1.6,
    must land on something that plays. Applied on the next rerender.

    Args:
        video: Workspace id or original video path
        start: Start in seconds
        end: End in seconds
        scale: Zoom factor, 1.05–1.6 (default 1.2)
        timeline: "edited" (default) or "original"
    """
    vid = _id(video)
    data = engine.add_effect(vid, {"type": "zoom", "start": start, "end": end, "scale": scale}, timeline=timeline)
    return _effects_text(data) + "\nRode rerender pra aplicar."


@mcp.tool()
@_guard
def add_broll(video: str, start: float, end: float, file: str, timeline: str = "edited") -> str:
    """Cover a stretch with an image or video (b-roll), full frame, keeping the
    speech audio. Validated: file exists (png/jpg/webp/mp4/mov/mkv/webm),
    0.5–30s. Applied on the next rerender.

    Args:
        video: Workspace id or original video path
        start: Start in seconds
        end: End in seconds
        file: Path of the image/video (relative = next to the original video)
        timeline: "edited" (default) or "original"
    """
    vid = _id(video)
    data = engine.add_effect(vid, {"type": "broll", "start": start, "end": end, "file": file}, timeline=timeline)
    return _effects_text(data) + "\nRode rerender pra aplicar."


@mcp.tool()
@_guard
def remove_effect(video: str, index: int = -1) -> str:
    """Remove one effect (index from list_effects) or all of them (index=-1).

    Args:
        video: Workspace id or original video path
        index: Effect index, or -1 for all
    """
    vid = _id(video)
    data = engine.remove_effect(vid, None if index < 0 else index)
    return _effects_text(data) + "\nRode rerender pra aplicar."


@mcp.tool()
@_guard
def adjust_captions(
    video: str,
    position: str | None = None,
    offset: float | None = None,
    size: float | None = None,
    hidden: bool | None = None,
    rerender: bool = True,
) -> str:
    """Adjust the burned-in captions of a short (only the keys you pass change)
    and, by default, re-burn only the captions.

    Args:
        video: Workspace id or original video path (a short)
        position: "top", "middle" or "bottom"
        offset: Distance from that edge, % of the video height (0–40)
        size: % of the style's base size (50–200)
        hidden: True hides the captions
        rerender: Re-burn the captions now (default True)
    """
    vid = _id(video)
    body = {k: v for k, v in
            {"position": position, "offset": offset, "size": size, "hidden": hidden}.items() if v is not None}
    data = engine.save_video_captions(vid, body)
    msg = f"Legenda: {_json(data['adjust'])}"
    if not rerender:
        return msg
    ws = _ws_of(vid)
    pl.recaption(ws)
    return msg + "\n" + _run_ralph(ws, language=pl.load(ws).get("language", "pt"))


@mcp.tool()
@_guard
def publish_info(video: str) -> str:
    """What would be published: suggested title/description/tags, title
    options, thumbnail variation (A/B/C), past uploads, account.

    Args:
        video: Workspace id or original video path
    """
    st = engine.publish_state(_id(video))
    if st is None:
        return "Edição não encontrada."
    keep = ("eligible", "reason", "defaults", "title_options", "thumbnail", "thumbnail_variant",
            "captions", "pinned_comment", "next_video", "published", "account")
    return _json({k: st.get(k) for k in keep})


@mcp.tool()
@_guard
def publish_youtube(
    video: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    privacy: str = "private",
    publish_at: str | None = None,
    thumbnail: str | None = None,
    captions: bool = True,
    comment: str | None = None,
    force: bool = False,
) -> str:
    """Upload the finished video to YouTube (with the chosen thumbnail and, for
    a long, the .srt). This publishes to the person's channel: confirm title,
    privacy and date with them before calling it.

    Args:
        video: Workspace id or original video path
        title: Title (default: the one from metadata)
        description: Description (default: from metadata, with chapters)
        tags: Tags (default: from metadata)
        privacy: "private" (default), "unlisted" or "public"
        publish_at: ISO date to schedule (forces private until then)
        thumbnail: "A", "B" or "C" to choose the variation (saved as the choice)
        captions: Send the .srt along (long only, default True)
        comment: Comment to post (to pin in the Studio)
        force: Upload again even if it was already sent
    """
    vid = _id(video)
    if thumbnail:
        engine.set_thumbnail_choice(vid, thumbnail)
    st = engine.publish_state(vid)
    d = st["defaults"]
    fields = {
        "title": title if title is not None else d.get("title", ""),
        "description": description if description is not None else d.get("description", ""),
        "tags": tags if tags is not None else d.get("tags") or [],
        "privacy": privacy,
        "publish_at": publish_at,
        "captions": captions,
        "comment": comment,
    }
    entry = engine.publish_now(vid, fields, force=force)
    return f"Enviado: {entry['url']} ({entry['privacy']})" + "".join(f"\n{x}" for x in entry.get("warnings") or [])


@mcp.tool()
@_guard
def retention(video: str, refresh: bool = False) -> str:
    """Where the audience left this video (YouTube Analytics), with what was
    being said, and how it compares to the previous videos.

    Args:
        video: Workspace id or original video path
        refresh: Fetch the curve from YouTube now (needs the account connected)
    """
    vid = _id(video)
    st = engine.refresh_retention(vid) if refresh else engine.retention_state(vid)
    if not st or not st.get("data"):
        return "Sem análise de retenção salva. Use refresh=True (o vídeo precisa estar publicado há 24–48h)."
    out = ret.format_summary(st["data"])
    vp = st.get("versus_previous")
    if vp:
        c = vp["at_30s"]
        if c["before"] is not None and c["after"] is not None:
            out += (f"\n\nVs os {vp['previous']} anteriores do mesmo tipo: aos 30s "
                    f"{c['after'] * 100:.0f}% (média antes {c['before'] * 100:.0f}%, {c['delta'] * 100:+.1f} pp)")
    return out


@mcp.tool()
@_guard
def retention_trend(video_type: str | None = None) -> str:
    """Is retention improving? Analyzed videos in publish order, older vs newer,
    and the ones planned with the retention lessons vs without.

    Args:
        video_type: "long", "short" or omitted for both
    """
    return ret.format_trend(engine.retention_trend(video_type))


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
