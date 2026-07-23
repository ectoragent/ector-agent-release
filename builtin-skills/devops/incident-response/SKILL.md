---
name: incident-response
description: "Resposta a incidentes: triage, comunicação, mitigação, postmortem. Triggers: incident, outage, SEV, postmortem, on-call."
version: 1.0.0
metadata:
  ector:
    tags: [devops, builtin]
    category: devops
---

# Incident Response

## Quando usar
- Outage/degradação, on-call, comunicação a stakeholders

## Passos
1. Declare incidente; canal único; roles (incident commander, comms).
2. Mitigue primeiro (rollback, feature flag, scale) — root cause depois.
3. Timeline factual; updates regulares.
4. Quando estável: postmortem blameless — causas, ações com donos/datas.
5. Siga ações até fechar; melhore alertas/runbooks.

## Armadilhas
- Debug eterno sem mitigar.
- Culpar pessoas em público.
- Postmortem sem action items.

## Verificação
- Serviço recuperado; comunicação clara; ações rastreadas.

