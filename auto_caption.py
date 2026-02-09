#!/usr/bin/env python
import argparse
import os
import subprocess
import sys
import re

import whisper
import pysubs2

# Import opcional da correção ADK
try:
    from adk_correction import corrigir_palavras_com_adk
except ImportError as e:
    print(f"⚠️  Aviso: Não foi possível importar o módulo de correção ADK: {e}")
    corrigir_palavras_com_adk = None


def transcrever(video_path: str, model_name: str = "small", language: str = "pt"):
    print(f"[1/3] Carregando modelo Whisper ({model_name})...")
    model = whisper.load_model(model_name)

    print(f"[2/3] Transcrevendo áudio de {video_path}...")
    # Precisamos ativar word_timestamps para ter o tempo de cada palavra
    result = model.transcribe(
        video_path,
        language=language,
        verbose=True,
        word_timestamps=True
    )
    return result["segments"]


import json

def salvar_segmentos_json(segments, json_path: str):
    """Salva os segmentos em arquivo JSON para edição posterior"""
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        print(f"Segmentos salvos em: {json_path}")
    except Exception as e:
        print(f"Erro ao salvar JSON de segmentos: {e}")

def carregar_segmentos_json(json_path: str):
    """Carrega segmentos de arquivo JSON"""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Erro ao carregar JSON de segmentos: {e}")
        return []

def interpolate_words(text, start, end):
    """
    Se o segmento não tiver 'words' (foi editado manualmente),
    quebra o texto em palavras e distribui o tempo uniformemente.
    """
    words = text.strip().split()
    if not words:
        return []
    
    duration = end - start
    per_word = duration / len(words)
    
    result = []
    current_start = start
    
    for w in words:
        w_end = current_start + per_word
        result.append({
            "word": w,
            "start": current_start,
            "end": w_end
        })
        current_start = w_end
        
    return result

