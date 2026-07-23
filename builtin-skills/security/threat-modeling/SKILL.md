---
name: threat-modeling
description: "Threat modeling: DFDs, STRIDE, abuse cases, mitigações. Triggers: threat model, STRIDE, abuse case, security design review."
version: 1.0.0
metadata:
  ector:
    tags: [security, builtin]
    category: security
---

# Threat Modeling

## Quando usar
- Design review de feature/sistema com risco, compliance, dados sensíveis

## Passos
1. Diagrama de fluxo de dados (trust boundaries).
2. Assets + adversários relevantes.
3. STRIDE (ou similar) por elemento; abuse cases.
4. Mitigações e residual risk aceito por owner.
5. Tickets de segurança priorizados; reavaliar em mudanças grandes.

## Armadilhas
- Modelo teatro (sem donos/mitigações).
- Só listar CVEs de libs sem ameaças de desenho.
- Atrasar demais no ciclo (shift-left).

## Verificação
- Doc curto com ameaças top + mitigações; owners nomeados.

