import os
import sys
from dotenv import load_dotenv

# Load .env from parent directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(parent_dir, '.env'))

import sys
import os

# Adiciona o diretório atual ao path para permitir imports absolutos como se estivesse na raiz
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.models.lite_llm import LiteLlm

try:
    from .tools import (
        list_videos, 
        remove_silence_tool, 
        add_subtitles_tool,
        analyze_takes_tool,
        cut_segments_tool
    )
except ImportError:
    # Fallback para execução direta ou via ADK onde 'agent' é um pacote
    try:
        from agent.tools import (
            list_videos, 
            remove_silence_tool, 
            add_subtitles_tool,
            analyze_takes_tool,
            cut_segments_tool
        )
    except ImportError:
        # Última tentativa: import direto do tools se estiver no path
        from tools import (
            list_videos, 
            remove_silence_tool, 
            add_subtitles_tool,
            analyze_takes_tool,
            cut_segments_tool
        )

# Helper para configurar modelo Ollama via LiteLLM
def get_ollama_model():
    model_name = os.environ.get("OLLAMA_MODEL", "llama3")
    # LiteLLM usa o formato "provider/model"
    # Para Ollama é geralmente "ollama/modelo" ou "ollama_chat/modelo"
    return LiteLlm(model=f"ollama_chat/{model_name}")

# --- Specialized Agents ---

cutter_agent = Agent(
    name="cutter_agent",
    model=get_ollama_model(),
    description="Especialista em remover silêncio de vídeos.",
    instruction="""
    Você é um editor de vídeo especialista em remover silêncio (jumpcuts).
    Sua única função é receber um vídeo e usar a ferramenta 'remove_silence_tool' para processá-lo.
    Sempre informe o usuário sobre o resultado.
    """,
    tools=[FunctionTool(remove_silence_tool)]
)

captioner_agent = Agent(
    name="captioner_agent",
    model=get_ollama_model(),
    description="Especialista em transcrever e legendar vídeos.",
    instruction="""
    Você é um especialista em legendagem.
    Sua função é adicionar legendas estilosas (estilo CapCut) aos vídeos.
    Use a ferramenta 'add_subtitles_tool'.
    Se o usuário não especificar o modelo, use 'small'.
    Se tiver algo escrito GABU, substitua por GABUL.
    """,
    tools=[FunctionTool(add_subtitles_tool)]
)

reviewer_agent = Agent(
    name="reviewer_agent",
    model=get_ollama_model(),
    description="Especialista em validar conteúdo e remover erros de gravação.",
    instruction="""
    Você é um revisor de conteúdo de vídeo.
    Seu trabalho é identificar quando o orador erra uma frase e a repete logo em seguida.
    
    Processo:
    1. Use 'analyze_takes_tool' para obter a lista de erros/redundâncias no vídeo.
    2. Analise a resposta. Se houver erros, informe ao usuário o que foi encontrado (ex: "Encontrei 2 tentativas falhas entre 0:10 e 0:15").
    3. Pergunte se o usuário quer proceder com os cortes OU, se o usuário já deu carta branca, prossiga.
    4. Use 'cut_segments_tool' passando o JSON exato retornado pela análise para remover os trechos ruins.
    """,
    tools=[FunctionTool(analyze_takes_tool), FunctionTool(cut_segments_tool)]
)

# --- Manager Agent ---

root_agent = Agent(
    name="root_agent",
    model=get_ollama_model(),
    description="Gerente da equipe de edição de vídeo.",
    instruction="""
    Você é o gerente de uma equipe de pós-produção de vídeo.
    Você tem acesso a agentes especialistas:
    - cutter_agent: Remove silêncio automaticamente.
    - reviewer_agent: Analisa o conteúdo, remove erros de fala e takes ruins.
    - captioner_agent: Adiciona legendas.
    
    E ferramentas:
    - list_videos: Para ver quais arquivos estão disponíveis.
    
    Fluxo de trabalho sugerido para "Processo Completo":
    1. Remover Silêncio (cutter_agent).
    2. Validar Conteúdo/Remover Erros (reviewer_agent) no vídeo cortado.
    3. Legendar (captioner_agent) o vídeo final limpo.
    
    Sempre coordene o fluxo passando o nome do arquivo resultante de um passo para o próximo.
    """,
    tools=[FunctionTool(list_videos)],
    sub_agents=[cutter_agent, captioner_agent, reviewer_agent]
)
