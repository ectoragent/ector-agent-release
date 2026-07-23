---
name: observability-logging
description: "Observabilidade: logs estruturados, métricas, traces, alertas. Triggers: logging, metrics, tracing, OpenTelemetry, alerting, SLO."
version: 1.0.0
metadata:
  ector:
    tags: [servers, builtin]
    category: servers
---

# Observability Logging

## Quando usar
- Instrumentar serviços, definir alertas, debug em produção

## Passos
1. Três pilares: logs, metrics, traces — com correlation ids.
2. Logs estruturados (JSON); níveis honestos; sem PII/secrets.
3. Métricas RED/USE; SLIs alinhados a SLOs.
4. Traces nas bordas e dependências; sampling consciente.
5. Alertas acionáveis (symptoms > causes); runbook linkado.
6. Dashboards por serviço + golden signals.

## Armadilhas
- Alert fatigue.
- Log spam que custa caro e esconde sinal.
- Métricas sem dono.

## Verificação
- Dá para diagnosticar um erro fake end-to-end; alerta dispara e tem runbook.

