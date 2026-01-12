# Auto Video Editor Agent

Este diretório contém a implementação do agente usando o **Google Agent Development Kit (ADK)**.

O sistema é composto por 3 agentes:
1. **root_agent (Gerente)**: Orquestra o trabalho e delega tarefas.
2. **cutter_agent**: Especialista em remover silêncio.
3. **captioner_agent**: Especialista em legendas.

## Como Executar

Certifique-se de estar em um ambiente Python (>= 3.10) onde as dependências do projeto estejam instaladas (whisper, pysubs2, google-generativeai, google-adk).

1. Instale o ADK e dependências (se ainda não tiver):
   ```bash
   pip install google-adk openai-whisper pysubs2 python-dotenv google-generativeai
   ```

2. Execute o agente interativo:
   ```bash
   adk run agent
   ```

3. Interaja com o gerente:
   - "Liste os vídeos para mim"
   - "Corte o vídeo X"
   - "Legende o vídeo Y"
   - "Faça o processo completo no vídeo Z"

## Estrutura

- `agent.py`: Definição dos agentes e do fluxo.
- `tools.py`: Wrappers para os scripts originais (`remove_silence.py`, `auto_caption.py`) que funcionam como ferramentas para os agentes.

