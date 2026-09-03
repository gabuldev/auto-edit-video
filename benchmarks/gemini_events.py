"""Gemini as a visual-event detector, not as a planner.

The first benchmark round showed the failure mode clearly: Gemini describes what
it sees correctly and then puts it in the wrong place on the timeline (it missed
by ~3 minutes on a 12-minute video and cut the outro). So this asks it for much
less, in a way that bounds the error by construction:

- the video is sent in short windows (`VideoMetadata.start_offset/end_offset`),
  so a timestamp can only be wrong by at most one window's length;
- timestamps come back relative to the window and we add the offset ourselves;
- `fps` is explicit — the default sampling of 1 frame/s is coarse for finding
  the exact moment someone steps out of frame;
- `response_schema` pins the output shape, so there is no JSON to repair;
- and it is asked only for what a transcript cannot show — the blind spot of our
  own planner. The cut decision stays with whoever has reliable timestamps.

    python benchmarks/gemini_events.py --video proxy.mp4 --until 120 --window 60

Writes the events as JSON (absolute seconds) to stdout or --out.
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

# Same cp1252 trap the pipeline hit: printing an accent or an arrow on Windows
# raises UnicodeEncodeError unless stdio is UTF-8.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from benchmarks.gemini_plan import (  # noqa: E402
    DEFAULT_MODEL,
    generate_with_retry,
    probe_duration,
    upload,
)

KINDS = (
    "fora_de_quadro",
    "mexendo_no_equipamento",
    "tela_ou_demo_travada",
    "take_perdido",
    "tempo_morto",
    "outro",
)

PROMPT = """Você está assistindo a UM TRECHO de uma gravação bruta, não ao vídeo inteiro.

Sua única tarefa: listar **eventos visuais** deste trecho que um editor cortaria
e que **não apareceriam numa transcrição de áudio**. Exemplos: o apresentador
sai do quadro, ele mexe na câmera / no microfone / no tripé, a demonstração
travou, um take foi perdido e reiniciado, a cena está vazia.

Regras que importam mais que a completude:

- Timestamps em segundos **contados do início DESTE TRECHO** (0 = primeiro
  frame que você recebeu), como número decimal. Nunca "MM:SS".
- Só relate o que você **realmente vê** neste trecho. Se não houver nenhum
  evento, devolva uma lista vazia — isso é uma resposta correta e útil.
- Não relate coisas de áudio (repetição de fala, hesitação, silêncio): outra
  etapa cuida disso e tem timestamps melhores que os seus.
- `confianca`: 0 a 1, quão certo você está de que o evento existe e de onde ele
  começa e termina.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "eventos": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start": {"type": "NUMBER"},
                    "end": {"type": "NUMBER"},
                    "tipo": {"type": "STRING", "enum": list(KINDS)},
                    "descricao": {"type": "STRING"},
                    "confianca": {"type": "NUMBER"},
                },
                "required": ["start", "end", "tipo", "descricao", "confianca"],
            },
        }
    },
    "required": ["eventos"],
}


def detect_window(client, handle, start: float, end: float, *, model: str, fps: float):
    """Ask about one window; returns (events with absolute timestamps, usage)."""
    from google.genai import types

    part = types.Part(
        file_data=types.FileData(file_uri=handle.uri, mime_type=handle.mime_type),
        video_metadata=types.VideoMetadata(
            start_offset=f"{start:.0f}s", end_offset=f"{end:.0f}s", fps=fps
        ),
    )
    response = generate_with_retry(
        client,
        model,
        [part, PROMPT],
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCHEMA,
            media_resolution="MEDIA_RESOLUTION_LOW",
        ),
    )
    payload = json.loads(response.text)
    events = []
    for event in payload.get("eventos") or []:
        try:
            local_start, local_end = float(event["start"]), float(event["end"])
        except (KeyError, TypeError, ValueError):
            continue
        # Relative -> absolute, clamped to the window we actually asked about:
        # this is what keeps a hallucinated timestamp from landing anywhere.
        abs_start = max(start, min(start + local_start, end))
        abs_end = max(start, min(start + local_end, end))
        if abs_end <= abs_start:
            continue
        events.append(
            {
                "start": round(abs_start, 2),
                "end": round(abs_end, 2),
                "tipo": event.get("tipo"),
                "descricao": event.get("descricao"),
                "confianca": event.get("confianca"),
                "window": [start, end],
            }
        )
    return events, getattr(response, "usage_metadata", None)


def merge_across_windows(events: list[dict], gap: float = 1.0) -> list[dict]:
    """Rejoin one event that a window boundary sliced in two.

    An event straddling the edge comes back as "58–60" from one call and
    "60–64" from the next: two findings that are really one. Same kind and
    touching in time means the same moment.
    """
    merged: list[dict] = []
    for event in sorted(events, key=lambda e: e["start"]):
        last = merged[-1] if merged else None
        touches = last and event["start"] - last["end"] <= gap and event["tipo"] == last["tipo"]
        if touches:
            last["end"] = max(last["end"], event["end"])
            last["confianca"] = max(last.get("confianca") or 0, event.get("confianca") or 0)
            last["descricao"] = f"{last['descricao']} / {event['descricao']}"
            last["window"] = [last["window"][0], event["window"][1]]
        else:
            merged.append(dict(event))
    return merged


def detect(
    video: Path,
    *,
    model: str = DEFAULT_MODEL,
    window: float = 60.0,
    fps: float = 2.0,
    until: float | None = None,
) -> dict:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY não definida (use `doppler run --`)")

    duration = probe_duration(video)
    horizon = min(duration, until) if until else duration
    client = genai.Client(api_key=api_key)
    handle = upload(client, video)

    events, tokens, started = [], 0, time.time()
    start = 0.0
    while start < horizon:
        end = min(start + window, horizon)
        print(f"[events] janela {start:.0f}-{end:.0f}s @ {fps}fps…", flush=True)
        found, usage = detect_window(client, handle, start, end, model=model, fps=fps)
        for event in found:
            print(f"         {event['start']:7.1f}-{event['end']:7.1f} [{event['tipo']}] "
                  f"conf={event['confianca']} {event['descricao'][:70]}")
        events.extend(found)
        tokens += getattr(usage, "total_token_count", 0) or 0
        start = end

    merged = merge_across_windows(events)
    if len(merged) != len(events):
        print(f"[events] {len(events)} achados -> {len(merged)} depois de juntar os partidos na fronteira")
    return {
        "video": str(video),
        "model": model,
        "window": window,
        "fps": fps,
        "horizon": horizon,
        "seconds": round(time.time() - started, 1),
        "total_tokens": tokens,
        "eventos": merged,
        "eventos_brutos": events,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--window", type=float, default=60.0)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--until", type=float, default=None, help="só os primeiros N segundos")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    result = detect(
        args.video.expanduser().resolve(),
        model=args.model,
        window=args.window,
        fps=args.fps,
        until=args.until,
    )
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"[events] {len(result['eventos'])} eventos -> {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
