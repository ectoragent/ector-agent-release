---
name: nextjs-app-router
description: "Next.js App Router: rotas, Server/Client Components, data fetching, caching, metadata. Triggers: Next.js, app/, RSC, server actions, route handlers."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Next.js App Router

## Quando usar
- Apps Next.js (App Router), migração pages→app, SSR/SSG/ISR

## Passos
1. Mapeie `app/` (layouts, pages, route groups, parallel routes).
2. Default = Server Component; marque `"use client"` só para interatividade/browser APIs.
3. Data: fetch no server com cache explícito; Client Components usam TanStack Query ou similar.
4. Mutations: Server Actions ou Route Handlers; valide input no server.
5. Metadata/OG em `generateMetadata`; não hardcode só no client.
6. Imagens: `next/image`; links: `next/link`; evite waterfalls desnecessários.
7. Env: `NEXT_PUBLIC_*` só para o que pode vazar no browser.

## Armadilhas
- Importar módulo server-only em Client Component.
- Cache stale sem `revalidate` / tags.
- Secrets em `NEXT_PUBLIC_`.

## Verificação
- Build (`next build`) ok; rotas críticas respondem; sem secrets no bundle client.

