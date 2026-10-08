"""Comandos `auto-edit publish` — conectar a conta e enviar um vídeo pronto."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, Progress, TextColumn

from auto_edit import engine
from auto_edit.publish import youtube as yt
from auto_edit.workspace import workspace_root

publish_app = typer.Typer(
    name="publish",
    help="Publica vídeos prontos direto nas plataformas (YouTube).",
    no_args_is_help=True,
)
console = Console()


@publish_app.command()
def auth(platform: str = typer.Argument("youtube")) -> None:
    """Conecta a conta (abre o navegador pro OAuth) e guarda o token."""
    if platform != "youtube":
        console.print(f"[red]Plataforma não suportada:[/red] {escape(platform)}")
        raise typer.Exit(1)
    try:
        channel = yt.connect()
    except yt.PublishError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]YouTube conectado[/green]{f' como {escape(channel)}' if channel else ''}.")


@publish_app.command()
def youtube(
    video: Path = typer.Argument(..., help="O mesmo vídeo que você passou pro `auto-edit short|long`"),
    privacy: str = typer.Option("private", "--privacy", help="private, unlisted ou public"),
    publish_at: Optional[str] = typer.Option(
        None, "--publish-at", help="Agenda (ISO com fuso, ex: 2026-10-10T18:00:00-03:00); vira privado até lá"
    ),
    title: Optional[str] = typer.Option(None, "--title", help="Troca o título gerado no metadata"),
    force: bool = typer.Option(False, "--force", help="Envia de novo mesmo se já foi publicado"),
    captions: bool = typer.Option(True, "--captions/--no-captions", help="Envia a legenda (.srt) junto (só long)"),
    comment: bool = typer.Option(False, "--comment", help="Posta o comentário pra fixar gerado no metadata (não funciona em vídeo privado)"),
) -> None:
    """Envia o vídeo final (+ thumbnail, no long) com o título e a descrição do metadata."""
    ws = workspace_root() / video.stem
    state = engine.publish_state(ws.name)
    if state is None:
        console.print(f"[red]Nenhum workspace em {escape(str(ws))}.[/red]")
        raise typer.Exit(1)
    if not state["eligible"]:
        console.print(f"[red]{escape(state['reason'])}[/red]")
        raise typer.Exit(1)
    if state["published"] and not force:
        last = state["published"][-1]
        console.print(f"Já enviado: {escape(last['url'])}. Use [bold]--force[/bold] pra enviar de novo.")
        raise typer.Exit(1)

    fields = dict(state["defaults"])
    p = engine.pl.load(ws)
    try:
        body = yt.build_body(
            title=title or fields["title"],
            description=fields["description"],
            tags=fields["tags"],
            privacy=privacy,
            publish_at=publish_at,
            language=p.get("language"),
        )
        yt.credentials()  # falha cedo se não conectado
    except yt.PublishError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        if not yt.is_connected():
            console.print("Rode [bold]auto-edit publish auth youtube[/bold] primeiro.")
        raise typer.Exit(1)

    video_file = engine.artifact_path(ws.name, "video")
    thumb = engine.artifact_path(ws.name, "thumbnail") if state["thumbnail"] else None
    console.print(f"[cyan]{escape(body['snippet']['title'])}[/cyan] · {body['status']['privacyStatus']}")

    with Progress(TextColumn("enviando"), BarColumn(), TextColumn("{task.percentage:>3.0f}%"), console=console) as bar:
        task = bar.add_task("upload", total=100)

        def emit(ev: dict) -> None:
            if ev.get("type") == "progress":
                bar.update(task, completed=ev["pct"])
            elif ev.get("type") == "log" and ev["line"].startswith("aviso:"):
                bar.console.print(f"[yellow]{escape(ev['line'])}[/yellow]")

        try:
            entry = engine.run_publish_youtube(
                ws, body, video=video_file, thumbnail=thumb, emit=emit,
                captions=engine.artifact_path(ws.name, "captions") if captions and state["captions"] else None,
                language=p.get("language"),
                comment=state.get("pinned_comment") if comment else None,
            )
        except yt.PublishError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1)

    console.print(f"[bold green]Enviado:[/bold green] {entry['url']}")
    if entry["privacy"] != "public" and not entry.get("publish_at"):
        console.print("[dim]Está privado/não listado — libere no YouTube Studio quando quiser.[/dim]")
