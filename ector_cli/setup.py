"""
Assistente de configuração interativo para o Ector Agent.

Assistente modular com seções executáveis independentemente:
  1. Modelo & Provedor — escolha seu provedor de IA e modelo
  2. Backend do Terminal — onde seu agente executa comandos
  3. Configurações do Agente — iterações, compressão, reinicialização de sessão
  4. Plataformas de Mensagens — conecte Telegram, Discord, etc.
  5. Ferramentas — configure TTS, busca web, geração de imagens, etc.

Arquivos de configuração são armazenados em ~/.ector/ para fácil acesso.
"""

import importlib.util
import logging
import os
import shutil
import sys
import copy
from pathlib import Path
from typing import Optional, Dict, Any

from utils import base_url_hostname

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _model_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    current_model = config.get("model")
    if isinstance(current_model, dict):
        return dict(current_model)
    if isinstance(current_model, str) and current_model.strip():
        return {"default": current_model.strip()}
    return {}


def _get_credential_pool_strategies(config: Dict[str, Any]) -> Dict[str, str]:
    strategies = config.get("credential_pool_strategies")
    return dict(strategies) if isinstance(strategies, dict) else {}


def _set_credential_pool_strategy(config: Dict[str, Any], provider: str, strategy: str) -> None:
    if not provider:
        return
    strategies = _get_credential_pool_strategies(config)
    strategies[provider] = strategy
    config["credential_pool_strategies"] = strategies


def _supports_same_provider_pool_setup(provider: str) -> bool:
    if not provider or provider == "custom":
        return False
    if provider == "openrouter":
        return True
    from ector_cli.auth import PROVIDER_REGISTRY

    pconfig = PROVIDER_REGISTRY.get(provider)
    if not pconfig:
        return False
    return pconfig.auth_type in {"api_key", "oauth_device_code"}


def _current_reasoning_effort(config: Dict[str, Any]) -> str:
    agent_cfg = config.get("agent")
    if isinstance(agent_cfg, dict):
        return str(agent_cfg.get("reasoning_effort") or "").strip().lower()
    return ""


def _set_reasoning_effort(config: Dict[str, Any], effort: str) -> None:
    agent_cfg = config.get("agent")
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
        config["agent"] = agent_cfg
    agent_cfg["reasoning_effort"] = effort




# Import config helpers
from ector_cli.config import (
    DEFAULT_CONFIG,
    get_ector_home,
    get_config_path,
    get_env_path,
    load_config,
    save_config,
    save_env_value,
    get_env_value,
    ensure_ector_home,
)
# display_ector_home imported lazily at call sites (stale-module safety during ector update)

from ector_cli.colors import Colors, color


def _merge_user_profile_from_disk(config: dict) -> None:
    """Refresh ``config['user']`` from disk after identity sync or provider saves.

    The setup wizard keeps a long-lived *config* dict loaded before login.
    Any ``save_config(config)`` with that stale dict would overwrite the
    ``user.*`` block that ``identity_auth`` just mirrored from /me.
    """
    try:
        disk_user = load_config().get("user")
    except Exception:
        return
    if not isinstance(disk_user, dict):
        return
    block = config.get("user")
    if not isinstance(block, dict):
        block = {}
        config["user"] = block
    for key, value in disk_user.items():
        text = str(value or "").strip()
        if text:
            block[key] = value


def print_header(title: str):
    """Print a section header (accent cyan — matches prompt_choice titles)."""
    print()
    print(color(f"◆ {title}", Colors.CYAN, Colors.BOLD))


_BOX_INNER = 55


def _box_rule() -> str:
    return "─" * (_BOX_INNER + 2)


def _box_row(text: str, *, align: str = "left") -> str:
    if len(text) > _BOX_INNER:
        text = text[: _BOX_INNER - 1] + "…"
    if align == "center":
        text = text.center(_BOX_INNER)
    elif align == "right":
        text = text.rjust(_BOX_INNER)
    else:
        text = text.ljust(_BOX_INNER)
    return f"│ {text} │"


def print_setup_panel(
    title: str,
    *body_lines: str,
    hint_line: str | None = None,
) -> None:
    """Painel com bordas alinhadas, título em destaque e corpo legível."""
    rule = _box_rule()
    print(color(f"┌{rule}┐", Colors.CYAN))
    print(color(_box_row(title, align="center"), Colors.CYAN, Colors.BOLD))
    if body_lines or hint_line:
        print(color(f"├{rule}┤", Colors.CYAN))
        for line in body_lines:
            print(color(_box_row(line), Colors.WHITE))
        if hint_line:
            print(color(_box_row(hint_line), Colors.DIM))
    print(color(f"└{rule}┘", Colors.CYAN))


from ector_cli.cli_output import (  # noqa: E402
    print_error,
    print_info,
    print_success,
    print_warning,
)


def is_interactive_stdin() -> bool:
    """Return True when stdin looks like a usable interactive TTY."""
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return False
    try:
        return bool(stdin.isatty())
    except Exception:
        return False


def _maybe_run_identity_login(args) -> None:
    """Run identity login as the first step of ``ector setup``.

    Skips when the user already has an active session or when a specific
    setup section was requested (the user is iterating on one knob, not
    bootstrapping from scratch).  Non-fatal: if login is declined or
    fails the wizard still proceeds — the agent gate will block real
    usage later until they run ``ector login``.
    """
    if getattr(args, "section", None):
        return
    try:
        from ector_cli import identity_auth
    except Exception:
        return

    try:
        if identity_auth.is_logged_in():
            return
    except Exception:
        return

    print()
    print(
        color("Olá, faça login para continuar", Colors.CYAN, Colors.BOLD)
    )
    
    try:
        ans = prompt(
            "Deseja fazer login agora?", default="s", prompt_color=Colors.WHITE
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        ans = "n"
    if ans not in ("", "s", "sim", "y", "yes"):
        print_warning(
            "Pulado. Você pode rodar `ector login` depois — "
            "comandos do agente continuarão bloqueados até lá."
        )
        return

    try:
        # ``identity_auth.login`` already prints the friendly success banner
        # ("Login realizado com sucesso." + optional "Olá <nick>!"), so we
        # don't repeat it here.
        identity_auth.login()
    except identity_auth.IdentityAuthError as exc:
        if exc.code == "user_cancelled":
            print_warning(
                "Login cancelado. Você pode rodar `ector login` depois — "
                "comandos do agente continuarão bloqueados até lá."
            )
            return
        print_warning(f"Login falhou: {exc}. Continue o setup e tente `ector login` depois.")
        return
    except KeyboardInterrupt:
        print_warning(
            "Login cancelado. Você pode rodar `ector login` depois — "
            "comandos do agente continuarão bloqueados até lá."
        )
        return
    except Exception as exc:  # noqa: BLE001
        print_warning(f"Erro inesperado no login: {exc}. Continue o setup e tente `ector login` depois.")
        return


def print_noninteractive_setup_guidance(reason: str | None = None) -> None:
    """Imprime orientações para fluxos de configuração sem interface/não interativos."""
    print()
    print(color("⚡ Configuração do Ector — Modo não interativo", Colors.CYAN, Colors.BOLD))
    print()
    if reason:
        print_info(reason)
    print_info("O assistente interativo não pode ser usado aqui.")
    print()
    from ector_constants import display_ector_home

    print_info("Configure o Ector editando config.yaml ou variáveis de ambiente:")
    print_info(f"  {display_ector_home()}/config.yaml  (model.provider, model.base_url, model.default)")
    print_info(f"  {display_ector_home()}/.env         (chaves de API)")
    print_info("  ector config edit                   (abre config.yaml no editor)")
    print()
    print_info("Ou defina OPENROUTER_API_KEY / OPENAI_API_KEY no seu ambiente.")
    print_info("Execute 'ector setup' em um terminal interativo para usar o assistente completo.")
    print()


def prompt(
    question: str,
    default: str = None,
    password: bool = False,
    *,
    prompt_color: str = Colors.CYAN,
) -> str:
    """Prompt for input with optional default."""
    if default:
        display = f"{question} [{default}]: "
    else:
        display = f"{question}: "

    try:
        if password:
            import getpass

            value = getpass.getpass(color(display, prompt_color))
        else:
            value = input(color(display, prompt_color))

        return value.strip() or default or ""
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)


def _curses_prompt_choice(question: str, choices: list, default: int = 0, description: str | None = None) -> int:
    """Single-select menu using curses. Delegates to curses_radiolist."""
    from ector_cli.curses_ui import curses_radiolist
    return curses_radiolist(question, choices, selected=default, cancel_returns=-1, description=description)



