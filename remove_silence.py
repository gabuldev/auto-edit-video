#!/usr/bin/env python
import argparse
import subprocess
import re
import sys
import os
import whisper

def detect_speech_intervals(input_file, model_name="tiny", language="pt", padding=0.25, min_silence=0.5, word_threshold=0.3):
    """
    Usa o Whisper para detectar onde REALMENTE há fala, ignorando ruídos.
    Retorna lista de tuplas (start, end) para manter.
    """
    print(f"[Corte Inteligente] Analisando fala com Whisper ({model_name})...")
    
    try:
        model = whisper.load_model(model_name)
    except Exception as e:
        print(f"Erro ao carregar Whisper para corte: {e}")
        return []

    # Transcreve com word_timestamps para precisão máxima
    result = model.transcribe(input_file, language=language, word_timestamps=True, verbose=False)
    
    # Achatar todas as palavras com filtragem de confiança
    all_words = []
    skipped_noise = 0
    
    for seg in result["segments"]:
        # Se a probabilidade de NÃO ter fala for alta (> 80%), ignora o segmento inteiro (alucinação)
        if seg.get("no_speech_prob", 0) > 0.8:
            continue

        for w in seg.get("words", []):
            # Filtra palavras com confiança baixa (provavelmente ruído/alucinação)
            if w.get("probability", 1.0) < word_threshold:
                skipped_noise += 1
                continue
            all_words.append(w)
            
    if not all_words:
        print("Nenhuma fala detectada.")
        return []
        
    print(f"Detectadas {len(all_words)} palavras. (Ignorados {skipped_noise} possíveis ruídos). Calculando intervalos...")
    
    keep_intervals = []
    
    # Lógica de agrupamento:
    # Se a próxima palavra começa logo depois da anterior (menos que min_silence de gap), junta.
    # Se o gap for grande, fecha o intervalo atual e abre um novo.
    
    current_start = max(0, all_words[0]["start"] - padding)
    current_end = all_words[0]["end"] + padding
    
    for i in range(1, len(all_words)):
        w = all_words[i]
        w_start = w["start"] - padding
        w_end = w["end"] + padding
        
        # Se o início desta palavra sobrepõe ou está perto do fim da anterior
        if w_start <= current_end + min_silence:
            # Estende o intervalo atual
            current_end = max(current_end, w_end)
        else:
            # Gap grande detectado -> Salva intervalo anterior e começa novo
            keep_intervals.append((current_start, current_end))
            current_start = w_start
            current_end = w_end
            
    # Adiciona o último
    keep_intervals.append((current_start, current_end))
    
    return keep_intervals


def detect_silence_ffmpeg(input_file, threshold_db=-40, min_duration=0.5):
    """
    Método antigo: Baseado puramente em volume (dB).
    """
    cmd = [
        "ffmpeg", "-i", input_file,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', check=True)
    except subprocess.CalledProcessError as e:
        print(f"Erro ao detectar silêncio ffmpeg: {e}")
        return []
        
    output = result.stderr
    silence_starts = []
    silence_ends = []
    
    for line in output.splitlines():
        if "silence_start" in line:
            match = re.search(r"silence_start: ([\d\.]+)", line)
            if match:
                silence_starts.append(float(match.group(1)))
        elif "silence_end" in line:
            match = re.search(r"silence_end: ([\d\.]+)", line)
            if match:
                silence_ends.append(float(match.group(1)))

    # Obter duração total
    duration_cmd = ["ffmpeg", "-i", input_file]
    dur_res = subprocess.run(duration_cmd, capture_output=True, text=True, encoding='utf-8')
    dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})", dur_res.stderr)
    if not dur_match:
        return []
        
    h, m, s = dur_match.groups()
    total_duration = float(h)*3600 + float(m)*60 + float(s)
    
    keep_intervals = []
    current_time = 0.0
    
    if silence_ends and (not silence_starts or silence_starts[0] > silence_ends[0]):
        silence_starts.insert(0, 0.0)

    for start, end in zip(silence_starts, silence_ends):
        if start > current_time:
            keep_intervals.append((current_time, start))
        current_time = end
        
    if current_time < total_duration:
        keep_intervals.append((current_time, total_duration))
        
    return keep_intervals


def remover_silencio(input_file, output_file, method="speech", threshold_db=-40, min_duration=0.5, padding=0.25):
    """
    Orquestrador de remoção de silêncio.
    method: 'speech' (Whisper) ou 'volume' (ffmpeg)
    """
    print(f"[Corte] Iniciando corte de silêncio em {input_file} usando método: {method.upper()}...")
    
    keep_intervals = []
    
    if method == "speech":
        # Usa Whisper (mais inteligente, ignora ruído)
        # Usamos modelo 'tiny' ou 'base' aqui para ser rápido, já que é só para cortar
        keep_intervals = detect_speech_intervals(input_file, model_name="base", min_silence=min_duration, padding=padding)
    else:
        # Usa Volume (mais rápido, mas pode pegar respiração/ruído)
        keep_intervals = detect_silence_ffmpeg(input_file, threshold_db, min_duration)

    if not keep_intervals:
        print("Nenhum intervalo válido encontrado para manter. Abortando.")
        return False

    print(f"Mantendo {len(keep_intervals)} blocos de conteúdo.")

    # Gerar filter_complex para ffmpeg
    # Atenção: Se houver MUITOS cortes (>100), filter_complex por linha de comando pode falhar no Windows/Shell.
    # O ideal seria usar concat demuxer file, mas isso exige reencodar cada pedaço.
    # Vamos manter filter_complex por enquanto.
    
    filter_str = ""
    concat_str = ""
    
    for i, (start, end) in enumerate(keep_intervals):
        filter_str += f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
        filter_str += f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
        concat_str += f"[v{i}][a{i}]"
        
    concat_str += f"concat=n={len(keep_intervals)}:v=1:a=1[outv][outa]"
    full_filter = filter_str + concat_str
    
    print("Renderizando vídeo cortado (Isso recodifica o vídeo para precisão)...")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-filter_complex", full_filter,
        "-map", "[outv]", "-map", "[outa]",
        # Encoding preset rápido para não demorar anos
        "-c:v", "libx264", "-preset", "fast", "-crf", "23", 
        "-c:a", "aac", "-b:a", "192k",
        output_file
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"Vídeo cortado salvo em: {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erro ao cortar vídeo: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Remove silêncio de vídeos.")
    parser.add_argument("input", help="Arquivo de entrada")
    parser.add_argument("--output", help="Arquivo de saída (opcional)")
    parser.add_argument("--method", choices=["speech", "volume"], default="speech", 
                        help="Método de corte: 'speech' (fala/whisper) ou 'volume' (dB/ffmpeg)")
    parser.add_argument("--threshold", type=int, default=-40, help="[Volume] Limiar em dB")
    parser.add_argument("--duration", type=float, default=0.5, help="Duração mínima de silêncio/gap")
    
    args = parser.parse_args()
    
    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"Arquivo não encontrado: {input_path}")
        sys.exit(1)
        
    base, ext = os.path.splitext(input_path)
    output_path = args.output or f"{base}_cut{ext}"
    
    remover_silencio(input_path, output_path, args.method, args.threshold, args.duration)

if __name__ == "__main__":
    main()
