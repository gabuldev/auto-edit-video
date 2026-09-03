"""Benchmark arm B — let Gemini watch the video and produce the cut plan.

Same editorial brief as our own planner (`agents/planner_long.md`), same output
schema. The only variables are the model and what it perceives: our planner
reads a Whisper transcript, this one watches and listens to the actual file.
That is the whole point of the comparison — everything downstream (snap,
executor, encoder settings) stays identical.

Usage:
    python benchmarks/gemini_plan.py <workspace> --video <file> [--model ...]

Writes <workspace>/reviewed_plan.json (our schema) plus a run report in
<workspace>/gemini_run.json (model, latency, token usage).

Requires GEMINI_API_KEY (or GOOGLE_API_KEY) and `pip install google-genai`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Models the agentic video understanding announcement covers.
DEFAULT_MODEL = "gemini-3.7-flash"

ADAPTER_HEADER = """You are planning the edit of a long-form video. The full video file is
attached: watch and listen to it directly. You have no transcript — use the
footage itself (frames, speech, silence, what is on screen) to decide.

Everything below is the exact brief our own editor agent works from. Follow it
as written, with one substitution: where it refers to the transcription, the
word-level timestamps or the energy map, use what you observe in the video.
Being able to SEE the video is your advantage — a lost take, a frozen screen,
the speaker leaving frame or fumbling with the camera are all cuttable and none
of them show up in a transcript.

All timestamps you emit must be seconds from the start of the video, as numbers
with decimals (e.g. 128.4), never "MM:SS" strings.

---

"""

ADAPTER_FOOTER = """

---

Reminder: respond with ONLY the JSON object described above. Timestamps in
seconds as decimal numbers. The video duration is {duration:.1f}s — no boundary
may exceed it.
"""


def build_prompt(brief_path: Path, context: str, duration: float) -> str:
    brief = brief_path.read_text(encoding="utf-8")
    context_block = f"\n\n## Context for this video\n\n{context}\n" if context else ""
    return ADAPTER_HEADER + brief + context_block + ADAPTER_FOOTER.format(duration=duration)


def upload(client, video: Path, poll: float = 5.0, timeout: float = 900.0):
    """Upload to the Files API and wait until the video is ACTIVE."""
    print(f"[gemini] uploading {video.name} ({video.stat().st_size / 1e6:.1f} MB)…")
    handle = client.files.upload(file=str(video))
    deadline = time.time() + timeout
    while getattr(handle.state, "name", str(handle.state)) == "PROCESSING":
        if time.time() > deadline:
            raise TimeoutError(f"file stuck in PROCESSING after {timeout:.0f}s")
        time.sleep(poll)
        handle = client.files.get(name=handle.name)
    state = getattr(handle.state, "name", str(handle.state))
    if state != "ACTIVE":
        raise RuntimeError(f"upload finished in state {state}")
    print(f"[gemini] file ready: {handle.name}")
    return handle


def extract_json(text: str) -> dict:
    """Parse the model's answer, tolerating markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in response: {text[:300]}")
    return json.loads(cleaned[start : end + 1])


def normalize(plan: dict, duration: float) -> dict:
    """Clamp to the timeline and rebuild kept_segments from the cuts.

    The cuts are what the model actually decided; kept_segments is arithmetic.
    Rebuilding them here removes a whole class of inconsistency that would
    otherwise show up as a difference in editorial judgment when it is really
    just bookkeeping.
    """
    cuts = []
    for cut in plan.get("cuts") or []:
        try:
            start, end = float(cut["start"]), float(cut["end"])
        except (KeyError, TypeError, ValueError):
            continue
        start, end = max(0.0, min(start, duration)), max(0.0, min(end, duration))
        if end - start <= 0.01:
            continue
        cuts.append({**cut, "start": round(start, 3), "end": round(end, 3)})
    cuts.sort(key=lambda c: c["start"])

    merged: list[dict] = []
    for cut in cuts:
        if merged and cut["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], cut["end"])
        else:
            merged.append(dict(cut))

    kept, cursor = [], 0.0
    for cut in merged:
        if cut["start"] - cursor > 0.05:
            kept.append({"start": round(cursor, 3), "end": round(cut["start"], 3)})
        cursor = cut["end"]
    if duration - cursor > 0.05:
        kept.append({"start": round(cursor, 3), "end": round(duration, 3)})

    # Carry the model's own summaries onto the segments they overlap.
    for seg in kept:
        for original in plan.get("kept_segments") or []:
            try:
                o_start, o_end = float(original["start"]), float(original["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if o_end > seg["start"] and o_start < seg["end"] and original.get("summary"):
                seg["summary"] = original["summary"]
                break

    return {
        "target_rationale": plan.get("target_rationale"),
        "dropped_blocks": plan.get("dropped_blocks") or [],
        "cuts": merged,
        "kept_segments": kept,
    }


def plan_with_gemini(
    workspace: Path,
    video: Path,
    *,
    model: str = DEFAULT_MODEL,
    context: str = "",
    duration: float | None = None,
    brief: Path | None = None,
) -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY não definida — coloque no .env (aistudio.google.com/apikey)")

    if duration is None:
        duration = probe_duration(video)
    brief = brief or REPO_ROOT / "agents" / "planner_long.md"
    prompt = build_prompt(brief, context, duration)

    client = genai.Client(api_key=api_key)
    handle = upload(client, video)

    print(f"[gemini] planning with {model}…")
    started = time.time()
    try:
        response = client.models.generate_content(
            model=model,
            contents=[handle, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        if "NOT_FOUND" in str(exc) or "not found" in str(exc).lower():
            raise SystemExit(
                f"modelo {model!r} indisponível nessa chave. Disponíveis: "
                + ", ".join(sorted(available_models(client)))
            ) from exc
        raise
    elapsed = time.time() - started
    print(f"[gemini] answered in {elapsed:.1f}s")

    plan = normalize(extract_json(response.text), duration)
    (workspace / "reviewed_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    usage = getattr(response, "usage_metadata", None)
    report = {
        "arm": "gemini",
        "model": model,
        "video": str(video),
        "duration": duration,
        "seconds": round(elapsed, 2),
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
        "total_tokens": getattr(usage, "total_token_count", None),
        "cuts": len(plan["cuts"]),
        "kept_segments": len(plan["kept_segments"]),
    }
    (workspace / "gemini_run.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[gemini] {report['cuts']} cortes, {report['kept_segments']} trechos mantidos")
    return report


def available_models(client) -> list[str]:
    """Model ids this key can call — printed when the chosen one is missing."""
    names = []
    for model in client.models.list():
        name = (getattr(model, "name", "") or "").removeprefix("models/")
        actions = getattr(model, "supported_actions", None) or []
        if name and (not actions or "generateContent" in actions):
            names.append(name)
    return names


def probe_duration(video: Path) -> float:
    import subprocess

    ffprobe = os.environ.get("AUTO_EDIT_FFPROBE", "ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Gemini arm of the planner benchmark")
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--context", default="")
    ap.add_argument("--brief", type=Path, default=None, help="prompt file (default: agents/planner_long.md)")
    args = ap.parse_args()

    args.workspace.mkdir(parents=True, exist_ok=True)
    plan_with_gemini(
        args.workspace,
        args.video,
        model=args.model,
        context=args.context,
        brief=args.brief,
    )


if __name__ == "__main__":
    main()
