---
name: ethical-hacking-playbook
description: "Ethical hacking (autorizado): mentalidade, lab, metodologia, reporte responsável. Triggers: ethical hacking, responsible disclosure, bug bounty, lab hacking."
version: 1.0.0
metadata:
  ector:
    tags: [security, builtin]
    category: security
---

# Ethical Hacking Playbook

## Quando usar
- Treino em lab, bug bounty **dentro das regras do programa**, disclosure responsável

## Regras absolutas
- Só alvos autorizados (lab próprio, programa de bounty, contrato).
- Proibido: dados reais de terceiros sem permissão, ransomware, extorsão, vandalismo.

## Passos
1. Leia regras do programa/lab; respeite rate limits e escopo.
2. Metodologia: recon → map → probe → exploit controlado → document.
3. Minimize impacto; não exfiltre mais dados que o necessário para PoC.
4. Reporte claro e respeitoso; prazos de disclosure coordenado.
5. Transforme aprendizado em hardening (patches, testes, WAF rules internas).

## Armadilhas
- Assumir que "é público" = autorizado.
- PoC destrutiva.
- Divulgar antes do fix sem acordo.

## Verificação
- Atividade dentro das regras; report útil; nenhum dano colateral.

