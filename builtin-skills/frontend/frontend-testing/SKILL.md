---
name: frontend-testing
description: "Testes frontend: unit (Vitest/Jest), componentes (Testing Library), E2E (Playwright). Triggers: vitest, jest, playwright, testing-library, frontend test."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Frontend Testing

## Quando usar
- Escrever/melhorar testes de UI, flaky tests, estratégia de pirâmide

## Passos
1. Pirâmide: muitos unit/component; poucos E2E críticos.
2. Testing Library: consulte como usuário (role/text), não detalhes de implementação.
3. Mocke rede na borda; prefira MSW quando o projeto já usa.
4. E2E: flows de negócio (login→ação→assert); seletores resilientes (`getByRole`).
5. Evite snapshots gigantes; prefira asserts pontuais.
6. CI: unit em todo PR; E2E em smoke + nightly se pesado.

## Armadilhas
- Testar implementação interna de hooks sem valor.
- E2E flaky por timing — use asserts/auto-wait, não `sleep` fixo.
- Cobertura % como meta única.

## Verificação
- Suite verde local/CI; falha reproduz bug real; nomes descrevem comportamento.

