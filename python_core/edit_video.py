#!/usr/bin/env python
import argparse
import os
import sys

# Importa funções dos outros scripts
# Certifique-se de que remove_silence.py e auto_caption.py estão na mesma pasta
from remove_silence import remover_silencio
from auto_caption import transcrever, gerar_ass_capcut, queimar_legenda

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline completo: Remove silêncio e adiciona legendas estilo CapCut."
    )
    parser.add_argument("video", help="Caminho do arquivo de vídeo de entrada")
    parser.add_argument("--output", help="Nome do arquivo final (opcional)")
    parser.add_argument("--model", default="small", help="Modelo Whisper (padrão: small)")
    parser.add_argument("--language", default="pt", help="Idioma (padrão: pt)")
    
    # Opções de silêncio
    parser.add_argument("--silence-method", choices=["speech", "volume"], default="speech", help="Método de corte")
    parser.add_argument("--silence-threshold", type=int, default=-40, help="dB silêncio (apenas modo volume)")
    parser.add_argument("--silence-duration", type=float, default=0.5, help="Duração silêncio")

    args = parser.parse_args()

    video_path = args.video
    if not os.path.isfile(video_path):
        print(f"Arquivo não encontrado: {video_path}")
        sys.exit(1)

    base, ext = os.path.splitext(video_path)
    
    # 1. Remover Silêncio
    cut_video_path = f"{base}_cut{ext}"
    print(f"\n=== PASSO 1: Remover Silêncio ===")
    
    sucesso_corte = remover_silencio(
        video_path, 
        cut_video_path,
        method=args.silence_method,
        threshold_db=args.silence_threshold, 
        min_duration=args.silence_duration
    )
    
    if sucesso_corte:
        video_para_legendar = cut_video_path
    else:
        print("Não foi possível cortar o silêncio (ou não houve necessidade). Usando original.")
        video_para_legendar = video_path

    # 2. Legendar
    print(f"\n=== PASSO 2: Transcrever e Legendar ===")
    
    # Define nome de saída final
    if args.output:
        final_output = args.output
    else:
        final_output = f"{base}_final_edit{ext}"

    # Define nome do arquivo de legenda temporário
    base_legend = os.path.splitext(video_para_legendar)[0]
    ass_path = f"{base_legend}.ass"

    try:
        segments = transcrever(
            video_para_legendar, 
            model_name=args.model, 
            language=args.language
        )
        
        gerar_ass_capcut(segments, ass_path)
        
        queimar_legenda(video_para_legendar, ass_path, final_output)
        
        print(f"\n✅ Processo completo!")
        print(f"Vídeo salvo em: {final_output}")
        
    except Exception as e:
        print(f"Erro durante o processo de legendagem: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

