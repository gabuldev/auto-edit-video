"""Onde o público sai: a curva de retenção do YouTube cruzada com o que é dito.

A YouTube Analytics API devolve, por vídeo, a fração do público que ainda
está assistindo em ~100 pontos (`elapsedVideoTimeRatio` → `audienceWatchRatio`)
e quanto isso está acima/abaixo de vídeos parecidos
(`relativeRetentionPerformance`). Aqui isso vira:

- retenção aos 30s, 60s e na metade;
- as **quedas acima do normal** — todo vídeo perde gente aos poucos; o que
  importa é onde perde mais rápido que no resto dele — com a fala daquele
  trecho (transcrição pós-corte do workspace, que é a timeline publicada);
- um resumo pro prompt do planner: os momentos em que o público saiu nos
  teus vídeos recentes, e que tipo de fala era (preâmbulo, tangente…).

`retention.json` fica no workspace. Nada aqui chama a API: quem busca a
curva é o connector do insights.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from auto_edit import opening

RETENTION_NAME = "retention.json"
DROP_WINDOW = 10.0  # seconds a drop is measured over
MIN_EXCESS = 0.02  # 2 pp beyond the video's typical decline in a window
MAX_DROPS = 5
# Every video loses people fast in the first seconds. There, a drop only
# counts when YouTube says this video is doing worse than similar ones
# (relativeRetentionPerformance below 0.5) at that point.
EARLY = 30.0
RELATIVE_TYPICAL = 0.5


def to_seconds(points: list[dict], duration: float) -> list[tuple[float, float]]:
    """(seconds, watch ratio) from the API's (ratio, watch ratio) rows."""
    curve = []
    for p in points:
        try:
            ratio, watch = float(p["ratio"]), float(p["watch"])
        except (KeyError, TypeError, ValueError):
            continue
        curve.append((ratio * duration, watch))
    return sorted(curve)


def watch_at(curve: list[tuple[float, float]], t: float) -> float | None:
    """Linear interpolation of the curve at `t` seconds."""
    if not curve:
        return None
    if t <= curve[0][0]:
        return curve[0][1]
    for (t0, w0), (t1, w1) in zip(curve, curve[1:]):
        if t0 <= t <= t1:
            return w0 if t1 == t0 else w0 + (w1 - w0) * (t - t0) / (t1 - t0)
    return curve[-1][1]


def find_drops(curve: list[tuple[float, float]], window: float = DROP_WINDOW,
               top: int = MAX_DROPS, relative: list[tuple[float, float]] | None = None) -> list[dict]:
    """Windows where the audience falls faster than this video usually does.

    Loss over each `window` is compared with the median loss per window of the
    whole video; the biggest excesses that don't overlap are returned, in
    time order. The first seconds are measured too (a fast exit there is the
    opening's problem) — the very first point is the click itself and is skipped.

    In the first `EARLY` seconds the natural exit is steep, so a window there
    only counts when `relative` (seconds → relativeRetentionPerformance) says
    the video is below similar videos at the end of it.
    """
    if len(curve) < 3:
        return []
    end = curve[-1][0]
    starts = [t for t, _ in curve[1:] if t + window <= end]
    losses = []
    for t in starts:
        a, b = watch_at(curve, t), watch_at(curve, t + window)
        losses.append((t, a - b, a, b))
    if not losses:
        return []
    typical = median(loss for _, loss, _, _ in losses)

    def counts(t: float) -> bool:
        if t >= EARLY:
            return True
        rel = watch_at(relative, t + window) if relative else None
        return rel is not None and rel < RELATIVE_TYPICAL

    candidates = sorted(
        ((t, loss - typical, loss, a, b) for t, loss, a, b in losses
         if loss - typical >= MIN_EXCESS and counts(t)),
        key=lambda c: c[1],
        reverse=True,
    )
    picked: list[dict] = []
    for t, excess, loss, a, b in candidates:
        if any(abs(t - d["start"]) < window for d in picked):
            continue
        picked.append({
            "start": round(t, 1),
            "end": round(t + window, 1),
            "from": round(a, 4),
            "to": round(b, 4),
            "loss": round(loss, 4),
            "excess": round(excess, 4),
        })
        if len(picked) == top:
            break
    return sorted(picked, key=lambda d: d["start"])


