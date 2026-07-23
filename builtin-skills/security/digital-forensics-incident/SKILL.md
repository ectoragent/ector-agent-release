---
name: digital-forensics-incident
description: "Forense digital pós-incidente: evidência, cadeia de custódia, IOCs, timeline de comprometimento. SOMENTE em incidente real/autorizado. Triggers: forensics, digital forensics, IOC, chain of custody, compromised, breach investigation."
version: 1.0.0
metadata:
  ector:
    tags: [security, builtin]
    category: security
---

# Forense Digital & Investigação de Incidente

## Quando usar
- Sistema possivelmente comprometido, precisa preservar evidência e reconstruir o que o atacante fez

## Regras absolutas
- Preserve evidência antes de "limpar"/reinstalar — sistema comprometido é cena de investigação até se decidir o contrário.
- Não altere/desligue o sistema afetado sem necessidade antes de coletar o essencial (memória volátil se aplicável).
- Cadeia de custódia documentada se o caso pode virar processo legal/seguro; sem isso, evidência perde valor.

## Passos
1. Contenha sem destruir: isole rede (não desligue) para preservar estado e não avisar o atacante, salvo risco ativo maior.
2. Colete evidência volátil primeiro (memória, conexões ativas, processos) antes do que é persistente (disco, logs).
3. Hash/timestamp de tudo coletado; investigue em cópias de trabalho, nunca no original.
4. Timeline de comprometimento: vetor inicial, movimentação lateral, persistência, exfiltração — cruze logs de múltiplas fontes (ver `log-trace-analysis`).
5. IOCs (hashes, IPs, domínios, padrões) documentados e checados em outros sistemas do ambiente.
6. Determine o escopo real: o que foi acessado/exfiltrado, não só o que foi "visto" nos logs disponíveis.
7. Reporte fatos com nível de confiança explícito; não afirme o que a evidência não confirma.
8. Depois: erradicação completa (não só o sintoma); lições viram hardening (ver `threat-modeling`, `secure-code-review`).

## Armadilhas
- Reinstalar/limpar o sistema antes de coletar evidência (perde tudo).
- Investigar direto no sistema comprometido sem cópia (contamina evidência).
- Confundir "não achei evidência de X" com "X não aconteceu".

## Verificação
- Timeline do incidente reconstruída com evidência; escopo do comprometimento delimitado; evidência preservada de forma defensável.
