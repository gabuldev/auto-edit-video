"""Pedidos livres de edição: zoom e B-roll num trecho, validados antes do FFmpeg.

O pipeline decide os cortes; isto cobre o que a pessoa pede depois, numa
conversa ("dá um zoom quando eu mostro a peça", "põe o print da tela aqui"):

    effects.json (no workspace)
    {"effects": [
      {"type": "zoom",  "start": 72.0, "end": 76.5, "scale": 1.2},
      {"type": "broll", "start": 130.0, "end": 136.0, "file": "/videos/tela.png"}
    ]}

Cada janela está no tempo do vídeo ORIGINAL, como o `sequence`: o efeito fica
preso ao conteúdo e sobrevive a um replanejamento (o plan reescreve o
reviewed_plan.json, não este arquivo). Na hora de renderizar, a janela é
recortada pelo que de fato toca (applied_intervals.json, já na ordem de
reprodução) e vira tempo do vídeo editado — um trecho que toca duas vezes
(teaser do cold open) leva o efeito nas duas.

Regras (fora delas o efeito é ignorado com o motivo no log; nunca derruba o
`execute` — se o FFmpeg falhar, o vídeo fica só com os cortes):

- `type` é `zoom` ou `broll`; `end > start`; entre 0,5s e 30s;
- zoom: `scale` de 1,05 a 1,6 (padrão 1,2), centralizado;
- broll: `file` existe e é imagem (png/jpg/webp) ou vídeo (mp4/mov/mkv/webm);
  caminho relativo é resolvido a partir da pasta do vídeo original. Cobre a
  tela inteira (recorte central), sem som: o áudio é sempre o da fala;
- precisa sobrar pelo menos 0,5s tocando depois do recorte pelos cortes;
- dois efeitos do mesmo tipo não se sobrepõem (o que vem depois na lista sai).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

FILE_NAME = "effects.json"
KINDS = ("zoom", "broll")
MIN_DURATION = 0.5
MAX_DURATION = 30.0
MAX_EFFECTS = 20
ZOOM_DEFAULT = 1.2
ZOOM_MIN = 1.05
ZOOM_MAX = 1.6
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
EPS = 1e-3

Interval = tuple[float, float]


class EffectError(ValueError):
    """A request that can't become an effect — the message says why."""


# ── Storage ───────────────────────────────────────────────────────────────────


