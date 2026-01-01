import os
import requests
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OllamaAgent:
    def __init__(self, model=None, url=None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3")
        self.url = url or os.environ.get("OLLAMA_API_URL", "http://localhost:11434")
        
        if self.url.endswith("/"):
            self.url = self.url[:-1]
            
        logger.info(f"OllamaAgent initialized with model: {self.model} at {self.url}")

    def generate(self, prompt, system=None, format=None, stream=False):
        """
        Generic method to call Ollama Generate API
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream
        }
        
        if system:
            payload["system"] = system
            
        if format:
            payload["format"] = format
            
        try:
            response = requests.post(f"{self.url}/api/generate", json=payload)
            response.raise_for_status()
            
            data = response.json()
            return data.get("response", "").strip()
        except Exception as e:
            logger.error(f"Error calling Ollama API: {e}")
            raise e

    def correct_words(self, words_list: list) -> list:
        """
        Corrigir a grafia das palavras mantendo a sincronia.
        Logic ported from adk_correction.py
        """
        system_prompt = """
        Você é um revisor de legendas ortográfico e gramatical EXPERT.
        Sua missão é corrigir erros de português em uma lista de palavras, mantendo ESTRITAMENTE a estrutura.
        
        REGRAS DE OURO:
        1. Você receberá palavras separadas por ' | '.
        2. Você deve retornar as palavras corrigidas separadas por ' | '.
        3. A quantidade de palavras na saída DEVE SER IDÊNTICA à entrada.
        4. NÃO mude a ordem das palavras.
        5. Corrija apenas: erros de digitação, acentuação (ex: 'eh' -> 'é', 'voce' -> 'você') e gramática óbvia.
        6. Não mude o estilo (gírias podem ser mantidas se estiverem grafadas corretamente, ex: 'tá' é aceitável, mas 'ta' deve virar 'tá').
        7. Se não houver erro, repita a palavra original.
        8. Retorne APENAS o texto corrigido, sem explicações.
        """

        logger.info(f"Correcting {len(words_list)} words...")
        
        # Batch processing
        BATCH_SIZE = 100
        corrected_words_list = []
        all_texts = [w['word'].strip() for w in words_list]
        
        for i in range(0, len(all_texts), BATCH_SIZE):
            batch = all_texts[i:i+BATCH_SIZE]
            batch_str = " | ".join(batch)
            
            prompt = f"Corrija esta lista:\n{batch_str}"
            
            try:
                texto_retornado = self.generate(prompt, system=system_prompt)
                
                palavras_corrigidas = [p.strip() for p in texto_retornado.split('|')]
                
                if len(palavras_corrigidas) != len(batch):
                    logger.warning(f"Batch size mismatch. Original: {len(batch)}, AI: {len(palavras_corrigidas)}. Ignoring batch.")
                    corrected_words_list.extend(batch)
                else:
                    corrected_words_list.extend(palavras_corrigidas)
                    
            except Exception as e:
                logger.error(f"Batch processing error: {e}")
                corrected_words_list.extend(batch)

        # Reconstruct list
        new_words_list = []
        for original_obj, new_text in zip(words_list, corrected_words_list):
            new_obj = original_obj.copy()
            new_obj['word'] = new_text
            new_words_list.append(new_obj)
            
        logger.info("Correction completed.")
        return new_words_list

    def analyze_takes(self, transcript_text: str) -> str:
        """
        Analisa a transcrição do vídeo para encontrar takes repetidos ou errados.
        Logic ported from agent/tools.py analyze_takes_tool
        """
        prompt = f"""
        Analise a seguinte transcrição de um vídeo bruto. 
        O orador pode ter cometido erros e repetido frases (takes ruins).
        Identifique os trechos que são claramente erros, gaguejadas ou tentativas falhas que foram corrigidas logo em seguida.
        
        TAMBÉM verifique grandes pausas ou silêncios que não foram transcritos mas podem ser inferidos pelos timestamps.
        
        Transcrição:
        {transcript_text}
        
        Retorne APENAS um JSON com a lista de intervalos para REMOVER.
        Seja conservador: Só remova se tiver CERTEZA que é um erro ou repetição desnecessária.
        
        Formato:
        {{
            "remove_intervals": [
                {{"start": 10.5, "end": 15.2, "reason": "Errou a frase e repetiu"}},
                ...
            ]
        }}
        Se não houver nada para remover, retorne lista vazia.
        """
        
        return self.generate(prompt, format="json")

