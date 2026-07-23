---
name: frontend-a11y
description: "Acessibilidade web: teclado, ARIA, contraste, forms, leitores de tela. Triggers: a11y, WCAG, screen reader, foco, aria, acessibilidade."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Frontend A11Y

## Quando usar
- Forms, modais, menus, compliance WCAG, bugs de teclado/SR

## Passos
1. HTML semântico primeiro (`button`, `a`, `label`, headings).
2. Teclado: tab order lógico; Escape fecha overlays; foco preso em modal.
3. ARIA só quando HTML não basta; não duplique roles.
4. Contraste AA; não use só cor para estado.
5. Forms: `label` associado, erros anunciados (`aria-live` / `aria-describedby`).
6. Imagens: alt útil ou alt vazio se decorativas.
7. Teste com teclado + um SR (VoiceOver/NVDA) nas flows críticas.

## Armadilhas
- `div onClick` sem role/keyboard.
- `outline: none` sem foco visível alternativo.
- Modais sem retorno de foco.

## Verificação
- axe/lighthouse a11y limpo nas telas tocadas; flow crítico 100% teclado.

