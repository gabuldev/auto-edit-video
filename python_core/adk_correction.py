import os
import google.generativeai as genai

def corrigir_palavras_com_adk(words_list: list, api_key: str = None):
    """
    Usa o Google Gemini para corrigir a grafia das palavras mantendo a sincronia.
    (Anteriormente usava 'adk', agora usa 'google.generativeai' diretamente para evitar erros de importação)
    """
    print(f"[AI Correction] Inicializando agente de correção...")
    
    # Configura o cliente se a chave for passada explicitamente
    if api_key:
        genai.configure(api_key=api_key)
    
    # Define o System Prompt
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
    """

    # Cria o modelo Gemini diretamente
    try:
        # Tenta usar system_instruction (versões mais recentes da lib)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_prompt
        )
    except TypeError:
        # Fallback para versões antigas que não aceitam system_instruction no init
        print("⚠️  Versão antiga do google-generativeai detectada. Tentando inicialização padrão...")
        model = genai.GenerativeModel("gemini-2.5-flash")
    except Exception as e:
        print(f"❌ Erro ao inicializar modelo Gemini (Verifique sua API KEY no .env): {e}")
        return words_list
    
    print(f"[AI Correction] Modelo pronto. Processando {len(words_list)} palavras...")
    
    # Processamento em lotes (Batch)
    BATCH_SIZE = 100
    corrected_words_list = []
    all_texts = [w['word'].strip() for w in words_list]
    
    for i in range(0, len(all_texts), BATCH_SIZE):
        batch = all_texts[i:i+BATCH_SIZE]
        batch_str = " | ".join(batch)
        
        prompt = f"Corrija esta lista:\n{batch_str}"
        
        try:
            # generate_content aceita string direta
            response = model.generate_content(prompt)
            # Acessa o texto
            texto_retornado = response.text.strip()
            
            palavras_corrigidas = [p.strip() for p in texto_retornado.split('|')]
            
            if len(palavras_corrigidas) != len(batch):
                print(f"⚠️  [AI] Desvio de tamanho no lote {i//BATCH_SIZE}. Original: {len(batch)}, IA: {len(palavras_corrigidas)}. Ignorando.")
                corrected_words_list.extend(batch)
            else:
                corrected_words_list.extend(palavras_corrigidas)
                
        except Exception as e:
            print(f"❌ [AI] Erro na requisição: {e}")
            corrected_words_list.extend(batch)

    # Reconstrói lista
    new_words_list = []
    for original_obj, new_text in zip(words_list, corrected_words_list):
        new_obj = original_obj.copy()
        new_obj['word'] = new_text
        new_words_list.append(new_obj)
        
    print("[AI Correction] Correção concluída.")
    return new_words_list
