# 🎬 Auto Video Editor

Este projeto é uma ferramenta de automação para edição de vídeo que utiliza inteligência artificial para remover silêncio, gerar legendas estilizadas (estilo CapCut) e corrigir erros de fala.

![Interface Web](https://img.shields.io/badge/Interface-Web-brightgreen) ![Python](https://img.shields.io/badge/Python-3.8+-blue) ![Whisper](https://img.shields.io/badge/AI-Whisper-orange) ![Gemini](https://img.shields.io/badge/AI-Gemini-purple) ![SQLite](https://img.shields.io/badge/Database-SQLite-003B57) ![Lottie](https://img.shields.io/badge/Animation-Lottie-00DDB3)

## ✨ Funcionalidades

### Processamento de Vídeo
- 🔇 **Remoção de Silêncio**: Detecta e remove pausas e silêncios automaticamente
  - Modo Inteligente (Whisper): Detecta fala com IA
  - Modo Volume (dB): Corta por threshold de áudio
- 📝 **Auto Legenda**: Gera legendas precisas usando OpenAI Whisper
- 🎨 **Estilo CapCut**: Legendas com destaque palavra a palavra (karaokê/highlight)
- 🤖 **Correção com IA**: Google Gemini corrige ortografia e pontuação
- 🧠 **Edição Inteligente**: Identifica e corta "takes" ruins ou repetições

### Interface & Design
- 🎯 **Design Moderno**: Interface cyberpunk com tema escuro elegante
- 🎬 **Lucide Icons**: Ícones profissionais em toda a interface
- ⚡ **Lottie Animations**: Animações fluidas durante o processamento
- 📁 **File Explorer**: Gerenciador de arquivos estilo Windows
- 🖼️ **Thumbnails de Vídeo**: Pré-visualização gerada automaticamente via FFmpeg
- 🔒 **Loading Overlay**: Bloqueia interação durante processamento
- 💡 **Tooltips Informativos**: Ajuda contextual nas configurações

## 🖥️ Interface Gráfica

O projeto conta com uma **interface web moderna, responsiva e com design profissional**!

### 🎨 Design System

A interface foi desenvolvida com foco em **UX/UI profissional**:

| Aspecto | Tecnologia/Abordagem |
|---------|---------------------|
| **Tema** | Dark Cyberpunk com gradientes suaves |
| **Ícones** | Lucide Icons (biblioteca profissional) |
| **Animações** | Lottie para loading fluido |
| **Layout** | Responsivo com sidebar fixa |
| **Tipografia** | SF Pro Display, Inter (fallback) |
| **Cores** | Ciano, roxo e verde neon em fundo escuro |

### 📂 File Explorer

Gerenciador de arquivos integrado com:
- 🗂️ Navegação por pastas (breadcrumbs)
- 🖼️ Thumbnails automáticos de vídeos
- ▶️ Preview/reprodução de vídeos
- ➕ Criar novas pastas
- 🔄 Mover arquivos entre pastas
- ✏️ Renomear arquivos e pastas
- 🗑️ Deletar com confirmação
- 📤 Importar vídeos do computador

### 🚀 Iniciar Interface

```bash
# Método 1: Script de inicialização (recomendado)
python start_gui.py

# Método 2: Diretamente
python web_app.py
```

Acesse: **http://localhost:3001**

### Screenshots

A interface inclui:
- 🎯 **Explorador de Arquivos** - Navegue e gerencie seus vídeos
- ⚙️ **Painel de Configurações** - Modelo Whisper, método de corte, idioma
- 📊 **Console em Tempo Real** - Progresso via Socket.IO
- 🔄 **Loading com Animação** - Feedback visual durante processamento
- 🎨 **Design Cyberpunk** - Tema escuro moderno com ícones Lucide

## 📋 Pré-requisitos

### 1. Sistema
- **Python 3.8+**
- **FFmpeg**: Essencial para manipulação de vídeo e áudio
  - *Mac*: `brew install ffmpeg`
  - *Windows*: Baixe e adicione ao PATH
  - *Linux*: `sudo apt install ffmpeg`

### 2. API Keys (Opcional)
Para usar a correção ortográfica com IA, você precisará de uma chave do Google Gemini.

## 🚀 Instalação

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/gabuldev/auto-edit-video.git
   cd auto-edit-video
   ```

2. **Crie e ative um ambiente virtual:**
   ```bash
   python -m venv .venv
   
   # Mac/Linux:
   source .venv/bin/activate
   
   # Windows:
   .venv\Scripts\activate
   ```

3. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

## ⚙️ Configuração

### API Key do Google Gemini (Opcional)

Para habilitar a correção ortográfica com IA, configure sua API Key:

**Opção 1: Arquivo .env**
```env
GEMINI_API_KEY=sua_chave_aqui
```

**Opção 2: Via Interface Web**
- Acesse a interface e clique em "Configurar API Key"

> 💡 Obtenha sua chave em: https://aistudio.google.com/apikey

## 📖 Como Usar

### 🌐 Interface Web (Recomendado)

```bash
python start_gui.py
```

A interface oferece:
1. **Explorar Arquivos**: Navegue pela pasta `upload/` e suas subpastas
2. **Selecionar Vídeo**: Clique em um vídeo para selecioná-lo
3. **Configurar**: Ajuste modelo Whisper, método de corte e idioma
4. **Processar**: Escolha entre:
   - ✂️ **Remover Silêncio** - Corta pausas automaticamente
   - 📝 **Gerar Legendas** - Adiciona legendas estilo CapCut
   - ⚡ **Processo Completo** - Faz tudo de uma vez

### 📁 Estrutura de Pastas

O projeto usa uma estrutura fixa para organização:

```
upload/                    # Pasta principal de trabalho
├── processados/           # Vídeos processados automaticamente
├── minhas-pastas/         # Crie suas próprias pastas
└── video.mp4              # Seus vídeos para editar
```

> 💡 Você pode criar pastas, mover e organizar arquivos diretamente pela interface!

### 💻 Menu Interativo (CLI)

```bash
python cli.py
```

### 📟 Linha de Comando

```bash
python edit_video.py "caminho/do/video.mp4" --output "final.mp4"
```

**Argumentos opcionais:**
| Argumento | Descrição | Padrão |
|-----------|-----------|--------|
| `--model` | Modelo Whisper (tiny, base, small, medium, large) | `small` |
| `--language` | Idioma do áudio (pt, en, es, etc.) | `pt` |
| `--silence-method` | Método de corte (`speech` ou `volume`) | `speech` |
| `--silence-threshold` | Nível de dB para corte (modo volume) | `-40` |

## 🔒 Segurança

Este projeto foi desenvolvido para **uso local**, **rede interna** ou **internet com proteção por senha**.

### 🔐 Proteção por Senha

Para expor na internet, ative a autenticação com senha única:

```bash
# Opção 1: Senha em texto (converte para hash automaticamente)
echo "ACCESS_PASSWORD=minha_senha_secreta" >> .env

# Opção 2: Hash da senha (mais seguro para produção)
python -c "from werkzeug.security import generate_password_hash; print('ACCESS_PASSWORD_HASH=' + generate_password_hash('minha_senha_secreta'))" >> .env
```

**Com senha configurada:**
- ✅ Tela de login protege toda a aplicação
- ✅ Sessão expira após 24h (configurável)
- ✅ CORS liberado (protegido pela senha)
- ✅ Pode expor na internet (com HTTPS recomendado)

**Sem senha configurada:**
- ⚠️ Acesso livre (apenas localhost/rede local)

### ⚠️ Modos de Uso

| Modo | Senha | Internet | Segurança |
|------|-------|----------|-----------|
| **Local** | ❌ | ❌ | ✅ OK |
| **Rede Interna** | Opcional | ❌ | ✅ OK |
| **Internet** | ✅ Obrigatória | ✅ | ⚠️ Use HTTPS |

### 🛡️ Medidas de Segurança Implementadas

- **Autenticação por Senha**: Hash seguro com werkzeug
- **Path Traversal**: Bloqueio de acesso a diretórios fora do workspace
- **Validação de Arquivos**: Apenas extensões de vídeo permitidas
- **Sanitização**: Remoção de caracteres perigosos em nomes de arquivos
- **Secret Key**: Geração automática de chave secreta
- **Logs de Auditoria**: Registro de eventos de segurança
- **Sessões Seguras**: Expiração configurável

### 📝 Configuração Completa

```bash
# Copie o arquivo de exemplo
cp env.sample .env

# Gere uma chave secreta para sessões
python -c "import secrets; print('FLASK_SECRET_KEY=' + secrets.token_hex(32))" >> .env

# Configure a senha de acesso (para internet)
echo "ACCESS_PASSWORD=sua_senha_forte" >> .env

# Tempo de sessão (opcional, padrão 24h)
echo "SESSION_LIFETIME_HOURS=48" >> .env
```

### 🚨 Para Uso em Produção na Internet

1. **Obrigatório**: Configure `ACCESS_PASSWORD` ou `ACCESS_PASSWORD_HASH`
2. **Recomendado**: Use proxy reverso (nginx, Caddy) com HTTPS
3. **Recomendado**: Use `gunicorn` em vez do servidor de desenvolvimento
4. **Opcional**: Configure firewall e rate limiting no proxy

## 🗄️ Banco de Dados Local (SQLite)

O projeto usa SQLite para armazenar dados localmente:

- **Configurações persistentes** - Salvam automaticamente (modelo Whisper, idioma, etc.)
- **API Key** - Não precisa configurar toda vez
- **Histórico de vídeos** - Registro de todos os processamentos
- **Logs de atividade** - Para auditoria e debug

```bash
# O banco é criado automaticamente em:
data.db

# APIs disponíveis:
GET  /api/settings     # Configurações salvas
POST /api/settings     # Salvar configurações
GET  /api/history      # Histórico de vídeos
GET  /api/logs         # Logs de atividade
GET  /api/stats        # Estatísticas de uso
```

## 📁 Estrutura do Projeto

```
auto-edit-video/
├── 🖥️ web_app.py          # Interface web (Flask + Socket.IO)
├── 🗄️ database.py         # Banco de dados SQLite
├── 🚀 start_gui.py         # Script de inicialização da GUI
├── 📋 cli.py               # Menu interativo CLI
├── 🔇 remove_silence.py    # Módulo de remoção de silêncio
├── 📝 auto_caption.py      # Módulo de legendas
├── ✏️ edit_video.py        # Pipeline de linha de comando
├── 🤖 adk_correction.py    # Correção com Google Gemini
├── 📂 templates/           # Templates HTML
│   ├── index.html          # Interface web principal (Lucide + Lottie)
│   └── login.html          # Página de login
├── 📂 upload/              # Pasta de trabalho (workspace)
│   └── processados/        # Vídeos processados
├── 📂 agent/               # Agentes autônomos (experimental)
├── 🎬 Loading.json         # Animação Lottie do loading
├── 📄 env.sample           # Exemplo de configuração
├── 📄 data.db              # Banco de dados local (auto-gerado)
└── 📄 requirements.txt     # Dependências
```

## 🎨 Stack de Frontend

| Tecnologia | Uso |
|------------|-----|
| **Tailwind CSS** | Estilização via CDN |
| **Lucide Icons** | Ícones vetoriais profissionais |
| **Lottie Web** | Animações JSON fluidas |
| **Socket.IO** | Comunicação em tempo real |
| **Vanilla JS** | Sem frameworks pesados |

## ⚡ Modelos Whisper

| Modelo | Velocidade | Precisão | VRAM |
|--------|------------|----------|------|
| `tiny` | ⚡⚡⚡⚡⚡ | ⭐⭐ | ~1 GB |
| `base` | ⚡⚡⚡⚡ | ⭐⭐⭐ | ~1 GB |
| `small` | ⚡⚡⚡ | ⭐⭐⭐⭐ | ~2 GB |
| `medium` | ⚡⚡ | ⭐⭐⭐⭐⭐ | ~5 GB |
| `large` | ⚡ | ⭐⭐⭐⭐⭐ | ~10 GB |

> 💡 **Recomendação**: Use `small` para a maioria dos casos. Ele oferece o melhor equilíbrio entre velocidade e qualidade.

## 🎨 Personalização das Legendas

As legendas são geradas no formato `.ass` com:
- Fonte: Prohibition (ou fallback para Montserrat/Arial)
- Destaque: Palavra atual em laranja/vermelho
- Posição: Centro inferior
- Máximo: 4 palavras por linha

## 📝 Notas

- O processo de transcrição pode ser pesado em modelos maiores
- Modelos `medium` e `large` requerem GPU para performance adequada
- As fontes personalizadas funcionam ao "queimar" a legenda no vídeo
- Thumbnails de vídeos são gerados e cacheados em `.thumbnails/`

## 🤝 Contribuindo

Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.

## 📄 Licença

Este projeto está sob a licença MIT.

---

**Feito com ❤️ e IA** | [Whisper](https://github.com/openai/whisper) • [Google Gemini](https://ai.google.dev/) • [Lucide Icons](https://lucide.dev/) • [Lottie](https://airbnb.io/lottie/)
