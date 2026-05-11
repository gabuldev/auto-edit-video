"""Content ideas backlog subcommand.

Manages a flat-file backlog of content ideas in ~/.auto-edit/ideas/.
Each idea is a YAML file that can later be linked to a plan slot via `pick`.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from auto_edit import config as cfg

ideas_app = typer.Typer(
    name="ideas",
    help="Manage your content ideas backlog.",
    no_args_is_help=True,
)

console = Console()

SOURCES = ["youtube-comment", "personal", "trend", "collaboration", "other"]
PRIORITIES = ["high", "medium", "low"]
STATUSES = ["backlog", "planned", "done", "dropped"]
FORMATS = ["tutorial", "opinion", "series", "review", "vlog", "other"]

_PRIORITY_STYLE = {
    "high": "red bold",
    "medium": "yellow",
    "low": "dim",
}

_STATUS_STYLE = {
    "backlog": "dim",
    "planned": "cyan",
    "done": "green",
    "dropped": "red dim",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _generate_id() -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"idea-{today}-"
    existing = sorted(cfg.ideas_dir().glob(f"{prefix}*.yaml"))
    if existing:
        last_num = int(existing[-1].stem.split("-")[-1])
        return f"{prefix}{last_num + 1:03d}"
    return f"{prefix}001"


def _idea_path(idea_id: str) -> Path:
    return cfg.ideas_dir() / f"{idea_id}.yaml"


def _load_idea(idea_id: str) -> dict:
    path = _idea_path(idea_id)
    if not path.exists():
        console.print(f"[red]Idea '{idea_id}' not found.[/]")
        raise typer.Exit(1)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _save_idea(idea_id: str, data: dict) -> Path:
    path = _idea_path(idea_id)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _all_ideas() -> list[dict]:
    cfg.ensure_dirs()
    ideas = []
    for f in sorted(cfg.ideas_dir().glob("idea-*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        if raw:
            ideas.append(raw)
    return ideas


def _resolve_idea_id(idea_id: str) -> str:
    """Accept full ID or short suffix (e.g. '001' matches 'idea-20260511-001')."""
    if _idea_path(idea_id).exists():
        return idea_id
    matches = [f.stem for f in cfg.ideas_dir().glob("idea-*.yaml") if f.stem.endswith(idea_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        console.print(f"[red]Ambiguous ID '{idea_id}'. Matches: {', '.join(matches)}[/]")
        raise typer.Exit(1)
    console.print(f"[red]Idea '{idea_id}' not found.[/]")
    raise typer.Exit(1)


# ── Commands ─────────────────────────────────────────────────────────────────


@ideas_app.command("add")
def add_idea(
    title: str = typer.Argument(..., help="Idea title."),
    source: Optional[str] = typer.Option(None, "--source", "-s", help=f"Source: {', '.join(SOURCES)}."),
    priority: str = typer.Option("medium", "--priority", "-p", help=f"Priority: {', '.join(PRIORITIES)}."),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags."),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help=f"Format: {', '.join(FORMATS)}."),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Description."),
    language: str = typer.Option("pt", "--language", "-l", help="Language: pt, en, es."),
) -> None:
    """Add a new content idea to the backlog."""
    cfg.ensure_dirs()

    if priority not in PRIORITIES:
        console.print(f"[red]Invalid priority '{priority}'. Choose: {', '.join(PRIORITIES)}[/]")
        raise typer.Exit(1)
    if source and source not in SOURCES:
        console.print(f"[red]Invalid source '{source}'. Choose: {', '.join(SOURCES)}[/]")
        raise typer.Exit(1)
    if fmt and fmt not in FORMATS:
        console.print(f"[red]Invalid format '{fmt}'. Choose: {', '.join(FORMATS)}[/]")
        raise typer.Exit(1)

    idea_id = _generate_id()
    now = datetime.now().isoformat(timespec="seconds")
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    data = {
        "id": idea_id,
        "title": title,
        "description": description or "",
        "source": source or "personal",
        "priority": priority,
        "status": "backlog",
        "tags": tag_list,
        "language": language,
        "format": fmt or "other",
        "created_at": now,
        "updated_at": now,
        "plan_id": None,
    }

    _save_idea(idea_id, data)
    console.print(f"[green]✓[/] Idea added: [bold]{idea_id}[/] — {title}")


@ideas_app.command("list")
def list_ideas(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="Filter by priority."),
    source: Optional[str] = typer.Option(None, "--source", help="Filter by source."),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag."),
    all_: bool = typer.Option(False, "--all", "-a", help="Show all ideas (including done/dropped)."),
) -> None:
    """List ideas in the backlog."""
    ideas = _all_ideas()
    if not ideas:
        console.print("[dim]No ideas yet. Run `auto-edit ideas add \"title\"` to create one.[/]")
        return

    if status:
        ideas = [i for i in ideas if i.get("status") == status]
    elif not all_:
        ideas = [i for i in ideas if i.get("status") in ("backlog", "planned")]

    if priority:
        ideas = [i for i in ideas if i.get("priority") == priority]
    if source:
        ideas = [i for i in ideas if i.get("source") == source]
    if tag:
        ideas = [i for i in ideas if tag in i.get("tags", [])]

    prio_order = {"high": 0, "medium": 1, "low": 2}
    ideas.sort(key=lambda i: (prio_order.get(i.get("priority", "medium"), 9), i.get("created_at", "")))

    if not ideas:
        console.print("[dim]No ideas match the filters.[/]")
        return

    t = Table(show_lines=False)
    t.add_column("ID", style="cyan", no_wrap=True)
    t.add_column("Title")
    t.add_column("Source", no_wrap=True)
    t.add_column("Priority", no_wrap=True)
    t.add_column("Status", no_wrap=True)
    t.add_column("Tags", no_wrap=True)
    t.add_column("Plan", no_wrap=True)

    for idea in ideas:
        prio = idea.get("priority", "medium")
        stat = idea.get("status", "backlog")
        tags_str = ", ".join(idea.get("tags", []))
        plan_id = idea.get("plan_id") or "—"
        t.add_row(
            idea.get("id", ""),
            idea.get("title", ""),
            idea.get("source", ""),
            f"[{_PRIORITY_STYLE.get(prio, '')}]{prio}[/]",
            f"[{_STATUS_STYLE.get(stat, '')}]{stat}[/]",
            tags_str,
            plan_id,
        )

    console.print(t)


@ideas_app.command("show")
def show_idea(
    idea_id: str = typer.Argument(..., help="Idea ID (full or suffix)."),
) -> None:
    """Show details of a specific idea."""
    idea_id = _resolve_idea_id(idea_id)
    idea = _load_idea(idea_id)

    prio = idea.get("priority", "medium")
    stat = idea.get("status", "backlog")

    console.print(f"\n[bold]{idea.get('title', '')}[/]")
    console.print(f"  ID:          [cyan]{idea.get('id', '')}[/]")
    if idea.get("description"):
        console.print(f"  Description: {idea['description']}")
    console.print(f"  Source:      {idea.get('source', '')}")
    console.print(f"  Priority:    [{_PRIORITY_STYLE.get(prio, '')}]{prio}[/]")
    console.print(f"  Status:      [{_STATUS_STYLE.get(stat, '')}]{stat}[/]")
    console.print(f"  Format:      {idea.get('format', '')}")
    console.print(f"  Language:    {idea.get('language', '')}")
    if idea.get("tags"):
        console.print(f"  Tags:        {', '.join(idea['tags'])}")
    if idea.get("plan_id"):
        console.print(f"  Plan:        [bold]{idea['plan_id']}[/]")
    console.print(f"  Created:     [dim]{idea.get('created_at', '')}[/]")
    console.print(f"  Updated:     [dim]{idea.get('updated_at', '')}[/]")
    console.print()


@ideas_app.command("edit")
def edit_idea(
    idea_id: str = typer.Argument(..., help="Idea ID (full or suffix)."),
) -> None:
    """Open an idea YAML in $EDITOR."""
    idea_id = _resolve_idea_id(idea_id)
    path = _idea_path(idea_id)
    if not path.exists():
        console.print(f"[red]Idea '{idea_id}' not found.[/]")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    subprocess.call([*shlex.split(editor), str(path)])


@ideas_app.command("update")
def update_idea(
    idea_id: str = typer.Argument(..., help="Idea ID (full or suffix)."),
    title: Optional[str] = typer.Option(None, "--title", help="New title."),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description."),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="New source."),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="New priority."),
    status: Optional[str] = typer.Option(None, "--status", help="New status."),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="New comma-separated tags (replaces all)."),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help="New format."),
    language: Optional[str] = typer.Option(None, "--language", "-l", help="New language."),
) -> None:
    """Update fields of an existing idea."""
    idea_id = _resolve_idea_id(idea_id)
    idea = _load_idea(idea_id)

    if priority and priority not in PRIORITIES:
        console.print(f"[red]Invalid priority '{priority}'. Choose: {', '.join(PRIORITIES)}[/]")
        raise typer.Exit(1)
    if status and status not in STATUSES:
        console.print(f"[red]Invalid status '{status}'. Choose: {', '.join(STATUSES)}[/]")
        raise typer.Exit(1)
    if source and source not in SOURCES:
        console.print(f"[red]Invalid source '{source}'. Choose: {', '.join(SOURCES)}[/]")
        raise typer.Exit(1)
    if fmt and fmt not in FORMATS:
        console.print(f"[red]Invalid format '{fmt}'. Choose: {', '.join(FORMATS)}[/]")
        raise typer.Exit(1)

    updated = False
    for field, value in [
        ("title", title),
        ("description", description),
        ("source", source),
        ("priority", priority),
        ("status", status),
        ("format", fmt),
        ("language", language),
    ]:
        if value is not None:
            idea[field] = value
            updated = True

    if tags is not None:
        idea["tags"] = [t.strip() for t in tags.split(",")]
        updated = True

    if not updated:
        console.print("[dim]Nothing to update. Pass at least one --flag.[/]")
        raise typer.Exit(1)

    idea["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_idea(idea_id, idea)
    console.print(f"[green]✓[/] Updated: [bold]{idea_id}[/]")


@ideas_app.command("remove")
def remove_idea(
    idea_id: str = typer.Argument(..., help="Idea ID (full or suffix)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove an idea from the backlog."""
    idea_id = _resolve_idea_id(idea_id)
    idea = _load_idea(idea_id)

    if not yes:
        confirm = typer.confirm(f"Remove idea '{idea.get('title', idea_id)}'?")
        if not confirm:
            console.print("[dim]Cancelled.[/]")
            raise typer.Exit()

    _idea_path(idea_id).unlink()
    console.print(f"[green]✓[/] Removed: [bold]{idea_id}[/] — {idea.get('title', '')}")