def gerar_ass_capcut(segments, ass_path: str, highlight_color=None, text_color=None, outline_color=None, highlight_width=5.0, outline_width=1.5, font_name="Prohibition", font_size=10):
    """
    Gera um arquivo .ass com legendas dinâmicas, RESPEITANDO OS SEGMENTOS.
    """
    print(f"[3/3] Gerando arquivo de legenda ASS em {ass_path}...")

    subs = pysubs2.SSAFile()

    # CORES E ESTILOS (Ajuste Fino)
    HIGHLIGHT_COLOR = highlight_color if highlight_color else "&H0045FF&" 
    BLACK_COLOR = outline_color if outline_color else "&H000000&"
    WHITE_COLOR = text_color if text_color else "&HFFFFFF&"
    
    def to_ass_color(c):
        if c and c.startswith('#') and len(c) == 7:
            r = c[1:3]
            g = c[3:5]
            b = c[5:7]
            return f"&H{b}{g}{r}&"
        return c

    HIGHLIGHT_COLOR = to_ass_color(HIGHLIGHT_COLOR)
    BLACK_COLOR = to_ass_color(BLACK_COLOR)
    WHITE_COLOR = to_ass_color(WHITE_COLOR)

    # Estilo Base
    style = pysubs2.SSAStyle()
    style.fontname = font_name
    style.fontsize = font_size
    style.bold = True
    style.primarycolor = pysubs2.Color(255, 255, 255)
    style.outlinecolor = pysubs2.Color(0, 0, 0)
    style.outline = 1.0
    style.shadow = 0
    style.alignment = 2   # centro inferior
    style.marginv = 95

    subs.styles["Default"] = style

    def sec_to_ms(t):
        return int(t * 1000)

    BORDER_NORMAL = float(outline_width)
    BORDER_HIGHLIGHT = float(highlight_width)
    BLUR_HIGHLIGHT = 2.0
    
    HIGHLIGHT_TAG = rf"{{\1c{WHITE_COLOR}}}{{\3c{HIGHLIGHT_COLOR}}}{{\bord{BORDER_HIGHLIGHT}}}{{\blur{BLUR_HIGHLIGHT}}}"
    NORMAL_TAG = rf"{{\1c{WHITE_COLOR}}}{{\3c{BLACK_COLOR}}}{{\bord{BORDER_NORMAL}}}{{\blur0}}"

    # ITERA SOBRE OS SEGMENTOS (RESPEITANDO A EDIÇÃO)
    for seg in segments:
        # Se tiver palavras com timestamps, usa. Se não, interpola.
        seg_words = seg.get("words", [])
        if not seg_words:
            seg_words = interpolate_words(seg["text"], seg["start"], seg["end"])
            
        if not seg_words:
            continue

        # Texto base deste segmento (para exibir o contexto da frase)
        chunk_texts = [w["word"].strip().upper() for w in seg_words]
        
        # Gera eventos de destaque (karaokê) DENTRO do tempo deste segmento
        for j, word_obj in enumerate(seg_words):
            w_start = sec_to_ms(word_obj["start"])
            w_end = sec_to_ms(word_obj["end"])
            
            # Garante que não ultrapasse o tempo do segmento pai
            # (Útil se a interpolação ou o whisper derem timestamps zoados)
            seg_end_ms = sec_to_ms(seg["end"])
            if w_end > seg_end_ms:
                w_end = seg_end_ms
            
            # Monta o texto visual
            display_parts = []
            for k, text_part in enumerate(chunk_texts):
                if k == j:
                    display_parts.append(f"{HIGHLIGHT_TAG}{text_part}{NORMAL_TAG}")
                else:
                    display_parts.append(text_part)
            
            final_text = " ".join(display_parts)

            # Ajuste para evitar flicker entre palavras
            # Se não for a última palavra, estica até a próxima
            if j < len(seg_words) - 1:
                next_start = sec_to_ms(seg_words[j + 1]["start"])
                if next_start - w_end < 500: # Se o gap for pequeno
                    w_end = next_start
            
            # Cria o evento
            event = pysubs2.SSAEvent(start=w_start, end=w_end, text=final_text, style="Default")
            subs.events.append(event)

    subs.save(ass_path)
    print("Legenda .ass criada.")


