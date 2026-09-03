"""
EXTRACT stage — Fase 1
Runs Whisper transcription + FFmpeg energy map.
Writes workspace/transcription.json and updates pipeline stage.

Usage: python tools/extract.py <workspace_dir>
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

# Whisper import com aviso amigável se não estiver instalado
try:
    import whisper
except ImportError:
    print("ERROR: openai-whisper not installed. Run: uv pip install openai-whisper", file=sys.stderr)
    sys.exit(1)

# numba mock — evita crash em ambientes sem numba (igual ao legado)
try:
    import numba  # noqa: F401
except ImportError:
    import unittest.mock as mock
    sys.modules["numba"] = mock.MagicMock()
    sys.modules["numba.core"] = mock.MagicMock()


ENERGY_RESOLUTION = 0.5   # segundos por bucket do energy map (vai pro prompt)
# Mapa fino: usado só pelo snap. Com buckets de 0.5s a fala vizinha vaza pra
# dentro de uma pausa de 0.3s e ela passa a medir como fala.
ENERGY_FINE_RESOLUTION = 0.1
WORD_CONFIDENCE_THRESHOLD = 0.3
NO_SPEECH_PROB_THRESHOLD = 0.8
SAMPLE_RATE = 16000        # Hz — Whisper usa 16kHz internamente
SILENCE_DB = -120.0        # sentinela para silêncio total


def _load_pipeline(workspace: Path) -> dict:
    import json as _json
    return _json.loads((workspace / "pipeline.json").read_text())


def extract(workspace: Path) -> None:
    pipeline = _load_pipeline(workspace)
    video_path = Path(pipeline["video_path"])
    model_name = pipeline.get("whisper_model", "small")
    language = pipeline.get("language", "pt")

    print(f"[extract] Video: {video_path.name}")
    print(f"[extract] Whisper model: {model_name}")

    # 1. Extrair áudio como WAV mono 16kHz
    audio_path = workspace / "audio.wav"
    _extract_audio(video_path, audio_path)

    # 2. Duração do vídeo
    duration = _get_duration(audio_path)
    print(f"[extract] Duration: {duration:.1f}s")

    # 3. Energy map via PCM raw
    print("[extract] Computing energy map...")
    energy_db, energy_db_fine = _compute_energy_maps(audio_path, duration)
    print(f"[extract] Energy buckets: {len(energy_db)} (+{len(energy_db_fine)} fine)")

    # 4. Whisper transcription com word_timestamps
    context = pipeline.get("context", "")
    print(f"[extract] Running Whisper ({model_name})...")
    words, segments = _transcribe(audio_path, model_name, language, context)
    print(f"[extract] Words: {len(words)}, Segments: {len(segments)}")

    # 5. Correção da transcrição com Claude (corrige alucinações e erros do Whisper)
    words, segments = _correct_transcription(words, segments, context, language)

    # 6. Montar transcription.json
    transcription = {
        "duration": round(duration, 3),
        "resolution_seconds": ENERGY_RESOLUTION,
        "energy_db": energy_db,
        "fine_resolution_seconds": ENERGY_FINE_RESOLUTION,
        "energy_db_fine": energy_db_fine,
        "words": words,
        "segments": segments,
    }

    out_path = workspace / "transcription.json"
    out_path.write_text(
        json.dumps(transcription, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[extract] Written: {out_path}")
    print("[extract] Done.")


# ── Audio extraction ──────────────────────────────────────────────────────────

def _extract_audio(video: Path, out: Path) -> None:
    """Extrai áudio como WAV mono 16kHz para Whisper + energy map."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-ac", "1",           # mono
        "-ar", str(SAMPLE_RATE),
        "-vn",                # sem vídeo
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"FFmpeg failed extracting audio from {video}")


