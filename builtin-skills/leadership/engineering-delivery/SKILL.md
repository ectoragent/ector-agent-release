---
name: engineering-delivery
description: "Entrega de engenharia: fluxo, WIP, SLAs internos, DORA-ish, qualidade. Triggers: delivery, lead time, WIP, DORA, throughput, cycle time."
version: 1.0.0
metadata:
  ector:
    tags: [leadership, builtin]
    category: leadership
---

# Engineering Delivery

## Quando usar
- Time lento, muito WIP, releases dolorosos, qualidade instável

## Passos
1. Visualize fluxo (board); limite WIP.
2. Fatia trabalho pequeno; reduza batch size.
3. Meça lead time, fail rate, MTTR (use com cuidado — contexto > vanity).
4. Definition of Done inclui testes + observabilidade básica.
5. Remova filas de aprovação desnecessárias; automatize gates.
6. Postmortems sem culpa para incidentes (veja `incident-response`).

## Armadilhas
- Individual utilization 100% (mata flow).
- Feature factory sem qualidade.
- Métricas usadas punitivamente.

## Verificação
- Menos itens envelhecendo no board; releases mais frequentes e calmos.

