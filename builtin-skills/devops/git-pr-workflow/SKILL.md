---
name: git-pr-workflow
description: "Git operacional: status, branch, commit, rebase, conflito, reflog, worktree, bisect. Triggers: git, commit, branch, rebase, merge conflict, stash, worktree, bisect, reflog, cherry-pick, pull request."
version: 1.1.0
metadata:
  ector:
    tags: [devops, git, builtin]
    category: devops
---

# Git & PR Workflow

Playbook operacional. **Execute** os comandos via terminal; não invente flags nem reescreva histórico sem checar o estado.

## Quando usar
- Qualquer tarefa com repositório Git local (commit, branch, PR prep, conflito, histórico)
- Antes de `gh` / GitLab / Bitbucket — Git local primeiro

## Passos

### 0. Diagnóstico (sempre primeiro)

```bash
git rev-parse --is-inside-work-tree
git status -sb
git remote -v
git branch -vv
git log --oneline -10
```

Detecte o host pelo remote (`github.com` → skill `github-cli`; `gitlab` → `gitlab-cli`; `bitbucket.org` → `bitbucket-cli`).

### 1. Branch curta a partir de main atualizada

```bash
git fetch origin
git switch main   # ou master/develop — use a default do remote
git pull --ff-only
git switch -c tipo/descricao-curta   # feat/, fix/, chore/
```

### 2. Staging e commit focado

```bash
git diff
git diff --staged
git add -p                    # preferir seletivo a `git add .`
git commit -m "$(cat <<'EOF'
tipo(escopo): porquê da mudança

EOF
)"
```

- Mensagem explica o **porquê**, não o diff.
- Nunca commitar `.env`, keys, `identity.json`, binários enormes.
- Só `--amend` se o commit for seu, local e não pushed (ou pedido explícito).

### 3. Sincronizar com main sem bagunçar

```bash
git fetch origin
git rebase origin/main        # branch pessoal
# se branch compartilhada: git merge origin/main (combinado com o time)
```

Conflito:

```bash
git status
# edite os arquivos; remova marcadores <<<<<<< ======= >>>>>>>
git add <arquivos>
git rebase --continue
# abortar: git rebase --abort
```

### 4. Desfazer com segurança

```bash
git restore --staged <file>   # unstage
git restore <file>            # descartar working tree (cuidado)
git stash push -u -m "wip"
git stash list && git stash pop
git reflog                    # recuperar commit “perdido”
git reset --soft HEAD~1       # desfaz commit, mantém staged
# NÃO use reset --hard / push --force em main/master
```

### 5. Investigar regressão

```bash
git bisect start
git bisect bad HEAD
git bisect good <sha-bom>
# teste; depois: git bisect good|bad
git bisect reset
```

### 6. Worktree paralelo (evitar stash eterno)

```bash
git fetch origin
git worktree add ../repo-fix origin/main
# ... trabalho ...
git worktree remove ../repo-fix
```

### 7. Antes do PR / push

```bash
git status -sb
git log origin/main..HEAD --oneline
git diff origin/main...HEAD
# rode testes/linters do projeto
git push -u origin HEAD
```

Depois: use a skill do host (`github-cli`, `gitlab-cli`, `bitbucket-cli`).

## Armadilhas
- `git add .` + secrets no histórico.
- `push --force` em branch protegida / compartilhada.
- Rebase de branch que outros já puxaram, sem coordenação.
- Confiar na memória do modelo em vez de `git status` / `git log`.
- Assumir que a default branch é `main` sem checar `origin/HEAD`.

## Verificação
- `git status` limpo ou só com mudanças intencionais.
- Histórico linear/compreensível no range do PR.
- Nenhum secret no `git diff` / `git log -p`.
- Remote e branch corretos antes de abrir o MR/PR.