def queimar_legenda(video_path: str, ass_path: str, output_path: str):
    print(f"Renderizando vídeo final com ffmpeg → {output_path}")

    ass_norm = os.path.abspath(ass_path).replace("\\", "/")
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"subtitles='{ass_norm}'",
        "-c:a", "copy",
        output_path,
    ]

    print("Comando:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print("Erro ao rodar ffmpeg:", e)
        sys.exit(1)

def regroup_words_into_segments(words, max_chars=80, max_duration=7.0, min_gap=0.5):
    """
    Reagrupa palavras em segmentos menores baseados em:
    - Comprimento máximo de caracteres (max_chars)
    - Duração máxima (max_duration)
    - Pausa entre palavras (min_gap)
    """
    if not words:
        return []

    segments = []
    current_segment = {
        "start": words[0]["start"],
        "end": words[0]["end"],
        "words": [],
        "text": ""
    }
    
    last_end = words[0]["start"]

    for w in words:
        w_start = w["start"]
        w_end = w["end"]
        w_text = w["word"]
        
        # Calcula gap em relação à palavra anterior no loop
        gap = w_start - last_end
        
        # Decisão de quebra
        should_break = False
        
        # 1. Gap grande (silêncio)
        if gap > min_gap and len(current_segment["words"]) > 0:
            should_break = True
            
        # 2. Tamanho do texto excedido
        current_len = len(current_segment["text"]) + len(w_text) + 1
        if current_len > max_chars:
            should_break = True
            
        # 3. Duração excessiva do segmento
        seg_duration = w_end - current_segment["start"]
        if seg_duration > max_duration:
            should_break = True

        if should_break:
            # Finaliza segmento anterior
            segments.append(current_segment)
            # Inicia novo
            current_segment = {
                "start": w_start,
                "end": w_end,
                "words": [w],
                "text": w_text
            }
        else:
            # Adiciona ao atual
            current_segment["words"].append(w)
            current_segment["end"] = w_end
            if current_segment["text"]:
                current_segment["text"] += " " + w_text
            else:
                current_segment["text"] = w_text
        
        last_end = w_end

    # Adiciona o último
    if current_segment["words"]:
        segments.append(current_segment)

    return segments

def processar_legenda_completo(video_path, output_path, model_name="small", language="pt", gemini_key=None, 
                               highlight_color=None, text_color=None, outline_color=None, highlight_width=5.0, outline_width=1.5, font_name="Prohibition", font_size=10,
                               only_generate=False):
    """
    Pipeline completo: Transcrever -> (Corrigir IA) -> Gerar ASS -> Queimar
    Se only_generate=True, para após gerar o ASS e salva JSON.
    """
    base, ext = os.path.splitext(video_path)
    ass_path = f"{base}.ass"
    json_path = f"{base}.json"

    # 1. Transcrever
    segments = transcrever(video_path, model_name=model_name, language=language)
    
    # 2. Corrigir (se solicitado)
    # Se gemini_key for passada ou None (confiando no env), e o módulo existir
    if corrigir_palavras_com_adk:
        # Verifica se deve tentar (chave explicita ou env implícito)
        should_try = False
        if gemini_key:
            should_try = True
        elif os.path.exists(".env") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            should_try = True
            
        if should_try:
            print("\n[Auto Caption] Tentando correção com IA...")
            all_words = []
            for seg in segments:
                if "words" in seg:
                    all_words.extend(seg["words"])
            
            if all_words:
                try:
                    corrected_words = corrigir_palavras_com_adk(all_words, gemini_key)
                    if corrected_words:
                        # Reconstrói estrutura para o gerador, mas segmentado
                        segments = regroup_words_into_segments(corrected_words)
                except Exception as e:
                    print(f"❌ Falha na correção IA: {e}. Usando original.")
        else:
            print("[Auto Caption] Pulando correção IA (sem chave ou não solicitada).")
            if not corrigir_palavras_com_adk:
                print("⚠️  Módulo 'adk_correction' não carregado corretamente.")

    # Salva JSON dos segmentos para edição futura
    salvar_segmentos_json(segments, json_path)

    # 3. Gerar ASS
    gerar_ass_capcut(segments, ass_path, highlight_color, text_color, outline_color, highlight_width, outline_width, font_name, font_size)
    
    if only_generate:
        print("Apenas geração solicitada. Parando antes de queimar.")
        return ass_path

    # 4. Queimar
    queimar_legenda(video_path, ass_path, output_path)
    
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Gera legenda estilo CapCut automaticamente com Whisper e queima no vídeo."
    )
    parser.add_argument("video", help="Caminho do arquivo de vídeo de entrada")
    parser.add_argument(
        "--model",
        default="small",
        help="Modelo Whisper (tiny, base, small, medium, large). Padrão: small",
    )
    parser.add_argument(
        "--language",
        default="pt",
        help="Código do idioma da fala (ex: pt, en, es). Padrão: pt",
    )
    parser.add_argument(
        "--output",
        help="Nome do vídeo de saída (opcional). Se não passar, cria <nome>_legendado.mp4",
    )
    parser.add_argument(
        "--gemini-key",
        help="API Key do Google Gemini para correção de texto.",
    )

    args = parser.parse_args()

    video_path = args.video
    if not os.path.isfile(video_path):
        print(f"Arquivo não encontrado: {video_path}")
        sys.exit(1)

    base, ext = os.path.splitext(video_path)
    output_path = args.output or f"{base}_legendado.mp4"

    processar_legenda_completo(
        video_path, 
        output_path, 
        model_name=args.model, 
        language=args.language,
        gemini_key=args.gemini_key
    )

    print("\n✅ Pronto!")
    print(f"Vídeo legendado salvo em: {output_path}")


if __name__ == "__main__":
    main()
