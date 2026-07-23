---
name: monorepo-navigation
description: "Navegar e trabalhar em monorepos (pnpm/npm/yarn workspaces, turbo, nx, cargo, go.work). Identificar o package certo, filters, e onde rodar install/build/test. Triggers: monorepo, workspace, pnpm --filter, turbo, nx, packages/, apps/"
version: 1.0.0
metadata:
  ector:
    tags: [monorepo, workspace, pnpm, turbo, nx, cargo, devops]
    category: web-development
    related_skills: []
---

# Monorepo navigation

Use esta skill quando o repositório tiver vários packages (`apps/`, `packages/`,
`pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `go.work`, `Cargo.toml` workspace).

## Antes de editar ou rodar comandos

1. **Confirme a raiz do workspace** — procure na ordem:
   - `pnpm-workspace.yaml` / `package.json` → `workspaces`
   - `turbo.json` / `nx.json` / `lerna.json`
   - `go.work` / `[workspace]` em `Cargo.toml` / `[tool.uv.workspace]`
2. **Identifique o package alvo** pelo caminho do arquivo ou pelo pedido do usuário.
3. **Leia o manifesto do package** (`package.json`, `Cargo.toml`, `pyproject.toml`) —
   não assuma deps do root.
4. **Respeite `AGENTS.md` / `CLAUDE.md` do package** além do da raiz.

## Comandos preferidos

### pnpm

```bash
pnpm --filter <name> <script>
pnpm --filter ./packages/ui add lodash
pnpm -r run build          # só quando o usuário pedir build de todos
```

### turbo

```bash
npx turbo run test --filter=@acme/web
npx turbo run build --filter=...@acme/web   # package + deps
```

### nx

```bash
npx nx run web:test
npx nx run-many -t build --projects=web,api
```

### cargo / go

```bash
cargo test -p crate_name
go test ./services/api/...
```

## Regras anti-erro

- Não rode `npm install` na raiz sem checar o gerenciador (`pnpm-lock.yaml` → pnpm).
- Não misture packages: fix em `packages/ui` não justifica rebuild completo sem necessidade.
- Imports cross-package: use o nome publicado/`workspace:` — não invente path relativo profundo.
- Testes: rode no package alterado primeiro; suite monorepo inteira só se pedido ou CI local explícito.
- Se o cwd da sessão já for um package, prefira comandos sem `cd` (ou `workdir` nesse package).

## Descoberta rápida

```bash
# listar packages (pnpm)
pnpm ls -r --depth -1

# ou ler manifests
# read_file: pnpm-workspace.yaml, turbo.json, package.json (workspaces)
```
