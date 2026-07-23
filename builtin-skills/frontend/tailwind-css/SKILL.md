---
name: tailwind-css
description: "Tailwind CSS: utility-first, tema via config/@theme, variantes, cn()/tailwind-merge. Triggers: Tailwind, tailwindcss, utility-first, @apply, tailwind.config, cn(), tailwind-merge, clsx."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Tailwind CSS

## Quando usar
- Estilizar com Tailwind, migrar CSS solto para utilities, configurar tema/tokens no Tailwind

## Passos
1. Utility-first no JSX/template; se um conjunto de classes se repete 3+ vezes, extraia componente — não crie classe CSS custom.
2. Tema no `tailwind.config`/`@theme` (v4): cores, spacing, radius, fontes mapeados aos tokens do design system — nunca hex/px soltos direto nas classes.
3. Classes condicionais com `clsx`/`cva` + `tailwind-merge` via um helper `cn()` — evita duas classes da mesma propriedade brigando (`px-2` vs `px-4`).
4. Variantes de componente com `class-variance-authority` (`cva`), tipadas — não string concatenada manual (`isActive ? 'bg-blue' : ''`).
5. Responsivo mobile-first (`sm:`/`md:`/`lg:`); estado com `hover:`/`focus-visible:`/`disabled:`; dark mode via `dark:` ligado a tokens, não hardcoded.
6. `@apply` só para casos raros (reset de lib externa) — não vire uma segunda linguagem de CSS paralela às utilities.
7. Arbitrary values (`w-[137px]`) são escape hatch, não padrão; se aparece toda hora, falta um token na escala.
8. Purga/JIT automáticos — cuidado com classes montadas por template string dinâmica (`` `text-${color}-500` ``), o compilador não enxerga isso.

## Armadilhas
- Classe dinâmica construída por interpolação de string — o Tailwind não gera essa classe no build final.
- `cn()`/`clsx` esquecido → resultado final depende da ordem de import do CSS, não da intenção do código.
- Reimplementar em CSS custom algo que já é um utility pronto do Tailwind.

## Verificação
- Build de produção contém as classes usadas (nada cortado pelo purge); trocar tema é só mudar tokens/config; nenhum `!important` para vencer especificidade.
