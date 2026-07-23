---
name: ci-cd-pipelines
description: "CI/CD: pipelines rápidas, caches, secrets, deploy progressivo. Triggers: CI, CD, GitHub Actions, GitLab CI, deploy, pipeline."
version: 1.0.0
metadata:
  ector:
    tags: [devops, builtin]
    category: devops
---

# CI/CD Pipelines

## Quando usar
- Criar/consertar pipelines, acelerar CI, deploys seguros

## Passos
1. Gates: lint/type/test em PR; build artifacts reproduzíveis.
2. Cache de deps com key correta; paralelize jobs independentes.
3. Secrets no secret store do CI — nunca no YAML.
4. Deploy: staging → prod; health check; rollback fácil.
5. Progressive delivery (canary/blue-green) quando o risco pede.
6. Falhas: logs artefatos; flaky quarantine com dono.

## Armadilhas
- CI minutos inflados por falta de cache.
- Deploy sem smoke test.
- Permissões de token amplas demais.

## Verificação
- Pipeline < meta de tempo; deploy com rollback testado; secrets auditáveis.

