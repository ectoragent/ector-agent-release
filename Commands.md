# Comandos Ector

Referência gerada a partir do código (`ector_cli/main.py`, `ector_cli/commands.py`). Para detalhes e flags: `ector <comando> --help`.

---

## Uso sem subcomando

`ector` (sem subcomando) abre o **painel web** (`http://ector.localhost:9000`). Em SSH, só imprime a URL (sem abrir o browser).

Flags úteis no nível raiz:

- `ector --up-online` — Nginx + TLS/BasicAuth para VPS (`--server-name`, `--listen-port`, `--tls`, …)
- `ector kill` — encerra o painel em execução

Para retomar uma sessão, use `ector sessions browse` ou abra `/chat` no painel.

---

## Subcomandos do CLI (`ector <subcomando>`)

### `provider`

Seletor interativo de provedor e modelo padrão.

### `fallback`

- `list` (alias `ls`)
- `add`
- `remove` (alias `rm`)
- `clear`

### `gateway`

- `run` (foreground; se omitir o subcomando, equivale a `run`)
- `start`, `stop`, `restart`, `status`
- `install`, `uninstall`
- `setup`
- `migrate-legacy`

### `setup`

Assistente de configuração; seção opcional: `model`, `tts`, `terminal`, `gateway`, `tools`, `agent`.

### `whatsapp`

Fluxo de configuração WhatsApp.

### `slack`

- `manifest` — gera manifesto de app Slack

### `login` / `logout` / `me`

Identidade Ector (`ector.cc`) e, com `--provider`, fluxos OAuth de inferência.

**Login em SSH (servidor remoto):** por padrão usa *device code* — a CLI imprime
uma URL e um código; abra o link no browser do seu portátil, faça login no site
se necessário e clique em autorizar. Não depende de redirect para `127.0.0.1` no
servidor.

- `ector login` — em SSH escolhe device code automaticamente
- `ector login --device` — força device code
- `ector login --local` — força callback local (`127.0.0.1`, máquina com browser)
- `ector login --no-browser` — só imprime a URL (útil em ambos os modos)

### `auth`

- `add`, `list`, `remove`, `reset`, `status`, `logout`

### `status`

Status dos componentes (`--all`, `--deep`).

### `cron`

- `list`, `create` (alias `add`), `edit`, `pause`, `resume`, `run`, `remove` (aliases `rm`, `delete`), `status`, `tick`

### `webhook`

- `subscribe` (alias `add`), `list` (alias `ls`), `remove` (alias `rm`), `test`

### `hooks`

- `list` (alias `ls`), `test`, `revoke` (aliases `remove`, `rm`), `doctor`

### `doctor`

Diagnóstico (`--fix`).

### `reset`

Formata dados do perfil (`--hard`, `-y` / `--yes`).

### `dump`

Exporta config ativa como JSON (`--redact`).

### `debug`

- `share` — envia relatório de depuração (info do sistema + logs) para serviço de paste
- `delete` — remove pastes previamente enviados (`ector debug delete <url> …`)

O parser também declara `config`, `env`, `tokenizer`, `tools`, `prompt`, `cache`, `trace`, `logs`; o comportamento exato depende da versão (entrada em `cmd_debug` → `ector_cli.debug.run_debug`).

### `backup` / `import`

Backup e restauração de dados/config.

### `config`

- `show`, `edit`, `set`, `path`, `env-path`, `check`, `migrate`

### `pairing`

- `list` — pedidos pendentes e utilizadores aprovados
- `approve <plataforma> <código>` — aprovar acesso via DM
- `revoke <plataforma> <user_id>` — revogar utilizador aprovado
- `clear-pending` — limpar códigos pendentes

### `skills`

- `list` (alias `ls`), `install`, `inspect`, `check`, `update`, `audit`, `uninstall`, `reset`, `publish`
- `snapshot` → `export`, `import`
- `tap` → `list`, `add`, `remove`
- `config` — UI interativa de habilitar/desabilitar skills

### `plugins`

- `install`, `update`, `remove` (aliases `rm`, `uninstall`), `list` (alias `ls`), `enable`, `disable`

### Comando extra do plugin de memória (dinâmico)

Se `memory.provider` em `config.yaml` apontar para um provedor com `cli.py` e `register_cli`, o CLI registra um subcomando com o **nome do provedor** (por exemplo o id do plugin em `plugins/memory/<nome>/`). Sem provedor externo ativo, nada é adicionado.

### `memory`

- `setup`, `status`, `off`, `reset` (`--yes`, `--target`)

### `tools`

Sem subcomando: TUI interativa. Com subcomando:

