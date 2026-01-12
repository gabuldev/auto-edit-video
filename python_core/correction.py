import os
import sys
import typing

try:
    import google.generativeai as genai
except ImportError:
    genai = None

def corrigir_palavras_com_gemini(words_list: list, api_key: str):
    """
    Recebe uma lista de dicionários de palavras [{'word': 'oi', 'start': 0, 'end': 1}, ...]
    Usa o Gemini para corrigir a grafia das palavras mantendo a sincronia.
    """
    if not genai:
        print("❌ Biblioteca 'google-generativeai' não instalada.")
        return words_list

    if not api_key:
        print("⚠️  API Key do Google não fornecida. Pulando correção.")
        return words_list

    print(f"[IA] Conectando ao Google Gemini para corrigir {len(words_list)} palavras...")
    
    genai.configure(api_key=api_key)
    
    # Configuração do modelo
    generation_config = {
        "temperature": 0.1, # Baixa criatividade, foco em precisão
        "top_p": 1,
        "top_k": 1,
        "max_output_tokens": 8192,
    }

    model = genai.GenerativeModel(model_name="gemini-2.5-flash", generation_config=generation_config)

    # Para evitar estourar o contexto ou limites, vamos processar em lotes grandes (ex: 50 palavras)
    # O ideal é mandar frases completas, mas como temos uma lista de palavras soltas do whisper,
    # vamos agrupar e pedir para ele devolver a lista corrigida.
    
    BATCH_SIZE = 100
    corrected_words_list = []
    
    # Extrai apenas o texto para enviar
    all_texts = [w['word'].strip() for w in words_list]
    
    for i in range(0, len(all_texts), BATCH_SIZE):
        batch = all_texts[i:i+BATCH_SIZE]
        batch_str = " | ".join(batch)
        
        prompt = f"""
        Você é um revisor de legendas em Português.
        Abaixo está uma lista de palavras extraídas de um áudio (separadas por ' | ').
        Sua tarefa é corrigir APENAS a ortografia e acentuação (ex: 'voce' -> 'você', 'eh' -> 'é').
        
        REGRAS CRÍTICAS:
        1. Mantenha EXATAMENTE o mesmo número de palavras.
        2. NÃO mude a ordem.
        3. NÃO reescreva a frase para mudar o sentido. Apenas corrija erros óbvios.
        4. Retorne as palavras corrigidas separadas por ' | '.
        5. Se a palavra já estiver correta, mantenha ela.
        
        Lista:
        {batch_str}
        """
        
        try:
            response = model.generate_content(prompt)
            texto_retornado = response.text.strip()
            
            # Tenta separar
            palavras_corrigidas = [p.strip() for p in texto_retornado.split('|')]
            
            # Validação de segurança: Se o número de palavras mudou, ignoramos a correção desse lote
            if len(palavras_corrigidas) != len(batch):
                print(f"⚠️  Aviso: O Gemini retornou {len(palavras_corrigidas)} palavras, mas enviei {len(batch)}. Ignorando correção deste lote para não quebrar sincronia.")
                corrected_words_list.extend(batch) # Usa original
            else:
                corrected_words_list.extend(palavras_corrigidas)
                
        except Exception as e:
            print(f"❌ Erro ao chamar API do Gemini: {e}")
            corrected_words_list.extend(batch) # Usa original em caso de erro

    # Reconstrói a lista de objetos com os timestamps originais e texto novo
    new_words_list = []
    for original_obj, new_text in zip(words_list, corrected_words_list):
        new_obj = original_obj.copy()
        new_obj['word'] = new_text
        new_words_list.append(new_obj)
        
    print("[IA] Correção concluída.")
    return new_words_list

