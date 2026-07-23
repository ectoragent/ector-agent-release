---
name: kubernetes-basics
description: "Kubernetes básico: pods, deploy, services, ingress, probes, config. Triggers: Kubernetes, k8s, kubectl, deployment, ingress, probe."
version: 1.0.0
metadata:
  ector:
    tags: [devops, builtin]
    category: devops
---

# Kubernetes Basics

## Quando usar
- Deploy/debug em Kubernetes, probes, networking básico no cluster

## Passos
1. Workload: Deployment + resource requests/limits.
2. Service + Ingress/Gateway; TLS no edge.
3. Probes: liveness ≠ readiness; não mate pods por cold start longo sem warmup.
4. ConfigMap/Secret; prefer external secrets em prod.
5. Rollout: `kubectl rollout status`; rollback.
6. Debug: `describe`, `logs`, `events`, `kubectl exec` com cuidado.

## Armadilhas
- latest tags.
- Sem requests (noisy neighbor).
- Liveness que depende de dependência externa (restart storm).

## Verificação
- Rollout healthy; probes corretos; serviço alcançável pelo Ingress.

