---
name: test-strategy
description: "Estratégia de testes: pirâmide, riscos, o que automatizar vs manual. Triggers: test strategy, test plan, QA strategy, coverage strategy."
version: 1.0.0
metadata:
  ector:
    tags: [qa, builtin]
    category: qa
---

# Test Strategy

## Quando usar
- Planejar qualidade de release/feature, escolher tipos de teste

## Passos
1. Riscos: o que quebra o negócio se falhar?
2. Pirâmide alinhada ao risco; E2E só nos caminhos críticos.
3. Dados de teste estáveis; ambientes parecidos com prod nos pontos que importam.
4. Critérios de saída do release explícitos.
5. Débito de teste: pague junto com features de alto risco.

## Armadilhas
- 100% E2E.
- Zero testes em lógica financeira/auth.
- "QA no fim" sem tempo.

## Verificação
- Plano escrito curto; riscos cobertos; dones claros.

