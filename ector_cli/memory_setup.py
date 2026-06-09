"""``ector memory`` — configure and inspect memory providers.

Subcommands:
- ``status`` (default) — Rich overview of native + external memory
- ``setup`` — interactive provider picker (curses)
- ``off`` — disable external provider (native MEMORY.md/USER.md stays on)
- ``reset`` — delete built-in memory files under ``<ECTOR_HOME>/memories/``
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from ector_constants import display_ector_home, get_ector_home

_ECTOR_ACCENT = "#00D1FF"


def _memory_console():
    from rich.console import Console

    return Console()


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _print_memory_panel(
    console,
    *,
    title: str,
    rows: list[tuple[str, str]],
    footer: str = "",
) -> None:
    from rich.panel import Panel
    from rich.table import Table

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right", no_wrap=True)
    grid.add_column()
    for label, value in rows:
        grid.add_row(label, value)

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold {_ECTOR_ACCENT}]{title}[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(1, 2),
        ),
    )
    if footer:
        console.print()
        console.print(f"[dim]{footer}[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Curses-based interactive picker (same pattern as ector tools)
# ---------------------------------------------------------------------------

def _curses_select(title: str, items: list[tuple[str, str]], default: int = 0) -> int:
    """Interactive single-select with arrow keys.

    items: list of (label, description) tuples.
    Returns selected index, or default on escape/quit.
    """
    from ector_cli.curses_ui import curses_radiolist
    # Format (label, desc) tuples into display strings
    display_items = [
        f"{label}  {desc}" if desc else label
        for label, desc in items
    ]
    return curses_radiolist(title, display_items, selected=default, cancel_returns=default)


def _prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    """Prompt for a value with optional default and secret masking."""
    suffix = f" [{default}]" if default else ""
    if secret:
        sys.stdout.write(f"  {label}{suffix}: ")
        sys.stdout.flush()
        if sys.stdin.isatty():
            val = getpass.getpass(prompt="")
        else:
            val = sys.stdin.readline().strip()
    else:
        sys.stdout.write(f"  {label}{suffix}: ")
        sys.stdout.flush()
        val = sys.stdin.readline().strip()
    return val or (default or "")


# ---------------------------------------------------------------------------
# Provider discovery
# ---------------------------------------------------------------------------

def _install_dependencies(provider_name: str) -> None:
    """Install pip dependencies declared in plugin.yaml."""
    import subprocess
    from plugins.memory import find_provider_dir

    plugin_dir = find_provider_dir(provider_name)
    if not plugin_dir:
        return
    yaml_path = plugin_dir / "plugin.yaml"
    if not yaml_path.exists():
        return

    try:
        import yaml
        with open(yaml_path) as f:
            meta = yaml.safe_load(f) or {}
    except Exception:
        return

    pip_deps = meta.get("pip_dependencies", [])
    if not pip_deps:
        return

    # pip name → import name mapping for packages where they differ
    _IMPORT_NAMES = {
        "mem0ai": "mem0",
        "hindsight-client": "hindsight_client",
        "hindsight-all": "hindsight",
    }

    # Check which packages are missing
    missing = []
    for dep in pip_deps:
        import_name = _IMPORT_NAMES.get(dep, dep.replace("-", "_").split("[")[0])
        try:
            __import__(import_name)
        except ImportError:
            missing.append(dep)

    if not missing:
        return

    print(f"\n  Instalando dependências: {', '.join(missing)}")

    import shutil
    uv_path = shutil.which("uv")
    if not uv_path:
        print(f"  ▲ uv não encontrado — não é possível instalar dependências")
        print(f"  Instale o uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
        print(f"  Depois execute novamente: ector memory setup")
        return

    try:
        subprocess.run(
            [uv_path, "pip", "install", "--python", sys.executable, "--quiet"] + missing,
            check=True, timeout=120,
            capture_output=True,
        )
        print(f"  ✔ Instalado {', '.join(missing)}")
    except subprocess.CalledProcessError as e:
        print(f"  ▲ Falha ao instalar {', '.join(missing)}")
        stderr = (e.stderr or b"").decode()[:200]
        if stderr:
            print(f"    {stderr}")
        print(f"  Execute manualmente: uv pip install --python {sys.executable} {' '.join(missing)}")
    except Exception as e:
        print(f"  ▲ Falha na instalação: {e}")
        print(f"  Execute manualmente: uv pip install --python {sys.executable} {' '.join(missing)}")

    # Também mostra dependências externas (não-pip), se houver
    ext_deps = meta.get("external_dependencies", [])
    for dep in ext_deps:
        dep_name = dep.get("name", "")
        check_cmd = dep.get("check", "")
        install_cmd = dep.get("install", "")
        if check_cmd:
            try:
                subprocess.run(
                    check_cmd, shell=True, capture_output=True, timeout=5
                )
            except Exception:
                if install_cmd:
                    print(f"\n  ▲ '{dep_name}' não encontrado. Instale com:")
                    print(f"    {install_cmd}")


def _get_available_providers() -> list:
    """Discover memory providers from plugins/memory/.

    Returns list of (name, description, provider_instance) tuples.
    """
    try:
        from plugins.memory import discover_memory_providers, load_memory_provider
        raw = discover_memory_providers()
    except Exception:
        raw = []

    results = []
    for name, desc, available in raw:
        try:
            provider = load_memory_provider(name)
            if not provider:
                continue
        except Exception:
            continue

        schema = provider.get_config_schema() if hasattr(provider, "get_config_schema") else []
        has_secrets = any(f.get("secret") for f in schema)
        has_non_secrets = any(not f.get("secret") for f in schema)
        if has_secrets and has_non_secrets:
            setup_hint = "Chave de API / local"
        elif has_secrets:
            setup_hint = "requer chave de API"
        elif not schema:
            setup_hint = "nenhuma configuração necessária"
        else:
            setup_hint = "local"

        results.append((name, setup_hint, provider))
    return results


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------

def cmd_setup_provider(provider_name: str) -> None:
    """Run memory setup for a specific provider, skipping the picker."""
    from ector_cli.config import load_config, save_config

    providers = _get_available_providers()
    match = None
    for name, desc, provider in providers:
        if name == provider_name:
            match = (name, desc, provider)
            break

    if not match:
        dhh = display_ector_home()
        console = _memory_console()
        console.print()
        console.print(
            f"[red]Erro:[/red] Provedor de memória [bold]{provider_name}[/bold] não encontrado."
        )
        console.print(
            f"[dim]Execute [bold]ector memory setup[/bold] ou "
            f"[bold]ector memory status[/bold].[/dim]"
        )
        console.print(
            f"[dim]Plugins vivem em {dhh}/plugins/ ou em plugins/memory/ do Ector.[/dim]"
        )
        console.print()
        return

    name, _, provider = match

    _install_dependencies(name)

    config = load_config()
    if not isinstance(config.get("memory"), dict):
        config["memory"] = {}

    if hasattr(provider, "post_setup"):
        ector_home = str(get_ector_home())
        provider.post_setup(ector_home, config)
        return

    # Fallback: configuração genérica baseada em schema
    config["memory"]["provider"] = name
    save_config(config)
    _print_setup_complete(name)


def _print_setup_complete(provider_name: str | None = None) -> None:
    """Show a consistent success panel after setup/off."""
    dhh = display_ector_home()
    if provider_name:
        rows = [
            ("Provedor", f"[bold green]{provider_name}[/bold green]"),
            ("Nativo", "[green]MEMORY.md / USER.md[/green]"),
            ("Config", f"{dhh}/config.yaml"),
            ("Segredos", f"{dhh}/.env [dim](se aplicável)[/dim]"),
        ]
        footer = "Inicie uma nova sessão para ativar o provedor externo."
    else:
        rows = [
            ("Provedor externo", "[dim]desativado[/dim]"),
            ("Nativo", "[green]MEMORY.md / USER.md[/green]"),
            ("Config", f"{dhh}/config.yaml"),
        ]
        footer = "A memória embutida continua ativa em todas as sessões."

    _print_memory_panel(
        _memory_console(),
        title="Memória configurada",
        rows=rows,
        footer=footer,
    )


def cmd_setup(args) -> None:
    """Interactive external memory plugin setup wizard."""
    from ector_cli.config import load_config, save_config

    providers = _get_available_providers()

    if not providers:
        dhh = display_ector_home()
        console = _memory_console()
        console.print()
        console.print("[yellow]▲[/yellow]  Nenhum plugin de memória externa detectado.")
        console.print(
            f"[dim]Os plugins empacotados ficam em [bold]plugins/memory/[/bold] do Ector; "
            f"instalações extras vão para [bold]{dhh}/plugins/[/bold].[/dim]"
        )
        console.print(
            "[dim]Configure com [bold]ector memory setup[/bold] quando um plugin estiver "
            "disponível.[/dim]"
        )
        console.print()
        return

    # Itens do seletor
    items = []
    for name, desc, _ in providers:
        items.append((name, f"— {desc}"))
    items.append(("Apenas nativo", "— MEMORY.md / USER.md (padrão)"))

    builtin_idx = len(items) - 1
    selected = _curses_select("Configuração do plugin de memória", items, default=builtin_idx)

    config = load_config()
    if not isinstance(config.get("memory"), dict):
        config["memory"] = {}

    # Apenas nativo
    if selected >= len(providers) or selected < 0:
        config["memory"]["provider"] = ""
        save_config(config)
        _print_setup_complete(None)
        return

    name, _, provider = providers[selected]

    # Install pip dependencies if declared in plugin.yaml
    _install_dependencies(name)

    # If the provider has a post_setup hook, delegate entirely to it.
    # The hook handles its own config, connection test, and activation.
    if hasattr(provider, "post_setup"):
        ector_home = str(get_ector_home())
        provider.post_setup(ector_home, config)
        return

    schema = provider.get_config_schema() if hasattr(provider, "get_config_schema") else []

    provider_config = config["memory"].get(name, {})
    if not isinstance(provider_config, dict):
        provider_config = {}

    env_path = get_ector_home() / ".env"
    env_writes = {}

    if schema:
        print(f"\n  Configurando {name}:\n")

        for field in schema:
            key = field["key"]
            desc = field.get("description", key)
            default = field.get("default")
            # Default dinâmico: busca o padrão a partir do valor de outro campo
            default_from = field.get("default_from")
            if default_from and isinstance(default_from, dict):
                ref_field = default_from.get("field", "")
                ref_map = default_from.get("map", {})
                ref_value = provider_config.get(ref_field, "")
                if ref_value and ref_value in ref_map:
                    default = ref_map[ref_value]
            is_secret = field.get("secret", False)
            choices = field.get("choices")
            env_var = field.get("env_var")
            url = field.get("url")

            # Pula campos cujas condições "when" não batem
            when = field.get("when")
            if when and isinstance(when, dict):
                if not all(provider_config.get(k) == v for k, v in when.items()):
                    continue

            if choices and not is_secret:
                # Usa seletor curses para campos de escolha
                choice_items = [(c, "") for c in choices]
                current = provider_config.get(key, default)
                current_idx = 0
                if current and current in choices:
                    current_idx = choices.index(current)
                sel = _curses_select(f"  {desc}", choice_items, default=current_idx)
                provider_config[key] = choices[sel]
            elif is_secret:
                # Prompt para segredo
                existing = os.environ.get(env_var, "") if env_var else ""
                if existing:
                    masked = f"...{existing[-4:]}" if len(existing) > 4 else "definido"
                    val = _prompt(f"{desc} (atual: {masked}, em branco para manter)", secret=True)
                else:
                    hint = f"  Obtenha a sua em {url}" if url else ""
                    if hint:
                        print(hint)
                    val = _prompt(desc, secret=True)
                if val and env_var:
                    env_writes[env_var] = val
            else:
                # Prompt de texto comum
                current = provider_config.get(key)
                effective_default = current or default
                val = _prompt(desc, default=str(effective_default) if effective_default else None)
                if val:
                    provider_config[key] = val
                    # Também escreve no .env se este campo tiver um env_var
                    if env_var and env_var not in env_writes:
                        env_writes[env_var] = val

    # Write activation key to config.yaml
    config["memory"]["provider"] = name
    save_config(config)

    # Write non-secret config to provider's native location
    ector_home = str(get_ector_home())
    if provider_config and hasattr(provider, "save_config"):
        try:
            provider.save_config(provider_config, ector_home)
        except Exception as e:
            print(f"  Failed to write provider config: {e}")

    # Write secrets to .env
    if env_writes:
        _write_env_vars(env_path, env_writes)

    _print_setup_complete(name)


def _write_env_vars(env_path: Path, env_writes: dict) -> None:
    """Append or update env vars in .env file."""
    env_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()

    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        key_match = line.split("=", 1)[0].strip() if "=" in line else ""
        if key_match in env_writes:
            new_lines.append(f"{key_match}={env_writes[key_match]}")
            updated_keys.add(key_match)
        else:
            new_lines.append(line)

    for key, val in env_writes.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _active_provider_details(
    provider_name: str,
    mem_config: dict,
    providers: list,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Return (config_rows, missing_env_rows) for the active provider."""
    config_rows: list[tuple[str, str]] = []
    missing_env: list[tuple[str, str, str]] = []

    provider_config = mem_config.get(provider_name, {})
    if isinstance(provider_config, dict) and provider_config:
        for key, val in provider_config.items():
            config_rows.append((key, str(val)))

    for pname, _, provider in providers:
        if pname != provider_name:
            continue
        if provider.is_available():
            config_rows.append(("Disponibilidade", "disponível"))
        else:
            config_rows.append(("Disponibilidade", "indisponível"))
            schema = (
                provider.get_config_schema()
                if hasattr(provider, "get_config_schema")
                else []
            )
            for field in schema:
                env_var = field.get("env_var", "")
                if not env_var:
                    continue
                url = field.get("url", "")
                is_set = bool(os.environ.get(env_var))
                if not is_set:
                    missing_env.append((env_var, url or "", field.get("label", env_var)))
        break

    return config_rows, missing_env


