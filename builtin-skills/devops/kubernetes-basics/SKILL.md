---
name: kubernetes-basics
description: "kubectl day-2: context, pods, logs, describe, rollout, port-forward, apply. Triggers: Kubernetes, k8s, kubectl, deployment, ingress, probe, rollout, kubectl logs, CrashLoopBackOff."
version: 1.1.0
metadata:
  ector:
    tags: [devops, kubernetes, kubectl, builtin]
    category: devops
---

# Kubernetes Basics (`kubectl`)

Debug e deploy com **comandos reais**. Não invente nomes de resource/API.

## Quando usar
- Deploy/debug em cluster Kubernetes
- CrashLoop, ImagePull, rollout, logs, networking básico

## Passos

### 0. Contexto e namespace

```bash
kubectl config current-context
kubectl config get-contexts
kubectl get ns
kubectl config set-context --current --namespace=<ns>
# ou: -n <ns> em cada comando
```

### 1. Visão geral

```bash
kubectl get deploy,po,svc,ingress -o wide
kubectl get events --sort-by=.lastTimestamp | tail -30
kubectl top pods 2>/dev/null || true
```

### 2. Debug de pod

```bash
kubectl describe pod <pod>
kubectl logs <pod> --tail=200
kubectl logs <pod> -c <container> --previous   # crash anterior
kubectl get pod <pod> -o yaml
kubectl exec -it <pod> -- sh                   # se a imagem tiver shell
```

Sinais comuns: `CrashLoopBackOff` → logs; `ImagePullBackOff` → image/pull secrets; `Pending` → events/recursos/affinity.

### 3. Rollout

```bash
kubectl rollout status deploy/<name>
kubectl rollout history deploy/<name>
kubectl rollout undo deploy/<name>
kubectl set image deploy/<name> <container>=repo:tag
```

### 4. Apply / diff

```bash
kubectl diff -f manifest.yaml
kubectl apply -f manifest.yaml
kubectl apply -k overlays/prod    # se kustomize
kubectl delete -f manifest.yaml   # só com confirmação
```

Prefira GitOps do time quando existir; não bypassar Argo/Flux sem pedido.

### 5. Service / Ingress / port-forward

```bash
kubectl get svc,ingress -o wide
kubectl port-forward svc/<name> 8080:80
kubectl port-forward pod/<pod> 9229:9229
```

### 6. Probes e recursos (checklist ao escrever manifests)
- `resources.requests/limits` definidos
- readiness ≠ liveness; cold start: `initialDelaySeconds` / startupProbe
- Secrets via Secret/ExternalSecrets — não em plaintext no Deployment

### 7. Helm (se o release for Helm)

```bash
command -v helm && helm list -n <ns>
helm status <release> -n <ns>
helm history <release> -n <ns>
# rollback: helm rollback <release> <rev> -n <ns>
```

## Armadilhas
- Contexto errado (prod vs staging).
- `kubectl delete` amplo (`-l`, namespace inteiro) sem confirmação.
- Tag `latest` em produção.
- Liveness dependente de DB externo → restart storm.
- `exec`/shell em prod sem necessidade.

## Verificação
- Context/namespace corretos.
- Rollout `successfully rolled out` ou causa da falha nos events/logs.
- Serviço alcançável (port-forward ou Ingress) conforme esperado.
