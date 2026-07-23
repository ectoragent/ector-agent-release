---
name: react-typescript
description: "Padrões React + TypeScript: componentes, hooks, tipagem estrita, composição. Triggers: React, TSX, hooks, props, generics, component library."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# React + TypeScript

## Quando usar
- Componentes React com TypeScript
- Refactors de props/hooks, libraries de UI, tipagem de eventos/forms

## Passos
1. Confirme a stack do projeto antes de inventar a sua — hoje o default costuma ser Vite + Tailwind + shadcn/ui (Radix) + TanStack Query; siga o que já existe no repo.
2. Prefira componentes função + hooks; evite classes.
3. Tipagem: props explícitas; evite `any`; use `unknown` + narrowing.
4. Estado: local com `useState`/`useReducer`; server state vai em TanStack Query (`state-data-fetching`), não em `useEffect`+`fetch` manual.
5. Efeitos: `useEffect` só para sync com o mundo externo; derive estado quando possível.
6. Variantes de componente (tamanho/cor/estado) com `cva`, não classes concatenadas na mão (ver `shadcn-radix-ui`, `tailwind-css`).
7. Listas: `key` estável; memoize só com medição (React Compiler / profiling).
8. Acessibilidade: labels, roles, foco — veja também `frontend-a11y`.

## Armadilhas
- Propagar context demais → re-renders; fatie providers.
- `useEffect` para calcular valor derivado.
- Tipar children como `any` ou omitir handlers.
- Buscar dados com `useEffect`+`fetch` manual quando o projeto já usa TanStack Query.

## Verificação
- `tsc --noEmit` limpo; componente renderiza sem warnings; props públicas documentadas.