def print_memory_status() -> None:
    """Render ``ector memory status`` with Rich panels."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ector_cli.config import load_config

    console = Console()
    config = load_config()
    mem_config = config.get("memory", {})
    if not isinstance(mem_config, dict):
        mem_config = {}
    provider_name = (mem_config.get("provider") or "").strip()
    dhh = display_ector_home()
    providers = _get_available_providers()
    provider_installed = any(name == provider_name for name, _, _ in providers) if provider_name else False

    overview = Table.grid(padding=(0, 2))
    overview.add_column(style="dim", justify="right", no_wrap=True)
    overview.add_column()
    overview.add_row("Nativo", "[green]sempre ativo[/green]")
    if provider_name:
        label = f"[bold green]{provider_name}[/bold green]"
        if not provider_installed:
            label += " [red](plugin não instalado)[/red]"
        overview.add_row("Provedor", label)
    else:
        overview.add_row("Provedor", "[dim]nenhum (apenas nativo)[/dim]")
    overview.add_row("Pasta", f"{dhh}/memories/")
    _delta = mem_config.get("session_delta_injection", False)
    if _delta is True or (isinstance(_delta, str) and _delta.lower() in ("true", "yes", "on", "1")):
        overview.add_row("Delta de sessão", "[green]ativo[/green]")
    else:
        overview.add_row("Delta de sessão", "[dim]desligado[/dim]")

    console.print()
    console.print(
        Panel(
            overview,
            title=f"[bold {_ECTOR_ACCENT}]Status da memória[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(1, 2),
        ),
    )

    if provider_name:
        config_rows, missing_env = _active_provider_details(
            provider_name, mem_config, providers
        )
        if config_rows or missing_env:
            detail = Table.grid(padding=(0, 2))
            detail.add_column(style="dim", justify="right", no_wrap=True)
            detail.add_column()
            for key, val in config_rows:
                if val == "disponível":
                    cell = "[green]disponível[/green]"
                elif val == "indisponível":
                    cell = "[red]indisponível[/red]"
                else:
                    cell = val
                detail.add_row(key, cell)
            for env_var, url, _label in missing_env:
                hint = f" [dim]→ {url}[/dim]" if url else ""
                detail.add_row(env_var, f"[red]ausente[/red]{hint}")

            console.print()
            console.print(
                Panel(
                    detail,
                    title=f"[bold {_ECTOR_ACCENT}]Provedor ativo: {provider_name}[/bold {_ECTOR_ACCENT}]",
                    border_style=_ECTOR_ACCENT,
                    padding=(1, 2),
                ),
            )
        elif not provider_installed:
            console.print()
            console.print(
                f"[{_ECTOR_ACCENT}]▲[/{_ECTOR_ACCENT}]  Instale o plugin em "
                f"[bold]{dhh}/plugins/{provider_name}[/bold] ou execute "
                f"[bold]ector plugins install …[/bold]"
            )

    if providers:
        table = Table(
            title=f"[bold {_ECTOR_ACCENT}]Plugins de memória[/bold {_ECTOR_ACCENT}]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            expand=True,
            padding=(0, 1),
            title_justify="left",
            border_style=_ECTOR_ACCENT,
        )
        table.add_column("Plugin", style="bold", no_wrap=True, ratio=1, max_width=16)
        table.add_column("Configuração", overflow="fold", ratio=2, style="dim")
        table.add_column("Estado", no_wrap=True, min_width=14)

        for pname, desc, provider in providers:
            if pname == provider_name:
                state = "[bold green]◆ ativo[/bold green]"
            elif provider.is_available():
                state = "[green]disponível[/green]"
            else:
                state = "[dim]indisponível[/dim]"
            table.add_row(pname, desc, state)

        console.print()
        console.print(table)

    console.print()
    console.print(
        "[dim]Perfil (apelido/personalidade/iniciativa): ector.cc — "
        "USER.md guarda preferências locais curadas pelo agente; "
        "MEMORY.md guarda ambiente/projeto. "
        "Delta de sessão: [bold]memory.session_delta_injection[/bold] em config.yaml.[/dim]"
    )
    console.print(
        "[dim]Comandos: [bold]ector memory setup[/bold]  ·  "
        "[bold]ector memory off[/bold]  ·  "
        "[bold]ector memory reset[/bold][/dim]"
    )
    console.print()


def cmd_off() -> None:
    """Disable external memory provider (native memory stays on)."""
    from ector_cli.config import load_config, save_config

    config = load_config()
    if not isinstance(config.get("memory"), dict):
        config["memory"] = {}
    config["memory"]["provider"] = ""
    save_config(config)
    _print_setup_complete(None)


def cmd_reset(args) -> None:
    """Delete built-in MEMORY.md / USER.md files."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    mem_dir = get_ector_home() / "memories"
    dhh = display_ector_home()
    target = getattr(args, "target", "all")
    console = _memory_console()

    files_to_reset = []
    if target in ("all", "memory"):
        files_to_reset.append(("MEMORY.md", "notas do agente"))
    if target in ("all", "user"):
        files_to_reset.append(("USER.md", "perfil do utilizador"))

    existing = [(f, desc) for f, desc in files_to_reset if (mem_dir / f).exists()]
    if not existing:
        console.print()
        console.print(
            f"[dim]Nada para redefinir — nenhum ficheiro em {dhh}/memories/.[/dim]"
        )
        console.print()
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
        border_style=_ECTOR_ACCENT,
    )
    table.add_column("Ficheiro", style="bold", no_wrap=True)
    table.add_column("Conteúdo", style="dim", overflow="fold", ratio=2)
    table.add_column("Tamanho", justify="right", no_wrap=True)

    for fname, desc in existing:
        size = (mem_dir / fname).stat().st_size
        table.add_row(fname, desc, _format_bytes(size))

    console.print()
    console.print(
        Panel(
            table,
            title=f"[bold {_ECTOR_ACCENT}]Apagar memória nativa[/bold {_ECTOR_ACCENT}]",
            subtitle=f"[dim]{dhh}/memories/[/dim]",
            border_style=_ECTOR_ACCENT,
            padding=(0, 1),
        ),
    )

    if not getattr(args, "yes", False):
        try:
            answer = input("\n  Digite 'sim' para confirmar: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelado.[/dim]\n")
            return
        if answer not in ("sim", "yes"):
            console.print("[dim]Cancelado.[/dim]\n")
            return

    deleted = []
    for fname, desc in existing:
        (mem_dir / fname).unlink()
        deleted.append(f"{fname} ({desc})")

    _print_memory_panel(
        console,
        title="Memória redefinida",
        rows=[
            ("Apagados", ", ".join(deleted)),
            ("Pasta", f"{dhh}/memories/"),
            ("Efeito", "[dim]novas sessões começam do zero[/dim]"),
        ],
        footer="O provedor externo (se configurado) não é alterado.",
    )


def cmd_status(args) -> None:
    """Mostra a configuração atual do plugin de memória."""
    print_memory_status()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def memory_command(args) -> None:
    """Route memory subcommands."""
    sub = getattr(args, "memory_command", None)
    if sub == "setup":
        cmd_setup(args)
    elif sub == "off":
        cmd_off()
    elif sub == "reset":
        cmd_reset(args)
    elif sub in (None, "status"):
        cmd_status(args)
    else:
        cmd_status(args)