def said_between(transcript: dict, start: float, end: float, limit: int = 300) -> str:
    said = [
        (s.get("text") or "").strip()
        for s in transcript.get("segments") or []
        if float(s.get("end", 0)) > start and float(s.get("start", 0)) < end
    ]
    text = " ".join(t for t in said if t)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def analyze(points: list[dict], duration: float, transcript: dict | None) -> dict:
    """Everything the screen and the planner need from one video's curve."""
    curve = to_seconds(points, duration)
    relative = to_seconds(
        [{"ratio": p.get("ratio"), "watch": p.get("relative")} for p in points if p.get("relative") is not None],
        duration,
    )
    drops = find_drops(curve, relative=relative)
    for d in drops:
        # A little lead-in: people leave a beat after what made them leave.
        text = said_between(transcript or {}, max(0.0, d["start"] - 3.0), d["end"]) if transcript else ""
        d["text"] = text
        d["preamble"] = opening.preamble_kind(text) if text else None

    def at(t: float) -> float | None:
        return round(watch_at(curve, t), 4) if curve and t <= curve[-1][0] else None

    relative = [float(p["relative"]) for p in points if p.get("relative") is not None]
    return {
        "duration": round(duration, 1),
        "at_30s": at(30.0),
        "at_60s": at(60.0),
        "at_half": at(duration / 2) if duration else None,
        "relative_median": round(median(relative), 3) if relative else None,
        "curve": [[round(t, 1), round(w, 4)] for t, w in curve],
        "drops": drops,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Workspace ─────────────────────────────────────────────────────────────────


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def youtube_id(ws: Path) -> str | None:
    """The YouTube id this workspace was published as: the last upload in
    publish.json or, for a video published by hand, the one a previous
    `insights retention --url` saved in retention.json."""
    record = _read(ws / "publish.json") or {}
    uploads = record.get("youtube") or []
    if uploads:
        return uploads[-1].get("video_id")
    saved = _read(ws / RETENTION_NAME)
    return saved.get("video_id") if isinstance(saved, dict) else None


def save(ws: Path, video_id: str, data: dict) -> dict:
    data = {"video_id": video_id, **data}
    (ws / RETENTION_NAME).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def load(ws: Path) -> dict | None:
    data = _read(ws / RETENTION_NAME)
    return data if isinstance(data, dict) else None


def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def lessons(library: Path, video_type: str, limit_videos: int = 6, per_video: int = 3) -> str:
    """Prompt block: where people left in the most recent analyzed videos of
    this type, with what was being said. "" when there is nothing yet."""
    entries = []
    for path in library.glob(f"*/{RETENTION_NAME}"):
        data = _read(path)
        pipeline = _read(path.parent / "pipeline.json") or {}
        if not isinstance(data, dict) or pipeline.get("type") != video_type or not data.get("drops"):
            continue
        entries.append((data.get("fetched_at") or "", path.parent, data, pipeline))
    if not entries:
        return ""
    entries.sort(key=lambda e: e[0], reverse=True)

    out = []
    for _, ws, data, pipeline in entries[:limit_videos]:
        metadata = _read(ws / "metadata.json") or {}
        title = metadata.get("youtube_title") or metadata.get("short_title") or pipeline.get("context") or ws.name
        out.append(f'### "{title}" — aos 30s: {_pct(data.get("at_30s"))}, aos 60s: {_pct(data.get("at_60s"))}')
        worst = sorted(data["drops"], key=lambda d: d["excess"], reverse=True)[:per_video]
        for d in sorted(worst, key=lambda d: d["start"]):
            kind = f" [{d['preamble']}]" if d.get("preamble") else ""
            out.append(
                f'- {_mmss(d["start"])}–{_mmss(d["end"])}: -{d["loss"] * 100:.0f}% do público{kind} — "{d.get("text") or "?"}"'
            )
    return "\n".join(out)


def format_summary(data: dict) -> str:
    """Human summary for the CLI."""
    lines = [
        f"Retenção aos 30s: {_pct(data.get('at_30s'))} · 60s: {_pct(data.get('at_60s'))} · "
        f"metade: {_pct(data.get('at_half'))}"
    ]
    rel = data.get("relative_median")
    if rel is not None:
        lines.append(f"Comparado a vídeos parecidos do YouTube: {rel:.2f} (0,5 = na média)")
    if data.get("drops"):
        lines.append("")
        lines.append("Onde mais gente saiu (além do normal deste vídeo):")
        for d in data["drops"]:
            kind = f" [{d['preamble']}]" if d.get("preamble") else ""
            lines.append(
                f"  {_mmss(d['start'])}–{_mmss(d['end'])}  -{d['loss'] * 100:.0f}%{kind}  {d.get('text') or ''}"
            )
    return "\n".join(lines)


# ── Evolução: a retenção melhorando de vídeo pra vídeo ────────────────────────

# pipeline.json: how many recent videos' drops the planner saw when it planned
# this one (runner.py writes it). Absent = planned before this was recorded.
LESSONS_KEY = "retention_lessons"
TREND_METRICS = ("at_30s", "at_60s", "at_half", "relative_median")


def _published_at(ws: Path, data: dict, pipeline: dict) -> str:
    """When it went out: the first upload (or its schedule), else when it was
    edited — what orders the trend."""
    uploads = (_read(ws / "publish.json") or {}).get("youtube") or []
    for up in uploads:
        when = up.get("publish_at") or up.get("published_at")
        if when:
            return str(when)
    return str(pipeline.get("created_at") or data.get("fetched_at") or "")


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _compare(older: list[dict], newer: list[dict]) -> dict:
    out = {}
    for m in TREND_METRICS:
        a = _avg([r[m] for r in older if r.get(m) is not None])
        b = _avg([r[m] for r in newer if r.get(m) is not None])
        out[m] = {"before": a, "after": b,
                  "delta": None if a is None or b is None else round(b - a, 4)}
    return out


def trend(library: Path, video_type: str | None = None) -> dict:
    """Every analyzed video in publish order, and whether retention is going up.

    `summary[type]` compares the older half with the newer half and, when both
    exist, the videos planned *with* the retention lessons against the ones
    planned without — the loop the planner closes.
    """
    rows = []
    for path in Path(library).glob(f"*/{RETENTION_NAME}"):
        data = _read(path)
        ws = path.parent
        pipeline = _read(ws / "pipeline.json") or {}
        kind = pipeline.get("type")
        if not isinstance(data, dict) or kind not in ("long", "short"):
            continue
        if video_type and kind != video_type:
            continue
        metadata = _read(ws / "metadata.json") or {}
        lessons = pipeline.get(LESSONS_KEY)
        rows.append({
            "id": ws.name,
            "type": kind,
            "title": metadata.get("youtube_title") or metadata.get("short_title") or pipeline.get("name") or ws.name,
            "youtube_id": data.get("video_id"),
            "published_at": _published_at(ws, data, pipeline),
            "duration": data.get("duration"),
            **{m: data.get(m) for m in TREND_METRICS},
            "lessons": lessons if isinstance(lessons, int) else None,
            "drops": len(data.get("drops") or []),
        })
    rows.sort(key=lambda r: r["published_at"])

    summary = {}
    for kind in ("long", "short"):
        mine = [r for r in rows if r["type"] == kind]
        if not mine:
            continue
        entry: dict = {"count": len(mine)}
        if len(mine) >= 2:
            half = len(mine) // 2
            entry["older_vs_newer"] = {"older": half, "newer": len(mine) - half,
                                       **_compare(mine[:half], mine[half:])}
        with_ = [r for r in mine if r["lessons"]]
        without = [r for r in mine if not r["lessons"]]
        if with_ and without:
            entry["with_vs_without_lessons"] = {"without": len(without), "with": len(with_),
                                                **_compare(without, with_)}
        summary[kind] = entry
    return {"videos": rows, "summary": summary}


def versus_previous(library: Path, ws: Path) -> dict | None:
    """This video against the average of the ones of its type published before
    it — the line the retention card shows. None without both."""
    ws = Path(ws)
    data = trend(library)
    rows = data["videos"]
    me = next((r for r in rows if r["id"] == ws.name), None)
    if me is None:
        return None
    before = [r for r in rows if r["type"] == me["type"] and r["published_at"] < me["published_at"]]
    if not before:
        return None
    cmp = _compare(before, [me])
    return {"previous": len(before), "lessons": me["lessons"], **cmp}


def _pp(delta: float | None) -> str:
    if delta is None:
        return ""
    return f" ({'+' if delta >= 0 else ''}{delta * 100:.1f} pp)"


def format_trend(data: dict) -> str:
    """Human summary for the CLI / MCP."""
    rows = data.get("videos") or []
    if not rows:
        return ("Nenhum vídeo com retenção analisada ainda. Rode `auto-edit insights retention --all` "
                "depois que os vídeos publicados tiverem 24–48h.")
    lines = []
    for kind, entry in (data.get("summary") or {}).items():
        lines.append(f"{kind}: {entry['count']} vídeo(s) analisado(s)")
        ovn = entry.get("older_vs_newer")
        if ovn:
            lines.append(f"  mais antigos ({ovn['older']}) → mais recentes ({ovn['newer']}):")
            for m, label in (("at_30s", "aos 30s"), ("at_60s", "aos 60s"), ("at_half", "na metade")):
                c = ovn[m]
                if c["before"] is not None and c["after"] is not None:
                    lines.append(f"    {label}: {_pct(c['before'])} → {_pct(c['after'])}{_pp(c['delta'])}")
        wvl = entry.get("with_vs_without_lessons")
        if wvl:
            c = wvl["at_30s"]
            lines.append(
                f"  planejados com as lições de retenção ({wvl['with']}) vs sem ({wvl['without']}): "
                f"aos 30s {_pct(c['after'])} vs {_pct(c['before'])}{_pp(c['delta'])}"
            )
    lines.append("")
    lines.append("Por vídeo (ordem de publicação):")
    for r in rows:
        when = (r["published_at"] or "")[:10]
        learned = " · com lições" if r["lessons"] else ""
        lines.append(
            f"  {when}  [{r['type']}] 30s {_pct(r['at_30s'])} · 60s {_pct(r['at_60s'])} · "
            f"metade {_pct(r['at_half'])}{learned}  {r['title']}"
        )
    return "\n".join(lines)


class RetentionError(RuntimeError):
    """Nothing to analyze yet (not published, no curve) — shown as is."""


def refresh(ws: Path, fetch, video_id: str | None = None) -> dict:
    """Fetch the curve of the video this workspace was published as, analyze
    it against the post-cut transcript and save `retention.json`.

    `fetch(video_id) -> points` is the connector call (injected for tests).
    """
    ws = Path(ws)
    video_id = video_id or youtube_id(ws)
    if not video_id:
        raise RetentionError(
            f"{ws.name} não tem vídeo do YouTube associado — publique pelo auto-edit "
            "ou passe a URL (--url)."
        )
    transcript = _read(ws / "post_cut_transcription.json")
    duration = float((transcript or {}).get("duration") or 0)
    if not duration:
        raise RetentionError(f"{ws.name} não tem transcrição pós-corte pra saber a duração.")
    points = fetch(video_id)
    if not points:
        raise RetentionError(
            "O YouTube ainda não tem curva de retenção pra esse vídeo "
            "(costuma aparecer em 24–48h, e precisa de algumas visualizações)."
        )
    return save(ws, video_id, analyze(points, duration, transcript))
