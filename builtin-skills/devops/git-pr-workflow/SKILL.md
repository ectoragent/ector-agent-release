---
name: git-pr-workflow
description: "Git e PRs: branches, commits, review, squash/rebase, conventional commits. Triggers: git, pull request, code review, branch, commit message."
version: 1.0.0
metadata:
  ector:
    tags: [devops, builtin]
    category: devops
---

# Git & PR Workflow

## Quando usar
- Fluxo de branch/PR, mensagens de commit, preparação de review

## Passos
1. Branch curta a partir de main atualizada.
2. Commits pequenos e focados; mensagem explica o porquê.
3. Antes do PR: rebase/merge main; testes locais; diff limpo.
4. PR: descrição, screenshots se UI, riscos, plano de teste.
5. Review: peça reviewers certos; responda comentários com mudanças ou rationale.
6. Não force-push em main; respeite hooks/CI.

## Armadilhas
- PR monstro sem narrativa.
- Secrets no histórico.
- Rebase de branch compartilhada sem coordenação.

## Verificação
- CI verde; descrição clara; histórico compreensível.

