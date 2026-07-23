---
name: css-design-systems
description: "CSS e design systems: tokens, theming, Tailwind/CSS modules, consistência visual. Triggers: Tailwind, design system, CSS variables, theme, tokens."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# CSS & Design Systems

## Quando usar
- Estilizar UI, alinhar a um design system, theming light/dark

## Passos
1. Use tokens do sistema (cor, espaço, tipo, radius) — não hex soltos.
2. Prefira primitives do DS/shadcn antes de CSS custom (ver `shadcn-radix-ui`); utilities do Tailwind antes de CSS solto (ver `tailwind-css`).
3. Layout: flex/grid; spacing consistente (escala 4/8); classes condicionais sempre via `cn()` (`clsx`+`tailwind-merge`).
4. Dark mode via tokens/CSS vars, não overrides ad hoc.
5. Responsivo mobile-first; breakpoints do DS.
6. Container queries (`@container`) quando o componente precisa reagir ao pai, não à viewport.
7. CSS moderno com bom suporte: `:has()`, `gap` em flex, `clamp()` para fluid type/spacing, subgrid.
8. Evite `!important` e z-index mágicos — documente stacking.

## Armadilhas
- Duplicar componentes que o DS já tem.
- Valores mágicos fora da escala.
- CSS global que vaza entre rotas.
- Breakpoint de viewport para um componente que na verdade precisa de container query.

## Verificação
- UI alinhada aos tokens; tema alterna sem regressão; sem CSS morto óbvio.

