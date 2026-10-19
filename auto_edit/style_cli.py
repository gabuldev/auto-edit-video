"""`auto-edit style`: create a style with AI, export and import style files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from auto_edit import styles

style_app = typer.Typer(help="Estilos visuais: criar com IA, exportar e importar.", no_args_is_help=True)
console = Console()


def _fail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _progress(msg: str) -> None:
    typer.echo(f"· {msg}", err=True)


@style_app.command("generate")
def generate(
    description: str = typer.Argument("", help="Como o estilo deve ser (ex.: 'tech escuro, neon roxo')"),
    image: Optional[Path] = typer.Option(None, "--image", "-i", help="Thumbnail de referência (a IA reproduz o layout)"),
    rounds: int = typer.Option(styles.AI_ROUNDS, "--rounds", min=1, max=5, help="Respostas da IA no total (1 = sem conferir)"),
    save: bool = typer.Option(False, "--save", help="Salva como um estilo seu"),
    activate: bool = typer.Option(False, "--activate", help="Salva e passa a usar"),
):
    """Cria um estilo com a IA (rascunho; --save grava)."""
    try:
        draft = styles.generate(description, image.read_bytes() if image else None, rounds=rounds, on_progress=_progress)
    except (OSError, styles.StyleError) as exc:
        _fail(str(exc))
    if save or activate:
        saved = styles.save(draft["name"], draft["tokens"], None, draft["description"])
        if activate:
            styles.set_active(saved["id"])
        console.print(f"[green]salvo:[/green] {saved['name']} ({saved['id']})")
    else:
        typer.echo(json.dumps(draft, indent=2, ensure_ascii=False))


@style_app.command("adjust")
def adjust(
    style_id: str = typer.Argument(..., help="Id do estilo de partida"),
    request: str = typer.Argument(..., help="O que mudar (ex.: 'título maior, tira o círculo')"),
    image: Optional[Path] = typer.Option(None, "--image", "-i", help="Thumbnail de referência"),
    rounds: int = typer.Option(styles.AI_ROUNDS, "--rounds", min=1, max=5, help="Respostas da IA no total"),
    activate: bool = typer.Option(False, "--activate", help="Passa a usar"),
):
    """Ajusta um estilo com a IA e salva como um estilo novo (o original fica)."""
    base = styles.get(style_id)
    if not base:
        _fail(f"estilo não encontrado: {style_id}")
    try:
        draft = styles.generate(request, image.read_bytes() if image else None, base=base["tokens"],
                                rounds=rounds, on_progress=_progress)
    except (OSError, styles.StyleError) as exc:
        _fail(str(exc))
    saved = styles.save(f"{base['name'][:28]} (ajustado)", draft["tokens"], None, base["description"])
    if activate:
        styles.set_active(saved["id"])
    console.print(f"[green]salvo:[/green] {saved['name']} ({saved['id']})")


@style_app.command("export")
def export(
    style_id: str = typer.Argument(..., help="Id do estilo"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help=f"Arquivo (padrão: <id>{styles.FILE_SUFFIX})"),
):
    """Exporta um estilo pra um arquivo compartilhável (sem a sua marca)."""
    try:
        data = styles.export(style_id)
    except styles.StyleError as exc:
        _fail(str(exc))
    out = output or Path(f"{style_id}{styles.FILE_SUFFIX}")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]exportado:[/green] {out}")


@style_app.command("import")
def import_(
    file: Path = typer.Argument(..., help="Arquivo .autoedit-style.json"),
    activate: bool = typer.Option(False, "--activate", help="Passa a usar"),
):
    """Importa um estilo (vira um estilo seu, nunca sobrescreve)."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _fail(styles.NOT_A_STYLE)
    try:
        saved = styles.import_(data)
    except styles.StyleError as exc:
        _fail(str(exc))
    if activate:
        styles.set_active(saved["id"])
    console.print(f"[green]importado:[/green] {saved['name']} ({saved['id']})")
