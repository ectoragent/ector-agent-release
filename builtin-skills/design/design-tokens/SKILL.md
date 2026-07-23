---
name: design-tokens
description: "Design tokens: cor, tipo, espaço, export para código. Triggers: design tokens, Figma variables, theme tokens, CSS variables."
version: 1.0.0
metadata:
  ector:
    tags: [design, builtin]
    category: design
---

# Design Tokens

## Quando usar
- Criar/manter tokens, sync design↔código, theming

## Passos
1. Camadas: primitive → semantic → component.
2. Nomeie por papel (`color.text.muted`), não por valor (`color.gray.500`) na camada semântica.
3. Documente dark/light e estados (hover/disabled).
4. Exporte para CSS vars / Tailwind theme / estilo nativo.
5. Breaking changes de token = migração versionada.

## Armadilhas
- Tokens semânticos apontando direto a hex sem primitives.
- Tokens mortos não usados.
- Divergência Figma vs código.

## Verificação
- Tema troca só por tokens; amostra de componentes sem hex hardcoded.

