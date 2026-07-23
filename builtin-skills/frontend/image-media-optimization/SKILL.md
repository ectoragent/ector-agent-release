---
name: image-media-optimization
description: "Otimização de imagem e vídeo web: formatos, responsive images, lazy loading. Triggers: image optimization, responsive images, srcset, WebP, AVIF, lazy loading, video embed."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Otimização de Imagem & Mídia

## Quando usar
- Site pesado por mídia, LCP ruim por causa de imagem, embutir vídeo sem travar a página

## Passos
1. Formatos modernos (AVIF/WebP) com fallback; escolha por conteúdo (foto vs. gráfico com poucas cores/flat).
2. `srcset`/`sizes` (ou `next/image`/equivalente) para servir a resolução certa por viewport.
3. Dimensões explícitas (`width`/`height` ou `aspect-ratio`) — evita layout shift enquanto a imagem carrega.
4. Elemento LCP (geralmente o hero) carrega com prioridade, sem `loading="lazy"`; o resto da página usa lazy loading.
5. Vídeo: `poster` frame, `preload="metadata"`; considere host externo (YouTube/Vimeo/Cloudflare Stream) para não pesar o bundle.
6. Compressão com qualidade perceptual (~75–85%), não "sem perda" por padrão.
7. CDN/edge para servir mídia perto do usuário; cache longo com hash no nome do arquivo.

## Armadilhas
- Lazy-load do elemento LCP (atrasa exatamente a métrica mais importante).
- Imagem em resolução 4K servida para um card de 200px.
- Vídeo autoplay pesado sem `muted`/`playsinline` (trava ou é bloqueado no mobile).

## Verificação
- LCP dentro da meta; nenhuma imagem maior que o necessário no viewport onde aparece; CLS baixo relacionado a mídia.
