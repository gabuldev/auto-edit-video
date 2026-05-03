"""Content planning subcommand (monthly or weekly).

Generates a content plan (longs + shorts) using the same LLM backends as
the editing pipeline. Plans live outside the repo, in ~/.auto-edit/plans/,
so personal data stays off this opensource codebase.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from auto_edit import config as cfg
from auto_edit.runner import _extract_json, invoke_cursor

plan_app = typer.Typer(
    name="plan",
    help="Plan content (monthly or weekly) using your channel profile.",
    no_args_is_help=True,
)

console = Console()


# ── Period resolution ─────────────────────────────────────────────────────────

@dataclass
class Period:
    id: str           # "2026-06" or "2026-W23"
    kind: str         # "month" or "week"
    start: date
    end: date
    label: str        # human-readable

    def days(self) -> int:
        return (self.end - self.start).days + 1


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$", re.IGNORECASE)


def _resolve_period(month: Optional[str], week: Optional[str]) -> Period:
    if month and week:
        raise typer.BadParameter("Use either --month or --week, not both.")
    if not month and not week:
        raise typer.BadParameter("Provide --month YYYY-MM or --week YYYY-Www.")

    if month:
        alias = month.strip().lower()
        if alias in ("current", "now", "this"):
            t = date.today()
            y, mo = t.year, t.month
        elif alias == "next":
            t = date.today()
            y, mo = (t.year + (1 if t.month == 12 else 0), 1 if t.month == 12 else t.month + 1)
        else:
            m = _MONTH_RE.match(month)
            if not m:
                raise typer.BadParameter(
                    f"--month must be YYYY-MM (e.g. 2026-06), or 'current'/'next' (got {month!r})."
                )
            y, mo = int(m.group(1)), int(m.group(2))
        start = date(y, mo, 1)
        end = (date(y + (mo // 12), (mo % 12) + 1, 1) - timedelta(days=1)) if mo < 12 else date(y, 12, 31)
        label = start.strftime("%B %Y")
        return Period(id=f"{y}-{mo:02d}", kind="month", start=start, end=end, label=label)

    assert week
    alias = week.strip().lower()
    if alias in ("current", "now", "this"):
        y, wk, _ = date.today().isocalendar()
    elif alias == "next":
        y, wk, _ = (date.today() + timedelta(days=7)).isocalendar()
    else:
        w = _WEEK_RE.match(week)
        if not w:
            raise typer.BadParameter(
                f"--week must be YYYY-Www (e.g. 2026-W19), or 'current'/'next' (got {week!r})."
            )
        y, wk = int(w.group(1)), int(w.group(2))
    try:
        start = date.fromisocalendar(y, wk, 1)  # Monday
    except ValueError as e:
        raise typer.BadParameter(f"Invalid ISO week: {e}") from e
    end = start + timedelta(days=6)
    pid = f"{y}-W{wk:02d}"
    label = f"Week {wk}, {y} ({start.isoformat()} → {end.isoformat()})"
    return Period(id=pid, kind="week", start=start, end=end, label=label)


def _default_counts(kind: str) -> tuple[int, int]:
    """Defaults match Gabul's stated cadence: 3 longs + 6 shorts per week."""
    return (12, 24) if kind == "month" else (3, 6)


# ── LLM invocation ────────────────────────────────────────────────────────────

def _backend() -> str:
    raw = (os.environ.get("AUTO_EDIT_LLM") or "claude").lower()
    if raw in ("agent", "cursor"):
        return "cursor"
    return "claude"


def _repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _call_llm(prompt: str, timeout: int = 600) -> str:
    backend = _backend()
    if backend == "claude":
        if not shutil.which("claude"):
            raise RuntimeError("'claude' CLI not found on PATH")
        cmd = ["claude", "-p", prompt]
        model = os.environ.get("AUTO_EDIT_CLAUDE_MODEL")
        if model:
            cmd = ["claude", "--model", model, "-p", prompt]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"claude failed: {r.stderr or r.stdout}")
        return r.stdout

    with tempfile.TemporaryDirectory() as td:
        prompt_path = Path(td) / "prompt.txt"
        out_path = Path(td) / "out.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        rc = invoke_cursor(prompt_path, out_path, _repo_root())
        if rc != 0:
            raise RuntimeError(f"cursor agent failed (exit {rc})")
        raw = out_path.read_text(encoding="utf-8")
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict) and "result" in wrapper:
            return str(wrapper["result"])
    except json.JSONDecodeError:
        pass
    return raw


