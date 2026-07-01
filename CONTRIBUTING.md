# Contributing

Obrigado pelo interesse em contribuir com o **auto-edit-video**! 🎬

## Antes de começar

- Abra uma issue descrevendo o bug/feature antes de mandar um PR grande.
- Rode os checks locais antes de submeter:

```bash
python -m pytest tests/ -v
ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501
bash -n ralph.sh
```

- Nunca commite direto na `main` — sempre use branch + PR.

## Licença das contribuições (importante)

Este projeto é distribuído sob a **PolyForm Noncommercial License 1.0.0**
(uso não-comercial), enquanto o mantenedor oferece licenças comerciais e uma
versão hosted paga à parte (modelo *dual licensing*).

Para que esse modelo funcione, o mantenedor precisa deter todos os direitos
sobre o código. Por isso:

> Ao enviar uma contribuição (Pull Request, patch, ou qualquer código) para
> este projeto, você declara que é o autor do trabalho e **concede ao mantenedor
> do projeto (Gabriel Sampaio / gabuldev) uma licença perpétua, mundial, não
> exclusiva, isenta de royalties e irrevogável — incluindo o direito de
> relicenciar** a sua contribuição sob quaisquer termos, inclusive licenças
> comerciais e proprietárias.**

Isso preserva a capacidade do mantenedor de vender licenças comerciais e manter
a versão hosted. Se você não concorda com esses termos, por favor não envie
contribuições de código.

Contribuições de documentação, tradução e reporte de bugs são muito bem-vindas
sob as mesmas condições.

## Dúvidas

Abra uma issue ou entre em contato: contato@gabul.dev
