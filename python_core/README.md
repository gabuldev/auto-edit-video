# Auto Video Editor

Este projeto é uma ferramenta de automação para edição de vídeo que utiliza inteligência artificial para remover silêncio, gerar legendas estilizadas (estilo CapCut) e corrigir erros de fala.

## Funcionalidades

- **Remoção de Silêncio**: Detecta e remove pausas e silêncios no vídeo automaticamente.
- **Auto Legenda**: Gera legendas precisas usando OpenAI Whisper.
- **Estilo CapCut**: As legendas são geradas no formato `.ass` com destaque na palavra atual (karaokê/highlight) e fonte personalizada.
- **Correção com IA**: Usa o Google Gemini para corrigir ortografia e pontuação das transcrições antes de gerar a legenda final.
- **Edição Inteligente**: Identifica e corta "takes" ruins ou repetições de fala (via Agentes).

## Pré-requisitos

### 1. Sistema
- **Python 3.8+**
- **FFmpeg**: Essencial para manipulação de vídeo e áudio.
  - *Mac*: `brew install ffmpeg`
  - *Windows*: Baixe e adicione ao PATH.
  - *Linux*: `sudo apt install ffmpeg`

### 2. API Keys
Você precisará de uma chave de API do Google Gemini para usar as funcionalidades de correção de texto e os agentes inteligentes.

## Instalação

1. Clone o repositório:
   ```bash
   git clone https://github.com/gabuldev/auto-edit-video.git
   cd auto-edit-video
   ```

2. Crie e ative um ambiente virtual (recomendado):
   ```bash
   python -m venv .venv
   # Mac/Linux:
   source .venv/bin/activate
   # Windows:
   .venv\Scripts\activate
   ```

3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

## Configuração (.env)

Crie um arquivo `.env` na raiz do projeto e adicione sua chave do Gemini:

```env
GEMINI_API_KEY=sua_chave_aqui
```
> Você também pode usar `GOOGLE_API_KEY` se preferir.

## Como Usar

### Menu Interativo (Recomendado)

O jeito mais fácil de usar é através do menu interativo:

```bash
python cli.py
```

O menu oferecerá as seguintes opções:
1. **Remover Silêncio**: Apenas corta as partes silenciosas.
2. **Gerar Legendas**: Transcreve e adiciona legendas a um vídeo.
3. **Processo Completo**: Remove silêncio e depois legenda o resultado.

### Linha de Comando (Pipeline)

Para automatizar em scripts, use o `edit_video.py`:

```bash
python edit_video.py "caminho/do/video.mp4" --output "final.mp4"
```

Argumentos opcionais:
- `--model`: Modelo do Whisper (tiny, base, small, medium, large). Padrão: `small`.
- `--silence-method`: Método de corte (`speech` ou `volume`).
- `--silence-threshold`: Nível de dB para corte (se usar método volume).

### Agentes (Experimental)

O projeto contém uma estrutura de agentes em `agent/` que utilizam o Google ADK para orquestrar tarefas complexas de edição (como "revisar conteúdo").

## Estrutura do Projeto

- `cli.py`: Menu principal interativo.
- `remove_silence.py`: Módulo responsável pelos cortes de silêncio.
- `auto_caption.py`: Módulo de transcrição e geração de legendas.
- `edit_video.py`: Script para execução via linha de comando com argumentos.
- `correction.py`: Módulo auxiliar para correção de texto via LLM.
- `agent/`: Implementação de agentes autônomos para edição.

## Notas
- O processo de transcrição (Whisper) pode ser pesado. Modelos maiores (`medium`, `large`) requerem mais memória e GPU (se disponível).
- As fontes usadas nas legendas (ex: "Prohibition") devem estar instaladas no sistema para o player de vídeo reconhecer se você abrir o `.ass` separadamente, mas ao "queimar" a legenda (burn-in) com FFmpeg, ele usará a configuração fornecida.

