"""
MCP Server Management CLI — ``ector mcp`` subcommand.

Implements ``ector mcp add/remove/list/test/configure`` for interactive
MCP server lifecycle management (issue #690 Phase 2).

Relies on tools/mcp_tool.py for connection/discovery and keeps
configuration in ~/.ector/config.yaml under the ``mcp_servers`` key.
"""

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ector_cli.config import (
    load_config,
    save_config,
    get_env_value,
    save_env_value,
    get_ector_home,  # noqa: F401 — used by test mocks
)
from ector_cli.colors import Colors, color
from ector_constants import display_ector_home

logger = logging.getLogger(__name__)

_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ECTOR_ACCENT = "#00D1FF"


_MCP_PRESETS: Dict[str, Dict[str, Any]] = {}


# ─── Auxiliares de UI ───────────────────────────────────────────────────────────────

def _info(text: str):
    print(color(f"  {text}", Colors.DIM))

def _success(text: str):
    print(color(f"  ✔ {text}", Colors.GREEN))

def _warning(text: str):
    print(color(f"  ▲ {text}", Colors.YELLOW))

def _error(text: str):
    print(color(f"  ✖ {text}", Colors.RED))


def _confirm(question: str, default: bool = True) -> bool:
    default_str = "S/n" if default else "s/N"
    try:
        val = input(color(f"  {question} ({default_str}): ", Colors.YELLOW)).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return default
    if not val:
        return default
    return val in ("s", "sim", "y", "yes")


def _prompt(question: str, *, password: bool = False, default: str = "") -> str:
    from ector_cli.cli_output import prompt as _shared_prompt
    return _shared_prompt(question, default=default, password=password)


def _mcp_enabled(cfg: dict) -> bool:
    """Whether a server is enabled — matches agent/toolset resolution."""
    from ector_cli.tools_config import _parse_enabled_flag

    return _parse_enabled_flag(cfg.get("enabled", True), default=True)


def _print_mcp_examples(console) -> None:
    """Show placeholder-based examples — clearly not copy-paste literals."""
    from rich.panel import Panel
    from rich.table import Table

    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="dim", justify="right", no_wrap=True, width=10)
    grid.add_column()
    grid.add_row("", "[dim]Modelos de comando — substitua[/dim] [bold]<nome>[/bold][dim],[/dim] "
                 "[bold]<url>[/bold] [dim]e[/dim] [bold]<cmd>[/bold][dim] pelos seus valores.[/dim]")
    grid.add_row("HTTP", "[dim]ector mcp add[/dim] [bold]<nome>[/bold] [dim]--url[/dim] [bold]<url>[/bold]")
    grid.add_row("stdio", "[dim]ector mcp add[/dim] [bold]<nome>[/bold] [dim]--command[/dim] [bold]<cmd>[/bold] "
                 "[dim]--args[/dim] [bold]…[/bold]")
    grid.add_row("", "")
    grid.add_row("p.ex.", "[dim italic]ector mcp add files --command npx --args -y "
                 "@modelcontextprotocol/server-filesystem /tmp[/dim italic]")

    console.print(
        Panel(
            grid,
            title=f"[bold {_ECTOR_ACCENT}]Exemplos[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(0, 1),
        ),
    )


def _print_mcp_agent_note(console, *, servers_configured: int = 0, servers_active: int = 0) -> None:
    """Explain how configured MCP servers reach the agent."""
    if servers_configured == 0:
        console.print(
            "[dim]Servidores MCP expõem ferramentas externas ao agente. "
            "Após [bold]ector mcp add[/bold], reinicie o chat para carregar as ferramentas.[/dim]"
        )
        return

    if servers_active == 0:
        console.print(
            "[dim]Todos os servidores estão desativados — o agente não carrega ferramentas MCP "
            "até reativar um servidor ou adicionar outro.[/dim]"
        )
        return

    console.print(
        "[dim]Ferramentas dos servidores ativos entram no agente ao iniciar uma sessão. "
        "Alterações em [bold]configure[/bold] ou [bold]remove[/bold] exigem nova sessão.[/dim]"
    )


