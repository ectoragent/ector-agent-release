---
name: architecture-adrs
description: "Architecture Decision Records: quando escrever, template, supersede. Triggers: ADR, architecture decision, RFC técnico."
version: 1.0.0
metadata:
  ector:
    tags: [leadership, builtin]
    category: leadership
---

# Architecture ADRs

## Quando usar
- Decisões de arquitetura duradouras, RFCs, trade-offs

## Passos
1. ADR quando custo de reverter é alto ou impacta vários times.
2. Template: contexto, decisão, alternativas, consequências.
3. Curto; links a spikes/benchmarks.
4. Status: proposed → accepted → superseded.
5. Guarde no repo (`docs/adr/`); referencie em PRs.

## Armadilhas
- ADR-novelas.
- Decidir em call sem registro.
- Não marcar superseded (docs fantasmas).

## Verificação
- Leitor novo entende o porquê em <5 min; alternativas listadas.

