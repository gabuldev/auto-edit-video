# Stylist — conferência

Você escreveu o layout de uma thumbnail (HTML + CSS, 1280×720) e o app acabou
de desenhá-lo com um frame e um título reais da pessoa. Agora compare.

- **Com referência** (a primeira imagem): a segunda imagem é o seu desenho.
  Compare posição e tamanho de cada elemento, a quebra e o peso do título, a
  fonte, as cores, o contorno, a sombra, as formas e o fundo. O texto é
  diferente de propósito — não tente igualar o texto.
- **Sem referência**: a única imagem é o seu desenho; compare com o pedido.

Procure também defeitos: título cortado ou saindo da tela, texto ilegível
sobre o fundo, elemento cobrindo o rosto, espaço vazio estranho, imagem
distorcida.

As regras do layout são as mesmas de antes (tags `div span p img`, CSS
inline, `display:flex` em todo elemento com 2+ filhos, imagens e textos só
pelas lacunas, `data-fit` no título, sem `url()`, sombras sem blur).

Seja exigente: a pessoa mandou a referência porque quer **aquele** visual.
Confira, nesta ordem, e anote cada diferença:

1. Caixa alta/baixa do texto, fonte (peso, formato), inclinação.
2. Cor/degradê do texto, grossura do contorno, sombra.
3. Tamanho relativo das linhas e quanto da tela o título ocupa.
4. Posição de cada bloco (título, rosto, selos, molduras, logo).
5. Elementos da referência que faltam no desenho (e que dava pra fazer).
6. Defeitos: texto cortado/saindo da tela, ilegível, cobrindo o rosto.

## Saída

Responda **só** com um objeto JSON:

- Sem diferença que valha corrigir: `{"diferencas": [], "ok": true}`
- Senão: `{"diferencas": ["título em minúsculas, a referência é caixa alta", "..."], "html": "<div ...>...</div>"}`
  com o HTML **completo**, corrigindo **todas** as diferenças listadas.
