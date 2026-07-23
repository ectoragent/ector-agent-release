---
name: typography-web-fonts
description: "Tipografia web: escala, hierarquia, carregamento de fontes, legibilidade. Triggers: web fonts, font-display, variable font, type scale, line-height, legibilidade, tipografia."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Tipografia & Web Fonts

## Quando usar
- Definir sistema tipográfico de um site, corrigir FOIT/FOUT, melhorar legibilidade de conteúdo

## Passos
1. Escala tipográfica limitada (4–6 tamanhos) com ritmo consistente (ex.: modular scale 1.25).
2. `line-height` maior em corpo de texto (1.5–1.6) e menor em headings (1.1–1.3).
3. Largura de linha legível: ~45–75 caracteres por linha no corpo do texto.
4. `font-display: swap` (ou `optional` se layout shift importa mais que ver a fonte rápido); preload da fonte crítica do hero.
5. Subset de fonte (só os charsets usados) e formato `woff2` para peso mínimo.
6. Variable fonts quando precisa de múltiplos pesos — um arquivo só em vez de vários downloads.
7. Contraste de texto AA/AAA; hierarquia não pode depender só de cor.

## Armadilhas
- FOIT (texto invisível) esperando fonte custom carregar sem fallback decente.
- `line-height` apertado demais em blocos longos de texto.
- Carregar 6 pesos de fonte quando o site usa só 2.

## Verificação
- CLS baixo causado por fonte; texto legível em mobile sem precisar de zoom; peso de fonte carregado é o realmente usado no site.