- `list`, `disable`, `enable`

### `mcp`

- `serve`, `add`, `remove` (alias `rm`), `list` (alias `ls`), `test`, `configure` (alias `config`), `login`

### `sessions`

- `list`, `export`, `delete`, `prune`, `stats`, `rename`, `browse`

### `stats`

Métricas de uso (`--days`, `--source`). Alias legado: `insights`.

### `version`

### `update`

### `uninstall`

### `acp`

Servidor ACP (editores).

### `profile`

- `list`, `use`, `create`, `delete`, `show`, `alias`, `rename`, `export`, `import`

### `kill`

Encerra o painel web em execução (`--port`, padrão 9000). Também desabilita o site Nginx `ector-dashboard` no Linux, quando aplicável.

### `logs`

Nome de log posicional (`agent`, `errors`, `gateway`, ou `list`) + filtros (`-n`, `-f`, `--level`, `--session`, `--since`, `--component`).

---

## Comandos slash (dentro do chat / gateway)

Fonte: `COMMAND_REGISTRY` em `ector_cli/commands.py`. Uso: `/nome` (e aliases entre parênteses).

### Sessão

| Comando | Aliases | Notas |
|---------|---------|--------|
| `/new` | | |
| `/reset` | | só CLI; args `[--hard]` |
| `/clear` | | só CLI |
| `/redraw` | | só CLI |
| `/history` | | só CLI |
| `/save` | | só CLI |
| `/retry` | | |
| `/undo` | | |
| `/title` | | `[nome]` |
| `/branch` | `fork` | `[nome]` |
| `/compress` | | `[tópico]` |
| `/rollback` | | `[número]` |
| `/snapshot` | `snap` | só CLI; `create`, `restore <id>`, `prune` |
| `/stop` | | |
| `/approve` | | só gateway; opcional `sessão` ou `always` |
| `/deny` | | só gateway |
| `/background` | `bg`, `btw` | `<prompt>` |
| `/agents` | `tasks` | |
| `/queue` | `q` | `<prompt>` |
| `/steer` | | `<prompt>` |
| `/status` | | |
| `/sethome` | `set-home` | só gateway |
| `/resume` | | `[nome]` |
| `/restart` | | só gateway |
| `/login` | | identidade ector.cc |
| `/logout` | `signout` | encerra sessão Ector (registro: categoria Sair) |

### Configuração

| Comando | Aliases | Notas |
|---------|---------|--------|
| `/config` | | só CLI |
| `/provider` | | `[modelo] [--provider …] [--global]` |
| `/personality` | | `[nome]` |
| `/statusbar` | `sb` | só CLI |
| `/verbose` | | só CLI; no gateway se `display.tool_progress_command` |
| `/yolo` | | |
| `/reasoning` | | subcomandos sugeridos: none, minimal, low, medium, high, xhigh, show, hide, on, off |
| `/fast` | | normal, fast, status, on, off |
| `/voice` | | on, off, tts, status |
| `/busy` | | só CLI; queue, steer, interrupt, status |
| `/rag` | | on, off, status, max-results, max-chars, min-query-chars |

### Ferramentas e habilidades

| Comando | Aliases | Notas |
|---------|---------|--------|
| `/tools` | | só CLI |
| `/toolsets` | | só CLI |
| `/skills` | | só CLI; search, browse, inspect, install |
| `/cron` | | só CLI; list, parity, add, create, edit, pause, resume, run, remove |
| `/reload` | | só CLI |
| `/reload-mcp` | `reload_mcp` | |
| `/browser` | | só CLI; connect, disconnect, status |
| `/plugins` | | só CLI |

### Informações

| Comando | Aliases | Notas |
|---------|---------|--------|
| `/commands` | | só gateway; `[página]` |
| `/help` | | |
| `/usage` | | |
| `/stats` | `insights` | `[dias]` |
| `/platforms` | `gateway` | só CLI; no chat web mostra estado + link para `/channels` |
| `/copy` | | só CLI; `[número]` |
| `/paste` | | só CLI |
| `/image` | | só CLI; `<caminho>` |
| `/debug` | | upload de relatório |
| `/gquota` | | só CLI |
| `/profile` | | perfil ativo (slash; não confundir com `ector profile`) |
| `/me` | `whoami` | nickname, usuário, status da sessão |

### Sair (CLI)

| Comando | Aliases |
|---------|---------|
| `/quit` | `exit` (só CLI) |

---

## Manutenção deste arquivo

Ao adicionar subcomandos no argparse ou entradas em `COMMAND_REGISTRY`, atualize esta lista ou regenere-a a partir do código.