def _print_mcp_subcommands_help(console) -> None:
    """Rich command reference when ``ector mcp`` is invoked without a subcommand."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Comando", no_wrap=True, style="bold")
    table.add_column("Descrição", overflow="fold")

    rows = [
        ("ector mcp add <nome> …", "Adiciona servidor (HTTP ou stdio) com descoberta de ferramentas"),
        ("ector mcp list", "Lista servidores configurados"),
        ("ector mcp test <nome>", "Testa conexão e lista ferramentas descobertas"),
        ("ector mcp configure <nome>", "Alterna quais ferramentas ficam ativas"),
        ("ector mcp remove <nome>", "Remove servidor da configuração"),
        ("ector mcp login <nome>", "Reautentica servidor OAuth"),
        ("ector mcp serve", "Expõe o Ector como servidor MCP para outros agentes"),
    ]
    for cmd, desc in rows:
        table.add_row(cmd, desc)

    console.print(
        Panel(
            table,
            title=f"[bold {_ECTOR_ACCENT}]Comandos[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(0, 1),
        ),
    )


def _get_mcp_servers(config: Optional[dict] = None) -> Dict[str, dict]:
    """Return the ``mcp_servers`` dict from config, or empty dict."""
    if config is None:
        config = load_config()
    servers = config.get("mcp_servers")
    if not servers or not isinstance(servers, dict):
        return {}
    return servers


def _save_mcp_server(name: str, server_config: dict):
    """Add or update a server entry in config.yaml."""
    config = load_config()
    config.setdefault("mcp_servers", {})[name] = server_config
    save_config(config)


def _remove_mcp_server(name: str) -> bool:
    """Remove a server from config.yaml.  Returns True if it existed."""
    config = load_config()
    servers = config.get("mcp_servers", {})
    if name not in servers:
        return False
    del servers[name]
    if not servers:
        config.pop("mcp_servers", None)
    save_config(config)
    return True


def _env_key_for_server(name: str) -> str:
    """Convert server name to an env-var key like ``MCP_MYSERVER_API_KEY``."""
    return f"MCP_{name.upper().replace('-', '_')}_API_KEY"


def _parse_env_assignments(raw_env: Optional[List[str]]) -> Dict[str, str]:
    """Parse ``KEY=VALUE`` strings from CLI args into an env dict."""
    parsed: Dict[str, str] = {}
    for item in raw_env or []:
        text = str(item or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"Invalid --env value '{text}' (expected KEY=VALUE)")
        key, value = text.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --env value '{text}' (missing variable name)")
        if not _ENV_VAR_NAME_RE.match(key):
            raise ValueError(f"Invalid --env variable name '{key}'")
        parsed[key] = value
    return parsed


def _apply_mcp_preset(
    name: str,
    *,
    preset_name: Optional[str],
    url: Optional[str],
    command: Optional[str],
    cmd_args: List[str],
    server_config: Dict[str, Any],
) -> tuple[Optional[str], Optional[str], List[str], bool]:
    """Apply a known MCP preset when transport details were omitted."""
    if not preset_name:
        return url, command, cmd_args, False

    preset = _MCP_PRESETS.get(preset_name)
    if not preset:
        raise ValueError(f"Unknown MCP preset: {preset_name}")

    if url or command:
        return url, command, cmd_args, False

    url = preset.get("url")
    command = preset.get("command")
    cmd_args = list(preset.get("args") or [])

    if url:
        server_config["url"] = url
    if command:
        server_config["command"] = command
    if cmd_args:
        server_config["args"] = cmd_args

    return url, command, cmd_args, True


# ─── Discovery (temporary connect) ───────────────────────────────────────────

def _probe_single_server(
    name: str, config: dict, connect_timeout: float = 30
) -> List[Tuple[str, str]]:
    """Temporarily connect to one MCP server, list its tools, disconnect.

    Returns list of ``(tool_name, description)`` tuples.
    Raises on connection failure.
    """
    from tools.mcp_tool import (
        _ensure_mcp_loop,
        _run_on_mcp_loop,
        _connect_server,
        _stop_mcp_loop,
    )

    _ensure_mcp_loop()

    tools_found: List[Tuple[str, str]] = []

    async def _probe():
        server = await asyncio.wait_for(
            _connect_server(name, config), timeout=connect_timeout
        )
        for t in server._tools:
            desc = getattr(t, "description", "") or ""
            # Truncate long descriptions for display
            if len(desc) > 80:
                desc = desc[:77] + "..."
            tools_found.append((t.name, desc))
        await server.shutdown()

    try:
        _run_on_mcp_loop(_probe(), timeout=connect_timeout + 10)
    except BaseException as exc:
        raise _unwrap_exception_group(exc) from None
    finally:
        _stop_mcp_loop()

    return tools_found


def _unwrap_exception_group(exc: BaseException) -> Exception:
    """Extract the root-cause exception from anyio TaskGroup wrappers.

    The MCP SDK uses anyio task groups, which wrap errors in
    ``BaseExceptionGroup`` / ``ExceptionGroup``.  This makes error
    messages opaque ("unhandled errors in a TaskGroup").  We unwrap
    to surface the real cause (e.g. "401 Unauthorized").
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    # Retorna uma Exception comum para que os chamadores possam capturar normalmente
    if isinstance(exc, Exception):
        return exc
    return RuntimeError(str(exc))