# ── Plan integration ─────────────────────────────────────────────────────────


def _load_plan(period_id: str) -> tuple[dict, Path]:
    path = cfg.plans_dir() / f"{period_id}.yaml"
    if not path.exists():
        console.print(f"[red]Plan '{period_id}' not found. Run `auto-edit plan new` first.[/]")
        raise typer.Exit(1)
    plan = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return plan, path


def _save_plan(path: Path, plan: dict) -> None:
    path.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _find_slot(plan: dict, slot_id: str) -> tuple[str, int, dict] | None:
    """Find a slot in longs or shorts by ID (e.g. 'L2', 'S3'). Returns (list_key, index, item)."""
    for key in ("longs", "shorts"):
        for i, item in enumerate(plan.get(key, [])):
            if item.get("id", "").upper() == slot_id.upper():
                return key, i, item
    return None


def _available_slots(plan: dict) -> list[dict]:
    """Return plan slots that are still 'planned' and have no source_folder."""
    out = []
    for key in ("longs", "shorts"):
        for item in plan.get(key, []):
            if item.get("status") == "planned" and not item.get("source_folder"):
                out.append(item)
    return out


@ideas_app.command("pick")
def pick_idea(
    idea_id: str = typer.Argument(..., help="Idea ID (full or suffix)."),
    plan: str = typer.Option(..., "--plan", help="Plan period: YYYY-Www, YYYY-MM, 'current', 'next'."),
    slot: Optional[str] = typer.Option(None, "--slot", help="Slot ID (e.g. L2, S3). Omit to see available."),
) -> None:
    """Link an idea to a plan slot."""
    from auto_edit.plan import _resolve_period

    idea_id = _resolve_idea_id(idea_id)
    idea = _load_idea(idea_id)

    if idea.get("plan_id"):
        console.print(f"[red]Idea already linked to {idea['plan_id']}. Use `ideas unpick` first.[/]")
        raise typer.Exit(1)

    month_arg = plan if "-W" not in plan.upper() and plan not in ("current", "next", "now", "this") else None
    week_arg = plan if month_arg is None else None
    period = _resolve_period(month_arg, week_arg)

    plan_data, plan_path = _load_plan(period.id)

    if not slot:
        available = _available_slots(plan_data)
        if not available:
            console.print(f"[red]No available slots in plan {period.id}.[/]")
            raise typer.Exit(1)
        console.print(f"\n[bold]Available slots in {period.id}:[/]\n")
        for s in available:
            console.print(f"  [cyan]{s.get('id', '')}[/] — {s.get('topic', '(empty)')}")
        console.print("\n[dim]Re-run with --slot <ID> to link.[/]")
        return

    result = _find_slot(plan_data, slot)
    if not result:
        console.print(f"[red]Slot '{slot}' not found in plan {period.id}.[/]")
        raise typer.Exit(1)

    list_key, idx, slot_item = result

    if slot_item.get("source_folder"):
        console.print(f"[red]Slot {slot} already has a source_folder assigned.[/]")
        raise typer.Exit(1)

    full_plan_id = f"{period.id}/{slot_item['id']}"

    plan_data[list_key][idx]["topic"] = idea["title"]
    plan_data[list_key][idx]["language"] = idea.get("language", "pt")
    plan_data[list_key][idx]["format"] = idea.get("format", "other")
    plan_data[list_key][idx]["idea_id"] = idea_id
    _save_plan(plan_path, plan_data)

    idea["status"] = "planned"
    idea["plan_id"] = full_plan_id
    idea["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_idea(idea_id, idea)

    console.print(f"[green]✓[/] Linked [bold]{idea_id}[/] → [bold]{full_plan_id}[/]")


@ideas_app.command("unpick")
def unpick_idea(
    idea_id: str = typer.Argument(..., help="Idea ID (full or suffix)."),
) -> None:
    """Unlink an idea from its plan slot."""
    idea_id = _resolve_idea_id(idea_id)
    idea = _load_idea(idea_id)

    plan_id = idea.get("plan_id")
    if not plan_id:
        console.print(f"[dim]Idea '{idea_id}' is not linked to any plan.[/]")
        raise typer.Exit(1)

    if "/" not in plan_id:
        console.print(f"[red]Malformed plan_id '{plan_id}' in idea.[/]")
        raise typer.Exit(1)

    period_id, slot_id = plan_id.split("/", 1)

    plan_path = cfg.plans_dir() / f"{period_id}.yaml"
    if plan_path.exists():
        plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        result = _find_slot(plan_data, slot_id)
        if result:
            list_key, idx, _ = result
            plan_data[list_key][idx].pop("idea_id", None)
            _save_plan(plan_path, plan_data)

    idea["status"] = "backlog"
    idea["plan_id"] = None
    idea["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_idea(idea_id, idea)

    console.print(f"[green]✓[/] Unlinked [bold]{idea_id}[/] from [bold]{plan_id}[/]")
