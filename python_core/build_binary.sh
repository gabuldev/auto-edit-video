#!/bin/bash

# Nome do executável
APP_NAME="auto-editor"

# Caminho para o ambiente virtual
VENV_DIR=".venv"

# Verifica se o ambiente virtual existe
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Erro: Ambiente virtual '$VENV_DIR' não encontrado!"
    echo "Certifique-se de estar na raiz do projeto e ter criado o venv."
    exit 1
fi

# Caminho para o PyInstaller dentro do venv
PYINSTALLER="$VENV_DIR/bin/pyinstaller"

# Verifica se o PyInstaller está instalado
if [ ! -f "$PYINSTALLER" ]; then
    echo "📦 Instalando PyInstaller..."
    "$VENV_DIR/bin/pip" install pyinstaller
fi

# Limpa builds anteriores
echo "🧹 Limpando builds antigos..."
rm -rf build dist "$APP_NAME.spec"

# Caminho dos assets do Whisper
WHISPER_ASSETS="$VENV_DIR/lib/python3.9/site-packages/whisper/assets"

# Verifica se a pasta de assets existe (pode variar dependendo da versão do python)
if [ ! -d "$WHISPER_ASSETS" ]; then
    # Tenta encontrar dinamicamente se o caminho acima falhar (ex: python3.10, 3.11)
    WHISPER_ASSETS=$(find "$VENV_DIR/lib" -name "assets" | grep "whisper/assets" | head -n 1)
fi

if [ -z "$WHISPER_ASSETS" ]; then
    echo "⚠️  Aviso: Assets do Whisper não encontrados automaticamente."
    echo "O binário pode falhar ao rodar. Verifique o caminho em: $VENV_DIR/lib/.../whisper/assets"
else
    echo "✅ Assets do Whisper encontrados em: $WHISPER_ASSETS"
fi

echo "🚀 Gerando executável '$APP_NAME'..."

# Comando do PyInstaller
# --onefile: Gera um único arquivo
# --name: Nome do executável
# --add-data: Inclui os assets do Whisper (SOURCE:DEST)
# --hidden-import: Força inclusão de dependências não detectadas (google-generativeai, adk)
# --clean: Limpa cache do PyInstaller
"$PYINSTALLER" --clean --onefile --name "$APP_NAME" \
    --add-data "$WHISPER_ASSETS:whisper/assets" \
    --hidden-import google.generativeai \
    --hidden-import google.ai \
    --hidden-import google.api_core \
    --hidden-import google.auth \
    --hidden-import adk \
    cli.py

# Move o executável para a raiz
if [ -f "dist/$APP_NAME" ]; then
    mv "dist/$APP_NAME" .
    echo ""
    echo "🎉 Sucesso! O executável '$APP_NAME' foi criado na raiz do projeto."
    echo "Para rodar: ./$APP_NAME"
else
    echo ""
    echo "❌ Erro: O executável não foi criado."
    exit 1
fi