# ─── ector mcp add ──────────────────────────────────────────────────────────

def cmd_mcp_add(args):
    """Adiciona um novo servidor MCP com seleção de ferramentas baseada em descoberta."""
    name = args.name
    url = getattr(args, "url", None)
    command = getattr(args, "command", None)
    cmd_args = getattr(args, "args", None) or []
    auth_type = getattr(args, "auth", None)
    preset_name = getattr(args, "preset", None)
    raw_env = getattr(args, "env", None)

    server_config: Dict[str, Any] = {}
    try:
        explicit_env = _parse_env_assignments(raw_env)
        url, command, cmd_args, _preset_applied = _apply_mcp_preset(
            name,
            preset_name=preset_name,
            url=url,
            command=command,
            cmd_args=list(cmd_args),
            server_config=server_config,
        )
    except ValueError as exc:
        _error(str(exc))
        return

    if url and explicit_env:
        _error("--env é suportado apenas para servidores MCP stdio (--command ou presets stdio)")
        return

    # Valida o transporte
    if not url and not command:
        _error("Deve especificar --url <endpoint>, --command <cmd> ou --preset <nome>")
        from rich.console import Console

        console = Console()
        console.print()
        _print_mcp_examples(console)
        console.print()
        return

    # Verifica se o servidor já existe
    existing = _get_mcp_servers()
    if name in existing:
        if not _confirm(f"O servidor '{name}' já existe. Sobrescrever?", default=False):
            _info("Cancelado.")
            return

    # Constrói config inicial
    if url:
        server_config["url"] = url
    else:
        server_config["command"] = command
        if cmd_args:
            server_config["args"] = cmd_args
        if explicit_env:
            server_config["env"] = explicit_env


    # ── Autenticação ──────────────────────────────────────────────────

    if url and auth_type == "oauth":
        print()
        _info(f"Iniciando fluxo OAuth para '{name}'...")
        oauth_ok = False
        try:
            from tools.mcp_oauth_manager import get_manager
            oauth_auth = get_manager().get_or_build_provider(name, url, None)
            if oauth_auth:
                server_config["auth"] = "oauth"
                _success("OAuth configurado (tokens serão adquiridos na primeira conexão)")
                oauth_ok=True
            else:
                _warning("Configuração de OAuth falhou — módulo de autenticação do MCP SDK não disponível")
        except Exception as exc:
            _warning(f"Erro no OAuth: {exc}")

        if not oauth_ok:
            _info("Este servidor pode não suportar OAuth.")
            if _confirm("Continuar sem autenticação?", default=True):
                # Não armazena auth: oauth — o servidor não suporta
                pass
            else:
                _info("Cancelado.")
                return

    elif url:
        # Prompt para chave de API / Bearer token para servidores HTTP
        print()
        _info(f"Conectando a {url}")
        needs_auth = _confirm("Este servidor requer autenticação?", default=True)
        if needs_auth:
            if auth_type == "header" or not auth_type:
                env_key = _env_key_for_server(name)
                existing_key = get_env_value(env_key)
                if existing_key:
                    _success(f"{env_key}: já configurado")
                    api_key = existing_key
                else:
                    api_key = _prompt("Chave de API / Bearer token", password=True)
                    if api_key:
                        save_env_value(env_key, api_key)
                        _success(f"Salvo em {display_ector_home()}/.env como {env_key}")

                # Define cabeçalho com interpolação de var de ambiente
                if api_key or existing_key:
                    server_config["headers"] = {
                        "Authorization": f"Bearer ${{{env_key}}}"
                    }

    # ── Descoberta: conectar e listar ferramentas ────────────────────

    print()
    print(color(f"  Conectando a '{name}'...", Colors.CYAN))

    try:
        tools = _probe_single_server(name, server_config)
    except Exception as exc:
        _error(f"Falha ao conectar: {exc}")
        if _confirm("Salvar configuração mesmo assim (você pode testar depois)?", default=False):
            server_config["enabled"] = False
            _save_mcp_server(name, server_config)
            _success(f"Salvo '{name}' na configuração (desativado)")
            _info("Corrija o problema e depois: ector mcp test " + name)
        return

    if not tools:
        _warning("Servidor conectado, mas não relatou ferramentas.")
        if _confirm("Salvar configuração mesmo assim?", default=True):
            _save_mcp_server(name, server_config)
            _success(f"Salvo '{name}' na configuração")
        return

    # ── Seleção de ferramentas ────────────────────────────────────────

    print()
    _success(f"Conectado! Encontrada(s) {len(tools)} ferramenta(s) de '{name}':")
    print()
    for tool_name, desc in tools:
        short = desc[:60] + "..." if len(desc) > 60 else desc
        print(f"    {color(tool_name, Colors.GREEN):40s} {short}")
    print()

    # Pergunta: ativar tudo, selecionar ou cancelar
    try:
        choice = input(
            color(f"  Ativar todas as {len(tools)} ferramentas? (S/n/selecionar): ", Colors.YELLOW)
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        _info("Cancelado.")
        return

    if choice in ("n", "no", "não"):
        _info("Cancelado — servidor não salvo.")
        return

    if choice in ("s", "select", "selecionar"):
        # Seleção interativa de ferramentas
        from ector_cli.curses_ui import curses_checklist

        labels = [f"{t[0]}  —  {t[1]}" for t in tools]
        pre_selected = set(range(len(tools)))

        chosen = curses_checklist(
            f"Selecione as ferramentas para '{name}'",
            labels,
            pre_selected,
        )

        if not chosen:
            _info("Nenhuma ferramenta selecionada — servidor não salvo.")
            return

        chosen_names = [tools[i][0] for i in sorted(chosen)]
        server_config.setdefault("tools", {})["include"] = chosen_names

        tool_count = len(chosen_names)
        total = len(tools)
    else:
        # Ativar tudo (sem necessidade de filtro — comportamento padrão)
        tool_count = len(tools)
        total = len(tools)

    # ── Salvar ────────────────────────────────────────────────────────

    server_config["enabled"] = True
    _save_mcp_server(name, server_config)

    print()
    _success(f"Salvo '{name}' em {display_ector_home()}/config.yaml ({tool_count}/{total} ferramentas ativadas)")
    _info("Inicie uma nova sessão para usar estas ferramentas.")


# ─── ector mcp remove ───────────────────────────────────────────────────────

def cmd_mcp_remove(args):
    """Remove um servidor MCP da configuração."""
    name = args.name
    existing = _get_mcp_servers()

    if name not in existing:
        _error(f"Servidor '{name}' não encontrado na configuração.")
        servers = list(existing.keys())
        if servers:
            _info(f"Servidores disponíveis: {', '.join(servers)}")
        return

    if not _confirm(f"Remover servidor '{name}'?", default=True):
        _info("Cancelado.")
        return

    _remove_mcp_server(name)
    _success(f"Removido '{name}' da configuração")

    # Limpa tokens OAuth se existirem
    try:
        from tools.mcp_oauth_manager import get_manager
        get_manager().remove(name)
        _success("Tokens OAuth limpos")
    except Exception:
        pass


# ─── ector mcp list ──────────────────────────────────────────────────────────

def _mcp_transport_label(cfg: dict) -> str:
    if "url" in cfg:
        url = cfg["url"]
        if len(url) > 40:
            return url[:37] + "..."
        return url
    if "command" in cfg:
        cmd = cfg["command"]
        cmd_args = cfg.get("args", [])
        if isinstance(cmd_args, list) and cmd_args:
            transport = f"{cmd} {' '.join(str(a) for a in cmd_args[:2])}"
        else:
            transport = cmd
        if len(transport) > 40:
            return transport[:37] + "..."
        return transport
    return "?"


def _mcp_tools_label(cfg: dict) -> str:
    tools_cfg = cfg.get("tools", {})
    if isinstance(tools_cfg, dict):
        include = tools_cfg.get("include")
        exclude = tools_cfg.get("exclude")
        if include and isinstance(include, list):
            return f"{len(include)} selecionadas"
        if exclude and isinstance(exclude, list):
            return f"-{len(exclude)} excluídas"
    return "todas"


def cmd_mcp_list(args=None):
    """Lista todos os servidores MCP configurados."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    servers = _get_mcp_servers()
    console = Console()
    dhh = display_ector_home()
    config_hint = f"{dhh}/config.yaml [dim]→ mcp_servers[/dim]"

    if not servers:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="dim", justify="right", no_wrap=True)
        grid.add_column()
        grid.add_row("Estado", "[dim]nenhum servidor configurado[/dim]")
        grid.add_row("Config", config_hint)

        console.print()
        console.print(
            Panel(
                grid,
                title=f"[bold {_ECTOR_ACCENT}]Servidores MCP[/bold {_ECTOR_ACCENT}]",
                border_style=_ECTOR_ACCENT,
                padding=(1, 2),
            ),
        )
        console.print()
        _print_mcp_examples(console)
        console.print()
        _print_mcp_agent_note(console)
        console.print()
        console.print(
            "[dim]Próximos passos: [bold]ector mcp test <nome>[/bold]  ·  "
            "[bold]ector mcp configure <nome>[/bold][/dim]"
        )
        console.print()
        return

    enabled_count = sum(1 for cfg in servers.values() if _mcp_enabled(cfg))
    disabled_count = len(servers) - enabled_count

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
        border_style=_ECTOR_ACCENT,
    )
    table.add_column("Nome", style="bold", no_wrap=True, ratio=1, max_width=16)
    table.add_column("Transporte", overflow="fold", ratio=3)
    table.add_column("Ferramentas", no_wrap=True, min_width=14)
    table.add_column("Estado", no_wrap=True, min_width=12)

    for name, cfg in servers.items():
        if _mcp_enabled(cfg):
            status = "[green]ativado[/green]"
        else:
            status = "[dim]desativado[/dim]"
        table.add_row(
            name,
            _mcp_transport_label(cfg),
            _mcp_tools_label(cfg),
            status,
        )

    console.print()
    console.print(
        Panel(
            table,
            title=(
                f"[bold {_ECTOR_ACCENT}]Servidores MCP[/bold {_ECTOR_ACCENT}] "
                f"[dim]({enabled_count}/{len(servers)} ativos"
                + (f", {disabled_count} desativado(s)" if disabled_count else "")
                + ")[/dim]"
            ),
            subtitle=config_hint,
            border_style=_ECTOR_ACCENT,
            padding=(0, 1),
        ),
    )
    console.print()
    _print_mcp_agent_note(
        console,
        servers_configured=len(servers),
        servers_active=enabled_count,
    )
    console.print()
    console.print(
        "[dim]Gerir: [bold]ector mcp add[/bold]  ·  "
        "[bold]ector mcp remove <nome>[/bold]  ·  "
        "[bold]ector mcp test <nome>[/bold]  ·  "
        "[bold]ector mcp configure <nome>[/bold][/dim]"
    )
    if enabled_count == 0:
        console.print()
        _print_mcp_examples(console)
    console.print()


# ─── ector mcp test ──────────────────────────────────────────────────────────

def cmd_mcp_test(args):
    """Testa a conexão com um servidor MCP."""
    name = args.name
    servers = _get_mcp_servers()

    if name not in servers:
        _error(f"Servidor '{name}' não encontrado na configuração.")
        available = list(servers.keys())
        if available:
            _info(f"Disponível: {', '.join(available)}")
        return

    cfg = servers[name]
    print()
    print(color(f"  Testando '{name}'...", Colors.CYAN))

    # Mostra info de transporte
    if "url" in cfg:
        _info(f"Transporte: HTTP → {cfg['url']}")
    else:
        cmd = cfg.get("command", "?")
        _info(f"Transporte: stdio → {cmd}")

    # Mostra info de auth (mascarada)
    auth_type = cfg.get("auth", "")
    headers = cfg.get("headers", {})
    if auth_type == "oauth":
        _info("Auth: OAuth 2.1 PKCE")
    elif headers:
        for k, v in headers.items():
            if isinstance(v, str) and ("key" in k.lower() or "auth" in k.lower()):
                # Mascara o valor
                resolved = _interpolate_value(v)
                if len(resolved) > 8:
                    masked = resolved[:4] + "***" + resolved[-4:]
                else:
                    masked = "***"
                print(f"    {k}: {masked}")
    else:
        _info("Auth: nenhuma")

    # Tenta conexão
    start = time.monotonic()
    try:
        tools = _probe_single_server(name, cfg)
        elapsed_ms = (time.monotonic() - start) * 1000
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        _error(f"Conexão falhou ({elapsed_ms:.0f}ms): {exc}")
        return

    _success(f"Conectado ({elapsed_ms:.0f}ms)")
    _success(f"Ferramentas descobertas: {len(tools)}")

    if tools:
        print()
        for tool_name, desc in tools:
            short = desc[:55] + "..." if len(desc) > 55 else desc
            print(f"    {color(tool_name, Colors.GREEN):36s} {short}")
    print()


def _interpolate_value(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in a string."""
    def _replace(m):
        return os.getenv(m.group(1), "")
    return re.sub(r"\$\{(\w+)\}", _replace, value)


# ─── ector mcp login ────────────────────────────────────────────────────────

def cmd_mcp_login(args):
    """Força a reautenticação para um servidor MCP baseado em OAuth."""
    name = args.name
    servers = _get_mcp_servers()

    if name not in servers:
        _error(f"Servidor '{name}' não encontrado na configuração.")
        if servers:
            _info(f"Servidores disponíveis: {', '.join(servers)}")
        return

    server_config = servers[name]
    url = server_config.get("url")
    if not url:
        _error(f"O servidor '{name}' não tem URL — não é um servidor compatível com OAuth")
        return
    if server_config.get("auth") != "oauth":
        _error(f"O servidor '{name}' não está configurado para OAuth (auth={server_config.get('auth')})")
        _info("Use `ector mcp remove` + `ector mcp add` para reconfigurar a autenticação.")
        return

    # Limpa o cache tanto em disco quanto em memória
    try:
        from tools.mcp_oauth_manager import get_manager
        mgr = get_manager()
        mgr.remove(name)
    except Exception as exc:
        _warning(f"Não foi possível limpar o estado OAuth existente: {exc}")

    print()
    _info(f"Iniciando fluxo OAuth para '{name}'...")

    # Probe dispara o fluxo OAuth (redirecionamento do navegador + captura de callback).
    try:
        tools = _probe_single_server(name, server_config)
        if tools:
            _success(f"Autenticado — {len(tools)} ferramenta(s) disponível(is)")
        else:
            _success("Autenticado (o servidor não relatou ferramentas)")
    except Exception as exc:
        _error(f"Falha na autenticação: {exc}")


# ─── ector mcp configure ────────────────────────────────────────────────────

def cmd_mcp_configure(args):
    """Reconfigura quais ferramentas estão ativadas para um servidor MCP existente."""
    import sys as _sys
    if not _sys.stdin.isatty():
        print("Erro: 'ector mcp configure' requer um terminal interativo.", file=_sys.stderr)
        _sys.exit(1)
    name = args.name
    servers = _get_mcp_servers()

    if name not in servers:
        _error(f"Servidor '{name}' não encontrado na configuração.")
        available = list(servers.keys())
        if available:
            _info(f"Disponível: {', '.join(available)}")
        return

    cfg = servers[name]

    # Descobre todas as ferramentas disponíveis
    print()
    print(color(f"  Conectando a '{name}' para descobrir ferramentas...", Colors.CYAN))

    try:
        all_tools = _probe_single_server(name, cfg)
    except Exception as exc:
        _error(f"Falha ao conectar: {exc}")
        return

    if not all_tools:
        _warning("O servidor não relata ferramentas.")
        return

    # Determina quais estão ativadas atualmente
    tools_cfg = cfg.get("tools", {})
    if isinstance(tools_cfg, dict):
        include = tools_cfg.get("include")
        exclude = tools_cfg.get("exclude")
    else:
        include = None
        exclude = None

    tool_names = [t[0] for t in all_tools]

    if include and isinstance(include, list):
        include_set = set(include)
        pre_selected = {
            i for i, tn in enumerate(tool_names) if tn in include_set
        }
    elif exclude and isinstance(exclude, list):
        exclude_set = set(exclude)
        pre_selected = {
            i for i, tn in enumerate(tool_names) if tn not in exclude_set
        }
    else:
        pre_selected = set(range(len(all_tools)))

    currently = len(pre_selected)
    total = len(all_tools)
    _info(f"Atualmente {currently}/{total} ferramentas ativadas para '{name}'.")
    print()

    # Checklist interativo
    from ector_cli.curses_ui import curses_checklist

    labels = [f"{t[0]}  —  {t[1]}" for t in all_tools]

    chosen = curses_checklist(
        f"Selecione as ferramentas para '{name}'",
        labels,
        pre_selected,
    )

    if chosen == pre_selected:
        _info("Nenhuma alteração feita.")
        return

    # Atualiza config
    config = load_config()
    server_entry = config.get("mcp_servers", {}).get(name, {})

    if len(chosen) == total:
        # Tudo selecionado → remove include/exclude (registra tudo)
        server_entry.pop("tools", None)
    else:
        chosen_names = [tool_names[i] for i in sorted(chosen)]
        server_entry.setdefault("tools", {})
        server_entry["tools"]["include"] = chosen_names
        server_entry["tools"].pop("exclude", None)

    config.setdefault("mcp_servers", {})[name] = server_entry
    save_config(config)

    new_count = len(chosen)
    _success(f"Configuração atualizada: {new_count}/{total} ferramentas ativadas")
    _info("Inicie uma nova sessão para que as alterações entrem em vigor.")


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def mcp_command(args):
    """Despachante principal para os subcomandos de ``ector mcp``."""
    action = getattr(args, "mcp_action", None)

    if action == "serve":
        from mcp_serve import run_mcp_server
        run_mcp_server(verbose=getattr(args, "verbose", False))
        return

    handlers = {
        "add": cmd_mcp_add,
        "remove": cmd_mcp_remove,
        "rm": cmd_mcp_remove,
        "list": cmd_mcp_list,
        "ls": cmd_mcp_list,
        "test": cmd_mcp_test,
        "configure": cmd_mcp_configure,
        "config": cmd_mcp_configure,
        "login": cmd_mcp_login,
    }

    handler = handlers.get(action)
    if handler:
        handler(args)
    else:
        from rich.console import Console

        console = Console()
        cmd_mcp_list()
        console.print()
        _print_mcp_subcommands_help(console)
        console.print()
