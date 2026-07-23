---
name: secure-code-review
description: "Secure code review: checklist, hotspots, secrets, authz. Triggers: secure code review, security review PR, secret leak."
version: 1.0.0
metadata:
  ector:
    tags: [security, builtin]
    category: security
---

# Secure Code Review

## Quando usar
- Review de PR com ângulo de segurança, auditoria pontual de código

## Passos
1. Entenda a change: superfície de ataque nova?
2. Hotspots: authz, crypto, parsers, deserialização, uploads, SSRF, comandos shell.
3. Secrets: keys em código/logs; use vault/env.
4. Validate inputs na trust boundary; encode outputs.
5. Dependências novas: manutenção e CVEs.
6. Peça testes negativos quando o risco for alto.

## Armadilhas
- Bike-shedding estilo sem olhar authz.
- Aprovar "depois ajeitamos" em issues críticas internet-facing.

## Verificação
- Comentários acionáveis; issues críticas bloqueantes resolvidas ou explicitamente aceitas.

