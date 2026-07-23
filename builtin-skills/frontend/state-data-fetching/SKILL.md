---
name: state-data-fetching
description: "Estado servidor vs cliente com TanStack Query (default) ou SWR: cache, invalidação, optimistic UI. Triggers: tanstack query, react-query, SWR, cache, invalidate, refetch, queryOptions, useSuspenseQuery."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# State Data Fetching

## Quando usar
- Fetch de API no client, cache, sync após mutação, loading/error UX
- Default do stack atual: TanStack Query para server state — não reinvente cache em Redux/Context

## Passos
1. Separe server state (TanStack Query) de UI state (`useState`/`useReducer`) — não duplique um no outro.
2. Query keys estáveis e hierárquicas (`['chats', chatId, 'messages']`); inclua todos os params que afetam o resultado.
3. `queryOptions()` para definir key+fn+options reutilizáveis entre `useQuery`/`prefetchQuery`/`useSuspenseQuery`.
4. Após mutation: `invalidateQueries` (mais simples) ou update otimista via `onMutate`/`onError` com rollback.
5. Trate `isPending` / `isFetching` / `isError` de forma distinta na UX (skeleton ≠ refetch em background ≠ erro).
6. `staleTime` consciente por tipo de dado; `gcTime` (v5, era `cacheTime`) para quanto tempo manter em memória sem uso.
7. Prefetch em rotas previsíveis (hover/link) com `queryClient.prefetchQuery`.
8. React Query Devtools em dev para inspecionar cache e estado das queries.

## Armadilhas
- Duplicar a mesma query com keys diferentes (cache nunca é compartilhado entre elas).
- Optimistic UI sem rollback (`onError` não reverte o `setQueryData`).
- Guardar resposta de API em Redux/Context sem motivo — TanStack Query já é a fonte de verdade do server state.

## Verificação
- Mutação reflete na UI; refresh não mostra dados fantasma; erros recuperáveis.

