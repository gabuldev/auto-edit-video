"""Comandos `auto-edit insights` — auth / sync / link / report."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from auto_edit import config as cfg
from auto_edit.insights import connector, service, store

insights_app = typer.Typer(
    name="insights",
    help="Ingestão de métricas das redes (YouTube). Read-only.",
    no_args_is_help=True,
)
console = Console()


def _open():
    return store.connect(cfg.insights_db_path())


@insights_app.command()
def auth(platform: str = typer.Argument("youtube")) -> None:
    """Autentica numa plataforma (OAuth) e guarda o token."""
    try:
        c = connector.get_connector(platform)
        c.authenticate()
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Autenticado em {platform}.[/green]")


@insights_app.command()
def sync(platform: str = typer.Argument("youtube"),
         since: str = typer.Option(None, "--since", help="ISO date YYYY-MM-DD")) -> None:
    """Puxa uploads + métricas do canal e grava no store."""
    try:
        c = connector.get_connector(platform)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    conn = _open()
    res = service.sync(conn, c, since=since)
    console.print(f"[green]{res.videos_seen} vídeos, {res.snapshots_written} snapshots.[/green]")


@insights_app.command()
def link(workspace_or_video: str = typer.Argument(...),
         url: str = typer.Argument(...)) -> None:
    """Linka um vídeo publicado ao workspace (marca template/topic)."""
    conn = _open()
    res = service.link(conn, url, workspace_or_video)
    color = "green" if res.ok else "red"
    console.print(f"[{color}]{res.message}[/{color}]")
    if not res.ok:
        raise typer.Exit(1)


@insights_app.command()
def report(platform: str = typer.Option(None, "-p", "--platform"),
           by: str = typer.Option(None, "--by", help="template|topic"),
           top: int = typer.Option(None, "--top")) -> None:
    """Mostra a performance (tabela)."""
    conn = _open()
    rows = service.build_report(conn, platform=platform, by=by, top=top)
    if not rows:
        console.print("[yellow]Sem dados. Rode `auto-edit insights sync` primeiro.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    if by in ("template", "topic"):
        table.add_column(by)
        for col in ("videos", "views", "ctr", "avg_view_pct"):
            table.add_column(col)
        for r in rows:
            table.add_row(str(r.get(by)), str(r.get("videos")), str(r.get("views")),
                          str(r.get("ctr")), str(r.get("avg_view_pct")))
    else:
        for col in ("title", "views", "watch_time_min", "avg_view_pct", "ctr", "likes"):
            table.add_column(col)
        for r in rows:
            table.add_row(str(r.get("title"))[:40], str(r.get("views")),
                          str(r.get("watch_time_min")), str(r.get("avg_view_pct")),
                          str(r.get("ctr")), str(r.get("likes")))
    console.print(table)
