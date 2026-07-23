---
name: shadcn-radix-ui
description: "shadcn/ui + Radix: componentes copy-paste, acessibilidade pronta, cva, customização local. Triggers: shadcn, shadcn/ui, Radix UI, radix-ui, cva, class-variance-authority, components/ui."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# shadcn/ui & Radix UI

## Quando usar
- Montar biblioteca de componentes de UI, precisar de primitives acessíveis (dialog, dropdown, popover, select), customizar um componente gerado pelo shadcn

## Passos
1. shadcn/ui não é uma lib npm — o código vai para `components/ui/` do seu repo; você é dono e edita livremente, sem "ejetar" nada.
2. Gere a base com o CLI do shadcn (`add <componente>`) em vez de recriar do zero o que já existe no catálogo.
3. Radix UI por baixo resolve teclado/foco/ARIA (dialog, menu, popover) — não reimplemente esse comportamento na mão com `div`+state.
4. Variantes via `cva` (`variant`, `size`, etc.), tipadas; componha com `cn()` (`clsx`+`tailwind-merge`) para permitir override seguro via `className`.
5. `asChild` (Radix Slot) para trocar o elemento renderizado sem duplicar markup — ex. `<Button asChild><Link .../></Button>`.
6. Tema via tokens/CSS vars do Tailwind (`--primary`, `--radius`, etc.); trocar tema não deve exigir editar cada componente individualmente.
7. Composição sobre configuração: componha primitives (`Dialog.Root/Trigger/Content`) em vez de um componente monolítico com props gigantes.
8. Acessibilidade do conteúdo ainda é sua responsabilidade (labels, alt, foco inicial) — Radix cobre o esqueleto de interação, não o conteúdo.

## Armadilhas
- Procurar o componente em `node_modules` para editar — ele é local, o arquivo já está em `components/ui/`.
- Reimplementar dialog/menu com `div`+state próprio quando Radix já resolve foco/escape/click-outside.
- `className` acumulando lógica condicional gigante em vez de variantes `cva` bem definidas.

## Verificação
- Componente navega/fecha por teclado (Tab/Escape/setas) sem código extra; tema muda só via tokens; variantes cobrem os casos reais sem `className` mágico por instância.
