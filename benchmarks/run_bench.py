"""Planner benchmark — our transcript-reading planner vs Gemini watching the video.

Both arms get the same recording, the same editorial brief and the same
downstream: `auto_edit.snap` repairs boundaries, `tools/executor.py` cuts with
identical settings. The only thing that differs is who decides where to cut,
and what it perceived when deciding.

    python benchmarks/run_bench.py --video bruto.mp4 --context "review de teclado"

Produces:
    workspace/bench_<slug>_ours/     our pipeline through review (dry-run)
    workspace/bench_<slug>_gemini/   same transcript, plan from Gemini
    benchmarks/reports/<slug>/       report.md, both plans, metrics.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from auto_edit import pipeline as pl  # noqa: E402
from auto_edit.workspace import workspace_root  # noqa: E402
from benchmarks import metrics  # noqa: E402
from benchmarks.gemini_plan import DEFAULT_MODEL, plan_with_gemini  # noqa: E402

PYTHON = sys.executable
ARMS = ("nosso", "gemini")


def run(cmd: list[str], env: dict | None = None) -> float:
    """Run a step, streaming its output. Returns wall time in seconds."""
    print(f"\n$ {' '.join(str(c) for c in cmd)}\n", flush=True)
    started = time.time()
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
    if result.returncode != 0:
        raise SystemExit(f"passo falhou (rc={result.returncode}): {' '.join(str(c) for c in cmd)}")
    return time.time() - started


def make_workspace(path: Path, video: Path, context: str, language: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    pl.init(
        workspace=path,
        video_path=video,
        video_type="long",
        context=context,
        language=language,
    )
    return path


def arm_ours(video: Path, context: str, slug: str, language: str) -> tuple[Path, float]:
    """Our pipeline up to (and including) review — where --dry-run stops."""
    ws = workspace_root() / f"bench_{slug}_ours"
    if (ws / "reviewed_plan.json").exists():
        print(f"[bench] reaproveitando {ws} (já tem plano)")
        return ws, 0.0

    make_workspace(ws, video, context, language)
    env = os.environ.copy()
    env["AUTO_EDIT_DRY_RUN"] = "1"
    env["AUTO_EDIT_LANGUAGE"] = language
    env["PYTHON"] = PYTHON
    return ws, run(["bash", str(REPO_ROOT / "ralph.sh"), str(ws)], env=env)


def arm_gemini(
    video: Path, context: str, slug: str, language: str, model: str, transcription: Path
) -> tuple[Path, dict]:
    """Same workspace shape, but the plan comes from Gemini watching the file."""
    ws = workspace_root() / f"bench_{slug}_gemini"
    make_workspace(ws, video, context, language)
    # The executor needs duration + energy map; the Gemini arm never reads it,
    # but everything downstream must be identical for the comparison to mean
    # anything.
    shutil.copy2(transcription, ws / "transcription.json")

    duration = json.loads(transcription.read_text(encoding="utf-8")).get("duration")
    report = plan_with_gemini(ws, video, model=model, context=context, duration=duration)
    return ws, report


def snap_and_measure(ws: Path, words: list[dict]) -> dict:
    """Apply the shared boundary repair, reporting how much each plan needed it."""
    raw = ws / "reviewed_plan.raw.json"
    if not raw.exists():
        shutil.copy2(ws / "reviewed_plan.json", raw)

    def clipped(path: Path) -> int:
        plan = json.loads(path.read_text(encoding="utf-8"))
        return metrics.words_clipped(words, metrics.intervals(plan, "cuts"))

    before = clipped(raw)
    run([PYTHON, "-m", "auto_edit.snap", str(ws)])
    return {"before": before, "after": clipped(ws / "reviewed_plan.json")}


def rationale(ws: Path) -> str | None:
    try:
        plan = json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return plan.get("target_rationale")


def our_tokens(ws: Path) -> int | None:
    try:
        stats = json.loads((ws / "token_stats.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stats.get("total_estimated_tokens")


def write_report(
    video: Path, context: str, model: str, report: dict, extra: dict, out_dir: Path
) -> Path:
    lines = [
        f"# Benchmark de planner — {video.name}",
        "",
        f"- **Contexto:** {context or '—'}",
        "- **Nosso:** `agents/planner_long.md` lendo `transcription.json` (Whisper)",
        f"- **Gemini:** `{model}` assistindo o arquivo, mesmo brief",
        "- **Downstream idêntico:** `auto_edit.snap` + `tools/executor.py`",
        "",
        "## Números",
        "",
        metrics.render(report),
        "",
        "## Reparo mecânico (snap)",
        "",
        "Palavras cortadas ao meio pelo plano, antes e depois do snap:",
        "",
        "| braço | antes | depois |",
        "|---|---|---|",
    ]
    for name, stat in extra.get("snap", {}).items():
        lines.append(f"| {name} | {stat['before']} | {stat['after']} |")

    lines += ["", "## Custo e tempo", "", "| braço | tempo | tokens |", "|---|---|---|"]
    for name, cost in extra.get("cost", {}).items():
        lines.append(f"| {name} | {cost.get('seconds', '—')}s | {cost.get('tokens') or '—'} |")

    lines += ["", "## O que cada um disse que ia fazer", ""]
    for name, text in extra.get("rationale", {}).items():
        lines += [f"**{name}:** {text or '—'}", ""]

    if extra.get("outputs"):
        lines += ["## Arquivos", ""]
        for name, path in extra["outputs"].items():
            lines.append(f"- **{name}:** `{path}`")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps({"report": report, **extra}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--context", default="")
    ap.add_argument("--language", default="pt")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--slug", default=None, help="nome da pasta do relatório (default: nome do vídeo)")
    ap.add_argument("--skip-render", action="store_true", help="compara só os planos, sem FFmpeg")
    args = ap.parse_args()

    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"vídeo não encontrado: {video}")
    slug = args.slug or video.stem.replace(" ", "_")[:40]

    print(f"\n=== Braço A — nosso planner ({video.name}) ===")
    ws_ours, ours_seconds = arm_ours(video, args.context, slug, args.language)
    transcription = ws_ours / "transcription.json"
    if not transcription.exists():
        raise SystemExit(f"braço A não produziu transcription.json em {ws_ours}")

    print("\n=== Braço B — Gemini assistindo o vídeo ===")
    ws_gem, gemini_report = arm_gemini(
        video, args.context, slug, args.language, args.model, transcription
    )

    words = json.loads(transcription.read_text(encoding="utf-8")).get("words") or []
    workspaces = {"nosso": ws_ours, "gemini": ws_gem}
    snap_stats = {name: snap_and_measure(ws, words) for name, ws in workspaces.items()}

    report = metrics.compare(
        transcription, {name: ws / "reviewed_plan.json" for name, ws in workspaces.items()}
    )

    outputs = {}
    if not args.skip_render:
        print("\n=== Renderizando os dois cortes ===")
        for name, ws in workspaces.items():
            run([PYTHON, str(REPO_ROOT / "tools" / "executor.py"), str(ws)])
            edited = ws / "edited_video.mp4"
            outputs[name] = str(edited) if edited.exists() else "(não gerado)"

    out_dir = REPO_ROOT / "benchmarks" / "reports" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, ws in workspaces.items():
        shutil.copy2(ws / "reviewed_plan.json", out_dir / f"plan_{name}.json")

    extra = {
        "snap": snap_stats,
        "cost": {
            "nosso": {"seconds": round(ours_seconds, 1), "tokens": our_tokens(ws_ours)},
            "gemini": {
                "seconds": gemini_report.get("seconds"),
                "tokens": gemini_report.get("total_tokens"),
            },
        },
        "rationale": {name: rationale(ws) for name, ws in workspaces.items()},
        "outputs": outputs,
    }
    path = write_report(video, args.context, args.model, report, extra, out_dir)

    print("\n" + metrics.render(report))
    print(f"\n[bench] relatório: {path}")


if __name__ == "__main__":
    main()
