#!/usr/bin/env python
"""
🎬 Auto Video Editor - Script de Inicialização
Inicia a interface gráfica web automaticamente
"""

import subprocess
import sys
import os
import time
import webbrowser
from pathlib import Path

def check_dependencies():
    """Verifica se as dependências estão instaladas"""
    try:
        import flask
        import flask_socketio
        import whisper
        import pysubs2
        return True
    except ImportError:
        return False

def install_dependencies():
    """Instala as dependências necessárias"""
    print("📦 Instalando dependências (Isso pode demorar um pouco na primeira vez)...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "flask", "flask-socketio", "openai-whisper", "pysubs2", "python-dotenv", "requests"
        ])
        print("✅ Dependências instaladas!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao instalar dependências: {e}")
        print("Tente instalar manualmente: pip install -r requirements.txt")
        sys.exit(1)

def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   🎬  AUTO VIDEO EDITOR - Interface Gráfica                  ║
║                                                               ║
║   Edição automática de vídeos com IA                         ║
║   • Remoção de silêncio inteligente                          ║
║   • Legendas estilo CapCut (karaokê)                         ║
║   • Correção ortográfica com Gemini                          ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Verificar dependências
    if not check_dependencies():
        install_dependencies()
    
    # Mudar para o diretório do script
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    print("🚀 Iniciando servidor web...")
    print("🌐 URL: http://localhost:3001")
    print("")
    print("💡 Dica: Coloque seus vídeos na mesma pasta do projeto")
    print("📁 Pasta atual:", script_dir)
    print("")
    print("═" * 60)
    print("Pressione Ctrl+C para encerrar")
    print("═" * 60)
    print("")
    
    # Abrir navegador automaticamente após 2 segundos
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:3001")
    
    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Importar e iniciar o app
    print(f"   • Python: {sys.executable}")
    from web_app import app, socketio
    socketio.run(app, host='0.0.0.0', port=3001, debug=False, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    main()

