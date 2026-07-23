---
name: log-trace-analysis
description: "Análise de logs, traces e métricas para investigar incidentes: correlação, timeline, sinal vs ruído. Triggers: analisar logs, log analysis, trace, correlation id, timeline de incidente, grep logs."
version: 1.0.0
metadata:
  ector:
    tags: [investigation, builtin]
    category: investigation
---

# Log & Trace Analysis

## Quando usar
- Investigar produção com logs/traces existentes, reconstruir timeline de um incidente, achar agulha no palheiro em volume grande de logs

## Passos
1. Delimite a janela de tempo e o escopo (serviço, request id, usuário afetado) antes de vasculhar tudo.
2. Correlation/trace id para seguir uma requisição através de serviços; sem isso, correlacione por timestamp+contexto com cautela (clock skew entre hosts).
3. Construa a timeline a partir do primeiro sinal anômalo, não do primeiro erro visível — a causa geralmente precede o erro que "aparece".
4. Separe sinal de ruído: erros esperados/retries normais vs. anomalia real; compare volume atual com baseline histórico.
5. Grep/query estruturado (não scroll visual) em volume grande; filtre por nível, serviço, campo estruturado.
6. Cruze logs com métricas/deploys/mudanças de config no mesmo intervalo — correlação temporal é a pista mais comum.
7. Amostragem: se o volume é gigante, pegue uma amostra representativa do padrão de falha em vez de ler tudo.

## Armadilhas
- Focar no primeiro erro que aparece e ignorar o log anterior que já mostrava o problema real.
- Confundir efeito colateral (erro em cascata) com causa.
- Ler logs sem delimitar janela de tempo — perder tempo em ruído histórico irrelevante.

## Verificação
- Timeline reconstruída é consistente entre serviços/fontes; a causa apontada explica todos os sintomas observados, não só parte deles.
