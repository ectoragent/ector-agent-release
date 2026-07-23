---
name: root-cause-analysis
description: "Investigação sistemática de bugs/incidentes: isolar variável, bisect, 5 porquês, causa raiz vs sintoma. Triggers: root cause, RCA, debug, bisect, 5 whys, investigar bug, reproduzir bug."
version: 1.0.0
metadata:
  ector:
    tags: [investigation, builtin]
    category: investigation
---

# Root Cause Analysis

## Quando usar
- Bug difícil de reproduzir, comportamento inesperado, decidir entre "corrigir sintoma" e achar a causa real

## Passos
1. Reproduza antes de teorizar; sem repro confiável, qualquer "causa" é chute.
2. Isole variáveis: mude uma coisa por vez; bisect (`git bisect`, remover metade do input/config) para achar o commit/condição que introduziu o problema.
3. Diferencie causa raiz de sintoma: "5 porquês" até chegar em algo acionável — não em "erro humano" genérico.
4. Leia o erro/stack trace completo antes de teorizar — a resposta costuma estar ali, não na primeira linha só.
5. Compare o caso que falha com um caso que funciona (diff de estado, config, dados, ambiente, versão).
6. Instrumente em vez de adivinhar: log/print/breakpoint no ponto exato de divergência, não tentativa e erro espalhada.
7. Documente a causa raiz encontrada e por que as hipóteses anteriores estavam erradas — economiza a próxima investigação.
8. Corrija a causa; se só dá para mitigar o sintoma agora, registre a dívida explicitamente.

## Armadilhas
- Aceitar a primeira explicação plausível sem confirmar (correlação ≠ causa).
- Corrigir o sintoma e fechar o ticket sem entender a causa raiz.
- Mudar várias coisas ao mesmo tempo — quando "resolve", não se sabe o que resolveu de fato.

## Verificação
- Causa raiz reproduz e a correção elimina o sintoma de forma explicada, não só "parou de acontecer"; teste de regressão cobre o caso.
