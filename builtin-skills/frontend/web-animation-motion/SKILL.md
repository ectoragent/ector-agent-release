---
name: web-animation-motion
description: "Motion design na web: transições, micro-interações, scroll animation, performance. Triggers: animation, motion design, transition, Framer Motion, GSAP, scroll animation, micro-interaction."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Motion & Animação Web

## Quando usar
- Adicionar transições/micro-interações, animação de entrada ou scroll, motion em design system

## Passos
1. Anime só `transform`/`opacity` no caminho crítico — são compositor-only, sem custo de layout/paint.
2. Motion com propósito: reforça hierarquia/feedback/continuidade, não é decoração aleatória.
3. Duração 150–300ms em micro-interações; easing natural (ease-out entrando, ease-in saindo).
4. Respeite `prefers-reduced-motion`; ofereça versão estática/reduzida para quem pediu menos movimento.
5. Scroll-based com `IntersectionObserver` ou CSS `scroll-timeline` — nunca `scroll` listener sem throttle/rAF.
6. Bibliotecas (Framer Motion/GSAP) só quando orquestração complexa justifica o peso; CSS puro resolve a maioria dos casos.
7. Não bloqueie interação durante a animação — usuário clica e algo deve responder imediatamente.

## Armadilhas
- Animar `width`/`top`/`left` em vez de `transform` (jank, layout thrashing).
- Motion excessivo que atrasa a tarefa do usuário (loading fake, delay artificial só por estética).
- Ignorar `prefers-reduced-motion` (problema de acessibilidade/vestibular real).

## Verificação
- 60fps no DevTools Performance durante a animação; comportamento correto com reduced motion ativado; ação do usuário não é atrasada pelo motion.
