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

## Saída

Responda **só** com um objeto JSON:

- Ficou bom (fiel à referência / ao pedido e sem defeitos): `{"ok": true}`
- Precisa corrigir: `{"html": "<div ...>...</div>"}` com o HTML **completo**
  corrigido.
