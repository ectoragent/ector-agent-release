---
name: metrics-north-star
description: "Métricas de produto: north star, input metrics, guardrails, instrumentation. Triggers: north star, KPI, product metrics, funnel, analytics."
version: 1.0.0
metadata:
  ector:
    tags: [product, builtin]
    category: product
---

# Metrics North Star

## Quando usar
- Definir sucesso de feature/produto, instrumentar analytics

## Passos
1. North star = valor entregue ao usuário (não vanity).
2. Input metrics acionáveis pelo time; guardrails (ex.: churn, latência).
3. Funil com etapas claras; defina eventos e propriedades.
4. Baseline antes do ship; janela de leitura combinada.
5. Privacidade: minimize PII; respeite consentimento.

## Armadilhas
- Otimizar métrica que não reflete valor (Goodhart).
- Eventos inconsistentes entre plataformas.
- Sem guardrail (cresce engagement e quebra confiabilidade).

## Verificação
- Dashboard com NS + inputs + guardrails; eventos documentados.