# ── Prompt assembly ───────────────────────────────────────────────────────────

def _summarize_inbox() -> str:
    """Describe the recorded-but-unedited inbox for the planner.

    Returns a markdown blob with one entry per subfolder: name, clip count,
    total size, last-modified date. Returns "" if no inbox is configured/empty.
    """
    env = os.environ.get("AUTO_EDIT_INBOX")
    if not env:
        return ""
    inbox = Path(env).expanduser()
    if not inbox.exists() or not inbox.is_dir():
        return ""
    rows: list[str] = []
    for d in sorted(inbox.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        vids = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _VIDEO_EXTS]
        if not vids:
            continue
        total_mb = sum(v.stat().st_size for v in vids) / 1_000_000
        last = max(v.stat().st_mtime for v in vids)
        last_str = datetime.fromtimestamp(last).strftime("%Y-%m-%d")
        rows.append(f"- `{d.name}` — {len(vids)} clip(s), {total_mb:.0f} MB, last recorded {last_str}")
    return "\n".join(rows)


def _build_prompt(period: Period, context: str, seed: str, n_longs: int, n_shorts: int, lang: Optional[str]) -> str:
    base = (_repo_root() / "agents" / "plan_month.md").read_text(encoding="utf-8")

    profile = cfg.load_profile() or "(no profile yet — drop .md files in ~/.auto-edit/profile/)"

    recent = []
    for p in cfg.load_recent_plans(limit=3):
        recent.append(f"### {p.stem}\n\n```yaml\n{p.read_text(encoding='utf-8')}\n```")
    recent_blob = "\n\n".join(recent) if recent else "(no previous plans)"

    lang_block = (
        f"# LANGUAGE\nEvery item MUST have language: {lang}. Override any history-based language inference.\n\n"
        if lang else ""
    )
    today = date.today()
    effective_start = max(period.start, today)
    inbox_blob = _summarize_inbox()
    inbox_section = (
        f"# INBOX (already recorded, waiting to be edited)\n"
        f"These are real folders the creator has shot. Each folder name reflects intent.\n"
        f"PREFER creating slots whose topics match these recordings (so they map 1:1 in ingest).\n"
        f"For each slot you create that corresponds to an inbox folder, set the slot `id` so the\n"
        f"creator can rename the folder to `{{period}}_{{id}}_...` later (e.g. `2026-W19_L2_bambulab`).\n\n"
        f"{inbox_blob}\n\n"
        if inbox_blob else ""
    )
    return (
        f"{base}\n\n"
        f"---\n\n"
        f"{lang_block}"
        f"# TODAY\n{today.isoformat()}\n"
        f"HARD RULE: every publish_at and record_by MUST be >= TODAY. Never schedule anything in the past.\n\n"
        f"# PERIOD\n"
        f"id: {period.id}\n"
        f"kind: {period.kind}\n"
        f"label: {period.label}\n"
        f"start: {period.start.isoformat()}\n"
        f"end: {period.end.isoformat()}\n"
        f"effective_start: {effective_start.isoformat()}  # use this as the real floor for scheduling\n"
        f"days: {period.days()}\n\n"
        f"# COUNTS\nlongs: {n_longs}\nshorts: {n_shorts}\n\n"
        f"# CONTEXT\n{context or '(none)'}\n\n"
        f"# SEED\n{seed or '(none)'}\n\n"
        f"{inbox_section}"
        f"# PROFILE\n{profile}\n\n"
        f"# RECENT_PLANS\n{recent_blob}\n"
    )


# ── Plan IO ───────────────────────────────────────────────────────────────────

def _plan_path(period_id: str) -> Path:
    return cfg.plans_dir() / f"{period_id}.yaml"


def _normalize(plan: dict, period: Period, context: str, seed: str) -> dict:
    plan["period"] = period.id
    plan["kind"] = period.kind
    plan["start"] = period.start.isoformat()
    plan["end"] = period.end.isoformat()
    plan["context"] = context
    plan["seed"] = seed
    plan["created_at"] = datetime.now().isoformat(timespec="seconds")
    for item in plan.get("longs", []):
        item.setdefault("status", "planned")
    for item in plan.get("shorts", []):
        item.setdefault("status", "planned")
    return plan


# ── Commands ──────────────────────────────────────────────────────────────────

