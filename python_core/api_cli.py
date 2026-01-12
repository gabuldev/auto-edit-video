#!/usr/bin/env python
import os
import sys
import argparse
import json
from dotenv import load_dotenv

# Carrega ambiente
load_dotenv()

# Ajusta path para importar módulos locais
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def cmd_remove_silence(args):
    from remove_silence import remover_silencio
    
    video_path = args.file
    if not os.path.exists(video_path):
        print(f"Error: File not found: {video_path}")
        sys.exit(1)
        
    base, ext = os.path.splitext(video_path)
    output_path = f"{base}_cut{ext}"
    
    method = args.method or "speech"
    threshold = args.threshold
    
    print(f"Processing: Removing silence from {video_path} using {method}...")
    success = remover_silencio(video_path, output_path, method=method, threshold_db=threshold)
    
    if success:
        print(f"SUCCESS: Output saved to {output_path}")
        print(json.dumps({"status": "success", "output_path": output_path}))
    else:
        print("ERROR: Failed to remove silence")
        sys.exit(1)

def cmd_auto_caption(args):
    from auto_caption import processar_legenda_completo
    
    video_path = args.file
    if not os.path.exists(video_path):
        print(f"Error: File not found: {video_path}")
        sys.exit(1)

    base, ext = os.path.splitext(video_path)
    output_path = f"{base}_captioned{ext}"
    
    model = args.model or "small"
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    print(f"Processing: Generating captions for {video_path} (Model: {model})...")
    
    final_path = processar_legenda_completo(
        video_path,
        output_path,
        model_name=model,
        language="pt",
        gemini_key=gemini_key
    )
    
    print(f"SUCCESS: Output saved to {final_path}")
    print(json.dumps({"status": "success", "output_path": final_path}))

def main():
    parser = argparse.ArgumentParser(description="Auto Video Editor API CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Command: remove-silence
    parser_rs = subparsers.add_parser("remove-silence", help="Remove silence from video")
    parser_rs.add_argument("--file", required=True, help="Path to input video")
    parser_rs.add_argument("--method", default="speech", choices=["speech", "volume"], help="Method to detect silence")
    parser_rs.add_argument("--threshold", type=float, default=-40.0, help="Volume threshold in dB (for volume method)")

    # Command: auto-caption
    parser_ac = subparsers.add_parser("auto-caption", help="Generate captions")
    parser_ac.add_argument("--file", required=True, help="Path to input video")
    parser_ac.add_argument("--model", default="small", help="Whisper model size")
    
    args = parser.parse_args()
    
    if args.command == "remove-silence":
        cmd_remove_silence(args)
    elif args.command == "auto-caption":
        cmd_auto_caption(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()

