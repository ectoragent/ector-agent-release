---
name: secrets-management
description: "Gestão de secrets: vault, rotação, least privilege, remoção de segredo vazado. Triggers: secrets management, vault, rotate secret, leaked key, env secret, KMS."
version: 1.0.0
metadata:
  ector:
    tags: [devops, builtin]
    category: devops
---

# Secrets Management

## Quando usar
- Guardar/rotacionar credenciais, remover segredo vazado, distribuir secrets para apps/CI

## Passos
1. Secret store dedicado (Vault, cloud secret manager, SOPS+KMS) — nunca em código ou `.env` versionado.
2. Least privilege: cada serviço/CI job só acessa os secrets que precisa.
3. Rotação regular e automatizável; secrets de longa duração são risco acumulado.
4. Injeção em runtime (env var, sidecar, volume) — não hardcode em imagem/build.
5. Auditoria: quem/quando acessou; alerta em acesso anômalo.
6. Segredo vazado (commit, log): revogue/rotacione primeiro, depois limpe histórico — vazamento já é considerado comprometido.
7. Diferencie por ambiente (dev/stage/prod); nunca reuse a mesma credencial prod em dev.

## Armadilhas
- Achar que remover do último commit resolve (git history/forks ainda têm).
- Secret de longa duração sem dono nem data de expiração.
- Logar payload que contém token/senha "só para debug".

## Verificação
- Nenhum secret em texto claro no repo/imagem; rotação testada sem downtime; acesso auditável.
