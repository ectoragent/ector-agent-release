---
name: forms-validation-ux
description: "Forms: validação, UX de erro, acessibilidade, libs (RHF/Zod). Triggers: form, validação, schema, zod, react-hook-form, input error."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Forms, Validation & UX

## Quando usar
- Criar/refatorar formulários, validação client/server, UX de erro

## Passos
1. Stack default: `react-hook-form` + `Zod` (`@hookform/resolvers/zod`) + componentes `Form` do shadcn — evite reinventar o que essas libs já resolvem.
2. Defina schema único (Zod) compartilhado client+server quando possível.
3. Valide no submit; inline após blur/dirty — não grite no first keystroke.
4. Mensagens específicas e acionáveis; associe ao campo (a11y).
5. Disable submit durante request; mostre progresso; trate erros de rede.
6. Defaults e dirty-check antes de abandonar a página.
7. Senhas/PII: autocomplete correto; nunca logar valores sensíveis.

## Armadilhas
- Só validação client.
- Erros genéricos "inválido".
- Perder input no re-render.

## Verificação
- Casos felizes + inválidos cobertos; mensagens ligadas aos campos; server rejeita payload inválido.