def prompt_choice(question: str, choices: list, default: int = 0, description: str | None = None) -> int:
    """Prompt for a choice from a list with arrow key navigation.

    Escape keeps the current default (skips the question).
    Ctrl+C exits the wizard.
    """
    try:
        idx = _curses_prompt_choice(question, choices, default, description=description)
    except Exception:
        # If curses is unavailable/misconfigured, gracefully fall back to
        # the plain numbered prompt below.
        idx = None

    if idx == -1:
        # ESC in curses menus means "keep current selection".
        print_info("  Pulado (mantendo o atual)")
        print()
        return default

    if idx >= 0:
        if idx == default:
            print_info("  Pulado (mantendo o atual)")
            print()
            return default
        print()
        return idx

    print(color(question, Colors.CYAN, Colors.BOLD))
    for i, choice in enumerate(choices):
        marker = "●" if i == default else "○"
        if i == default:
            print(color(f"  {marker} {choice}", Colors.GREEN))
        else:
            print(f"  {marker} {choice}")

    print_info(f"  Enter para o padrão ({default + 1})  Ctrl+C para sair")

    while True:
        try:
            value = input(
                color(f"  Selecione [1-{len(choices)}] ({default + 1}): ", Colors.DIM)
            )
            if not value:
                return default
            idx = int(value) - 1
            if 0 <= idx < len(choices):
                return idx
            print_error(f"Por favor, insira um número entre 1 e {len(choices)}")
        except ValueError:
            print_error("Por favor, insira um número")
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt for yes/no. Ctrl+C exits, empty input returns default."""
    default_str = "S/n" if default else "s/N"

    while True:
        try:
            value = (
                input(color(f"{question} ({default_str}): ", Colors.CYAN))
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)

        if not value:
            return default
        if value in ("s", "sim", "y", "yes"):
            return True
        if value in ("n", "no", "não"):
            return False
        print_error("Por favor, insira 's' ou 'n'")


def prompt_checklist(title: str, items: list, pre_selected: list = None) -> list:
    """
    Display a multi-select checklist and return the indices of selected items.

    Each item in `items` is a display string. `pre_selected` is a list of
    indices that should be checked by default. A "Continue →" option is
    appended at the end — the user toggles items with Space and confirms
    with Enter on "Continue →".

    Falls back to a numbered toggle interface when simple_term_menu is
    unavailable.

    Returns:
        List of selected indices (not including the Continue option).
    """
    if pre_selected is None:
        pre_selected = []

    from ector_cli.curses_ui import curses_checklist

    chosen = curses_checklist(
        title,
        items,
        set(pre_selected),
        # ESC/cancel should mean "don't change anything now", not "apply all
        # currently pre-selected items" (which can unexpectedly trigger
        # reconfiguration flows).
        cancel_returns=set(),
    )
    return sorted(chosen)


def _prompt_api_key(var: dict):
    """Display a nicely formatted API key input screen for a single env var."""
    tools = var.get("tools", [])
    tools_str = ", ".join(tools[:3])
    if len(tools) > 3:
        tools_str += f", +{len(tools) - 3} mais"

    print()
    print(color(f"  ─── {var.get('description', var['name'])} ───", Colors.CYAN))
    print()
    if tools_str:
        print_info(f"  Habilita: {tools_str}")
    if var.get("url"):
        print_info(f"  Obtenha sua chave em: {var['url']}")
    print()

    if var.get("password"):
        value = prompt(f"  {var.get('prompt', var['name'])}", password=True)
    else:
        value = prompt(f"  {var.get('prompt', var['name'])}")

    if value:
        save_env_value(var["name"], value)
        print_success("  ✔ Salvo")
    else:
        print_warning("  Pulado (configure mais tarde com 'ector setup')")


def _print_setup_summary(config: dict, ector_home):
    """Print the setup completion summary."""
    # Tool availability summary
    print()
    print_header("Resumo de Disponibilidade de Ferramentas")

    tool_status = []

    # Vision — use the same runtime resolver as the actual vision tools
    try:
        from agent.auxiliary_client import get_available_vision_backends

        _vision_backends = get_available_vision_backends()
    except Exception:
        _vision_backends = []

    if _vision_backends:
        tool_status.append(("Visão (análise de imagem)", True, None))
    else:
        tool_status.append(("Visão (análise de imagem)", False, "execute 'ector setup' para configurar"))

    # Mixture of Agents — requires OpenRouter specifically (calls multiple models)
    if get_env_value("OPENROUTER_API_KEY"):
        tool_status.append(("Mistura de Agentes (MoA)", True, None))
    else:
        tool_status.append(("Mistura de Agentes (MoA)", False, "OPENROUTER_API_KEY"))

    # Web tools (Exa, Parallel, Firecrawl, or Tavily)
    try:
        from tools.web_tools import check_web_api_key as _web_ok
        web_ok = _web_ok()
    except Exception:
        web_ok = False
    if web_ok:
        backend = (config.get("web") or {}).get("backend")
        label = f"Busca Web & Extração ({backend})" if backend else "Busca Web & Extração"
        tool_status.append((label, True, None))
    else:
        tool_status.append(("Busca Web & Extração", False, "EXA_API_KEY, PARALLEL_API_KEY, FIRECRAWL_API_KEY/FIRECRAWL_API_URL, ou TAVILY_API_KEY"))

    # Browser tools (local Chromium, Camofox, Browserbase, Browser Use)
    browser_provider = (config.get("browser") or {}).get("cloud_provider")
    browser_ok = browser_provider == "local" or bool(
        get_env_value("BROWSER_USE_API_KEY")
        or (get_env_value("BROWSERBASE_API_KEY") and get_env_value("BROWSERBASE_PROJECT_ID"))
        or get_env_value("CAMOFOX_URL")
    )
    if browser_ok:
        label = "Automação de Navegador"
        if browser_provider:
            label = f"Automação de Navegador ({browser_provider})"
        tool_status.append((label, True, None))
    else:
        missing_browser_hint = "npm install -g agent-browser, configure CAMOFOX_URL, ou configure Browser Use ou Browserbase"
        if browser_provider == "Browserbase":
            missing_browser_hint = (
                "npm install -g agent-browser e configure "
                "BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID"
            )
        elif browser_provider == "Browser Use":
            missing_browser_hint = (
                "npm install -g agent-browser e configure BROWSER_USE_API_KEY"
            )
        elif browser_provider == "Camofox":
            missing_browser_hint = "CAMOFOX_URL"
        elif browser_provider == "Local browser":
            missing_browser_hint = "npm install -g agent-browser"
        tool_status.append(
            ("Automação de Navegador", False, missing_browser_hint)
        )

    # Image generation — FAL (direct) or any plugin-registered provider
    image_ok = False
    try:
        from tools.image_generation_tool import check_image_generation_requirements
        image_ok = check_image_generation_requirements()
    except Exception:
        image_ok = False
    if image_ok:
        tool_status.append(("Geração de Imagem", True, None))
    else:
        # Fall back to probing plugin-registered providers so OpenAI-only
        # setups don't show as "missing FAL_KEY".
        _img_backend = None
        try:
            from agent.image_gen_registry import list_providers
            from ector_cli.plugins import _ensure_plugins_discovered

            _ensure_plugins_discovered()
            for _p in list_providers():
                if _p.name == "fal":
                    continue
                try:
                    if _p.is_available():
                        _img_backend = _p.display_name
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if _img_backend:
            tool_status.append((f"Geração de Imagem ({_img_backend})", True, None))
        else:
            tool_status.append(("Geração de Imagem", False, "FAL_KEY ou OPENAI_API_KEY"))

    # TTS — show configured provider
    tts_provider = config.get("tts", {}).get("provider", "edge")
    if tts_provider == "elevenlabs" and get_env_value("ELEVENLABS_API_KEY"):
        tool_status.append(("Text-to-Speech (ElevenLabs)", True, None))
    elif tts_provider == "openai" and (
        get_env_value("VOICE_TOOLS_OPENAI_KEY") or get_env_value("OPENAI_API_KEY")
    ):
        tool_status.append(("Text-to-Speech (OpenAI)", True, None))
    elif tts_provider == "minimax" and get_env_value("MINIMAX_API_KEY"):
        tool_status.append(("Text-to-Speech (MiniMax)", True, None))
    elif tts_provider == "mistral" and get_env_value("MISTRAL_API_KEY"):
        tool_status.append(("Text-to-Speech (Mistral Voxtral)", True, None))
    elif tts_provider == "gemini" and (get_env_value("GEMINI_API_KEY") or get_env_value("GOOGLE_API_KEY")):
        tool_status.append(("Text-to-Speech (Google Gemini)", True, None))
    elif tts_provider == "neutts":
        try:
            neutts_ok = importlib.util.find_spec("neutts") is not None
        except Exception:
            neutts_ok = False
        if neutts_ok:
            tool_status.append(("Text-to-Speech (NeuTTS local)", True, None))
        else:
            tool_status.append(("Text-to-Speech (NeuTTS — não instalado)", False, "execute 'ector setup tts'"))
    elif tts_provider == "kittentts":
        try:
            import importlib.util
            kittentts_ok = importlib.util.find_spec("kittentts") is not None
        except Exception:
            kittentts_ok = False
        if kittentts_ok:
            tool_status.append(("Text-to-Speech (KittenTTS local)", True, None))
        else:
            tool_status.append(("Text-to-Speech (KittenTTS — não instalado)", False, "execute 'ector setup tts'"))
    else:
        tool_status.append(("Text-to-Speech (Edge TTS)", True, None))

    from tools.tool_backend_helpers import has_direct_modal_credentials

    if config.get("terminal", {}).get("backend") == "modal":
        if has_direct_modal_credentials():
            tool_status.append(("Execução Modal (Modal direto)", True, None))
        else:
            tool_status.append(("Execução Modal", False, "execute 'ector setup terminal'"))

    # Tinker + WandB (RL training)
    if get_env_value("TINKER_API_KEY") and get_env_value("WANDB_API_KEY"):
        tool_status.append(("Treinamento RL (Tinker)", True, None))
    elif get_env_value("TINKER_API_KEY"):
        tool_status.append(("Treinamento RL (Tinker)", False, "WANDB_API_KEY"))
    else:
        tool_status.append(("Treinamento RL (Tinker)", False, "TINKER_API_KEY"))

    # Home Assistant
    if get_env_value("HASS_TOKEN"):
        tool_status.append(("Casa Inteligente (Home Assistant)", True, None))

    # Terminal (always available if system deps met)
    tool_status.append(("Terminal/Comandos", True, None))

    # Task planning (always available, in-memory)
    tool_status.append(("Planejamento de Tarefas (todo)", True, None))

    # Skills (always available -- bundled skills + user-created skills)
    tool_status.append(("Habilidades (ver, criar, editar)", True, None))

    # Print status
    available_count = sum(1 for _, avail, _ in tool_status if avail)
    total_count = len(tool_status)

    print_info(f"{available_count}/{total_count} categorias de ferramentas disponíveis:")
    print()

    for name, available, missing_var in tool_status:
        if available:
            print(f"   {color('✔', Colors.GREEN)} {name}")
        else:
            print(
                f"   {color('✖', Colors.RED)} {name} {color(f'(ausente {missing_var})', Colors.DIM)}"
            )

    print()

    disabled_tools = [(name, var) for name, avail, var in tool_status if not avail]
    if disabled_tools:
        print(
            color(
                "▲ Algumas ferramentas estão desativadas. Execute 'ector setup tools' para configurá-las,",
                Colors.CYAN,
            )
        )
        from ector_constants import display_ector_home as _dhh
        print(
            color(
                f"▲ ou edite {_dhh()}/.env diretamente para adicionar as chaves API ausentes.",
                Colors.CYAN,
            )
        )
        print()

    # Done banner
    print()
    print(
        color(
            "┌─────────────────────────────────────────────────────────┐", Colors.GREEN
        )
    )
    print(
        color(
            "│              ✔ Configuração Concluída!                  │", Colors.GREEN
        )
    )
    print(
        color(
            "└─────────────────────────────────────────────────────────┘", Colors.GREEN
        )
    )
    print()

    # Show file locations prominently
    from ector_constants import display_ector_home as _dhh
    print(color(f"🏠  Todos os seus arquivos estão em {_dhh()}/:", Colors.CYAN, Colors.BOLD))
    print()
    print(f"   {color('Configurações:', Colors.CYAN)}  {get_config_path()}")
    print(f"   {color('Chaves API:', Colors.CYAN)}     {get_env_path()}")
    print(
        f"   {color('Dados:', Colors.CYAN)}          {ector_home}/cron/, sessions/, logs/"
    )
    print()

    print(color("─" * 60, Colors.DIM))
    print()
    print(color("⚙️  Principais comandos de configuração:", Colors.CYAN, Colors.BOLD))
    print()
    print(f"   {color('ector setup', Colors.GREEN)}          Executar o assistente completo")
    print(f"   {color('ector setup model', Colors.GREEN)}    Alterar modelo/provedor")
    print(f"   {color('ector setup terminal', Colors.GREEN)} Alterar backend do terminal")
    print(f"   {color('ector setup gateway', Colors.GREEN)}  Configurar mensagens")
    print(f"   {color('ector setup tools', Colors.GREEN)}    Configurar provedores de ferramentas")
    print()
    print(f"   {color('ector config', Colors.GREEN)}         Ver configurações atuais")
    print(
        f"   {color('ector config edit', Colors.GREEN)}    Abrir config no seu editor"
    )
    print()
    print("   Ou edite os arquivos diretamente:")
    print(f"   {color(f'nano {get_config_path()}', Colors.DIM)}")
    print(f"   {color(f'nano {get_env_path()}', Colors.DIM)}")
    print()

    print(color("─" * 60, Colors.DIM))
    print()
    print(color("✨ Pronto para começar!", Colors.CYAN, Colors.BOLD))
    print()
    print(f"   {color('ector', Colors.GREEN)}              Iniciar chat")
    print(f"   {color('ector gateway', Colors.GREEN)}      Iniciar gateway de mensagens")
    print(f"   {color('ector doctor', Colors.GREEN)}       Verificar problemas")
    print()


def _prompt_container_resources(config: dict):
    """Prompt for container resource settings (Docker, Singularity, Modal, Daytona)."""
    terminal = config.setdefault("terminal", {})

    print()
    print_info("Configurações de Recursos do Container:")

    # Persistence
    current_persist = terminal.get("container_persistent", True)
    persist_label = "sim" if current_persist else "não"
    print_info("  O sistema de arquivos persistente mantém os arquivos entre as sessões.")
    print_info("  Defina como 'não' para sandboxes efêmeras que reiniciam a cada vez.")
    persist_str = prompt(
        "  Persistir sistema de arquivos entre sessões? (sim/não)", persist_label
    )
    terminal["container_persistent"] = persist_str.lower() in ("sim", "yes", "true", "y", "1")

    # CPU
    current_cpu = terminal.get("container_cpu", 1)
    cpu_str = prompt("  Núcleos de CPU", str(current_cpu))
    try:
        terminal["container_cpu"] = float(cpu_str)
    except ValueError:
        pass

    # Memory
    current_mem = terminal.get("container_memory", 5120)
    mem_str = prompt("  Memória em MB (5120 = 5GB)", str(current_mem))
    try:
        terminal["container_memory"] = int(mem_str)
    except ValueError:
        pass

    # Disk
    current_disk = terminal.get("container_disk", 51200)
    disk_str = prompt("  Disco em MB (51200 = 50GB)", str(current_disk))
    try:
        terminal["container_disk"] = int(disk_str)
    except ValueError:
        pass


# Tool categories and provider config are now in tools_config.py (shared
# between `ector tools` and `ector setup tools`).


# =============================================================================
# Section 1: Model & Provider Configuration
# =============================================================================



def setup_model_provider(config: dict, *, quick: bool = False):
    """Configure the inference provider and default model.

    Delegates to ``cmd_provider()`` (the same flow used by ``ector provider``)
    for provider selection, credential prompting, and model picking.
    This ensures a single code path for all provider setup — any new
    provider added to ``ector provider`` is automatically available here.

    When *quick* is True, skips credential rotation, vision, and TTS
    configuration — used by the streamlined first-time quick setup.
    """
    from ector_cli.config import load_config, save_config

    print_header("Configuração do Provedor")
    print_info("Escolha como se conectar ao seu modelo de chat principal.")
    print()

    # Delegate to the shared ector provider flow — handles provider picker,
    # credential prompting, model selection, and config persistence.
    from ector_cli.main import select_provider_and_model
    try:
        select_provider_and_model()
    except (SystemExit, KeyboardInterrupt):
        print()
        print_info("Configuração do provedor pulada.")
    except Exception as exc:
        logger.debug("select_provider_and_model error during setup: %s", exc)
        print_warning(f"A configuração do provedor encontrou um erro: {exc}")
        print_info("Você pode tentar novamente mais tarde com: ector provider")

    # Re-sync the wizard's config dict from what cmd_provider saved to disk.
    # This is critical: cmd_provider writes to disk via its own load/save cycle,
    # and the wizard's final save_config(config) must not overwrite those
    # changes with stale values (#4172).
    _refreshed = load_config()
    config["model"] = _refreshed.get("model", config.get("model"))
    if "custom_providers" in _refreshed:
        config["custom_providers"] = _refreshed["custom_providers"]
    else:
        config.pop("custom_providers", None)
    _merge_user_profile_from_disk(config)

    # Derive the selected provider for downstream steps (vision setup).
    selected_provider = None
    _m = config.get("model")
    if isinstance(_m, dict):
        selected_provider = _m.get("provider")

    # ── Same-provider fallback & rotation setup (full setup only) ──
    if not quick and _supports_same_provider_pool_setup(selected_provider):
        try:
            from types import SimpleNamespace
            from agent.credential_pool import load_pool
            from ector_cli.auth_commands import auth_add_command

            pool = load_pool(selected_provider)
            entries = pool.entries()
            entry_count = len(entries)
            manual_count = sum(1 for entry in entries if str(getattr(entry, "source", "")).startswith("manual"))
            auto_count = entry_count - manual_count
            print()
            print_header("Fallback & Rotação do Mesmo Provedor")
            print_info(
                "O Ector pode manter múltiplas credenciais para um provedor e alternar entre"
            )
            print_info(
                "elas quando uma credencial é esgotada ou sofre limite de taxa. Isso preserva"
            )
            print_info(
                "seu provedor primário enquanto reduz interrupções por problemas de cota."
            )
            print()
            if auto_count > 0:
                print_info(
                    f"Credenciais atuais no pool para {selected_provider}: {entry_count} "
                    f"({manual_count} manuais, {auto_count} detectadas automaticamente de env/auth compartilhado)"
                )
            else:
                print_info(f"Credenciais atuais no pool para {selected_provider}: {entry_count}")

            while prompt_yes_no("Adicionar outra credencial para fallback do mesmo provedor?", False):
                auth_add_command(
                    SimpleNamespace(
                        provider=selected_provider,
                        auth_type="",
                        label=None,
                        api_key=None,
                        portal_url=None,
                        inference_url=None,
                        client_id=None,
                        scope=None,
                        no_browser=False,
                        timeout=15.0,
                        insecure=False,
                        ca_bundle=None,
                        min_key_ttl_seconds=5 * 60,
                    )
                )
                pool = load_pool(selected_provider)
                entry_count = len(pool.entries())
                print_info(f"O pool do provedor agora tem {entry_count} credencial(is).")

            if entry_count > 1:
                strategy_labels = [
                    "Fill-first / fixo — continua usando a primeira credencial saudável até que se esgote",
                    "Round robin — alterna para a próxima credencial saudável após cada seleção",
                    "Aleatório — escolhe uma credencial saudável aleatória a cada vez",
                ]
                current_strategy = _get_credential_pool_strategies(config).get(selected_provider, "fill_first")
                default_strategy_idx = {
                    "fill_first": 0,
                    "round_robin": 1,
                    "random": 2,
                }.get(current_strategy, 0)
                strategy_idx = prompt_choice(
                    "Selecione a estratégia de rotação do mesmo provedor:",
                    strategy_labels,
                    default_strategy_idx,
                )
                strategy_value = ["fill_first", "round_robin", "random"][strategy_idx]
                _set_credential_pool_strategy(config, selected_provider, strategy_value)
                print_success(f"Estratégia de rotação salva para {selected_provider}: {strategy_value}")
        except Exception as exc:
            logger.debug("Could not configure same-provider fallback in setup: %s", exc)

    # ── Vision & Image Analysis Setup (full setup only) ──
    if quick:
        _vision_needs_setup = False
    else:
        try:
            from agent.auxiliary_client import get_available_vision_backends
            _vision_backends = set(get_available_vision_backends())
        except Exception:
            _vision_backends = set()

        _vision_needs_setup = not bool(_vision_backends)

        if selected_provider in _vision_backends:
            _vision_needs_setup = False

    if _vision_needs_setup:
        _prov_names = {
            "ector-api": "Chave API ector.cc",
            "copilot": "GitHub Copilot",
            "copilot-acp": "GitHub Copilot ACP",
            "zai": "Z.AI / GLM",
            "kimi-coding": "Kimi / Moonshot",
            "kimi-coding-cn": "Kimi / Moonshot (China)",
            "stepfun": "StepFun Step Plan",
            "minimax": "MiniMax",
            "minimax-cn": "MiniMax CN",
            "anthropic": "Anthropic",
            "ai-gateway": "Vercel AI Gateway",
            "custom": "seu endpoint personalizado",
        }
        _prov_display = _prov_names.get(selected_provider, selected_provider or "seu provedor")

        print()
        print_header("Visão & Análise de Imagens (opcional)")
        print_info(f"A visão usa um backend multimodal separado. {_prov_display}")
        print_info("não fornece atualmente um que o Ector possa usar automaticamente para visão,")
        print_info("então escolha um backend agora ou pule para configurar depois.")
        print()

        _vision_choices = [
            "OpenRouter — usa o Gemini (nível gratuito em openrouter.ai/keys)",
            "Endpoint compatível com OpenAI — URL base, chave API e modelo de visão",
            "Pular por enquanto",
        ]
        _vision_idx = prompt_choice("Configurar visão:", _vision_choices, 2)

        if _vision_idx == 0:  # OpenRouter
            _or_key = prompt("  Chave API do OpenRouter", password=True).strip()
            if _or_key:
                save_env_value("OPENROUTER_API_KEY", _or_key)
                print_success("Chave do OpenRouter salva — a visão usará o Gemini")
            else:
                print_info("Pulado — a visão não estará disponível")
        elif _vision_idx == 1:  # OpenAI-compatible endpoint
            _base_url = prompt("  URL Base (vazio para OpenAI)").strip() or "https://api.openai.com/v1"
            _api_key_label = "  Chave API"
            _is_native_openai = base_url_hostname(_base_url) == "api.openai.com"
            if _is_native_openai:
                _api_key_label = "  Chave API da OpenAI"
            _oai_key = prompt(_api_key_label, password=True).strip()
            if _oai_key:
                save_env_value("OPENAI_API_KEY", _oai_key)
                # Save vision base URL to config (not .env — only secrets go there)
                _vaux = config.setdefault("auxiliary", {}).setdefault("vision", {})
                _vaux["base_url"] = _base_url
                if _is_native_openai:
                    _oai_vision_models = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"]
                    _vm_choices = _oai_vision_models + ["Usar padrão (gpt-4o-mini)"]
                    _vm_idx = prompt_choice("Selecione o modelo de visão:", _vm_choices, 0)
                    _selected_vision_model = (
                        _oai_vision_models[_vm_idx]
                        if _vm_idx < len(_oai_vision_models)
                        else "gpt-4o-mini"
                    )
                else:
                    _selected_vision_model = prompt("  Modelo de visão (vazio = usar padrão principal/personalizado)").strip()
                save_env_value("AUXILIARY_VISION_MODEL", _selected_vision_model)
                print_success(
                    f"Visão configurada com {_base_url}"
                    + (f" ({_selected_vision_model})" if _selected_vision_model else "")
                )
            else:
                print_info("Pulado — a visão não estará disponível")
        else:
            print_info("Pulado — adicione depois com 'ector setup' ou configure as definições AUXILIARY_VISION_*")


    # Model selection flow completed above.
    save_config(config)

    if not quick and selected_provider != "ector":
        _setup_tts_provider(config)


# =============================================================================
# Section 1b: TTS Provider Configuration
# =============================================================================


def _check_espeak_ng() -> bool:
    """Check if espeak-ng is installed."""
    return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None


def _install_neutts_deps() -> bool:
    """Install NeuTTS dependencies with user approval. Returns True on success."""
    import subprocess
    import sys

    # Check espeak-ng
    if not _check_espeak_ng():
        print()
        print_warning("O NeuTTS requer espeak-ng para fonemização.")
        if sys.platform == "darwin":
            print_info("Instale com: brew install espeak-ng")
        elif sys.platform == "win32":
            print_info("Instale com: choco install espeak-ng")
        else:
            print_info("Instale com: sudo apt install espeak-ng")
        print()
        if prompt_yes_no("Instalar espeak-ng agora?", True):
            try:
                if sys.platform == "darwin":
                    subprocess.run(["brew", "install", "espeak-ng"], check=True)
                elif sys.platform == "win32":
                    subprocess.run(["choco", "install", "espeak-ng", "-y"], check=True)
                else:
                    subprocess.run(["sudo", "apt", "install", "-y", "espeak-ng"], check=True)
                print_success("espeak-ng instalado")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print_warning(f"Não foi possível instalar o espeak-ng automaticamente: {e}")
                print_info("Por favor, instale manualmente e execute o setup novamente.")
                return False
        else:
            print_warning("O espeak-ng é obrigatório para o NeuTTS. Instale manualmente antes de usar o NeuTTS.")

    # Install neutts Python package
    print()
    print_info("Instalando pacote Python neutts...")
    print_info("Isso também baixará o modelo de TTS (~300MB) no primeiro uso.")
    print()
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "neutts[all]", "--quiet"],
            check=True, timeout=300,
        )
        print_success("neutts instalado com sucesso")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print_error(f"Falha ao instalar o neutts: {e}")
        print_info("Tente manualmente: python -m pip install -U neutts[all]")
        return False


def _install_kittentts_deps() -> bool:
    """Install KittenTTS dependencies with user approval. Returns True on success."""
    import subprocess
    import sys

    wheel_url = (
        "https://github.com/KittenML/KittenTTS/releases/download/"
        "0.8.1/kittentts-0.8.1-py3-none-any.whl"
    )
    print()
    print_info("Instalando pacote Python kittentts (~25-80MB de modelo baixado no primeiro uso)...")
    print()
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", wheel_url, "soundfile", "--quiet"],
            check=True, timeout=300,
        )
        print_success("kittentts instalado com sucesso")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print_error(f"Falha ao instalar o kittentts: {e}")
        print_info(f"Tente manualmente: python -m pip install -U '{wheel_url}' soundfile")
        return False


def _setup_tts_provider(config: dict):
    """Interactive TTS provider selection with install flow for NeuTTS."""
    tts_config = config.get("tts", {})
    current_provider = tts_config.get("provider", "edge")

    provider_labels = {
        "edge": "Edge TTS",
        "elevenlabs": "ElevenLabs",
        "openai": "OpenAI TTS",
        "xai": "xAI TTS",
        "minimax": "MiniMax TTS",
        "mistral": "Mistral Voxtral TTS",
        "gemini": "Google Gemini TTS",
        "neutts": "NeuTTS",
        "kittentts": "KittenTTS",
    }
    current_label = provider_labels.get(current_provider, current_provider)

    print()
    print_header("Provedor de Text-to-Speech (opcional)")
    print_info(f"Atual: {current_label}")
    print()

    choices = []
    providers = []
    choices.extend(
        [
            "Edge TTS (gratuito, baseado em nuvem, sem necessidade de configuração)",
            "ElevenLabs (qualidade premium, precisa de chave API)",
            "OpenAI TTS (boa qualidade, precisa de chave API)",
            "xAI TTS (vozes do Grok, precisa de chave API)",
            "MiniMax TTS (alta qualidade com clonagem de voz, precisa de chave API)",
            "Mistral Voxtral TTS (multilíngue, Opus nativo, precisa de chave API)",
            "Google Gemini TTS (30 vozes pré-construídas, controláveis por prompt, precisa de chave API)",
            "NeuTTS (local no dispositivo, gratuito, download de modelo de ~300MB)",
            "KittenTTS (local no dispositivo, gratuito, leve ONNX de ~25-80MB)",
        ]
    )
    providers.extend(["edge", "elevenlabs", "openai", "xai", "minimax", "mistral", "gemini", "neutts", "kittentts"])
    choices.append(f"Manter atual ({current_label})")
    keep_current_idx = len(choices) - 1
    idx = prompt_choice("Selecione o provedor de TTS:", choices, keep_current_idx)

    if idx == keep_current_idx:
        return

    selected = providers[idx]

    if selected == "neutts":
        # Check if already installed
        try:
            already_installed = importlib.util.find_spec("neutts") is not None
        except Exception:
            already_installed = False

        if already_installed:
            print_success("O NeuTTS já está instalado")
        else:
            print()
            print_info("NeuTTS requer:")
            print_info("  • Pacote Python: neutts (~50MB de instalação + ~300MB de modelo no primeiro uso)")
            print_info("  • Pacote de sistema: espeak-ng (phonemizer)")
            print()
            if prompt_yes_no("Instalar dependências do NeuTTS agora?", True):
                if not _install_neutts_deps():
                    print_warning("Instalação do NeuTTS incompleta. Voltando para Edge TTS.")
                    selected = "edge"
            else:
                print_info("Instalação pulada. Defina tts.provider para 'neutts' após instalar manualmente.")
                selected = "edge"

    elif selected == "elevenlabs":
        existing = get_env_value("ELEVENLABS_API_KEY")
        if not existing:
            print()
            api_key = prompt("Chave API da ElevenLabs", password=True)
            if api_key:
                save_env_value("ELEVENLABS_API_KEY", api_key)
                print_success("Chave API da ElevenLabs salva")
            else:
                print_warning("Nenhuma chave API fornecida. Voltando para Edge TTS.")
                selected = "edge"

    elif selected == "openai":
        existing = get_env_value("VOICE_TOOLS_OPENAI_KEY") or get_env_value("OPENAI_API_KEY")
        if not existing:
            print()
            api_key = prompt("Chave API da OpenAI para TTS", password=True)
            if api_key:
                save_env_value("VOICE_TOOLS_OPENAI_KEY", api_key)
                print_success("Chave API do OpenAI TTS salva")
            else:
                print_warning("Nenhuma chave API fornecida. Voltando para Edge TTS.")
                selected = "edge"

    elif selected == "xai":
        existing = get_env_value("XAI_API_KEY")
        if not existing:
            print()
            api_key = prompt("Chave API da xAI para TTS", password=True)
            if api_key:
                save_env_value("XAI_API_KEY", api_key)
                print_success("Chave API do xAI TTS salva")
            else:
                from ector_constants import display_ector_home as _dhh
                print_warning(
                    "Nenhuma chave API da xAI fornecida para TTS. Configure XAI_API_KEY via "
                    f"ector setup model ou {_dhh()}/.env para usar o xAI TTS. "
                    "Voltando para Edge TTS."
                )
                selected = "edge"

    elif selected == "minimax":
        existing = get_env_value("MINIMAX_API_KEY")
        if not existing:
            print()
            api_key = prompt("Chave API da MiniMax para TTS", password=True)
            if api_key:
                save_env_value("MINIMAX_API_KEY", api_key)
                print_success("Chave API do MiniMax TTS salva")
            else:
                print_warning("Nenhuma chave API fornecida. Voltando para Edge TTS.")
                selected = "edge"

    elif selected == "mistral":
        existing = get_env_value("MISTRAL_API_KEY")
        if not existing:
            print()
            api_key = prompt("Chave API da Mistral para TTS", password=True)
            if api_key:
                save_env_value("MISTRAL_API_KEY", api_key)
                print_success("Chave API do Mistral TTS salva")
            else:
                print_warning("Nenhuma chave API fornecida. Voltando para Edge TTS.")
                selected = "edge"

    elif selected == "gemini":
        existing = get_env_value("GEMINI_API_KEY") or get_env_value("GOOGLE_API_KEY")
        if not existing:
            print()
            print_info("Obtenha uma chave API gratuita em https://aistudio.google.com/app/apikey")
            api_key = prompt("Chave API do Gemini para TTS", password=True)
            if api_key:
                save_env_value("GEMINI_API_KEY", api_key)
                print_success("Chave API do Gemini TTS salva")
            else:
                print_warning("Nenhuma chave API fornecida. Voltando para Edge TTS.")
                selected = "edge"

    elif selected == "kittentts":
        # Check if already installed
        try:
            import importlib.util
            already_installed = importlib.util.find_spec("kittentts") is not None
        except Exception:
            already_installed = False

        if already_installed:
            print_success("O KittenTTS já está instalado")
        else:
            print()
            print_info("O KittenTTS é leve (~25-80MB, apenas CPU, sem necessidade de chave API).")
            print_info("Vozes: Jasper, Bella, Luna, Bruno, Rosie, Hugo, Kiki, Leo")
            print()
            if prompt_yes_no("Instalar KittenTTS agora?", True):
                if not _install_kittentts_deps():
                    print_warning("Instalação do kittentts incompleta. Voltando para Edge TTS.")
                    selected = "edge"
            else:
                print_info("Instalação pulada. Defina tts.provider para 'kittentts' após instalar manualmente.")
                selected = "edge"

    # Save the selection
    if "tts" not in config:
        config["tts"] = {}
    config["tts"]["provider"] = selected
    save_config(config)
    print_success(f"Provedor de TTS definido como: {provider_labels.get(selected, selected)}")


def setup_tts(config: dict):
    """Standalone TTS setup (for 'ector setup tts')."""
    _setup_tts_provider(config)


# =============================================================================
# Section 2: Terminal Backend Configuration
# =============================================================================


def setup_terminal_backend(config: dict):
    """Configure the terminal execution backend."""
    import platform as _platform
    print_header("Backend do Terminal")
    print_info("Escolha onde o Ector executa comandos shell e código.")
    print_info("Isso afeta a execução de ferramentas, acesso a arquivos e isolamento.")
    print()

    current_backend = config.get("terminal", {}).get("backend", "local")
    is_linux = _platform.system() == "Linux"

    # Build backend choices with descriptions
    terminal_choices = [
        "Local - executa diretamente nesta máquina (padrão)",
        "Docker - contêiner isolado com recursos configuráveis",
        "Modal - sandbox em nuvem serverless",
        "SSH - executa em uma máquina remota",
        "Daytona - ambiente de desenvolvimento persistente em nuvem",
    ]
    idx_to_backend = {0: "local", 1: "docker", 2: "modal", 3: "ssh", 4: "daytona"}
    backend_to_idx = {"local": 0, "docker": 1, "modal": 2, "ssh": 3, "daytona": 4}

    next_idx = 5
    if is_linux:
        terminal_choices.append("Singularity/Apptainer - contêiner amigável para HPC")
        idx_to_backend[next_idx] = "singularity"
        backend_to_idx["singularity"] = next_idx
        next_idx += 1

    # Add keep current option
    keep_current_idx = next_idx
    terminal_choices.append(f"Manter atual ({current_backend})")
    idx_to_backend[keep_current_idx] = current_backend

    terminal_idx = prompt_choice(
        "Selecione o backend do terminal:", terminal_choices, keep_current_idx
    )

    selected_backend = idx_to_backend.get(terminal_idx)

    if terminal_idx == keep_current_idx:
        print_info(f"Mantendo o backend atual: {current_backend}")
        return

    config.setdefault("terminal", {})["backend"] = selected_backend

    if selected_backend == "local":
        print_success("Backend do terminal: Local")
        print_info("Comandos executados diretamente nesta máquina.")

        # CWD for messaging
        print()
        print_info("Diretório de trabalho para sessões de mensagens:")
        print_info("  Ao usar o Ector via Telegram/Discord, é aqui que")
        print_info(
            "  o agente começa. O modo CLI sempre começa no diretório atual."
        )
        current_cwd = config.get("terminal", {}).get("cwd", "")
        cwd = prompt("  Diretório de trabalho para mensagens", current_cwd or str(Path.home()))
        if cwd:
            config["terminal"]["cwd"] = cwd

        # Sudo support
        print()
        existing_sudo = get_env_value("SUDO_PASSWORD")
        if existing_sudo:
            print_info("Senha sudo: configurada")
        else:
            if prompt_yes_no(
                "Ativar suporte a sudo? (armazena senha para apt install, etc.)", False
            ):
                sudo_pass = prompt("  Senha sudo", password=True)
                if sudo_pass:
                    save_env_value("SUDO_PASSWORD", sudo_pass)
                    print_success("Senha sudo salva")

    elif selected_backend == "docker":
        print_success("Backend do terminal: Docker")

        # Check if Docker is available
        docker_bin = shutil.which("docker")
        if not docker_bin:
            print_warning("Docker não encontrado no PATH!")
            print_info("Instale o Docker: https://docs.docker.com/get-docker/")
        else:
            print_info(f"Docker encontrado: {docker_bin}")

        # Docker image
        current_image = config.get("terminal", {}).get(
            "docker_image", "nikolaik/python-nodejs:python3.11-nodejs20"
        )
        image = prompt("  Imagem Docker", current_image)
        config["terminal"]["docker_image"] = image
        save_env_value("TERMINAL_DOCKER_IMAGE", image)

        _prompt_container_resources(config)

    elif selected_backend == "singularity":
        print_success("Backend do terminal: Singularity/Apptainer")

        # Check if singularity/apptainer is available
        sing_bin = shutil.which("apptainer") or shutil.which("singularity")
        if not sing_bin:
            print_warning("Singularity/Apptainer não encontrado no PATH!")
            print_info(
                "Instale: https://apptainer.org/docs/admin/main/installation.html"
            )
        else:
            print_info(f"Encontrado: {sing_bin}")

        current_image = config.get("terminal", {}).get(
            "singularity_image", "docker://nikolaik/python-nodejs:python3.11-nodejs20"
        )
        image = prompt("  Imagem do contêiner", current_image)
        config["terminal"]["singularity_image"] = image
        save_env_value("TERMINAL_SINGULARITY_IMAGE", image)

        _prompt_container_resources(config)

    elif selected_backend == "modal":
        print_success("Backend do terminal: Modal")
        print_info("Sandboxes em nuvem serverless. Cada sessão recebe seu próprio contêiner.")
        config["terminal"]["modal_mode"] = "direct"
        print_info("Requer uma conta no Modal: https://modal.com")

        # Check if modal SDK is installed
        try:
            __import__("modal")
        except ImportError:
            print_info("Instalando SDK do modal...")
            import subprocess

            uv_bin = shutil.which("uv")
            if uv_bin:
                result = subprocess.run(
                    [
                        uv_bin,
                        "pip",
                        "install",
                        "--python",
                        sys.executable,
                        "modal",
                    ],
                    capture_output=True,
                    text=True,
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "modal"],
                    capture_output=True,
                    text=True,
                )
            if result.returncode == 0:
                print_success("SDK do modal instalado")
            else:
                print_warning("A instalação falhou — execute manualmente: pip install modal")

        # Modal token
        print()
        print_info("Autenticação do Modal:")
        print_info("  Obtenha seu token em: https://modal.com/settings")
        existing_token = get_env_value("MODAL_TOKEN_ID")
        if existing_token:
            print_info("  Token do Modal: já configurado")
            if prompt_yes_no("  Atualizar credenciais do Modal?", False):
                token_id = prompt("    Modal Token ID", password=True)
                token_secret = prompt("    Modal Token Secret", password=True)
                if token_id:
                    save_env_value("MODAL_TOKEN_ID", token_id)
                if token_secret:
                    save_env_value("MODAL_TOKEN_SECRET", token_secret)
        else:
            token_id = prompt("    Modal Token ID", password=True)
            token_secret = prompt("    Modal Token Secret", password=True)
            if token_id:
                save_env_value("MODAL_TOKEN_ID", token_id)
            if token_secret:
                save_env_value("MODAL_TOKEN_SECRET", token_secret)

        _prompt_container_resources(config)

    elif selected_backend == "daytona":
        print_success("Backend do terminal: Daytona")
        print_info("Ambientes de desenvolvimento em nuvem persistentes.")
        print_info("Cada sessão recebe uma sandbox dedicada com persistência de sistema de arquivos.")
        print_info("Cadastre-se em: https://daytona.io")

        # Check if daytona SDK is installed
        try:
            __import__("daytona_sdk")
        except ImportError:
            print_info("Instalando SDK do Daytona...")
            import subprocess

            uv_bin = shutil.which("uv")
            if uv_bin:
                result = subprocess.run(
                    [
                        uv_bin,
                        "pip",
                        "install",
                        "--python",
                        sys.executable,
                        "daytona-sdk",
                    ],
                    capture_output=True,
                    text=True,
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "daytona-sdk"],
                    capture_output=True,
                    text=True,
                )
            if result.returncode == 0:
                print_success("SDK do Daytona instalado")
            else:
                print_warning(
                    "A instalação falhou — execute manualmente: pip install daytona-sdk"
                )

        # Daytona credentials
        print()
        print_info("Autenticação do Daytona:")
        print_info("  Obtenha sua chave API em: https://app.daytona.io/settings")
        existing_key = get_env_value("DAYTONA_API_KEY")
        if existing_key:
            print_info("  Chave API do Daytona: já configurada")
            if prompt_yes_no("  Atualizar chave API do Daytona?", False):
                api_key = prompt("    Daytona API Key", password=True)
                if api_key:
                    save_env_value("DAYTONA_API_KEY", api_key)
        else:
            api_key = prompt("    Daytona API key", password=True)
            if api_key:
                save_env_value("DAYTONA_API_KEY", api_key)
                print_success("    Configurado")

        # Daytona image
        current_image = config.get("terminal", {}).get(
            "daytona_image", "nikolaik/python-nodejs:python3.11-nodejs20"
        )
        image = prompt("  Imagem da sandbox", current_image)
        config["terminal"]["daytona_image"] = image
        save_env_value("TERMINAL_DAYTONA_IMAGE", image)

        _prompt_container_resources(config)

    elif selected_backend == "ssh":
        print_success("Backend do terminal: SSH")
        print_info("Execute comandos em uma máquina remota via SSH.")

        # SSH host
        current_host = get_env_value("TERMINAL_SSH_HOST") or ""
        host = prompt("  SSH host (hostname or IP)", current_host)
        if host:
            save_env_value("TERMINAL_SSH_HOST", host)

        # SSH user
        current_user = get_env_value("TERMINAL_SSH_USER") or ""
        user = prompt("  SSH user", current_user or os.getenv("USER", ""))
        if user:
            save_env_value("TERMINAL_SSH_USER", user)

        # SSH port
        current_port = get_env_value("TERMINAL_SSH_PORT") or "22"
        port = prompt("  SSH port", current_port)
        if port and port != "22":
            save_env_value("TERMINAL_SSH_PORT", port)

        # SSH key
        current_key = get_env_value("TERMINAL_SSH_KEY") or ""
        default_key = str(Path.home() / ".ssh" / "id_rsa")
        ssh_key = prompt("  Caminho da chave privada SSH", current_key or default_key)
        if ssh_key:
            save_env_value("TERMINAL_SSH_KEY", ssh_key)

        # Test connection
        if host and prompt_yes_no("  Testar conexão SSH?", True):
            print_info("  Testando conexão...")
            import subprocess

            ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
            if ssh_key:
                ssh_cmd.extend(["-i", ssh_key])
            if port and port != "22":
                ssh_cmd.extend(["-p", port])
            ssh_cmd.append(f"{user}@{host}" if user else host)
            ssh_cmd.append("echo ok")
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print_success("  Conexão SSH bem-sucedida!")
            else:
                print_warning(f"  A conexão SSH falhou: {result.stderr.strip()}")
                print_info("  Verifique sua chave SSH e configurações de host.")

    # Sync terminal backend to .env so terminal_tool picks it up directly.
    # config.yaml is the source of truth, but terminal_tool reads TERMINAL_ENV.
    save_env_value("TERMINAL_ENV", selected_backend)
    if selected_backend == "modal":
        save_env_value("TERMINAL_MODAL_MODE", config["terminal"].get("modal_mode", "auto"))
    save_config(config)
    print()
    print_success(f"Backend do terminal definido como: {selected_backend}")


# =============================================================================
# Section 3: Agent Settings
# =============================================================================


def _apply_default_agent_settings(config: dict):
    """Apply recommended defaults for all agent settings without prompting."""
    config.setdefault("agent", {})["max_turns"] = 90
    save_env_value("ECTOR_MAX_ITERATIONS", "90")

    config.setdefault("display", {})["tool_progress"] = "all"

    config.setdefault("compression", {})["enabled"] = True
    config["compression"]["threshold"] = 0.50

    config.setdefault("session_reset", {}).update({
        "mode": "both",
        "idle_minutes": 1440,
        "at_hour": 4,
    })

    _merge_user_profile_from_disk(config)
    save_config(config)
    print_success("Padrões recomendados aplicados:")
    print_info("  Máximo de iterações: 90")
    print_info("  Progresso de ferramentas: all")
    print_info("  Limiar de compressão: 0.50")
    print_info("  Reset de sessão: inatividade (1440 min) + diário (4:00)")
    print_info("  Execute `ector setup agent` depois para personalizar.")


def setup_agent_settings(config: dict):
    """Configure agent behavior: iterations, progress display, compression, session reset."""

    print_header("Configurações do Agente")
    print()

    # ── Max Iterations ──
    current_max = get_env_value("ECTOR_MAX_ITERATIONS") or str(
        config.get("agent", {}).get("max_turns", 90)
    )
    print_info("Máximo de iterações de chamada de ferramentas por conversa.")
    print_info("Maior = tarefas mais complexas, mas custa mais tokens.")
    print_info(
        f"Pressione Enter para manter {current_max}. Use 90 para a maioria das tarefas ou 150+ para exploração aberta."
    )

    max_iter_str = prompt("Máximo de iterações", current_max)
    try:
        max_iter = int(max_iter_str)
        if max_iter > 0:
            save_env_value("ECTOR_MAX_ITERATIONS", str(max_iter))
            config.setdefault("agent", {})["max_turns"] = max_iter
            config.pop("max_turns", None)
            print_success(f"Máximo de iterações definido como {max_iter}")
    except ValueError:
        print_warning("Número inválido, mantendo o valor atual")

    # ── Tool Progress Display ──
    print_info("")
    print_info("Exibição de Progresso de Ferramentas")
    print_info("Controla quanto da atividade das ferramentas é mostrada (CLI e mensagens).")
    print_info("  off     — Silencioso, apenas a resposta final")
    print_info("  new     — Mostra o nome da ferramenta apenas quando ele muda (menos ruído)")
    print_info("  all     — Mostra cada chamada de ferramenta com uma prévia curta")
    print_info("  verbose — Argumentos completos, resultados e logs de depuração")

    current_mode = config.get("display", {}).get("tool_progress", "all")
    mode = prompt("Modo de progresso de ferramentas", current_mode)
    if mode.lower() in ("off", "new", "all", "verbose"):
        if "display" not in config:
            config["display"] = {}
        config["display"]["tool_progress"] = mode.lower()
        save_config(config)
        print_success(f"Progresso de ferramentas definido como: {mode.lower()}")
    else:
        print_warning(f"Modo desconhecido '{mode}', mantendo '{current_mode}'")

    # ── Context Compression ──
    print_header("Compressão de Contexto")
    print_info("Resume automaticamente mensagens antigas quando o contexto fica muito longo.")
    print_info(
        "Limiar maior = comprime depois (usa mais contexto). Menor = comprime antes."
    )

    config.setdefault("compression", {})["enabled"] = True

    current_threshold = config.get("compression", {}).get("threshold", 0.50)
    threshold_str = prompt("Limiar de compressão (0.5-0.95)", str(current_threshold))
    try:
        threshold = float(threshold_str)
        if 0.5 <= threshold <= 0.95:
            config["compression"]["threshold"] = threshold
    except ValueError:
        pass

    print_success(
        f"Limiar de compressão de contexto definido como {config['compression'].get('threshold', 0.50)}"
    )

    # ── Session Reset Policy ──
    print_header("Política de Reset de Sessão")
    print_info(
        "Sessões de mensagens (Telegram, Discord, etc.) acumulam contexto ao longo do tempo."
    )
    print_info(
        "Cada mensagem adiciona ao histórico da conversa, o que significa custos de API crescentes."
    )
    print_info("")
    print_info(
        "Para gerenciar isso, as sessões podem resetar automaticamente após um período de inatividade"
    )
    print_info(
        "ou em um horário fixo todos os dias. Quando um reset acontece, o agente salva coisas importantes"
    )
    print_info(
        "em sua memória persistente primeiro — mas o contexto da conversa é limpo."
    )
    print_info("")
    print_info("Você também pode resetar manualmente a qualquer momento digitando /reset no chat.")
    print_info("")

    reset_choices = [
        "Inatividade + reset diário (recomendado - reseta o que vier primeiro)",
        "Apenas inatividade (reseta após N minutos sem mensagens)",
        "Apenas diário (reseta em um horário fixo todos os dias)",
        "Nunca resetar automaticamente (o contexto vive até /reset ou compressão de contexto)",
        "Manter configurações atuais",
    ]

    current_policy = config.get("session_reset", {})
    current_mode = current_policy.get("mode", "both")
    current_idle = current_policy.get("idle_minutes", 1440)
    current_hour = current_policy.get("at_hour", 4)

    default_reset = {"both": 0, "idle": 1, "daily": 2, "none": 3}.get(current_mode, 0)

    reset_idx = prompt_choice("Modo de reset de sessão:", reset_choices, default_reset)

    config.setdefault("session_reset", {})

    if reset_idx == 0:  # Both
        config["session_reset"]["mode"] = "both"
        idle_str = prompt("  Tempo limite de inatividade (minutos)", str(current_idle))
        try:
            idle_val = int(idle_str)
            if idle_val > 0:
                config["session_reset"]["idle_minutes"] = idle_val
        except ValueError:
            pass
        hour_str = prompt("  Hora do reset diário (0-23, hora local)", str(current_hour))
        try:
            hour_val = int(hour_str)
            if 0 <= hour_val <= 23:
                config["session_reset"]["at_hour"] = hour_val
        except ValueError:
            pass
        print_success(
            f"Sessões resetam após {config['session_reset'].get('idle_minutes', 1440)} min ociosas ou diariamente às {config['session_reset'].get('at_hour', 4)}:00"
        )
    elif reset_idx == 1:  # Idle only
        config["session_reset"]["mode"] = "idle"
        idle_str = prompt("  Tempo limite de inatividade (minutos)", str(current_idle))
        try:
            idle_val = int(idle_str)
            if idle_val > 0:
                config["session_reset"]["idle_minutes"] = idle_val
        except ValueError:
            pass
        print_success(
            f"Sessões resetam após {config['session_reset'].get('idle_minutes', 1440)} min de inatividade"
        )
    elif reset_idx == 2:  # Daily only
        config["session_reset"]["mode"] = "daily"
        hour_str = prompt("  Hora do reset diário (0-23, hora local)", str(current_hour))
        try:
            hour_val = int(hour_str)
            if 0 <= hour_val <= 23:
                config["session_reset"]["at_hour"] = hour_val
        except ValueError:
            pass
        print_success(
            f"Sessões resetam diariamente às {config['session_reset'].get('at_hour', 4)}:00"
        )
    elif reset_idx == 3:  # None
        config["session_reset"]["mode"] = "none"
        print_info(
            "Sessões nunca resetarão automaticamente. O contexto é gerenciado apenas pela compressão."
        )
        print_warning(
            "Conversas longas aumentarão de custo. Use /reset manualmente quando necessário."
        )
    # else: keep current (idx == 4)

    save_config(config)


# =============================================================================
# Section 4: Messaging Platforms (Gateway)
# =============================================================================


def _setup_gateway_platform(platform_key: str) -> None:
    """Delegate messaging platform setup to gateway helpers (single source of truth)."""
    if platform_key == "whatsapp":
        from ector_cli.main import cmd_whatsapp
        import argparse

        cmd_whatsapp(argparse.Namespace())
        return

    from ector_cli.gateway import _PLATFORMS, _setup_standard_platform

    platform = next(p for p in _PLATFORMS if p["key"] == platform_key)
    _setup_standard_platform(platform)


def _build_gateway_platform_checklist() -> tuple[list[str], list[int], list[str]]:
    """Return checklist labels, pre-selected indices, and platform keys."""
    from ector_cli.gateway import _PLATFORMS
    from gateway.platform_catalog import platform_public_meta

    items: list[str] = []
    pre_selected: list[int] = []
    keys: list[str] = []

    for i, plat in enumerate(_PLATFORMS):
        key = plat["key"]
        meta = platform_public_meta(plat)
        label = meta.get("label") or key
        state = meta.get("state", "not_configured")
        status_text = meta.get("status_text") or ""

        if state in ("configured", "paired", "partial"):
            display = f"{label}  ({status_text})" if status_text else label
            pre_selected.append(i)
        else:
            display = label

        items.append(display)
        keys.append(key)

    return items, pre_selected, keys


def _write_slack_manifest_and_instruct():
    """Generate the Slack manifest, write it under ECTOR_HOME, and print
    paste-into-Slack instructions.

    Exposed as its own helper so both the initial setup flow and the
    "reconfigure? → no" branch can refresh the manifest without the user
    re-entering tokens. Failures are non-fatal — if the manifest write
    fails for any reason, we print a warning and skip rather than abort
    the whole Slack setup.
    """
    try:
        from ector_cli.slack_cli import _build_full_manifest
        from ector_constants import get_ector_home

        manifest = _build_full_manifest(
            bot_name="Ector",
            bot_description="Seu agente Ector no Slack",
        )
        target = Path(get_ector_home()) / "slack-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        target.write_text(
            _json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print_success(f"Manifesto do app Slack gravado em: {target}")
        print_info(
            "   Cole-o em https://api.slack.com/apps → seu app → Features "
            "→ App Manifest → Edit, depois Salve. O Slack solicitará a "
            "reinstalação se os escopos ou comandos slash mudarem."
        )
        print_info(
            "   Execute `ector slack manifest --write` a qualquer momento para atualizar após o "
            "Ector adicionar novos comandos."
        )
    except Exception as exc:  # pragma: no cover - best-effort UX helper
        print_warning(f"Não foi possível gravar o manifesto do Slack: {exc}")
        print_info(
            "   Você pode gerá-lo manualmente depois com: "
            "ector slack manifest --write"
        )


def _setup_slack() -> None:
    """Configure Slack — manifest helper plus shared gateway flow."""
    existing = get_env_value("SLACK_BOT_TOKEN")
    if existing and not prompt_yes_no("Reconfigurar o Slack?", False):
        if prompt_yes_no(
            "Regenerar o manifesto do app Slack com a lista de comandos "
            "mais recente? (recomendado após atualizar o Ector)",
            True,
        ):
            _write_slack_manifest_and_instruct()
        return

    _write_slack_manifest_and_instruct()
    _setup_gateway_platform("slack")


def _run_gateway_platform_setup(platform_key: str) -> None:
    """Run setup for one supported messaging platform."""
    if platform_key == "slack":
        _setup_slack()
    else:
        _setup_gateway_platform(platform_key)


def _setup_matrix():
    """Configure Matrix credentials."""
    print_header("Matrix")
    existing = get_env_value("MATRIX_ACCESS_TOKEN") or get_env_value("MATRIX_PASSWORD")
    if existing:
        print_info("Matrix: já configurado")
        if not prompt_yes_no("Reconfigurar o Matrix?", False):
            return

    print_info("Funciona com qualquer homeserver Matrix (Synapse, Conduit, Dendrite ou matrix.org).")
    print_info("   1. Crie um usuário de bot no seu homeserver, ou use sua própria conta")
    print_info("   2. Obtenha um token de acesso do Element, ou forneça ID de usuário + senha")
    print()
    homeserver = prompt("URL do Homeserver (ex: https://matrix.example.org)")
    if homeserver:
        save_env_value("MATRIX_HOMESERVER", homeserver.rstrip("/"))

    print()
    print_info("Autenticação: forneça um token de acesso (recomendado), ou ID de usuário + senha.")
    token = prompt("Token de acesso (deixe vazio para login por senha)", password=True)
    if token:
        save_env_value("MATRIX_ACCESS_TOKEN", token)
        user_id = prompt("ID de usuário (@bot:server — opcional, será detectado automaticamente)")
        if user_id:
            save_env_value("MATRIX_USER_ID", user_id)
        print_success("Token de acesso do Matrix salvo")
    else:
        user_id = prompt("ID de usuário (@bot:server)")
        if user_id:
            save_env_value("MATRIX_USER_ID", user_id)
        password = prompt("Senha", password=True)
        if password:
            save_env_value("MATRIX_PASSWORD", password)
            print_success("Credenciais do Matrix salvas")

    if token or get_env_value("MATRIX_PASSWORD"):
        print()
        want_e2ee = prompt_yes_no("Ativar criptografia ponta a ponta (E2EE)?", False)
        if want_e2ee:
            save_env_value("MATRIX_ENCRYPTION", "true")
            print_success("E2EE ativado")

        matrix_pkg = "mautrix[encryption]" if want_e2ee else "mautrix"
        try:
            __import__("mautrix")
        except ImportError:
            print_info(f"Instalando {matrix_pkg}...")
            import subprocess
            uv_bin = shutil.which("uv")
            if uv_bin:
                result = subprocess.run(
                    [uv_bin, "pip", "install", "--python", sys.executable, matrix_pkg],
                    capture_output=True, text=True,
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", matrix_pkg],
                    capture_output=True, text=True,
                )
            if result.returncode == 0:
                print_success(f"{matrix_pkg} instalado")
            else:
                print_warning(f"A instalação falhou — execute manualmente: pip install '{matrix_pkg}'")
                if result.stderr:
                    print_info(f"  Erro: {result.stderr.strip().splitlines()[-1]}")

        print()
        print_info("🔒 Segurança: Restrinja quem pode usar seu bot")
        print_info("   IDs de usuários Matrix se parecem com @usuario:servidor")
        print()
        allowed_users = prompt("IDs de usuários permitidos (separados por vírgula, deixe vazio para acesso aberto)")
        if allowed_users:
            save_env_value("MATRIX_ALLOWED_USERS", allowed_users.replace(" ", ""))
            print_success("Lista de permissões do Matrix configurada")
        else:
            print_info("▲  Nenhuma lista de permissões definida - qualquer um que puder enviar mensagens para o bot poderá usá-lo!")

        print()
        print_info("📬 Sala Principal: onde o Ector entrega resultados de tarefas agendadas e notificações.")
        print_info("   IDs de sala se parecem com !abc123:servidor (mostrado nas configurações de sala do Element)")
        print_info("   Você também pode configurar isso depois digitando /set-home em uma sala do Matrix.")
        home_room = prompt("ID da sala principal (deixe vazio para configurar depois com /set-home)")
        if home_room:
            save_env_value("MATRIX_HOME_ROOM", home_room)


def _setup_mattermost():
    """Configure Mattermost bot credentials."""
    print_header("Mattermost")
    existing = get_env_value("MATTERMOST_TOKEN")
    if existing:
        print_info("Mattermost: já configurado")
        if not prompt_yes_no("Reconfigurar o Mattermost?", False):
            return

    print_info("Funciona com qualquer instância Mattermost auto-hospedada.")
    print_info("   1. No Mattermost: Integrations → Bot Accounts → Add Bot Account")
    print_info("   2. Copie o token do bot")
    print()
    mm_url = prompt("URL do servidor Mattermost (ex: https://mm.example.com)")
    if mm_url:
        save_env_value("MATTERMOST_URL", mm_url.rstrip("/"))
    token = prompt("Token do bot", password=True)
    if not token:
        return
    save_env_value("MATTERMOST_TOKEN", token)
    print_success("Token do Mattermost salvo")

    print()
    print_info("🔒 Segurança: Restrinja quem pode usar seu bot")
    print_info("   Para encontrar seu ID de usuário: clique no seu avatar → Profile")
    print_info("   ou use a API: GET /api/v4/users/me")
    print()
    allowed_users = prompt("IDs de usuários permitidos (separados por vírgula, deixe vazio para acesso aberto)")
    if allowed_users:
        save_env_value("MATTERMOST_ALLOWED_USERS", allowed_users.replace(" ", ""))
        print_success("Lista de permissões do Mattermost configurada")
    else:
        print_info("▲  Nenhuma lista de permissões definida - qualquer um que puder enviar mensagens para o bot poderá usá-lo!")

    print()
    print_info("📬 Canal Principal: onde o Ector entrega resultados de tarefas agendadas e notificações.")
    print_info("   Para obter o ID de um canal: clique no nome do canal → View Info → copie o ID")
    print_info("   Você também pode configurar isso depois digitando /set-home em um canal do Mattermost.")
    home_channel = prompt("ID do canal principal (deixe vazio para configurar depois com /set-home)")
    if home_channel:
        save_env_value("MATTERMOST_HOME_CHANNEL", home_channel)


def _setup_weixin():
    """Configure Weixin (personal WeChat) via iLink Bot API QR login."""
    from ector_cli.gateway import _setup_weixin as _gateway_setup_weixin
    _gateway_setup_weixin()


def _setup_signal():
    """Configure Signal via gateway setup."""
    from ector_cli.gateway import _setup_signal as _gateway_setup_signal
    _gateway_setup_signal()


def _setup_email():
    """Configure Email via gateway setup."""
    from ector_cli.gateway import _setup_email as _gateway_setup_email
    _gateway_setup_email()


def _setup_sms():
    """Configure SMS (Twilio) via gateway setup."""
    from ector_cli.gateway import _setup_sms as _gateway_setup_sms
    _gateway_setup_sms()


def _setup_dingtalk():
    """Configure DingTalk via gateway setup."""
    from ector_cli.gateway import _setup_dingtalk as _gateway_setup_dingtalk
    _gateway_setup_dingtalk()


def _setup_yuanbao():
    """Configure Yuanbao via gateway setup."""
    from ector_cli.gateway import _setup_yuanbao as _gateway_setup_yuanbao
    _gateway_setup_yuanbao()


def _setup_wecom():
    """Configure WeCom (Enterprise WeChat) via gateway setup."""
    from ector_cli.gateway import _setup_wecom as _gateway_setup_wecom
    _gateway_setup_wecom()


def _setup_wecom_callback():
    """Configure WeCom Callback (self-built app) via gateway setup."""
    from ector_cli.gateway import _setup_wecom_callback as _gw_setup
    _gw_setup()




def _setup_bluebubbles():
    """Configure BlueBubbles iMessage gateway."""
    print_header("BlueBubbles (iMessage)")
    existing = get_env_value("BLUEBUBBLES_SERVER_URL")
    if existing:
        print_info("BlueBubbles: já configurado")
        if not prompt_yes_no("Reconfigurar o BlueBubbles?", False):
            return

    print_info("Conecta o Ector ao iMessage via BlueBubbles — um servidor macOS gratuito")
    print_info("e de código aberto que faz a ponte do iMessage para qualquer dispositivo.")
    print_info("   Requer um Mac rodando BlueBubbles Server v1.0.0+")
    print_info("   Download: https://bluebubbles.app/")
    print()
    print_info("No BlueBubbles Server → Settings → API, anote sua URL do Servidor e Senha.")
    print()

    server_url = prompt("URL do servidor BlueBubbles (ex: http://192.168.1.10:1234)")
    if not server_url:
        print_warning("A URL do servidor é obrigatória — pulando o setup do BlueBubbles")
        return
    save_env_value("BLUEBUBBLES_SERVER_URL", server_url.rstrip("/"))

    password = prompt("Senha do servidor BlueBubbles", password=True)
    if not password:
        print_warning("A senha é obrigatória — pulando o setup do BlueBubbles")
        return
    save_env_value("BLUEBUBBLES_PASSWORD", password)
    print_success("Credenciais do BlueBubbles salvas")

    print()
    print_info("🔒 Segurança: Restrinja quem pode enviar mensagens para seu bot")
    print_info("   Use endereços do iMessage: e-mail (usuario@icloud.com) ou telefone (+15551234567)")
    print()
    allowed_users = prompt("Endereços do iMessage permitidos (separados por vírgula, deixe vazio para acesso aberto)")
    if allowed_users:
        save_env_value("BLUEBUBBLES_ALLOWED_USERS", allowed_users.replace(" ", ""))
        print_success("Lista de permissões do BlueBubbles configurada")
    else:
        print_info("▲  Nenhuma lista de permissões definida — qualquer um que puder enviar iMessage para você poderá usar o bot!")

    print()
    print_info("📬 Canal Principal: telefone ou e-mail para entrega de tarefas agendadas e notificações.")
    print_info("   Você também pode configurar isso depois digitando /set-home no seu chat do iMessage.")
    home_channel = prompt("Endereço do canal principal (deixe vazio para configurar depois)")
    if home_channel:
        save_env_value("BLUEBUBBLES_HOME_CHANNEL", home_channel)

    print()
    print_info("Configurações avançadas (os padrões são adequados para a maioria dos casos):")
    if prompt_yes_no("Configurar definições do ouvinte de webhook?", False):
        webhook_port = prompt("Porta do ouvinte de webhook (padrão: 8645)")
        if webhook_port:
            try:
                save_env_value("BLUEBUBBLES_WEBHOOK_PORT", str(int(webhook_port)))
                print_success(f"Porta do webhook definida como {webhook_port}")
            except ValueError:
                print_warning("Número de porta inválido, usando o padrão 8645")

    print()
    print_info("Requer o auxiliar BlueBubbles Private API para indicadores de digitação,")
    print_info("recibos de leitura e reações tapback. O envio básico de mensagens funciona sem ele.")
    print_info("   Instalação: https://docs.bluebubbles.app/helper-bundle/installation")


def _setup_qqbot():
    """Configure QQ Bot (Official API v2) via gateway setup."""
    from ector_cli.gateway import _setup_qqbot as _gateway_setup_qqbot
    _gateway_setup_qqbot()


def _setup_webhooks():
    """Configure webhook integration."""
    print_header("Webhooks")
    existing = get_env_value("WEBHOOK_ENABLED")
    if existing:
        print_info("Webhooks: já configurados")
        if not prompt_yes_no("Reconfigurar webhooks?", False):
            return

    print()
    print_warning("▲  Plataformas de Webhook e SMS exigem a exposição das portas do gateway para a")
    print_warning("   internet. Por segurança, execute o gateway em um ambiente isolado")
    print_warning("   (Docker, VM, etc.) para limitar o raio de impacto de injeção de prompt.")
    print()
    print_info("   Guia completo: https://ector.cc/docs/user-guide/messaging/webhooks/")
    print()

    port = prompt("Porta do webhook (padrão 8644)")
    if port:
        try:
            save_env_value("WEBHOOK_PORT", str(int(port)))
            print_success(f"Porta do webhook definida como {port}")
        except ValueError:
            print_warning("Número de porta inválido, usando o padrão 8644")

    secret = prompt("Segredo HMAC global (compartilhado entre todas as rotas)", password=True)
    if secret:
        save_env_value("WEBHOOK_SECRET", secret)
        print_success("Segredo do webhook salvo")
    else:
        print_warning("Nenhum segredo definido — você deve configurar segredos por rota no config.yaml")

    save_env_value("WEBHOOK_ENABLED", "true")
    print()
    print_success("Webhooks ativados! Próximos passos:")
    from ector_constants import display_ector_home as _dhh
    print_info(f"   1. Defina as rotas de webhook em {_dhh()}/config.yaml")
    print_info("   2. Aponte seu serviço (GitHub, GitLab, etc.) para:")
    print_info("      http://seu-servidor:8644/webhooks/<nome-da-rota>")
    print()
    print_info("   Guia de configuração de rotas:")
    print_info("   https://ector.cc/docs/user-guide/messaging/webhooks/#configuring-routes")
    print()
    print_info("   Abrir configuração no seu editor:  ector config edit")


# Platform registry for the gateway checklist
_GATEWAY_PLATFORM_KEYS = ("whatsapp", "telegram", "discord", "slack")


def setup_gateway(config: dict):
    """Configure messaging platform integrations."""
    print_header("Plataformas de Mensagens")
    print_info("Conecte-se a plataformas de mensagens para conversar com o Ector de qualquer lugar.")
    print_info("Alterne com Espaço, confirme com Enter.")
    print()

    items, pre_selected, platform_keys = _build_gateway_platform_checklist()
    selected = prompt_checklist("Selecione as plataformas para configurar:", items, pre_selected)

    if not selected:
        print_info("Nenhuma plataforma selecionada. Execute 'ector setup gateway' mais tarde para configurar.")
        return

    for idx in selected:
        _run_gateway_platform_setup(platform_keys[idx])

    from ector_cli.gateway import (
        any_gateway_platform_configured,
        has_conflicting_systemd_units,
        has_legacy_ector_units,
        offer_gateway_service_actions,
        print_legacy_unit_warning,
        print_systemd_scope_conflict_warning,
        supports_systemd_services,
    )

    if not any_gateway_platform_configured():
        return

    print()
    print_info("━" * 50)
    print_success("Plataformas de mensagens configuradas!")

    missing_home = []
    if get_env_value("TELEGRAM_BOT_TOKEN") and not get_env_value("TELEGRAM_HOME_CHANNEL"):
        missing_home.append("Telegram")
    if get_env_value("DISCORD_BOT_TOKEN") and not get_env_value("DISCORD_HOME_CHANNEL"):
        missing_home.append("Discord")
    if get_env_value("SLACK_BOT_TOKEN") and not get_env_value("SLACK_HOME_CHANNEL"):
        missing_home.append("Slack")
    if (
        (get_env_value("WHATSAPP_ENABLED") or "").lower() == "true"
        and not get_env_value("WHATSAPP_HOME_CHANNEL")
    ):
        missing_home.append("WhatsApp")

    if missing_home:
        print()
        print_warning(f"Nenhum canal principal definido para: {', '.join(missing_home)}")
        print_info("   Sem um canal principal, as tarefas agendadas e mensagens")
        print_info("   entre plataformas não podem ser entregues nessas plataformas.")
        print_info("   Configure um mais tarde com /set-home no seu chat, ou edite")
        from ector_constants import display_ector_home as _dhh_home

        print_info(f"   {_dhh_home()}/.env (ex.: TELEGRAM_HOME_CHANNEL=<channel_id>)")

    if supports_systemd_services() and has_conflicting_systemd_units():
        print()
        print_systemd_scope_conflict_warning()

    if supports_systemd_services() and has_legacy_ector_units():
        print()
        print_legacy_unit_warning()

    print()
    offer_gateway_service_actions()
    print_info("━" * 50)


# =============================================================================
# Section 5: Tool Configuration (delegates to unified tools_config.py)
# =============================================================================


def setup_tools(config: dict, first_install: bool = False):
    """Configure tools — delegates to the unified tools_command() in tools_config.py.

    Both `ector setup tools` and `ector tools` use the same flow:
    platform selection → toolset toggles → provider/API key configuration.

    Args:
        first_install: When True, uses the simplified first-install flow
            (no platform menu, prompts for all unconfigured API keys).
    """
    from ector_cli.tools_config import tools_command

    tools_command(first_install=first_install, config=config)


# =============================================================================
# Post-Migration Section Skip Logic
# =============================================================================


def _model_section_has_credentials(config: dict) -> bool:
    """Return True when any known inference provider has usable credentials.

    Sources of truth:
      * ``PROVIDER_REGISTRY`` in ``ector_cli.auth`` — lists every supported
        provider along with its ``api_key_env_vars``.
      * ``active_provider`` in the auth store — covers OAuth device-code /
        external-OAuth providers (Ector, Codex, Qwen, Gemini CLI, ...).
      * The legacy OpenRouter aggregator env vars, which route generic
        ``OPENAI_API_KEY`` / ``OPENROUTER_API_KEY`` values through OpenRouter.
    """
    try:
        from ector_cli.auth import get_active_provider
        if get_active_provider():
            return True
    except Exception:
        pass

    try:
        from ector_cli.auth import PROVIDER_REGISTRY
    except Exception:
        PROVIDER_REGISTRY = {}  # type: ignore[assignment]

    def _has_key(pconfig) -> bool:
        for env_var in pconfig.api_key_env_vars:
            # CLAUDE_CODE_OAUTH_TOKEN is set by Claude Code itself, not by
            # the user — mirrors is_provider_explicitly_configured in auth.py.
            if env_var == "CLAUDE_CODE_OAUTH_TOKEN":
                continue
            if get_env_value(env_var):
                return True
        return False

    # Prefer the provider declared in config.yaml, avoids false positives
    # from stray env vars (GH_TOKEN, etc.) when the user has already picked
    # a different provider.
    model_cfg = config.get("model") if isinstance(config, dict) else None
    if isinstance(model_cfg, dict):
        provider_id = (model_cfg.get("provider") or "").strip().lower()
        if provider_id in PROVIDER_REGISTRY:
            if _has_key(PROVIDER_REGISTRY[provider_id]):
                return True
        if provider_id == "openrouter":
            for env_var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
                if get_env_value(env_var):
                    return True

    # OpenRouter aggregator fallback (no provider declared in config).
    for env_var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        if get_env_value(env_var):
            return True

    for pid, pconfig in PROVIDER_REGISTRY.items():
        # Skip copilot in auto-detect: GH_TOKEN / GITHUB_TOKEN are
        # commonly set for git tooling.  Mirrors resolve_provider in auth.py.
        if pid == "copilot":
            continue
        if _has_key(pconfig):
            return True
    return False


# =============================================================================
# Main Wizard Orchestrator
# =============================================================================

SETUP_SECTIONS = [
    ("model", "Model & Provider", setup_model_provider),
    ("tts", "Text-to-Speech", setup_tts),
    ("terminal", "Terminal Backend", setup_terminal_backend),
    ("gateway", "Messaging Platforms (Gateway)", setup_gateway),
    ("tools", "Tools", setup_tools),
    ("agent", "Agent Settings", setup_agent_settings),
]


def run_setup_wizard(args):
    """Run the interactive setup wizard.

    Supports full, quick, and section-specific setup:
      ector setup           — full or quick (auto-detected)
      ector setup model     — just model/provider
      ector setup tts       — just text-to-speech
      ector setup terminal  — just terminal backend
      ector setup gateway   — just messaging platforms
      ector setup tools     — just tool configuration
      ector setup agent     — just agent settings
    """
    from ector_cli.config import is_managed, managed_error
    if is_managed():
        managed_error("run setup wizard")
        return
    ensure_ector_home()

    from ector_cli.device_identity import get_or_create_install_id

    get_or_create_install_id()

    reset_requested = bool(getattr(args, "reset", False))
    if reset_requested:
        save_config(copy.deepcopy(DEFAULT_CONFIG))
        print_success("Configuração redefinida para os padrões.")

    reconfigure_requested = bool(getattr(args, "reconfigure", False))
    quick_requested = bool(getattr(args, "quick", False))

    config = load_config()
    ector_home = get_ector_home()

    # Detect non-interactive environments (headless SSH, Docker, CI/CD)
    non_interactive = getattr(args, 'non_interactive', False)
    if not non_interactive and not is_interactive_stdin():
        non_interactive = True

    if non_interactive:
        print_noninteractive_setup_guidance(
            "Executando em um ambiente não interativo (nenhum TTY detectado)."
        )
        return

    # Identity check: Ector requires an authenticated user before any
    # agent work.  Run the login flow before provider configuration so
    # the rest of the wizard knows who's setting up.
    _maybe_run_identity_login(args)
    _merge_user_profile_from_disk(config)

    # Check if a specific section was requested
    section = getattr(args, "section", None)
    if section:
        for key, label, func in SETUP_SECTIONS:
            if key == section:
                print()
                print_setup_panel(f"Ector Setup — {label}")
                func(config)
                _merge_user_profile_from_disk(config)
                save_config(config)
                print()
                print_success(f"Configuração de {label} concluída!")
                return

        print_error(f"Seção de setup desconhecida: {section}")
        print_info(f"Seções disponíveis: {', '.join(k for k, _, _ in SETUP_SECTIONS)}")
        return

    # Check if this is an existing installation with provider credentials.
    # Use the full provider registry/env detection helper instead of checking
    # only OpenRouter/OpenAI-base-url, which misses many configured providers.
    is_existing = _model_section_has_credentials(config)

    print()
    print_setup_panel(
        "Configuração do Ector",
        "Vamos configurar sua instalação.",
        hint_line="Pressione Ctrl+C a qualquer momento para sair.",
    )

    if is_existing:
        # Existing install — default is the full-wizard reconfigure flow.
        # Every prompt shows the current value as its default, so pressing
        # Enter keeps it.  Opt into `--quick` for the narrow "just fill in
        # missing items" flow when a required API key got cleared.
        if quick_requested:
            _run_quick_setup(config, ector_home)
            return

        print()
        print_header("Reconfigurar")
        print_success("Você já tem o Ector configurado.")
        print_info("Executando o assistente completo — cada prompt mostra seu valor atual.")
        print_info("Pressione Enter para mantê-lo, ou digite um novo valor para alterá-lo.")
        print_info("")
        print_info("Dica: vá direto para uma seção com 'ector setup model|terminal|")
        print_info("     gateway|tools|agent', ou preencha apenas itens ausentes com --quick.")
        # Fall through to the "Full Setup — run all sections" block below.
        # --reconfigure is now the default on existing installs; the flag
        # is preserved for backwards compatibility but is a no-op here.
    else:
        # ── First-Time Setup ──
        print()

        # --reconfigure / --quick on a fresh install are meaningless — fall
        # through to the normal first-time flow.
        if reconfigure_requested or quick_requested:
            print_info("Nenhuma configuração existente encontrada — executando configuração inicial.")
            print()

        setup_mode = prompt_choice("Como você gostaria de configurar o Ector?", [
            "Configuração rápida — provedor, modelo & mensagens (recomendado)",
            "Configuração completa — configurar tudo",
        ], 0)

        if setup_mode == 0:
            _run_first_time_quick_setup(config, ector_home, is_existing)
            return

    # ── Full Setup — run all sections ──
    print_header("Localização da Configuração")
    print_info(f"Arquivo de config:  {get_config_path()}")
    print_info(f"Arquivo de secrets: {get_env_path()}")
    print_info(f"Pasta de dados:    {ector_home}")
    print_info(f"Diretório instal:  {PROJECT_ROOT}")
    print()
    print_info("Dica: Você pode editar esses arquivos diretamente ou usar 'ector config edit'")

    # Section 1: Model & Provider
    setup_model_provider(config)

    # Section 2: Terminal Backend
    setup_terminal_backend(config)

    # Section 3: Agent Settings
    setup_agent_settings(config)

    # Section 4: Messaging Platforms
    setup_gateway(config)

    # Section 5: Tools
    setup_tools(config, first_install=not is_existing)

    # Save and show summary
    _merge_user_profile_from_disk(config)
    save_config(config)
    _print_setup_summary(config, ector_home)

    _offer_launch_chat()


def _resolve_ector_chat_argv() -> Optional[list[str]]:
    """Resolve argv for launching ``ector chat`` in a fresh process."""
    ector_bin = shutil.which("ector")
    if ector_bin:
        return [ector_bin, "chat"]

    try:
        if importlib.util.find_spec("ector_cli") is not None:
            return [sys.executable, "-m", "ector_cli.main", "chat"]
    except Exception:
        pass

    return None


def _offer_launch_chat():
    """Prompt the user to jump straight into chat after setup."""
    print()
    if not prompt_yes_no("Iniciar ector chat agora?", True):
        return

    chat_argv = _resolve_ector_chat_argv()
    if not chat_argv:
        print_info("Não foi possível reiniciar o Ector automaticamente. Execute 'ector chat' manualmente.")
        return

    os.execvp(chat_argv[0], chat_argv)


def _run_first_time_quick_setup(config: dict, ector_home, is_existing: bool):
    """Streamlined first-time setup: provider + model only.

    Applies sensible defaults for TTS (Edge), terminal (local), agent
    settings, and tools — the user can customize later via
    ``ector setup <section>``.
    """
    # Step 1: Model & Provider (essential — skips rotation/vision/TTS)
    setup_model_provider(config, quick=True)

    # Step 2: Apply defaults for everything else
    _apply_default_agent_settings(config)
    config.setdefault("terminal", {}).setdefault("backend", "local")

    _merge_user_profile_from_disk(config)
    save_config(config)

    # Step 3: Offer messaging gateway setup
    print()
    gateway_choice = prompt_choice(
        "Deseja conectar uma plataforma de mensagens? (WhatsApp, Telegram, Discord, etc.)",
        [
            "Sim, configurar mensagens agora (recomendado)",
            "Não, pular agora e configurar depois com 'ector setup gateway'",
        ],
        0,
    )

    if gateway_choice == 0:
        setup_gateway(config)
        _merge_user_profile_from_disk(config)
        save_config(config)

    print()
    print_success("Configuração concluída! Pronto para começar.")
    print()
    print_info("  Configurar tudo:           ector setup")
    if gateway_choice != 0:
        print_info("  Conectar Telegram/Discord: ector setup gateway")
    print()

    _print_setup_summary(config, ector_home)

    _offer_launch_chat()


def _run_quick_setup(config: dict, ector_home):
    """Quick setup — only configure items that are missing."""
    from ector_cli.config import (
        get_missing_env_vars,
        get_missing_config_fields,
        check_config_version,
    )

    print()
    print_header("Configuração Rápida — Apenas Itens Ausentes")

    # Check what's missing
    missing_required = [
        v for v in get_missing_env_vars(required_only=False) if v.get("is_required")
    ]
    missing_optional = [
        v for v in get_missing_env_vars(required_only=False) if not v.get("is_required")
    ]
    missing_config = get_missing_config_fields()
    current_ver, latest_ver = check_config_version()

    has_anything_missing = (
        missing_required
        or missing_optional
        or missing_config
        or current_ver < latest_ver
    )

    if not has_anything_missing:
        print_success("Tudo está configurado! Nada a fazer.")
        print()
        print_info("Execute 'ector setup' e escolha 'Configuração Completa' para reconfigurar,")
        print_info("ou escolha uma seção específica no menu.")
        return

    # Handle missing required env vars
    if missing_required:
        print()
        print_info(f"{len(missing_required)} configuração(ões) obrigatória(s) ausente(s):")
        for var in missing_required:
            print(f"     • {var['name']}")
        print()

        for var in missing_required:
            print()
            print(color(f"  {var['name']}", Colors.CYAN))
            print_info(f"  {var.get('description', '')}")
            if var.get("url"):
                print_info(f"  Obtenha a chave em: {var['url']}")

            if var.get("password"):
                value = prompt(f"  {var.get('prompt', var['name'])}", password=True)
            else:
                value = prompt(f"  {var.get('prompt', var['name'])}")

            if value:
                save_env_value(var["name"], value)
                print_success(f"  Salvo {var['name']}")
            else:
                print_warning(f"  Pulado {var['name']}")

    # Split missing optional vars by category
    missing_tools = [v for v in missing_optional if v.get("category") == "tool"]
    missing_messaging = [
        v
        for v in missing_optional
        if v.get("category") == "messaging" and not v.get("advanced")
    ]

    # ── Tool API keys (checklist) ──
    if missing_tools:
        print()
        print_header("Chaves API de Ferramentas")

        checklist_labels = []
        for var in missing_tools:
            tools = var.get("tools", [])
            tools_str = f" → {', '.join(tools[:2])}" if tools else ""
            checklist_labels.append(f"{var.get('description', var['name'])}{tools_str}")

        selected_indices = prompt_checklist(
            "Quais ferramentas você gostaria de configurar?",
            checklist_labels,
        )

        for idx in selected_indices:
            var = missing_tools[idx]
            _prompt_api_key(var)

    # ── Messaging platforms (checklist then prompt for selected) ──
    if missing_messaging:
        print()
        print_header("Plataformas de Mensagens")
        print_info("Conecte o Ector a apps de mensagens para conversar de qualquer lugar.")
        print_info("Você pode configurar isso depois com 'ector setup gateway'.")

        # Group by platform (preserving order)
        platform_order = []
        platforms = {}
        for var in missing_messaging:
            name = var["name"]
            if "TELEGRAM" in name:
                plat = "Telegram"
            elif "DISCORD" in name:
                plat = "Discord"
            elif "SLACK" in name:
                plat = "Slack"
            else:
                continue
            if plat not in platforms:
                platform_order.append(plat)
            platforms.setdefault(plat, []).append(var)

        platform_labels = [
            {
                "Telegram": "📱 Telegram",
                "Discord": "💬 Discord",
                "Slack": "💼 Slack",
            }.get(p, p)
            for p in platform_order
        ]

        selected_indices = prompt_checklist(
            "Quais plataformas você gostaria de configurar?",
            platform_labels,
        )

        for idx in selected_indices:
            plat = platform_order[idx]
            vars_list = platforms[plat]
            emoji = {"Telegram": "📱", "Discord": "💬", "Slack": "💼"}.get(plat, "")
            print()
            print(color(f"  ─── {emoji} {plat} ───", Colors.CYAN))
            print()
            for var in vars_list:
                print_info(f"  {var.get('description', '')}")
                if var.get("url"):
                    print_info(f"  {var['url']}")
                if var.get("password"):
                    value = prompt(f"  {var.get('prompt', var['name'])}", password=True)
                else:
                    value = prompt(f"  {var.get('prompt', var['name'])}")
                if value:
                    save_env_value(var["name"], value)
                    print_success("  ✔ Salvo")
                else:
                    print_warning("  Pulado")
                print()

    # Handle missing config fields
    if missing_config:
        print()
        print_info(
            f"Adicionando {len(missing_config)} nova(s) opção(ões) de configuração com padrões..."
        )
        for field in missing_config:
            print_success(f"  Adicionado {field['key']} = {field['default']}")

        # Update config version
        config["_config_version"] = latest_ver
        save_config(config)

    # Jump to summary
    _print_setup_summary(config, ector_home)
