---
name: user-stories-acceptance
description: "User stories e acceptance criteria: INVEST, Given/When/Then, slicing. Triggers: user story, acceptance criteria, Gherkin, backlog refinement."
version: 1.0.0
metadata:
  ector:
    tags: [product, builtin]
    category: product
---

# User Stories & Acceptance Criteria

## Quando usar
- Escrever/refinar stories, AC, splitting de backlog

## Passos
1. Formato: como [persona], quero [capacidade], para [resultado].
2. AC testáveis (Given/When/Then); inclua erros e limites.
3. INVEST: independente, negociável, valiosa, estimável, small, testável.
4. Fatia vertical (end-to-end fino) > fatias só de UI ou só de API.
5. Links a designs/métricas; defina out-of-scope.

## Armadilhas
- Stories técnicas disfarçadas sem valor de usuário.
- AC vagos ("rápido", "intuitivo").
- Escopo que não cabe em uma iteração.

## Verificação
- Dev/QA conseguem testar só com a story; demo mostra valor.

