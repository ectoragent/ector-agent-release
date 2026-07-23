---
name: frontend-performance
description: "Performance frontend: Core Web Vitals, bundle, lazy load, imagens, waterfall. Triggers: LCP, CLS, INP, bundle size, slow page, performance."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Frontend Performance

## Quando usar
- Página lenta, métricas ruins, otimização de bundle/imagens

## Passos
1. Meça antes: Lighthouse/Web Vitals (LCP, CLS, INP) + Network/Performance.
2. LCP: imagem/hero prioritária, preload font crítica, HTML server-first.
3. CLS: dimensões em img/embed; reserve espaço para ads/fonts.
4. INP: menos JS no main thread; defer listeners pesados; split code.
5. Bundle: analise (`source-map-explorer` / bundle analyzer); lazy routes e libs pesadas.
6. Listas longas: virtualização; imagens: responsive + modern formats.
7. Cache HTTP/CDN e HTTP/2/3 quando aplicável.

## Armadilhas
- Otimizar sem baseline.
- Lazy-load do LCP element.
- Hydration de árvores enormes sem necessidade.

## Verificação
- Vitais melhoram no lab e, se possível, RUM; bundle das rotas críticas menor.

