---
name: data-anomaly-investigation
description: "Investigar anomalias e discrepâncias em dados: número errado, métrica que quebrou, EDA investigativa. Triggers: número errado, métrica quebrada, anomalia nos dados, discrepância, dado inconsistente, EDA."
version: 1.0.0
metadata:
  ector:
    tags: [investigation, builtin]
    category: investigation
---

# Investigação de Anomalias em Dados

## Quando usar
- Métrica/dashboard mudou sem explicação, número não bate entre fontes, dado parece errado mas ninguém sabe por quê

## Passos
1. Confirme que é anomalia real, não mudança de definição/instrumentação recente — cheque changelog de eventos/schema primeiro.
2. Delimite o corte: quando começou, para qual segmento (todo mundo ou um subconjunto — plataforma, região, versão)?
3. Compare a mesma métrica calculada por caminhos diferentes (dashboard vs query direta vs log bruto) para achar onde diverge.
4. Amostre casos individuais (drill-down) em vez de só olhar o agregado — o agregado esconde onde exatamente quebra.
5. Suspeitos comuns: deploy/migration recente, JOIN fan-out (ver `sql-analytics`), timezone, filtro de data exclusivo/inclusivo, dado duplicado/late-arriving.
6. Valide contra uma fonte independente (dado bruto, sistema de origem) antes de aceitar que "o número novo está certo".
7. Documente a causa e o impacto (quais números/relatórios anteriores ficam incorretos) — não corrija silenciosamente.

## Armadilhas
- Assumir que o dado "sempre esteve certo" e o problema é só do dashboard novo.
- Corrigir o número sem entender por que divergiu — pode voltar a acontecer.
- Investigar só o agregado sem olhar exemplos individuais.

## Verificação
- Causa da divergência identificada e reproduzível; números após a correção batem com fonte independente; impacto histórico comunicado.