def _get_duration(audio: Path) -> float:
    """Retorna a duração em segundos via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


# ── Energy map ────────────────────────────────────────────────────────────────

def _rms_db(sum_squares: float, count: int) -> float:
    if count <= 0:
        return SILENCE_DB
    rms = math.sqrt(sum_squares / count)
    return round(20.0 * math.log10(rms), 1) if rms > 1e-9 else SILENCE_DB


def _compute_energy_maps(audio: Path, duration: float) -> tuple[list[float], list[float]]:
    """
    Lê PCM f32le do FFmpeg via pipe e calcula RMS dB por janela.

    Devolve (mapa de ENERGY_RESOLUTION, mapa de ENERGY_FINE_RESOLUTION). O
    grosso vai pro prompt do planner; o fino fica pro snap, que precisa medir
    pausas menores que um bucket grosso. Os dois saem do mesmo decode: o grosso
    é a soma dos quadrados dos buckets finos que ele cobre.
    Evita dependências extras (librosa, soundfile, etc).
    """
    fine_per_coarse = max(1, round(ENERGY_RESOLUTION / ENERGY_FINE_RESOLUTION))
    samples_per_bucket = int(SAMPLE_RATE * ENERGY_FINE_RESOLUTION)
    n_buckets = math.ceil(duration / ENERGY_FINE_RESOLUTION)

    # FFmpeg → raw PCM float32 little-endian, mono 16kHz
    cmd = [
        "ffmpeg", "-y", "-i", str(audio),
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "f32le", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg failed to export PCM")

    raw = proc.stdout
    n_samples = len(raw) // 4  # float32 = 4 bytes
    samples = struct.unpack(f"<{n_samples}f", raw[: n_samples * 4])

    fine_db: list[float] = []
    coarse_db: list[float] = []
    coarse_sum, coarse_count = 0.0, 0

    for i in range(n_buckets):
        start = i * samples_per_bucket
        end = min(start + samples_per_bucket, n_samples)
        bucket = samples[start:end]
        sum_squares = sum(s * s for s in bucket)
        fine_db.append(_rms_db(sum_squares, len(bucket)))

        coarse_sum += sum_squares
        coarse_count += len(bucket)
        if (i + 1) % fine_per_coarse == 0:
            coarse_db.append(_rms_db(coarse_sum, coarse_count))
            coarse_sum, coarse_count = 0.0, 0

    if coarse_count or n_buckets % fine_per_coarse:
        coarse_db.append(_rms_db(coarse_sum, coarse_count))

    return coarse_db, fine_db


# ── Whisper transcription ─────────────────────────────────────────────────────

def _transcribe(audio: Path, model_name: str, language: str, context: str = "") -> tuple[list[dict], list[dict]]:
    """
    Roda Whisper com word_timestamps=True.
    Filtra palavras com confiança baixa e segmentos sem fala.
    Retorna (words, segments).
    """
    print(f"[extract] Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name)
    print("[extract] Transcribing audio (this may take a while)...")
    transcribe_kwargs: dict = dict(
        language=language,
        word_timestamps=True,
        verbose=False,
    )
    if context:
        # Format as a glossary hint so Whisper primes vocabulary without
        # treating it as preceding speech (which causes hallucinated continuations)
        transcribe_kwargs["initial_prompt"] = f"Termos relevantes: {context}."
        print(f"[extract] Using initial_prompt from context ({len(context)} chars)")
    result = model.transcribe(str(audio), **transcribe_kwargs)

    words: list[dict] = []
    segments: list[dict] = []

    for seg in result["segments"]:
        # Ignora segmentos que provavelmente não têm fala (alucinação do Whisper)
        if seg.get("no_speech_prob", 0.0) > NO_SPEECH_PROB_THRESHOLD:
            continue

        seg_words: list[dict] = []
        for w in seg.get("words", []):
            confidence = w.get("probability", 1.0)
            if confidence < WORD_CONFIDENCE_THRESHOLD:
                continue
            word_entry = {
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "confidence": round(confidence, 3),
            }
            words.append(word_entry)
            seg_words.append(word_entry)

        if seg_words:
            segments.append(
                {
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "text": seg["text"].strip(),
                    "no_speech_prob": round(seg.get("no_speech_prob", 0.0), 3),
                    "words": seg_words,
                }
            )

    return words, segments


# ── Transcription correction ──────────────────────────────────────────────────

def _correct_transcription(
    words: list[dict],
    segments: list[dict],
    context: str,
    language: str,
) -> tuple[list[dict], list[dict]]:
    """
    Passa a transcrição pelo Claude para corrigir alucinações e erros do Whisper.
    Preserva todos os timestamps — só o texto das palavras é corrigido.
    Retorna (words, segments) corrigidos. Em caso de falha, retorna os originais.
    """
    if not words:
        return words, segments

    # Monta texto completo a partir dos segmentos para o prompt
    full_text = " ".join(seg["text"] for seg in segments)

    # Envia ao Claude uma lista indexada de palavras para corrigir
    word_list = "\n".join(f"{i}: {w['word']}" for i, w in enumerate(words))

    prompt = f"""Você é um revisor de transcrições de vídeo em {language}.

Contexto do vídeo: {context or "não informado"}

Texto transcrito pelo Whisper (pode conter erros):
{full_text}

Lista de palavras indexadas:
{word_list}

Sua tarefa: corrigir APENAS dois tipos de erro do Whisper:
A) Palavras que não existem no {language} E cuja correção é óbvia pelo contexto
B) Nomes de marcas/produtos do contexto que foram distorcidos (ex: "ZIGB" → "Zigbee" se o contexto menciona Zigbee)

Retorne APENAS um JSON com as correções necessárias, no formato:
{{"corrections": [{{"index": 0, "corrected": "palavra_certa"}}]}}