def load(ws: Path) -> list[dict]:
    try:
        data = json.loads((Path(ws) / FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("effects") if isinstance(data, dict) else None
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def save(ws: Path, effects: list[dict]) -> None:
    path = Path(ws) / FILE_NAME
    if not effects:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"effects": effects}, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Validation ────────────────────────────────────────────────────────────────


def resolve_file(file: str, base_dir: Path | None) -> Path:
    path = Path(os.path.expanduser(str(file)))
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return path


def media_kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return None


def clean(effect: dict, base_dir: Path | None = None) -> dict:
    """One request, normalized — EffectError with the reason otherwise.

    Checks what can be checked without knowing the cut: type, window, scale,
    file. Whether it lands on something that plays is `place`'s job.
    """
    if not isinstance(effect, dict):
        raise EffectError("efeito precisa ser um objeto")
    kind = str(effect.get("type") or "").strip().lower()
    if kind not in KINDS:
        raise EffectError(f"tipo de efeito desconhecido: {kind or '?'} (use zoom ou broll)")
    try:
        start, end = float(effect["start"]), float(effect["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectError("efeito precisa de start e end numéricos") from exc
    if start < 0:
        raise EffectError("start não pode ser negativo")
    if end <= start:
        raise EffectError("end precisa ser maior que start")
    dur = end - start
    if dur < MIN_DURATION:
        raise EffectError(f"efeito curto demais ({dur:.2f}s; mínimo {MIN_DURATION}s)")
    if dur > MAX_DURATION:
        raise EffectError(f"efeito longo demais ({dur:.1f}s; máximo {MAX_DURATION:.0f}s)")
    out: dict = {"type": kind, "start": round(start, 3), "end": round(end, 3)}

    if kind == "zoom":
        try:
            scale = float(effect.get("scale") or ZOOM_DEFAULT)
        except (TypeError, ValueError) as exc:
            raise EffectError("scale do zoom precisa ser número") from exc
        if not ZOOM_MIN <= scale <= ZOOM_MAX:
            raise EffectError(f"scale do zoom entre {ZOOM_MIN} e {ZOOM_MAX} (veio {scale})")
        out["scale"] = round(scale, 3)
    else:
        file = effect.get("file")
        if not file:
            raise EffectError("broll precisa de file (imagem ou vídeo)")
        path = resolve_file(file, base_dir)
        if media_kind(path) is None:
            raise EffectError(f"broll: formato não suportado ({path.suffix or 'sem extensão'})")
        if not path.is_file():
            raise EffectError(f"broll: arquivo não encontrado: {path}")
        out["file"] = str(path)
        try:
            offset = float(effect.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0.0
        if offset > 0:
            out["offset"] = round(offset, 3)  # where a video b-roll starts playing
    if effect.get("note"):
        out["note"] = str(effect["note"])[:200]
    return out


def _overlaps(a: dict, b: dict) -> bool:
    return a["type"] == b["type"] and a["start"] < b["end"] - EPS and b["start"] < a["end"] - EPS


def validate(effects, base_dir: Path | None = None) -> tuple[list[dict], list[str]]:
    """(valid effects, notes about the ones dropped), in list order."""
    kept: list[dict] = []
    notes: list[str] = []
    if not isinstance(effects, list):
        return [], ["effects não é lista — ignorado"] if effects else []
    for i, raw in enumerate(effects, 1):
        try:
            eff = clean(raw, base_dir)
        except EffectError as exc:
            notes.append(f"efeito {i} ignorado: {exc}")
            continue
        if any(_overlaps(eff, k) for k in kept):
            notes.append(f"efeito {i} ignorado: sobrepõe outro {eff['type']}")
            continue
        if len(kept) == MAX_EFFECTS:
            notes.append(f"efeito {i} ignorado: máximo de {MAX_EFFECTS} efeitos")
            continue
        kept.append(eff)
    return kept, notes


# ── Timelines ─────────────────────────────────────────────────────────────────


def place(effect: dict, playback: list[Interval]) -> list[dict]:
    """Where an effect plays in the edited video: one window per stretch of
    playback it covers (back-to-back ones merged — a zoom across a cut stays
    one zoom). Each carries `src`, how far into the effect window (original
    time) it starts, so a video b-roll picks up where that stretch is."""
    out: list[dict] = []
    offset = 0.0
    for s, e in playback:
        lo, hi = max(s, effect["start"]), min(e, effect["end"])
        if hi - lo > EPS:
            t0, t1 = offset + (lo - s), offset + (hi - s)
            src = lo - effect["start"]
            # Back to back in the edit: one window. A video b-roll also has to
            # continue in its own time (a cut in between makes it jump).
            joined = out and abs(out[-1]["t1"] - t0) < EPS
            if joined and (effect.get("type") != "broll" or abs(out[-1]["src_end"] - src) < EPS):
                out[-1]["t1"], out[-1]["src_end"] = t1, src + (hi - lo)
            else:
                out.append({"t0": t0, "t1": t1, "src": src, "src_end": src + (hi - lo)})
        offset += e - s
    return [{"t0": round(w["t0"], 3), "t1": round(w["t1"], 3), "src": round(w["src"], 3)} for w in out]


def to_original(start: float, end: float, playback: list[Interval]) -> list[Interval]:
    """A window of the EDITED video as the stretches of the original it shows
    (a window across a cut becomes two). [] when it's outside the video."""
    if end <= start:
        return []
    out: list[Interval] = []
    offset = 0.0
    for s, e in playback:
        d = e - s
        lo, hi = max(start, offset), min(end, offset + d)
        if hi - lo > EPS:
            out.append((round(s + (lo - offset), 3), round(s + (hi - offset), 3)))
        offset += d
    return out


def edited_duration(playback: list[Interval]) -> float:
    return sum(e - s for s, e in playback)


def playback(ws: Path) -> list[Interval]:
    """What plays, in order, in original time: what the executor cut
    (applied_intervals.json) or, before any render, what the plan describes."""
    ws = Path(ws)
    try:
        data = json.loads((ws / "applied_intervals.json").read_text(encoding="utf-8"))
        items = [(float(i["start"]), float(i["end"])) for i in data.get("intervals", [])]
        items = [(s, e) for s, e in items if e > s]
        if items:
            return items
    except (OSError, ValueError, KeyError, TypeError):
        pass
    from auto_edit import intervals as iv
    from auto_edit import sequence, snap

    try:
        transcription = json.loads((ws / "transcription.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plan_file = next((ws / n for n in ("reviewed_plan.json", "cut_plan.json") if (ws / n).exists()), None)
    if plan_file is None:
        return []
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    duration = float(transcription.get("duration") or 0.0)
    energy, resolution = snap.load_energy_map(ws)
    kept = iv.build_keep_intervals(plan, duration, energy, resolution)
    if plan.get("sequence"):
        kept, _ = sequence.apply(kept, plan["sequence"])
    return kept


def plan_effects(effects: list[dict], playback_: list[Interval]) -> tuple[list[dict], list[str]]:
    """Each effect with its windows in the edited video; the ones that land
    on nothing that plays (or too little of it) are dropped with a note."""
    placed: list[dict] = []
    notes: list[str] = []
    for i, eff in enumerate(effects, 1):
        windows = place(eff, playback_)
        shown = sum(w["t1"] - w["t0"] for w in windows)
        if shown < MIN_DURATION:
            notes.append(
                f"efeito {i} ({eff['type']} {eff['start']:.1f}–{eff['end']:.1f}s) ignorado: "
                "cai num trecho cortado"
            )
            continue
        placed.append({**eff, "windows": windows})
    return placed, notes


# ── FFmpeg ────────────────────────────────────────────────────────────────────


def build_command(
    video: Path, output: Path, placed: list[dict], size: tuple[int, int],
    codec: tuple[str, list[str]], *, has_audio: bool = True,
) -> list[str]:
    """One pass over the edited video: every zoom/b-roll window overlaid on
    the base, the audio copied untouched."""
    w, h = size
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(video)]
    graph: list[str] = []
    cur = "[0:v]"
    n_in = 1
    k = 0
    for eff in placed:
        for win in eff["windows"]:
            t0, t1 = win["t0"], win["t1"]
            dur = t1 - t0
            enable = f"enable='between(t,{t0:.3f},{t1:.3f})'"
            if eff["type"] == "zoom":
                s = eff["scale"]
                graph.append(f"{cur}split[base{k}][src{k}]")
                graph.append(
                    f"[src{k}]trim=start={t0:.3f}:end={t1:.3f},"
                    f"crop=trunc(iw/{s}/2)*2:trunc(ih/{s}/2)*2:(iw-trunc(iw/{s}/2)*2)/2:(ih-trunc(ih/{s}/2)*2)/2,"
                    f"scale={w}:{h}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS+{t0:.3f}/TB[fx{k}]"
                )
                graph.append(f"[base{k}][fx{k}]overlay=0:0:eof_action=pass:{enable}[v{k}]")
            else:
                path = Path(eff["file"])
                if media_kind(path) == "image":
                    cmd += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(path)]
                else:
                    start_in = float(eff.get("offset") or 0) + win["src"]
                    cmd += ["-ss", f"{start_in:.3f}", "-t", f"{dur:.3f}", "-i", str(path)]
                graph.append(
                    f"[{n_in}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                    f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS+{t0:.3f}/TB[fx{k}]"
                )
                graph.append(f"{cur}[fx{k}]overlay=0:0:eof_action=pass:{enable}[v{k}]")
                n_in += 1
            cur = f"[v{k}]"
            k += 1
    name, flags = codec
    cmd += ["-filter_complex", ";".join(graph), "-map", cur]
    if has_audio:
        cmd += ["-map", "0:a", "-c:a", "copy"]
    cmd += ["-c:v", name, *flags, "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-brand", "mp42", str(output)]
    return cmd


def apply(ws: Path, codec: tuple[str, list[str]], *, run=subprocess.run) -> list[str]:
    """Burn effects.json into edited_video.mp4 (in place). Returns log lines.

    Never raises: with nothing valid, or when FFmpeg fails, the edited video
    stays exactly as the executor left it.
    """
    from auto_edit import probe

    ws = Path(ws)
    raw = load(ws)
    if not raw:
        return []
    video = ws / "edited_video.mp4"
    if not video.is_file():
        return ["efeitos: sem edited_video.mp4 — pulando"]
    try:
        source = Path(json.loads((ws / "pipeline.json").read_text(encoding="utf-8")).get("video_path") or "")
    except (OSError, ValueError):
        source = Path()
    valid, notes = validate(raw, source.parent if str(source) else None)
    placed, more = plan_effects(valid, playback(ws))
    notes += more
    if not placed:
        return notes + ["efeitos: nenhum efeito válido — vídeo fica só com os cortes"]
    try:
        size = probe.video_size(video)
        has_audio = probe.has_audio_stream(video)
    except Exception as exc:  # noqa: BLE001 — never break the stage over a probe
        return notes + [f"efeitos: não deu pra ler o vídeo editado ({exc}) — pulando"]

    with tempfile.TemporaryDirectory(prefix="auto-edit-fx-", dir=ws) as td:
        out = Path(td) / "with_effects.mp4"
        cmd = build_command(video, out, placed, size, codec, has_audio=has_audio)
        result = run(cmd)
        if getattr(result, "returncode", 1) != 0 or not out.is_file():
            return notes + ["efeitos: FFmpeg falhou — vídeo fica só com os cortes"]
        shutil.move(str(out), str(video))
    lines = []
    for eff in placed:
        where = ", ".join(f"{w['t0']:.1f}–{w['t1']:.1f}s" for w in eff["windows"])
        what = f"zoom {eff['scale']}x" if eff["type"] == "zoom" else f"broll {Path(eff['file']).name}"
        lines.append(f"efeito: {what} em {where} do vídeo editado")
    return notes + lines