@plan_app.command("new")
def plan_new(
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Month to plan, format YYYY-MM."),
    week: Optional[str] = typer.Option(None, "--week", "-w", help="ISO week to plan, format YYYY-Www (e.g. 2026-W23)."),
    context: str = typer.Option("", "--context", "-c", help="One-line focus for the period."),
    seed: str = typer.Option("", "--seed", "-s", help="Specific topics that must be included."),
    longs: Optional[int] = typer.Option(None, "--longs", help="Number of long videos (default: 12 month / 3 week)."),
    shorts: Optional[int] = typer.Option(None, "--shorts", help="Number of short videos (default: 24 month / 6 week)."),
    lang: Optional[str] = typer.Option(None, "--lang", "-l", help="Force language for ALL items (pt|en). Overrides profile."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing plan for this period."),
) -> None:
    """Generate a fresh content plan (monthly or weekly)."""
    cfg.ensure_dirs()
    period = _resolve_period(month, week)

    n_longs, n_shorts = _default_counts(period.kind)
    if longs is not None:
        n_longs = longs
    if shorts is not None:
        n_shorts = shorts

    out = _plan_path(period.id)
    if out.exists() and not force:
        console.print(f"[yellow]Plan already exists:[/] {out}")
        console.print("Use --force to overwrite, or `auto-edit plan edit` to modify.")
        raise typer.Exit(1)

    today = date.today()
    remaining = (period.end - today).days + 1
    if remaining <= 0:
        console.print(f"[red]The period {period.id} already ended ({period.end.isoformat()}).[/] Use a future period.")
        raise typer.Exit(1)
    if remaining < period.days() and remaining <= 2:
        console.print(
            f"[yellow]Warning:[/] only {remaining} day(s) left in {period.id}. "
            f"Consider `-w next` / `-m next` for more breathing room."
        )

    console.print(f"[cyan]Generating {period.kind} plan {period.id}[/] ({n_longs} longs + {n_shorts} shorts)…")
    prompt = _build_prompt(period, context, seed, n_longs, n_shorts, lang)

    try:
        raw = _call_llm(prompt)
    except Exception as e:
        console.print(f"[red]LLM call failed:[/] {e}")
        raise typer.Exit(1)

    plan = _extract_json(raw)
    if not plan:
        console.print("[red]Could not parse JSON from LLM output. Raw output:[/]")
        console.print(raw[:2000])
        raise typer.Exit(1)

    plan = _normalize(plan, period, context, seed)

    out.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Plan saved:[/] {out}")
    flag = f"-m {period.id}" if period.kind == "month" else f"-w {period.id}"
    console.print(f"Run `auto-edit plan show {flag}` to view it.")


@plan_app.command("show")
def plan_show(
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Month plan to show, YYYY-MM."),
    week: Optional[str] = typer.Option(None, "--week", "-w", help="Week plan to show, YYYY-Www."),
    lang: Optional[str] = typer.Option(None, "--lang", "-l", help="Filter by language (pt|en)."),
    fmt: Optional[str] = typer.Option(None, "--format", help="Filter by format (tutorial|opinion|series)."),
) -> None:
    """Show a plan as a table."""
    if not month and not week:
        week = "current"
    period = _resolve_period(month, week)
    path = _plan_path(period.id)
    if not path.exists():
        flag = f"-m {period.id}" if period.kind == "month" else f"-w {period.id}"
        console.print(f"[red]No plan found for {period.id}.[/] Run `auto-edit plan new {flag}` first.")
        raise typer.Exit(1)

    plan = yaml.safe_load(path.read_text(encoding="utf-8"))

    def _match(item: dict) -> bool:
        if lang and item.get("language") != lang:
            return False
        if fmt and item.get("format") != fmt:
            return False
        return True

    header = plan.get("period") or plan.get("month") or period.id
    console.print(f"\n[bold]{header}[/] — {plan.get('theme', '')}")
    if plan.get("rationale"):
        console.print(f"[dim]{plan['rationale']}[/]\n")

    def _render(title: str, items: list[dict], extra_cols: list[str]) -> None:
        rows = [i for i in items if _match(i)]
        if not rows:
            return
        t = Table(title=title, show_lines=False)
        t.add_column("ID", style="cyan", no_wrap=True)
        t.add_column("Topic")
        t.add_column("Lang", no_wrap=True)
        t.add_column("Format", no_wrap=True)
        for col in extra_cols:
            t.add_column(col, no_wrap=True)
        t.add_column("Status", no_wrap=True)
        for it in rows:
            base = [it.get("id", ""), it.get("topic", ""), it.get("language", ""), it.get("format", "")]
            extras = [str(it.get(c.lower().replace(" ", "_"), "") or "") for c in extra_cols]
            t.add_row(*base, *extras, it.get("status", ""))
        console.print(t)

    _render("Longs", plan.get("longs", []), ["Record By", "Publish At"])
    _render("Shorts", plan.get("shorts", []), ["Parent Long", "Publish At"])


@plan_app.command("edit")
def plan_edit(
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Month plan, YYYY-MM."),
    week: Optional[str] = typer.Option(None, "--week", "-w", help="Week plan, YYYY-Www."),
) -> None:
    """Open the plan yaml in $EDITOR."""
    if not month and not week:
        week = "current"
    period = _resolve_period(month, week)
    path = _plan_path(period.id)
    if not path.exists():
        console.print(f"[red]No plan found for {period.id}.[/]")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    subprocess.call([*shlex.split(editor), str(path)])


@plan_app.command("list")
def plan_list() -> None:
    """List every plan in ~/.auto-edit/plans/."""
    cfg.ensure_dirs()
    plans = sorted(cfg.plans_dir().glob("*.yaml"))
    if not plans:
        console.print("[dim]No plans yet. Run `auto-edit plan new -m YYYY-MM` or `-w YYYY-Www`.[/]")
        return
    for p in plans:
        kind = "week " if "-W" in p.stem else "month"
        console.print(f"  [{kind}] {p.stem}  [dim]{p}[/]")


@plan_app.command("path")
def plan_path() -> None:
    """Print the auto-edit home directory (where plans + profile live)."""
    cfg.ensure_dirs()
    console.print(str(cfg.home_dir()))


# ── status ────────────────────────────────────────────────────────────────────

_STATUS_STYLE = {
    "planned": "dim",
    "recorded": "yellow",
    "edited": "cyan",
    "published": "green",
}


def _parse_iso(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@plan_app.command("status")
def plan_status(
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Month plan, YYYY-MM."),
    week: Optional[str] = typer.Option(None, "--week", "-w", help="Week plan, YYYY-Www."),
    all_plans: bool = typer.Option(False, "--all", "-a", help="Show every plan on disk."),
) -> None:
    """Show what's recorded / edited / late / pending across plans."""
    cfg.ensure_dirs()
    by_pid = workspaces_by_plan_id()
    today = date.today()

    if all_plans:
        plans = _all_plans()
        if not plans:
            console.print("[dim]No plans yet.[/]")
            return
    else:
        if not month and not week:
            week = "current"
        period = _resolve_period(month, week)
        path = _plan_path(period.id)
        if not path.exists():
            console.print(
                f"[yellow]No plan found for {period.id}.[/] "
                f"Run `auto-edit plan new -w {period.id}` or pass --all to see existing plans."
            )
            raise typer.Exit(1)
        plans = [(period.id, _load_plan_file(path), path)]

    for period_id, plan, _path in plans:
        items = _items_in_plan(plan)
        if not items:
            continue

        console.print(f"\n[bold]{period_id}[/]  [dim]{plan.get('theme', '')}[/]")

        t = Table(show_lines=False)
        t.add_column("ID", style="cyan", no_wrap=True)
        t.add_column("Kind", no_wrap=True)
        t.add_column("Topic")
        t.add_column("Publish", no_wrap=True)
        t.add_column("Status", no_wrap=True)
        t.add_column("Workspace", no_wrap=True)

        late_count = 0
        for it in items:
            full_id = f"{period_id}/{it.get('id', '')}"
            wss = by_pid.get(full_id, [])
            status = derive_status(it, wss)
            pub = it.get("publish_at", "")
            pub_date = _parse_iso(pub)

            late = (
                pub_date is not None
                and pub_date < today
                and status not in ("edited", "published")
            )
            if late:
                late_count += 1

            style = _STATUS_STYLE.get(status, "white")
            status_label = f"[{style}]{status}[/]" + (" [red]⚠[/]" if late else "")

            ws_label = ""
            if wss:
                ws_label = wss[0][0].name
                if len(wss) > 1:
                    ws_label += f" (+{len(wss)-1})"

            t.add_row(
                it.get("id", ""),
                it.get("_kind", ""),
                it.get("topic", ""),
                pub,
                status_label,
                ws_label,
            )

        console.print(t)

        # summary line
        counts: dict[str, int] = {}
        for it in items:
            full_id = f"{period_id}/{it.get('id', '')}"
            counts[derive_status(it, by_pid.get(full_id, []))] = counts.get(
                derive_status(it, by_pid.get(full_id, [])), 0
            ) + 1
        summary = "  ".join(
            f"[{_STATUS_STYLE.get(k, 'white')}]{k}: {v}[/]" for k, v in counts.items()
        )
        late_blob = f"  [red]late: {late_count}[/]" if late_count else ""
        console.print(f"  {summary}{late_blob}")


# ── interactive picker (used by short/long when --plan-id is omitted) ────────

def resolve_plan_id_arg(arg: Optional[str]) -> Optional[str]:
    """Normalize a user-supplied --plan-id value.

    Accepts: 'PERIOD/ITEM' (full id), or short 'S2'/'L1' (must be unambiguous
    across all pending items). Returns canonical 'PERIOD/ITEM' or None.

    Special values: 'none', 'skip' → None.
    """
    if not arg:
        return None
    if arg.strip().lower() in ("none", "skip", "no"):
        return None
    if "/" in arg:
        period, item = parse_plan_id(arg)
        return f"{period}/{item}"
    # short form — find unambiguously
    matches = [it for it in pending_items() if it.get("id") == arg]
    if not matches:
        # also search non-pending (already-recorded items) so resume flows work
        for period, plan, _ in _all_plans():
            for it in _items_in_plan(plan):
                if it.get("id") == arg:
                    matches.append({**it, "_period": period, "_full_id": f"{period}/{arg}"})
    if len(matches) == 1:
        return matches[0]["_full_id"]
    if not matches:
        raise typer.BadParameter(f"No plan item with id {arg!r}.")
    options = ", ".join(m["_full_id"] for m in matches)
    raise typer.BadParameter(
        f"Ambiguous --plan-id {arg!r} — exists in: {options}. Use full id 'PERIOD/ITEM'."
    )


_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}


def _video_duration(video: Path) -> Optional[str]:
    """Return formatted duration like '2:35' via ffprobe, or None on failure."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, timeout=10,
        )
        secs = float(r.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _open_preview(video: Path) -> None:
    """Open the video in the OS default viewer (macOS QuickLook via `open -a Preview`)."""
    try:
        if shutil.which("qlmanage"):
            subprocess.Popen(["qlmanage", "-p", str(video)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("open"):
            subprocess.Popen(["open", str(video)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            console.print("[yellow]No preview tool found (need `open` or `qlmanage`).[/]")
    except OSError as e:
        console.print(f"[yellow]Preview failed: {e}[/]")


def _video_files(folder: Path, recursive: bool = True) -> list[Path]:
    it = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        [p for p in it if p.is_file() and p.suffix.lower() in _VIDEO_EXTS],
        key=lambda p: p.stat().st_mtime,
    )


def _suggest_for(video: Path, candidates: list[dict]) -> Optional[int]:
    """Heuristic: suggest the candidate whose record_by is closest to video mtime."""
    if not candidates:
        return None
    mtime = datetime.fromtimestamp(video.stat().st_mtime).date()
    scored = []
    for i, it in enumerate(candidates):
        ref = _parse_iso(it.get("record_by") or it.get("publish_at") or "")
        if not ref:
            continue
        scored.append((abs((ref - mtime).days), i))
    if not scored:
        return None
    scored.sort()
    return scored[0][1]


# Folder name patterns we try to auto-match to a plan slot.
# Examples accepted:
#   2026-W19_S2                 → 2026-W19/S2
#   2026-W19-S2                 → 2026-W19/S2
#   2026-W19_S2_bambulab        → 2026-W19/S2
#   2026-05_L1                  → 2026-05/L1
#   S2                          → resolved if unambiguous across pending items
#   L1_setup                    → resolved if unambiguous
_FOLDER_FULL_RE = re.compile(
    r"^(?P<period>\d{4}-(?:W\d{1,2}|\d{2}))[_\-/](?P<item>[SLsl]\d+)(?:[_\-].*)?$"
)
_FOLDER_SHORT_RE = re.compile(r"^(?P<item>[SLsl]\d+)(?:[_\-].*)?$")


def _infer_plan_id_from_folder_name(name: str) -> Optional[str]:
    """Try to extract a canonical 'PERIOD/ITEM' from a folder name. Returns None if no match."""
    m = _FOLDER_FULL_RE.match(name)
    if m:
        period = m.group("period")
        item = m.group("item").upper()
        # Normalize week number to 2 digits
        if "W" in period:
            y, w = period.split("-W")
            period = f"{y}-W{int(w):02d}"
        return f"{period}/{item}"
    m = _FOLDER_SHORT_RE.match(name)
    if m:
        item = m.group("item").upper()
        try:
            return resolve_plan_id_arg(item)
        except typer.BadParameter:
            return None
    return None


def _video_subfolders(root: Path) -> list[Path]:
    """Return subfolders of `root` that directly contain at least one video file."""
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if any(p.suffix.lower() in _VIDEO_EXTS for p in d.iterdir() if p.is_file()):
            out.append(d)
    return out


def _folder_summary(folder: Path) -> str:
    vids = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _VIDEO_EXTS]
    if not vids:
        return "(empty)"
    total_mb = sum(v.stat().st_size for v in vids) / 1_000_000
    last = max(v.stat().st_mtime for v in vids)
    last_str = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M")
    return f"{len(vids)} clip(s), {total_mb:.0f} MB, latest {last_str}"


@plan_app.command("ingest")
def plan_ingest(
    folder: Optional[Path] = typer.Argument(None, help="Inbox folder containing per-topic subfolders. Defaults to $AUTO_EDIT_INBOX."),
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Restrict to a month plan, YYYY-MM."),
    week: Optional[str] = typer.Option(None, "--week", "-w", help="Restrict to a week plan, YYYY-Www."),
    run: bool = typer.Option(False, "--run", help="After pairing, kick off the editing pipeline for each linked folder."),
) -> None:
    """Pair pending plan slots with subfolders of recorded clips.

    Flow: shows pending slots → you pick one → shows inbox subfolders → you pick one →
    that folder is linked to that slot. Repeat until you quit.
    """
    if folder is None:
        env = os.environ.get("AUTO_EDIT_INBOX")
        if not env:
            console.print(
                "[red]No folder given and $AUTO_EDIT_INBOX is not set.[/]\n"
                "Set it in your shell, e.g. `export AUTO_EDIT_INBOX=/Volumes/XPG/Movies/precisa-editar`."
            )
            raise typer.Exit(1)
        folder = Path(env).expanduser()
    if not folder.exists() or not folder.is_dir():
        console.print(f"[red]Not a folder:[/] {folder}")
        raise typer.Exit(1)

    if not week and not month:
        week = "current"
    period_filter = _resolve_period(month, week).id

    pairings: list[tuple[Path, dict]] = []
    used_folders: set[Path] = set()

    # ── Auto-detect: match folders to slots by (a) name pattern, (b) source_folder field
    pending_now = pending_items(period_filter=period_filter)
    pending_by_id = {it["_full_id"]: it for it in pending_now}
    pending_by_source = {
        it["source_folder"]: it
        for it in pending_now
        if it.get("source_folder")
    }
    auto_pairs: list[tuple[Path, dict, str]] = []  # (folder, item, reason)
    for d in _video_subfolders(folder):
        # (a) name pattern like 2026-W19_S2
        guess = _infer_plan_id_from_folder_name(d.name)
        if guess:
            period, _ = parse_plan_id(guess)
            if (not period_filter or period == period_filter):
                item = pending_by_id.get(guess)
                if item:
                    auto_pairs.append((d, item, "folder name"))
                    continue
        # (b) folder name matches a slot's source_folder
        item = pending_by_source.get(d.name)
        if item:
            auto_pairs.append((d, item, "source_folder"))

    if auto_pairs:
        console.print(f"\n[bold green]Auto-detected {len(auto_pairs)} pairing(s):[/]")
        for d, it, reason in auto_pairs:
            console.print(
                f"  [green]✓[/] {d.name}  →  {it['_full_id']} [{it['_kind']}]  "
                f"{it.get('topic','')}  [dim](via {reason})[/]"
            )
        confirm = typer.prompt("Accept these? [Y/n/r=review one by one]", default="y").strip().lower()
        if confirm in ("y", "yes", ""):
            for d, it, _ in auto_pairs:
                pairings.append((d, it))
                used_folders.add(d)
        elif confirm in ("r", "review"):
            for d, it, _ in auto_pairs:
                if typer.confirm(f"Pair {d.name} → {it['_full_id']}?", default=True):
                    pairings.append((d, it))
                    used_folders.add(d)
        # 'n' or anything else: drop them, fall through to interactive

    while True:
        slots = [it for it in pending_items(period_filter=period_filter)
                 if not any(it["_full_id"] == p[1]["_full_id"] for p in pairings)]

        if not slots:
            console.print(f"\n[green]All slots in {period_filter} are paired or filled.[/]")
            break

        console.print(f"\n[bold]Pending slots in {period_filter}[/]")
        for i, it in enumerate(slots, 1):
            console.print(
                f"  [cyan]{i:>2}[/]. [dim]{it['id']}[/] [{it['_kind']:<5}] "
                f"{it.get('topic', '')}  [dim](publish {it.get('publish_at', '?')})[/]"
            )
        console.print("  [dim] q. quit (review what's paired so far)[/]")

        slot_choice = typer.prompt("Pick a slot", default="q").strip().lower()
        if slot_choice in ("q", "quit", ""):
            break
        try:
            sidx = int(slot_choice) - 1
            if not (0 <= sidx < len(slots)):
                raise ValueError
        except ValueError:
            console.print("[yellow]Invalid choice — try again.[/]")
            continue

        chosen_slot = slots[sidx]

        # Now pick a folder for this slot
        subfolders = [d for d in _video_subfolders(folder) if d not in used_folders]
        if not subfolders:
            console.print(f"[yellow]No subfolders with videos available in {folder}.[/]")
            console.print("[dim]Either drop a folder of clips into the inbox or quit.[/]")
            continue

        while True:  # folder-pick loop (allows preview)
            console.print(f"\n[bold]Folders in[/] [dim]{folder}[/]")
            console.print(f"[dim]Picking for: {chosen_slot['_full_id']} — {chosen_slot.get('topic','')}[/]")
            for i, d in enumerate(subfolders, 1):
                console.print(f"  [cyan]{i:>2}[/]. {d.name}  [dim]({_folder_summary(d)})[/]")
            console.print("  [dim] p N. preview Nth folder (opens first clip)    b. back to slots    s. skip[/]")

            raw = typer.prompt("Pick a folder", default="b").strip().lower()
            if raw in ("b", "back", ""):
                folder_choice = None
                break
            if raw in ("s", "skip"):
                folder_choice = "__skip__"
                break
            if raw.startswith("p"):
                rest = raw[1:].strip()
                try:
                    pidx = int(rest) - 1
                    target = subfolders[pidx]
                    first_clip = next(
                        (p for p in sorted(target.iterdir())
                         if p.is_file() and p.suffix.lower() in _VIDEO_EXTS),
                        None,
                    )
                    if first_clip:
                        _open_preview(first_clip)
                    else:
                        console.print("[yellow]Empty folder.[/]")
                except (ValueError, IndexError):
                    console.print("[yellow]Use `p N` (e.g. `p 2`) to preview folder N.[/]")
                continue
            try:
                fidx = int(raw) - 1
                if not (0 <= fidx < len(subfolders)):
                    raise ValueError
                folder_choice = subfolders[fidx]
                break
            except ValueError:
                console.print("[yellow]Invalid choice — try again.[/]")
                continue

        if folder_choice is None:
            continue  # back to slot picker
        if folder_choice == "__skip__":
            continue

        pairings.append((folder_choice, chosen_slot))
        used_folders.add(folder_choice)
        console.print(
            f"  [green]✓[/] {folder_choice.name}  →  {chosen_slot['_full_id']} "
            f"({chosen_slot['_kind']})"
        )

    if not pairings:
        console.print("\n[dim]No pairings made.[/]")
        return

    console.print(f"\n[bold]{len(pairings)} pairing(s) ready:[/]")
    for f, it in pairings:
        console.print(f"  {f.name}  →  {it['_full_id']}  ({it['_kind']})")

    if not run:
        console.print("\n[dim]Re-run with --run to start pipelines, or run them manually:[/]")
        for f, it in pairings:
            console.print(
                f"  auto-edit merge '{f}' --type {it['_kind']} "
                f"--name {it['_full_id'].replace('/','_')} --plan-id {it['_full_id']}"
            )
        return

    for f, it in pairings:
        name = it["_full_id"].replace("/", "_")
        cmd = ["auto-edit", "merge", str(f),
               "--type", it["_kind"], "--name", name,
               "--plan-id", it["_full_id"], "--no-plan-prompt"]
        if it.get("topic"):
            cmd += ["--context", it["topic"]]
        console.print(f"\n[cyan]→[/] {' '.join(cmd)}")
        rc = subprocess.call(cmd)
        if rc != 0:
            console.print(f"[red]Pipeline exited {rc} for {f.name} — stopping.[/]")
            raise typer.Exit(rc)


def prompt_for_plan_id() -> Optional[str]:
    """Show pending items across all plans, return chosen 'PERIOD/ITEM' or None."""
    items = pending_items()
    if not items:
        return None

    console.print("\n[bold]Pending plan items[/] (no workspace yet):")
    for i, it in enumerate(items, 1):
        console.print(
            f"  [cyan]{i:>2}[/]. [dim]{it['_period']}/{it['id']}[/] "
            f"[{it['_kind']:<5}] {it.get('topic','')}"
        )
    console.print("  [dim] s. skip (don't link to any plan)[/]")
    choice = typer.prompt("Pick a number", default="s")
    if choice.strip().lower() in ("s", "skip", ""):
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx]["_full_id"]
    except ValueError:
        pass
    console.print("[yellow]Invalid choice — skipping plan link.[/]")
    return None


# ── Cross-plan helpers (used by status / ingest / cli interactive picker) ────

def _load_plan_file(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _all_plans() -> list[tuple[str, dict, Path]]:
    """Return [(period_id, plan_dict, path)] for every plan on disk."""
    cfg.ensure_dirs()
    out = []
    for p in sorted(cfg.plans_dir().glob("*.yaml")):
        plan = _load_plan_file(p)
        period = plan.get("period") or plan.get("month") or p.stem
        out.append((period, plan, p))
    return out


def _items_in_plan(plan: dict) -> list[dict]:
    """Flatten longs + shorts, tagging each with `_kind`."""
    out = []
    for it in plan.get("longs", []):
        out.append({**it, "_kind": "long"})
    for it in plan.get("shorts", []):
        out.append({**it, "_kind": "short"})
    return out


def parse_plan_id(plan_id: str) -> tuple[str, str]:
    """Split "2026-W19/S2" into ("2026-W19", "S2"). Raises if malformed."""
    if "/" not in plan_id:
        raise ValueError(f"plan_id must be 'PERIOD/ITEM' (got {plan_id!r})")
    period, item = plan_id.split("/", 1)
    return period.strip(), item.strip()


def find_item(plan_id: str) -> Optional[dict]:
    """Look up a plan item by full id 'PERIOD/ITEM'. Returns the item dict or None."""
    period, item_id = parse_plan_id(plan_id)
    path = cfg.plans_dir() / f"{period}.yaml"
    if not path.exists():
        return None
    plan = _load_plan_file(path)
    for it in _items_in_plan(plan):
        if it.get("id") == item_id:
            return {**it, "_period": period}
    return None


def find_workspaces() -> list[tuple[Path, dict]]:
    """Scan workspace/ for pipelines. Returns [(workspace_path, pipeline_dict)]."""
    repo_root = _repo_root()
    ws_root = repo_root / "workspace"
    if not ws_root.exists():
        return []
    out = []
    for d in sorted(ws_root.iterdir()):
        if not d.is_dir():
            continue
        pj = d / "pipeline.json"
        if not pj.exists():
            continue
        try:
            out.append((d, json.loads(pj.read_text())))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def workspaces_by_plan_id() -> dict[str, list[tuple[Path, dict]]]:
    """Group workspaces by their plan_id. Workspaces without one are skipped."""
    grouped: dict[str, list[tuple[Path, dict]]] = {}
    for ws, pj in find_workspaces():
        pid = pj.get("plan_id")
        if not pid:
            continue
        grouped.setdefault(pid, []).append((ws, pj))
    return grouped


def derive_status(item: dict, workspaces: list[tuple[Path, dict]]) -> str:
    """Compute status for a plan item from its associated workspaces.

    Priority: published (manual yaml status) > edited > recorded > planned.
    A workspace is considered 'edited' only when current_stage == 'done', or
    when every non-'done' canonical stage is complete or skipped.
    """
    if item.get("status") == "published":
        return "published"
    if not workspaces:
        return "planned"
    # Lazy import to avoid circular deps
    from auto_edit.pipeline import STAGES

    canonical = [s for s in STAGES if s != "done"]
    for _, pj in workspaces:
        if pj.get("current_stage") == "done":
            return "edited"
        stages = pj.get("stages", {})
        # Every canonical stage must be present and complete/skip.
        if all(stages.get(name, {}).get("status") in ("complete", "skip") for name in canonical):
            return "edited"
    return "recorded"


def pending_items(period_filter: Optional[str] = None) -> list[dict]:
    """Return every plan item whose derived status is 'planned' (no workspace yet).

    If period_filter is given (e.g. '2026-W19'), restrict to that plan.
    """
    by_pid = workspaces_by_plan_id()
    out: list[dict] = []
    for period, plan, _ in _all_plans():
        if period_filter and period != period_filter:
            continue
        for it in _items_in_plan(plan):
            full_id = f"{period}/{it.get('id', '')}"
            wss = by_pid.get(full_id, [])
            if derive_status(it, wss) == "planned":
                out.append({**it, "_period": period, "_full_id": full_id})
    return out