REGRAS — leia com atenção:
1. A correção deve ser EXATAMENTE UMA palavra, sem espaços
2. Se uma palavra EXISTE em {language} (mesmo que pareça estranha no contexto), NÃO corrija — pode ser gíria, informalidade ou estilo do falante
3. Se não souber com certeza a correção correta de uma palavra desconhecida, IGNORE-a — não invente
4. Palavras que parecem incompletas (começam no meio de uma sílaba, sem maiúscula), IGNORE-as — são cortes de áudio
5. Marcas, produtos e siglas citados no contexto (ex: PLA, Matte): NÃO troque uns pelos outros — são termos distintos que podem coexistir na mesma frase
6. NÃO altere concordância, pontuação, gênero ou número — só erros do Whisper
7. NÃO use palavras de outros idiomas como correção
8. Se não houver nada a corrigir com certeza, retorne {{"corrections": []}}
9. Retorne SOMENTE o JSON, sem explicações"""

    try:
        print("[extract] Sending transcription to Claude for correction...")
        # Prompt on stdin, not argv: it carries the whole transcript, which is
        # past the 32KB command-line limit on Windows. The timeout has to clear
        # the CLI's own cold start (~30s) plus the correction itself, or the
        # step always "times out" and the raw Whisper text silently survives.
        result = subprocess.run(
            ["claude", "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("AUTO_EDIT_CORRECTION_TIMEOUT", "240")),
        )
        if result.returncode != 0:
            print("[extract] Claude correction skipped (non-zero exit)", file=sys.stderr)
            return words, segments

        output = result.stdout.strip()

        # Strip markdown fences if present
        if "```" in output:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", output)
            if match:
                output = match.group(1).strip()

        data = json.loads(output)
        corrections: list[dict] = data.get("corrections", [])

        if not corrections:
            print("[extract] Claude correction: no changes needed.")
            return words, segments

        # Safety filters — reject suspicious corrections before applying
        # Common short function words that should never be replaced
        _FUNCTION_WORDS = {"eu", "tu", "ele", "ela", "nós", "eles", "elas",
                           "um", "uma", "o", "a", "os", "as", "de", "da",
                           "do", "no", "na", "em", "e", "ou", "se", "que"}

        validated: list[dict] = []
        for c in corrections:
            idx = c["index"]
            corrected = c["corrected"]
            if idx < 0 or idx >= len(words):
                print(f"[extract] SKIP [{idx}]: index out of range", file=sys.stderr)
                continue
            original = words[idx]["word"]
            orig_clean = original.strip(".,!?;:")

            # Reject: original is a high-confidence common function word
            if orig_clean.lower() in _FUNCTION_WORDS and words[idx].get("confidence", 0) > 0.7:
                print(f"[extract] SKIP [{idx}]: '{original}' is a high-confidence function word")
                continue

            # Reject: correction has spaces (multi-word)
            if " " in corrected:
                print(f"[extract] SKIP [{idx}]: '{original}' → '{corrected}' has spaces")
                continue

            # Reject: correction is 3x+ longer than original (likely hallucination expanding a truncated word)
            if len(corrected.strip(".,!?;:")) > len(orig_clean) * 3 and len(orig_clean) > 2:
                print(f"[extract] SKIP [{idx}]: '{original}' → '{corrected}' too much longer than original")
                continue

            validated.append(c)

        if not validated:
            print("[extract] Claude correction: all suggestions rejected by safety filters.")
            return words, segments

        # Apply validated corrections to words list
        correction_map = {c["index"]: c["corrected"] for c in validated}
        corrected_words = []
        for i, w in enumerate(words):
            if i in correction_map:
                print(f"[extract] Corrected: '{w['word']}' → '{correction_map[i]}'")
                corrected_words.append({**w, "word": correction_map[i]})
            else:
                corrected_words.append(w)

        # Rebuild segments text from corrected words
        word_idx = 0
        corrected_segments = []
        for seg in segments:
            n = len(seg.get("words", []))
            seg_words = corrected_words[word_idx: word_idx + n]
            word_idx += n
            corrected_segments.append({
                **seg,
                "text": " ".join(w["word"] for w in seg_words),
                "words": seg_words,
            })

        print(f"[extract] Claude correction: {len(corrections)} word(s) fixed.")
        return corrected_words, corrected_segments

    except subprocess.TimeoutExpired:
        print("[extract] Claude correction timed out — using raw Whisper output.", file=sys.stderr)
        return words, segments
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[extract] Claude correction parse error ({e}) — using raw Whisper output.", file=sys.stderr)
        return words, segments


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/extract.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)

    workspace = Path(sys.argv[1])
    if not workspace.exists():
        print(f"Workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    extract(workspace)
