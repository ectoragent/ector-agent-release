---
name: design-critique-handoff
description: "Critique e handoff design→dev: specs, estados, assets, QA visual. Triggers: handoff, design review, critique, Figma dev mode, QA visual."
version: 1.0.0
metadata:
  ector:
    tags: [design, builtin]
    category: design
---

# Design Critique Handoff

## Quando usar
- Review de design, handoff para implementação, QA visual

## Passos
1. Critique: clareza do problema, hierarquia, a11y, edge states.
2. Handoff: todos os estados (hover/focus/error/empty), breakpoints, tokens.
3. Assets exportados (SVG/PDF) e naming estável.
4. Anote interações e motion (duração/easing) se houver.
5. Dev: tire dúvidas antes de inventar; compare build vs design em QA.

## Armadilhas
- Handoff só do happy path desktop.
- Medidas inconsistentes com tokens.
- Feedback vago ("não gostei") sem critério.

## Verificação
- Checklist de estados completo; diff visual das telas críticas aprovado.

