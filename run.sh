#!/bin/bash

# Define o caminho do venv
VENV_DIR=".venv"

# Verifica se o venv existe
if [ ! -d "$VENV_DIR" ]; then
    echo "⚠️  Ambiente virtual não encontrado. Criando..."
    python3 -m venv "$VENV_DIR"
fi

# Ativa o venv e instala dependências se necessário
echo "🚀 Iniciando no ambiente virtual..."
source "$VENV_DIR/bin/activate"

# Garante que pip está atualizado
pip install --upgrade pip -q

# Instala dependências (silencioso se já estiver instalado)
echo "📦 Verificando dependências..."
pip install -r requirements.txt -q
pip install openai-whisper pysubs2 python-dotenv flask flask-socketio requests -q

# Inicia a aplicação
echo "🎬 Iniciando aplicação..."
python start_gui.py