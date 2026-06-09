#!/usr/bin/env python3
"""
Ector CLI - Main entry point.

Usage:
    ector                     # Chat interativo — TUI Ink em TTY
    ector chat                # Chat interativo — TUI Ink em TTY
    ector gateway             # Executa o gateway em primeiro plano
    ector gateway start       # Inicia o serviço do gateway
    ector gateway stop        # Para o serviço do gateway
    ector gateway status      # Mostra o status do gateway
    ector gateway install     # Instala o serviço do gateway
    ector gateway uninstall   # Desinstala o serviço do gateway
    ector setup               # Assistente de configuração interativo
    ector logout              # Limpa a autenticação armazenada
    ector status              # Mostra o status de todos os componentes
    ector cron                # Gerencia tarefas cron
    ector cron list           # Lista tarefas cron
    ector cron status         # Verifica se o agendador cron está rodando
    ector doctor              # Verifica configuração e dependências
    ector version             Mostra versão
    ector uninstall           Desinstala o Ector Agent
    ector acp                 Executa como servidor ACP para integração com editores
    ector sessions browse     Seletor de sessão interativo com busca
"""

import argparse
import contextlib
import itertools
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

def _add_accept_hooks_flag(parser) -> None:
    """Attach the ``--accept-hooks`` flag.  Shared across every agent
    subparser so the flag works regardless of CLI position."""
    parser.add_argument(
        "--accept-hooks",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Auto-approve unseen shell hooks without a TTY prompt "
            "(equivalent to ECTOR_ACCEPT_HOOKS=1 / hooks_auto_accept: true)."
        ),
    )


def _require_tty(command_name: str) -> None:
    """Exit with a clear error if stdin is not a terminal.

    Interactive TUI commands (ector tools, ector setup, ector provider) use
    curses or input() prompts that spin at 100% CPU when stdin is a pipe.
    This guard prevents accidental non-interactive invocation.
    """
    if not sys.stdin.isatty():
        print(
            f"Erro: 'ector {command_name}' requer um terminal interativo.\n"
            f"Não pode ser executado através de um pipe ou subprocesso não interativo.\n"
            f"Execute-o diretamente no seu terminal.",
            file=sys.stderr,
        )
        sys.exit(1)


# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

def _bootstrap_first_run_if_needed(import_error: Exception) -> "None":
    """Best-effort local bootstrap for first run from a repo checkout.

    When users run `ector` before installing Python deps, imports like `yaml`
    or `dotenv` fail very early (before the CLI can show helpful guidance).
    If we're running from a repo checkout that contains `install.sh`, run it
    once and then re-exec `ector` from the created venv.
    """
    if os.environ.get("ECTOR_BOOTSTRAP_DONE") == "1":
        raise import_error

    installer = PROJECT_ROOT / "install.sh"
    venv_ector = PROJECT_ROOT / "venv" / "bin" / "ector"
    if not installer.is_file():
        raise import_error

    if sys.stdin.isatty():
        print("⚙️  Primeira execução detectada — instalando dependências automaticamente…")
    else:
        # Avoid hanging on prompts; install.sh now skips prompts when non-interactive.
        print("⚙️  Instalando dependências (modo não-interativo)…", file=sys.stderr)

    try:
        subprocess.run(["bash", str(installer)], cwd=str(PROJECT_ROOT), check=False)
    except Exception:
        raise import_error

    if venv_ector.is_file() and os.access(venv_ector, os.X_OK):
        os.environ["ECTOR_BOOTSTRAP_DONE"] = "1"
        os.execv(str(venv_ector), [str(venv_ector), *sys.argv[1:]])

    raise import_error


# ---------------------------------------------------------------------------
# Profile override — MUST happen before any ector module import.
#
# Many modules cache ECTOR_HOME at import time (module-level constants).
# We intercept --profile/-p from sys.argv here and set the env var so that
# every subsequent ``os.getenv("ECTOR_HOME", ...)`` resolves correctly.
# The flag is stripped from sys.argv so argparse never sees it.
# Falls back to ~/.ector/active_profile for sticky default.
# ---------------------------------------------------------------------------
def _apply_profile_override() -> None:
    """Pre-parse --profile/-p and set ECTOR_HOME before module imports."""
    argv = sys.argv[1:]
    profile_name = None
    consume = 0

    # 1. Check for explicit -p / --profile flag
    for i, arg in enumerate(argv):
        if arg in ("--profile", "-p") and i + 1 < len(argv):
            profile_name = argv[i + 1]
            consume = 2
            break
        elif arg.startswith("--profile="):
            profile_name = arg.split("=", 1)[1]
            consume = 1
            break

    # 2. If no flag, check active_profile in the ector root
    if profile_name is None:
        try:
            from ector_constants import get_default_ector_root

            active_path = get_default_ector_root() / "active_profile"
            if active_path.exists():
                name = active_path.read_text().strip()
                if name and name != "default":
                    profile_name = name
                    consume = 0  # don't strip anything from argv
        except (UnicodeDecodeError, OSError):
            pass  # corrupted file, skip

    # 3. If we found a profile, resolve and set ECTOR_HOME
    if profile_name is not None:
        try:
            from ector_cli.profiles import resolve_profile_env

            ector_home = resolve_profile_env(profile_name)
        except (ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            # A bug in profiles.py must NEVER prevent ector from starting
            print(
                f"Warning: profile override failed ({exc}), using default",
                file=sys.stderr,
            )
            return
        os.environ["ECTOR_HOME"] = ector_home
        # Strip the flag from argv so argparse doesn't choke
        if consume > 0:
            for i, arg in enumerate(argv):
                if arg in ("--profile", "-p"):
                    start = i + 1  # +1 because argv is sys.argv[1:]
                    sys.argv = sys.argv[:start] + sys.argv[start + consume :]
                    break
                elif arg.startswith("--profile="):
                    start = i + 1
                    sys.argv = sys.argv[:start] + sys.argv[start + 1 :]
                    break


_apply_profile_override()

# Load .env from ~/.ector/.env first, then project root as dev fallback.
# User-managed env files should override stale shell exports on restart.
try:
    from ector_cli.config import get_ector_home
    from ector_cli.env_loader import load_ector_dotenv
    load_ector_dotenv(project_env=PROJECT_ROOT / ".env")
except ModuleNotFoundError as exc:
    _bootstrap_first_run_if_needed(exc)

# Bridge security.redact_secrets from config.yaml → ECTOR_REDACT_SECRETS env
# var BEFORE ector_logging imports agent.redact (which snapshots the flag at
# module-import time). Without this, config.yaml's toggle is ignored because
# the setup_logging() call below imports agent.redact, which reads the env var
# exactly once. Env var in .env still wins — this is config.yaml fallback only.
try:
    if "ECTOR_REDACT_SECRETS" not in os.environ:
        import yaml as _yaml_early
        _cfg_path = get_ector_home() / "config.yaml"
        if _cfg_path.exists():
            with open(_cfg_path, encoding="utf-8") as _f:
                _early_sec_cfg = (_yaml_early.safe_load(_f) or {}).get("security", {})
            if isinstance(_early_sec_cfg, dict):
                _early_redact = _early_sec_cfg.get("redact_secrets")
                if _early_redact is not None:
                    os.environ["ECTOR_REDACT_SECRETS"] = str(_early_redact).lower()
            del _early_sec_cfg
        del _cfg_path
except Exception:
    pass  # best-effort — redaction stays at default (enabled) on config errors

# Initialize centralized file logging early — all `ector` subcommands
# (chat, setup, gateway, config, etc.) write to agent.log + errors.log.
try:
    from ector_logging import setup_logging as _setup_logging

    _setup_logging(mode="cli")
except Exception:
    pass  # best-effort — don't crash the CLI if logging setup fails

# Apply IPv4 preference early, before any HTTP clients are created.
try:
    from ector_cli.config import load_config as _load_config_early
    from ector_constants import apply_ipv4_preference as _apply_ipv4

    _early_cfg = _load_config_early()
    _net = _early_cfg.get("network", {})
    if isinstance(_net, dict) and _net.get("force_ipv4"):
        _apply_ipv4(force=True)
    del _early_cfg, _net
except Exception:
    pass  # best-effort — don't crash if config isn't available yet

import logging
import time as _time
from datetime import datetime

from ector_cli import __version__
from ector_constants import AI_GATEWAY_BASE_URL, OPENROUTER_BASE_URL, safe_getcwd

logger = logging.getLogger(__name__)

from ector_cli.cli_routing import (
    bare_ector_should_use_chat as _bare_ector_should_use_chat,
    command_requires_identity as _command_requires_identity,
    should_discover_plugins_and_hooks as _should_discover_plugins_and_hooks,
)
from ector_cli.provider_check import has_any_provider_configured as _has_any_provider_configured
from ector_cli.session_resolve import (
    relative_time as _relative_time,
    session_browse_picker as _session_browse_picker,
    resolve_last_session as _resolve_last_session,
    resolve_session_by_name_or_id as _resolve_session_by_name_or_id,
)
from ector_cli.tui_launch import (
    ensure_tui_node as _ensure_tui_node,
    launch_tui as _launch_tui,
    make_tui_argv as _make_tui_argv,
)
from ector_cli.web_build import build_web_ui as _build_web_ui
from ector_cli.provider_wizard import select_provider_and_model


def _probe_container(cmd: list, backend: str, via_sudo: bool = False):
    """Run a container inspect probe, returning the CompletedProcess.

    Catches TimeoutExpired specifically for a human-readable message;
    all other exceptions propagate naturally.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        label = f"sudo {backend}" if via_sudo else backend
        print(
            f"Erro: tempo limite esgotado esperando {label} responder.\n"
            f"O daemon {backend} pode estar sem resposta ou iniciando.",
            file=sys.stderr,
        )
        sys.exit(1)


def _exec_in_container(container_info: dict, cli_args: list):
    """Replace the current process with a command inside the managed container.

    Probes whether sudo is needed (rootful containers), then os.execvp
    into the container. On success the Python process is replaced entirely
    and the container's exit code becomes the process exit code (OS semantics).
    On failure, OSError propagates naturally.

    Args:
        container_info: dict with backend, container_name, exec_user, ector_bin
        cli_args: the original CLI arguments (everything after 'ector')
    """

    backend = container_info["backend"]
    container_name = container_info["container_name"]
    exec_user = container_info["exec_user"]
    ector_bin = container_info["ector_bin"]

    runtime = shutil.which(backend)
    if not runtime:
        print(
            f"Erro: {backend} não encontrado no PATH. Não é possível rotear para o contêiner.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rootful containers (NixOS systemd service) are invisible to unprivileged
    # users — Podman uses per-user namespaces, Docker needs group access.
    # Probe whether the runtime can see the container; if not, try via sudo.
    sudo_path = None
    probe = _probe_container(
        [runtime, "inspect", "--format", "ok", container_name],
        backend,
    )
    if probe.returncode != 0:
        sudo_path = shutil.which("sudo")
        if sudo_path:
            probe2 = _probe_container(
                [sudo_path, "-n", runtime, "inspect", "--format", "ok", container_name],
                backend,
                via_sudo=True,
            )
            if probe2.returncode != 0:
                print(
                    f"Erro: contêiner '{container_name}' não encontrado via {backend}.\n"
                    f"\n"
                    f"O contêiner provavelmente está rodando como root. Seu usuário não pode vê-lo\n"
                    f"porque o {backend} usa namespaces por usuário. Conceda sudo sem senha\n"
                    f"para o {backend} — a flag -n (não interativo) é necessária\n"
                    f"porque uma solicitação de senha travaria ou quebraria comandos via pipe.\n"
                    f"\n"
                    f"No NixOS:\n"
                    f"\n"
                    f"  security.sudo.extraRules = [{{\n"
                    f'    users = [ "{os.getenv("USER", "seu-usuario")}" ];\n'
                    f'    commands = [{{ command = "{runtime}"; options = [ "NOPASSWD" ]; }}];\n'
                    f"  }}];\n"
                    f"\n"
                    f"Ou execute: sudo ector {' '.join(cli_args)}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            print(
                f"Erro: contêiner '{container_name}' não encontrado via {backend}.\n"
                f"O contêiner pode estar rodando sob o root. Tente: sudo ector {' '.join(cli_args)}",
                file=sys.stderr,
            )
            sys.exit(1)

    is_tty = sys.stdin.isatty()
    tty_flags = ["-it"] if is_tty else ["-i"]

    env_flags = []
    for var in ("TERM", "COLORTERM", "LANG", "LC_ALL"):
        val = os.environ.get(var)
        if val:
            env_flags.extend(["-e", f"{var}={val}"])

    cmd_prefix = [sudo_path, "-n", runtime] if sudo_path else [runtime]
    exec_cmd = (
        cmd_prefix
        + ["exec"]
        + tty_flags
        + ["-u", exec_user]
        + env_flags
        + [container_name, ector_bin]
        + cli_args
    )

    os.execvp(exec_cmd[0], exec_cmd)



def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _chat_stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _interactive_chat_prefers_tui(args) -> bool:
    """Ink TUI is the only chat surface; cli.py is legacy (in-process slash + narrow fallbacks)."""
    if getattr(args, "oneshot", None):
        return False
    try:
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False
    return True


def _warn_legacy_chat_flag(message: str) -> None:
    print(message, file=sys.stderr)


def _exit_oneshot_from_chat_args(args, prompt: str) -> None:
    """Non-interactive chat: one-shot stdout only (replaces legacy cli.main -q)."""
    from ector_cli.oneshot import run_oneshot

    sys.exit(
        run_oneshot(
            prompt,
            model=getattr(args, "model", None),
            provider=getattr(args, "provider", None),
            image=getattr(args, "image", None),
        )
    )


def _enforce_identity_auth(args) -> None:
    """Block agent-invoking commands when no Ector session is active.

    Honoured by the gate:
      * Sessions in ``~/.ector/identity.json`` (preferred).
      * ``ECTOR_ACCESS_TOKEN`` + ``ECTOR_REFRESH_TOKEN`` env override
        (useful in CI / Docker / unattended setups).
    """
    if not _command_requires_identity(args):
        return

    try:
        from ector_cli.identity_auth import enforce_agent_runtime_access
    except Exception as exc:
        print(
            "Falha ao carregar autenticação de identidade (módulo indisponível). "
            "Reinstale o Ector ou execute `ector doctor` para diagnosticar.",
            file=sys.stderr,
        )
        logger.error("identity_auth import failed; blocking agent command", exc_info=True)
        print(f"Detalhe: {exc}", file=sys.stderr)
        sys.exit(2)

    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    enforce_agent_runtime_access(interactive=interactive)

    _schedule_cloud_skills_if_agent_command(args)


def _schedule_cloud_skills_if_agent_command(args) -> None:
    """Sync automático da biblioteca de skills antes de executar o agente."""
    if not _command_requires_identity(args):
        return
    try:
        from tools.cloud_skills_sync import (
            ensure_cloud_skills_for_agent_startup,
            maybe_schedule_cloud_skills_sync,
        )

        ensure_cloud_skills_for_agent_startup()
        maybe_schedule_cloud_skills_sync(quiet=True, force=False)
    except Exception:
        logger.debug("cloud skills auto-sync at CLI startup failed", exc_info=True)


def cmd_chat(args):
    """Run interactive chat CLI."""
    oneshot = getattr(args, "oneshot", None)
    if oneshot:
        from ector_cli.oneshot import run_oneshot

        sys.exit(
            run_oneshot(
                oneshot,
                model=getattr(args, "model", None),
                provider=getattr(args, "provider", None),
                image=getattr(args, "image", None),
            )
        )

    use_tui = _interactive_chat_prefers_tui(args)

    # Resolve --continue into --resume with the latest session or by name
    continue_val = getattr(args, "continue_last", None)
    if continue_val and not getattr(args, "resume", None):
        if isinstance(continue_val, str):
            # -c "nome da sessão" — resolve por título ou ID
            resolved = _resolve_session_by_name_or_id(continue_val)
            if resolved:
                args.resume = resolved
            else:
                print(f"Nenhuma sessão encontrada correspondente a '{continue_val}'.")
                print("Use 'ector sessions list' para ver as sessões disponíveis.")
                sys.exit(1)
        else:
            # -c sem argumento — continua a sessão mais recente
            source = "tui" if use_tui else "cli"
            last_id = _resolve_last_session(source=source)
            if not last_id and source == "tui":
                last_id = _resolve_last_session(source="cli")
            if last_id:
                args.resume = last_id
            else:
                kind = "TUI" if use_tui else "CLI"
                print(f"Nenhuma sessão anterior do {kind} encontrada para continuar.")
                sys.exit(1)

    # Resolve --resume by title if it's not a direct session ID
    resume_val = getattr(args, "resume", None)
    if resume_val:
        resolved = _resolve_session_by_name_or_id(resume_val)
        if resolved:
            args.resume = resolved

    # First-run guard: check if any provider is configured before launching
    if not _has_any_provider_configured():
        print()
        print(
            "O Ector ainda não está configurado"
        )

        from ector_cli.setup import (
            is_interactive_stdin,
            print_noninteractive_setup_guidance,
        )

        if not is_interactive_stdin():
            print_noninteractive_setup_guidance(
                "Nenhum TTY interativo detectado para o prompt de configuração da primeira execução."
            )
            sys.exit(1)

        try:
            reply = input("Deseja executar a configuração agora? (S/n) ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            reply = "n"
        if reply in ("", "s", "sim", "y", "yes"):
            cmd_setup(args)
            return
        print()
        print("Você pode executar 'ector setup' a qualquer momento para configurar.")
        sys.exit(1)

    # Start update check in background (runs while other init happens)
    try:
        from ector_cli.presentation import prefetch_update_check

        prefetch_update_check()
    except Exception:
        pass

    # --yolo: bypass all dangerous command approvals
    if getattr(args, "yolo", False):
        os.environ["ECTOR_YOLO_MODE"] = "1"

    # --ignore-user-config: make load_cli_config() / load_config() skip the
    # user's ~/.ector/config.yaml and return built-in defaults. Set BEFORE
    # importing cli (which runs `CLI_CONFIG = load_cli_config()` at module
    # import time). Credentials in .env are still loaded — this flag only
    # ignores behavioral/config settings.
    if getattr(args, "ignore_user_config", False):
        os.environ["ECTOR_IGNORE_USER_CONFIG"] = "1"

    # --ignore-rules: skip auto-injection of AGENTS.md/SOUL.md/.cursorrules
    # (rules), memory entries, and any preloaded skills coming from user config.
    # Maps to AIAgent(skip_context_files=True, skip_memory=True).
    if getattr(args, "ignore_rules", False):
        os.environ["ECTOR_IGNORE_RULES"] = "1"

    # --source: tag session source for filtering (e.g. 'tool' for third-party integrations)
    if getattr(args, "source", None):
        os.environ["ECTOR_SESSION_SOURCE"] = args.source

    query = getattr(args, "query", None)
    image = getattr(args, "image", None)

    if not use_tui:
        if query or image:
            if query and not image:
                _warn_legacy_chat_flag(
                    "Aviso: `ector chat -q` está obsoleto para uso não interativo; use `ector -z`."
                )
            _exit_oneshot_from_chat_args(args, query or "")
            return
        print(
            "O chat interativo requer um terminal (TTY). "
            "Use `ector -z \"pergunta\"` para one-shot ou redirecione com pipe.",
            file=sys.stderr,
        )
        sys.exit(2)

    initial_prompt = (query or "").strip() or None
    initial_image = None
    if image:
        initial_image = str(Path(image).expanduser())

    _launch_tui(
        PROJECT_ROOT,
        resume_session_id=getattr(args, "resume", None),
        model=getattr(args, "model", None),
        provider=getattr(args, "provider", None),
        initial_prompt=initial_prompt,
        initial_image=initial_image,
        worktree=bool(getattr(args, "worktree", False) or getattr(args, "w", False)),
    )


def cmd_gateway(args):
    """Gateway management commands."""
    from ector_cli.gateway import gateway_command

    gateway_command(args)


def cmd_whatsapp(args):
    """Set up WhatsApp: choose mode, configure, install bridge, pair via QR."""
    _require_tty("whatsapp")
    from ector_cli.cli_output import print_error, print_success, print_warning
    from ector_cli.colors import Colors, color
    from ector_cli.config import get_env_value, save_env_value

    def _ok(msg: str) -> None:
        print_success(msg)

    def _warn(msg: str) -> None:
        print_warning(msg)

    def _err(msg: str) -> None:
        print_error(msg)

    def _step(msg: str) -> None:
        print(color(msg, Colors.CYAN))

    def _prompt(msg: str, *, default_on_interrupt: str | None = None) -> str | None:
        try:
            return input(color(msg, Colors.BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            if default_on_interrupt is not None:
                return default_on_interrupt
            print(color("Configuração cancelada.", Colors.DIM))
            return None

    # ── Step 1: Choose mode ──────────────────────────────────────────────
    current_mode = get_env_value("WHATSAPP_MODE") or ""
    if not current_mode:
        print()
        print(color("Como você usará o WhatsApp com o Ector?", Colors.CYAN, Colors.BOLD))
        print()
        print(
            "  "
            + color("[1]", Colors.CYAN, Colors.BOLD)
            + " "
            + color("Número de bot separado", Colors.CYAN, Colors.BOLD)
            + " "
            + color("(recomendado)", Colors.GREEN)
        )
        print(
            "      "
            + color(
                "As pessoas enviam mensagens diretamente para o número do bot — experiência mais limpa.",
                Colors.DIM,
            )
        )
        print(
            "      "
            + color(
                "Requer um segundo número de telefone com o WhatsApp instalado em um dispositivo.",
                Colors.DIM,
            )
        )
        print()
        print(
            "  "
            + color("[2]", Colors.CYAN, Colors.BOLD)
            + " "
            + color("Número pessoal (auto-chat)", Colors.CYAN, Colors.BOLD)
        )
        print(
            "      "
            + color("Você envia mensagens para si mesmo para falar com o agente.", Colors.DIM)
        )
        print(
            "      "
            + color("Rápido de configurar, mas a experiência é menos intuitiva.", Colors.DIM)
        )
        print()
        choice = _prompt("  → Escolha [1/2]: ")
        if choice is None:
            return

        if choice == "1":
            save_env_value("WHATSAPP_MODE", "bot")
            wa_mode = "bot"
            _ok("Modo: número de bot separado")
            print()
            _box = Colors.CYAN
            _box_dim = Colors.DIM
            print(color("  ┌─────────────────────────────────────────────────────────┐", _box))
            print(
                color("  │  ", _box)
                + color("Obtendo um segundo número para o bot:", Colors.CYAN, Colors.BOLD)
                + color("                  │", _box)
            )
            print(color("  │                                                         │", _box_dim))
            print(
                color("  │  ", _box)
                + color("Mais fácil:", Colors.CYAN, Colors.BOLD)
                + color(" Instale o WhatsApp Business (app grátis)", Colors.DIM)
                + color("   │", _box)
            )
            print(
                color("  │  ", _box)
                + color("no seu telefone com um segundo número:", Colors.DIM)
                + color("                 │", _box)
            )
            print(
                color("  │    ", _box)
                + color("• Dual-SIM:", Colors.CYAN)
                + color(" use o 2º slot do chip", Colors.DIM)
                + color("                    │", _box)
            )
            print(
                color("  │    ", _box)
                + color("• eSIM:", Colors.CYAN)
                + color(" segunda linha no mesmo aparelho", Colors.DIM)
                + color("            │", _box)
            )
            print(
                color("  │    ", _box)
                + color("• Chip pré-pago:", Colors.CYAN)
                + color(" Vivo, Claro ou TIM (~R$10)", Colors.DIM)
                + color("          │", _box)
            )
            print(color("  │                                                         │", _box_dim))
            print(
                color("  │  ", _box)
                + color("O WhatsApp Business roda ao lado do seu WhatsApp", Colors.DIM)
                + color("       │", _box)
            )
            print(
                color("  │  ", _box)
                + color("pessoal — sem necessidade de um segundo telefone.", Colors.DIM)
                + color("      │", _box)
            )
            print(color("  └─────────────────────────────────────────────────────────┘", _box))
        else:
            save_env_value("WHATSAPP_MODE", "self-chat")
            wa_mode = "self-chat"
            _ok("Modo: número pessoal (auto-chat)")
    else:
        wa_mode = current_mode
        mode_label = (
            "número de bot separado" if wa_mode == "bot" else "número pessoal (auto-chat)"
        )
        print()
        _ok(f"Modo: {mode_label}")

    # ── Step 2: Enable WhatsApp ──────────────────────────────────────────
    print()
    current = get_env_value("WHATSAPP_ENABLED")
    if current and current.lower() == "true":
        _ok("WhatsApp já está ativado")
    else:
        save_env_value("WHATSAPP_ENABLED", "true")
        _ok("WhatsApp ativado")

    # ── Step 3: Allowed users ────────────────────────────────────────────
    current_users = get_env_value("WHATSAPP_ALLOWED_USERS") or ""
    if current_users:
        _ok(f"Usuários permitidos: {current_users}")
        response = _prompt("\n  Atualizar usuários permitidos? (s/n) ", default_on_interrupt="n")
        if response.lower() in ("s", "sim", "y", "yes"):
            if wa_mode == "bot":
                phone = _prompt(
                    "  Números de telefone que podem enviar mensagens para o bot (separados por vírgula): "
                )
            else:
                phone = _prompt("  Seu número de telefone (ex: 5511999999999): ")
            if phone is None:
                return
            if phone:
                save_env_value("WHATSAPP_ALLOWED_USERS", phone.replace(" ", ""))
                _ok(f"Atualizado para: {phone}")
    else:
        print()
        if wa_mode == "bot":
            print(color("  Quem deve ter permissão para enviar mensagens para o bot?", Colors.CYAN, Colors.BOLD))
            phone = _prompt(
                "  Números de telefone (separados por vírgula, ou * para qualquer pessoa): "
            )
        else:
            phone = _prompt("  Seu número de telefone (ex: 5511999999999): ")
        if phone is None:
            return
        if phone:
            save_env_value("WHATSAPP_ALLOWED_USERS", phone.replace(" ", ""))
            _ok(f"Usuários permitidos definidos: {phone}")
        else:
            _warn("Nenhuma lista de permissões — o agente responderá a TODAS as mensagens recebidas")

    # ── Step 4: Install bridge dependencies ──────────────────────────────
    project_root = Path(__file__).resolve().parents[1]
    bridge_dir = project_root / "scripts" / "whatsapp-bridge"
    bridge_script = bridge_dir / "bridge.js"

    if not bridge_script.exists():
        print()
        _err(f"Script de ponte não encontrado em {bridge_script}")
        return

    # ── Verify / auto-repair node_modules ────────────────────────────────
    # Check the key package exists on disk — fast and reliable.
    # A dynamic `node -e import(...)` probe is intentionally avoided: ESM
    # top-level await and Baileys' heavy initialisation make it slow and
    # prone to false negatives even when the package is perfectly intact.
    _nm = bridge_dir / "node_modules"

    # Baileys is published under @whiskeysockets/baileys but pnpm may
    # store it under a bare "baileys" symlink when installing from a git
    # tarball.  Check both locations.
    _baileys_index = (
        _nm / "@whiskeysockets" / "baileys" / "lib" / "index.js"
    )
    _baileys_bare = _nm / "baileys" / "lib" / "index.js"
    _baileys_ok = _baileys_index.exists() or _baileys_bare.exists()

    _needs_install = not _nm.exists() or not _baileys_ok

    if not _needs_install:
        _ok("Dependências da ponte já instaladas")
    else:
        if _nm.exists() and not _baileys_ok:
            print()
            _step("→ Dependências da ponte incompletas — reinstalando...")
            shutil.rmtree(_nm, ignore_errors=True)
        else:
            print()
            _step("→ Instalando dependências da ponte do WhatsApp (isso pode levar alguns minutos)...")

        # Same PATH bootstrap as the TUI: nvm/fnm/proto/brew or scripts/lib/node-bootstrap.sh
        # prepends the resolved node bin dir — without this, shutil.which often misses npm
        # when Ector was launched from a GUI or a minimal environment.
        _ensure_tui_node(PROJECT_ROOT)

        node_bin = shutil.which("node")
        pnpm_bin = shutil.which("pnpm")
        npm_bin = shutil.which("npm")
        pm_bin = pnpm_bin or npm_bin
        if not pm_bin:
            _err("Nenhum gerenciador de pacotes (pnpm/npm) encontrado no PATH.")
            print(
                color(
                    "     Instale Node.js (https://nodejs.org — inclui npm) ou inicie o Ector "
                    "no mesmo terminal onde `node -v` e `npm -v` funcionam "
                    "(gerenciadores como nvm/fnm só ajustam o PATH do shell).",
                    Colors.DIM,
                )
            )
            return

        def _get_version(bin_path: str, flag: str = "--version") -> str:
            try:
                result = subprocess.run(
                    [bin_path, flag],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=8,
                )
                return (result.stdout or "").strip().splitlines()[0]
            except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired, IndexError):
                return "indisponível"

        if node_bin:
            _step(
                "  → Ambiente detectado: "
                f"node={_get_version(node_bin)} "
                f"npm={_get_version(npm_bin) if npm_bin else 'ausente'} "
                f"pnpm={_get_version(pnpm_bin) if pnpm_bin else 'ausente'}"
            )

        bridge_pkg = bridge_dir / "package.json"
        bridge_lock = bridge_dir / "pnpm-lock.yaml"

        def _needs_lockfile_migration() -> bool:
            if not bridge_pkg.exists() or not bridge_lock.exists():
                return False
            try:
                pkg_text = bridge_pkg.read_text(encoding="utf-8")
                lock_text = bridge_lock.read_text(encoding="utf-8")
            except OSError:
                return False

            # Auto-heal old lockfiles that still pin Baileys via git tarball
            # (pnpm codeload URL or github# shorthand — triggers yarn in prepare).
            return '"@whiskeysockets/baileys": "7.0.0-rc.9"' in pkg_text and (
                "WhiskeySockets/Baileys#" in lock_text
                or "/Baileys/tar.gz" in lock_text
            )

        def _refresh_pnpm_lockfile() -> bool:
            if not pnpm_bin:
                return False
            result = subprocess.run(
                [pnpm_bin, "install", "--lockfile-only"],
                cwd=str(bridge_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if result.returncode == 0:
                return True
            out = (result.stdout or "").strip()
            preview = "\n".join(out.splitlines()[-20:]) if out else "(sem saída)"
            _warn("Falha ao atualizar o pnpm-lock.yaml automaticamente:")
            print(color(preview, Colors.DIM))
            return False

        if _needs_lockfile_migration():
            _step("  → Lockfile legado do Baileys detectado — atualizando automaticamente...")
            if _refresh_pnpm_lockfile():
                _ok("pnpm-lock.yaml atualizado para Baileys via npm registry")
            else:
                _warn("Seguindo com a instalação mesmo sem migrar o lockfile")

        def _run_install(bin_path: str) -> "subprocess.CompletedProcess[str]":
            pm = os.path.basename(bin_path)
            if pm == "pnpm":
                cmd = [bin_path, "install", "--no-frozen-lockfile"]
            else:
                cmd = [bin_path, "install", "--no-fund", "--no-audit"]
            return subprocess.run(
                cmd,
                cwd=str(bridge_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

        def _run_bridge_healthcheck() -> bool:
            has_baileys_files = _baileys_index.exists() or _baileys_bare.exists()
            if not has_baileys_files:
                _warn("Healthcheck: arquivos do Baileys não encontrados após instalação")
                return False
            if not node_bin:
                _warn("Healthcheck: node ausente no PATH (checagem de import ignorada)")
                return True
            import_check = subprocess.run(
                [
                    node_bin,
                    "--input-type=module",
                    "-e",
                    "await import('@whiskeysockets/baileys')",
                ],
                cwd=str(bridge_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if import_check.returncode == 0:
                _ok("Healthcheck: Baileys importado com sucesso")
                return True
            out = (import_check.stdout or "").strip()
            preview = "\n".join(out.splitlines()[-12:]) if out else "(sem saída)"
            _warn("Healthcheck: import do Baileys falhou:")
            print(color(preview, Colors.DIM))
            return False

        try:
            result = _run_install(pm_bin)
            if result.returncode != 0:
                # Show pnpm's real error before trying fallback
                pnpm_err = (result.stdout or "").strip()
                if pnpm_err:
                    preview = "\n".join(pnpm_err.splitlines()[-20:])
                    _warn("pnpm falhou:")
                    print(color(preview, Colors.DIM))
                # Known pnpm failure with git-hosted deps prepare/yarn-install.
                if (
                    pnpm_bin
                    and os.path.basename(pm_bin) == "pnpm"
                    and (
                        "ERR_PNPM_PREPARE_PACKAGE" in pnpm_err
                        or "yarn-install" in pnpm_err
                    )
                ):
                    _step("  → Falha conhecida do pnpm detectada, tentando auto-correção...")
                    try:
                        from ector_cli.yarn_bootstrap import ensure_yarn_on_path

                        if ensure_yarn_on_path():
                            _step("  → yarn disponível — repetindo pnpm install...")
                            result = _run_install(pnpm_bin)
                            pm_bin = pnpm_bin
                    except ImportError:
                        pass
                    if result.returncode != 0 and _refresh_pnpm_lockfile():
                        _step("  → Reexecutando pnpm install após corrigir lockfile...")
                        result = _run_install(pnpm_bin)
                        pm_bin = pnpm_bin
                # Fall back to npm when pnpm retries still fail.
                if result.returncode != 0 and pnpm_bin and npm_bin:
                    _step("  → tentando npm como fallback...")
                    result = _run_install(npm_bin)
                    pm_bin = npm_bin
        except KeyboardInterrupt:
            print()
            _err("Instalação cancelada")
            return

        if result.returncode != 0:
            out = (result.stdout or "").strip()
            preview = "\n".join(out.splitlines()[-30:]) if out else "(sem saída)"
            pm_name = os.path.basename(pm_bin)
            _err(f"{pm_name} install falhou:")
            print(color(preview, Colors.DIM))
            return
        _ok(f"Dependências instaladas ({os.path.basename(pm_bin)})")
        _run_bridge_healthcheck()

    # ── Step 5: Check for existing session ───────────────────────────────
    session_dir = get_ector_home() / "whatsapp" / "session"
    session_dir.mkdir(parents=True, exist_ok=True)

    if (session_dir / "creds.json").exists():
        _ok("Sessão existente do WhatsApp encontrada")
        response = _prompt(
            "\n  Emparelhar novamente? Isso limpará a sessão existente. (s/n) ",
            default_on_interrupt="n",
        )
        if response.lower() in ("s", "sim", "y", "yes"):
            shutil.rmtree(session_dir, ignore_errors=True)
            session_dir.mkdir(parents=True, exist_ok=True)
            _ok("Sessão limpa")
        else:
            print()
            _ok("O WhatsApp está configurado e emparelhado!")
            print(color("  Inicie o gateway com: ", Colors.DIM) + color("ector gateway", Colors.CYAN, Colors.BOLD))
            return

    # ── Step 6: QR code pairing ──────────────────────────────────────────
    print()
    print(color("─" * 50, Colors.DIM))
    print(color("  Emparelhamento via QR code", Colors.CYAN, Colors.BOLD))
    print(color("─" * 50, Colors.DIM))
    print()
    if wa_mode == "bot":
        open_hint = color("Abra o WhatsApp Business no telefone do bot", Colors.DIM)
    else:
        open_hint = color("Abra o WhatsApp no seu celular", Colors.DIM)
    print(color("  1. ", Colors.CYAN, Colors.BOLD) + open_hint)
    print(
        color("  2. ", Colors.CYAN, Colors.BOLD)
        + color(
            "Configurações → Aparelhos conectados → Conectar um aparelho",
            Colors.DIM,
        )
    )
    print(
        color("  3. ", Colors.CYAN, Colors.BOLD)
        + color("Aponte a câmera para o QR code abaixo", Colors.DIM)
    )
    print()

    try:
        subprocess.run(
            ["node", str(bridge_script), "--pair-only", "--session", str(session_dir)],
            cwd=str(bridge_dir),
        )
    except KeyboardInterrupt:
        pass

    # ── Step 7: Post-pairing ─────────────────────────────────────────────
    print()
    if (session_dir / "creds.json").exists():
        _ok("WhatsApp emparelhado com sucesso!")
        print()
        print(color("  Próximos passos:", Colors.CYAN, Colors.BOLD))
        if wa_mode == "bot":
            print(
                "    "
                + color("1.", Colors.CYAN, Colors.BOLD)
                + color(" Inicie o gateway:  ", Colors.DIM)
                + color("ector gateway", Colors.CYAN, Colors.BOLD)
            )
            print(
                "    "
                + color("2.", Colors.CYAN, Colors.BOLD)
                + color(" Envie uma mensagem para o número do WhatsApp do bot", Colors.DIM)
            )
            print(
                "    "
                + color("3.", Colors.CYAN, Colors.BOLD)
                + color(" O agente responderá automaticamente", Colors.DIM)
            )
        else:
            print(
                "    "
                + color("1.", Colors.CYAN, Colors.BOLD)
                + color(" Inicie o gateway:  ", Colors.DIM)
                + color("ector gateway", Colors.CYAN, Colors.BOLD)
            )
            print(
                "    "
                + color("2.", Colors.CYAN, Colors.BOLD)
                + color(" Abra o WhatsApp → Mensagem para você mesmo", Colors.DIM)
            )
            print(
                "    "
                + color("3.", Colors.CYAN, Colors.BOLD)
                + color(" Digite uma mensagem — o agente responderá", Colors.DIM)
            )
        print()
        print(
            color("  Ou instale como um serviço: ", Colors.DIM)
            + color("ector gateway install", Colors.CYAN, Colors.BOLD)
        )
    else:
        _warn("O emparelhamento pode não ter sido concluído. Execute 'ector whatsapp' para tentar novamente.")


def cmd_reset(args):
    """Format the agent and start fresh."""
    from ector_cli.reset import run_reset

    if not run_reset(args):
        return

    print()
    try:
        reply = input("Deseja executar a configuração agora? (S/n) ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        reply = "n"
    if reply in ("s", "sim", "y", "yes"):
        print()
        cmd_setup(args)
    else:
        print("Você pode executar 'ector setup' a qualquer momento.")


def cmd_setup(args):
    """Interactive setup wizard."""
    from ector_cli.setup import run_setup_wizard

    try:
        run_setup_wizard(args)
    except (KeyboardInterrupt, EOFError):
        # Keep setup cancellation clean (no traceback) when user presses Ctrl+C.
        print()
        print("Configuração cancelada pelo usuário.")


def cmd_provider(args):
    """Select default provider/model — starts with provider selection, then model picker."""
    _require_tty("provider")
    select_provider_and_model(args=args)


_BACK_TO_PROVIDER_MENU = "__back_to_provider_menu__"


def cmd_login(args):
    """Authenticate Ector CLI.

    Without ``--provider`` (default): identity login against the Ector
    backend (ector.cc). With ``--provider <id>``: legacy provider OAuth
    flow handled by :mod:`ector_cli.auth.login_command`.
    """
    provider = getattr(args, "provider", None)
    _PROVIDER_ONLY_LOGIN_FLAGS = (
        "portal_url",
        "inference_url",
        "client_id",
        "scope",
        "ca_bundle",
        "insecure",
    )
    if not provider:
        stray = [
            flag
            for flag in _PROVIDER_ONLY_LOGIN_FLAGS
            if getattr(args, flag, None) not in (None, False)
        ]
        if stray:
            labels = ", ".join(f"--{name.replace('_', '-')}" for name in stray)
            print(
                f"Opções de provedor ({labels}) só se aplicam com "
                "`ector login --provider <id>`.",
                file=sys.stderr,
            )
            sys.exit(2)

    if provider:
        from ector_cli.auth import login_command

        login_command(args)
        return

    from ector_cli.identity_commands import cmd_identity_login

    rc = cmd_identity_login(args)
    if rc:
        sys.exit(rc)


def cmd_logout(args):
    """Clear authentication.

    Without ``--provider``: identity logout (revokes the ector.cc
    session). With ``--provider``: clear that provider's credentials.
    """
    provider = getattr(args, "provider", None)
    if provider:
        from ector_cli.auth import logout_command

        logout_command(args)
        return

    from ector_cli.identity_commands import cmd_identity_logout

    rc = cmd_identity_logout(args)
    if rc:
        sys.exit(rc)


def cmd_me(args):
    """Show the current Ector identity (nickname, user, session status)."""
    from ector_cli.identity_commands import cmd_identity_me

    rc = cmd_identity_me(args)
    if rc:
        sys.exit(rc)


def cmd_auth(args):
    """Manage pooled credentials."""
    from ector_cli.auth_commands import auth_command

    auth_command(args)


def cmd_status(args):
    """Show status of all components."""
    from ector_cli.status import show_status

    show_status(args)


def cmd_cron(args):
    """Cron job management."""
    from ector_cli.cron import cron_command

    cron_command(args)


def cmd_webhook(args):
    """Webhook subscription management."""
    from ector_cli.webhook import webhook_command

    webhook_command(args)


def cmd_slack(args):
    """Slack integration helpers.

    Dispatches ``ector slack <subcommand>``. Currently supports:
      manifest — print or write a Slack app manifest with every gateway
                 command registered as a first-class slash.
    """
    sub = getattr(args, "slack_command", None)
    if sub in (None, ""):
        # No subcommand — print usage hint.
        print(
            "usage: ector slack <subcommand>\n"
            "\n"
            "subcommands:\n"
            "  manifest   Generate a Slack app manifest with every gateway\n"
            "             command registered as a native slash\n"
            "\n"
            "Run `ector slack manifest -h` for details.",
            file=sys.stderr,
        )
        return 1

    if sub == "manifest":
        from ector_cli.slack_cli import slack_manifest_command

        return slack_manifest_command(args)

    print(f"Unknown slack subcommand: {sub}", file=sys.stderr)
    return 1


def cmd_hooks(args):
    """Shell-hook inspection and management."""
    from ector_cli.hooks import hooks_command
    hooks_command(args)


def cmd_doctor(args):
    """Check configuration and dependencies."""
    from ector_cli.doctor import run_doctor

    run_doctor(args)


def cmd_dump(args):
    """Dump setup summary for support/debugging."""
    from ector_cli.dump import run_dump

    run_dump(args)


def cmd_debug(args):
    """Debug tools (share report, etc.)."""
    from ector_cli.debug import run_debug

    run_debug(args)


def cmd_config(args):
    """Configuration management."""
    from ector_cli.config import config_command

    config_command(args)


def cmd_backup(args):
    """Back up Ector home directory to a zip file."""
    if getattr(args, "quick", False):
        from ector_cli.backup import run_quick_backup

        run_quick_backup(args)
    else:
        from ector_cli.backup import run_backup

        run_backup(args)


def cmd_import(args):
    """Restore a Ector backup from a zip file."""
    from ector_cli.backup import run_import

    run_import(args)


def cmd_update(args):
    """Update Ector Agent to the latest release."""
    from ector_cli.update_cmd import cmd_update as _run_update

    _run_update(args)


def cmd_version(args):
    """Show version and install metadata (TUI-aligned banner, pt-BR)."""
    from ector_cli.presentation import print_version_screen

    print_version_screen()


def cmd_uninstall(args):
    """Uninstall Ector Agent."""
    _require_tty("uninstall")
    from ector_cli.uninstall import run_uninstall

    run_uninstall(args)



def _coalesce_session_name_args(argv: list) -> list:
    """Join unquoted multi-word session names after -c/--continue and -r/--resume.

    When a user types ``ector -c Demo Agent Dev`` without quoting the
    session name, argparse sees three separate tokens.  This function merges
    them into a single argument so argparse receives
    ``['-c', 'Demo Agent Dev']`` instead.

    Tokens are collected after the flag until we hit another flag (``-*``)
    or a known top-level subcommand.
    """
    _SUBCOMMANDS = {
        "chat",
        "model",
        "gateway",
        "setup",
        "whatsapp",
        "login",
        "logout",
        "auth",
        "status",
        "cron",
        "doctor",
        "config",
        "pairing",
        "skills",
        "tools",
        "mcp",
        "sessions",
        "stats",
        "version",
        "uninstall",
        "profile",
        "localhost",
        "plugins",
        "acp",
        "webhook",
        "memory",
        "dump",
        "debug",
        "backup",
        "import",
        "logs",
    }
    _SESSION_FLAGS = {"-c", "--continue", "-r", "--resume"}

    result = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in _SESSION_FLAGS:
            result.append(token)
            i += 1
            # Collect subsequent non-flag, non-subcommand tokens as one name
            parts: list = []
            while (
                i < len(argv)
                and not argv[i].startswith("-")
                and argv[i] not in _SUBCOMMANDS
            ):
                parts.append(argv[i])
                i += 1
            if parts:
                result.append(" ".join(parts))
        else:
            result.append(token)
            i += 1
    return result


def cmd_profile(args):
    """Profile management — create, delete, list, switch, alias."""
    from ector_cli.profiles import (
        list_profiles,
        create_profile,
        delete_profile,
        set_active_profile,
        get_active_profile_name,
        check_alias_collision,
        create_wrapper_script,
        remove_wrapper_script,
        print_profile_list,
        print_profile_status,
        _is_wrapper_dir_in_path,
        _get_wrapper_dir,
    )
    from ector_constants import display_ector_home

    action = getattr(args, "profile_action", None)

    if action is None:
        # Bare `ector profile` — show current profile status
        profile_name = get_active_profile_name()
        dhh = display_ector_home()
        profiles = list_profiles()
        active = None
        for p in profiles:
            if p.name == profile_name or (
                profile_name == "default" and p.is_default
            ):
                active = p
                break
        print_profile_status(profile_name, dhh, active)
        return

    if action == "list":
        profiles = list_profiles()
        active = get_active_profile_name()

        if not profiles:
            print("Nenhum perfil encontrado.")
            return

        print_profile_list(profiles, active)

    elif action == "use":
        name = args.profile_name
        try:
            set_active_profile(name)
            if name == "default":
                print(f"Mudou para: padrão (~/.ector)")
            else:
                print(f"Mudou para: {name}")
        except (ValueError, FileNotFoundError) as e:
            print(f"Erro: {e}")
            sys.exit(1)

    elif action == "create":
        name = args.profile_name
        clone = getattr(args, "clone", False)
        clone_all = getattr(args, "clone_all", False)
        no_alias = getattr(args, "no_alias", False)

        try:
            clone_from = getattr(args, "clone_from", None)

            profile_dir = create_profile(
                name=name,
                clone_from=clone_from,
                clone_all=clone_all,
                clone_config=clone,
                no_alias=no_alias,
            )
            print(f"\nPerfil '{name}' criado em {profile_dir}")

            if clone or clone_all:
                source_label = (
                    getattr(args, "clone_from", None) or get_active_profile_name()
                )
                if clone_all:
                    print(f"Cópia completa de {source_label}.")
                else:
                    print(f"Config, .env, SOUL.md clonados de {source_label}.")

            # Create wrapper alias
            if not no_alias:
                collision = check_alias_collision(name)
                if collision:
                    print(f"\n▲  Não é possível criar alias '{name}' — {collision}")
                    print(
                        f"  Escolha um alias personalizado:  ector profile alias {name} --name <custom>"
                    )
                    print(f"  Ou acesse via flag:     ector -p {name} chat")
                else:
                    wrapper_path = create_wrapper_script(name)
                    if wrapper_path:
                        print(f"Wrapper criado: {wrapper_path}")
                        if not _is_wrapper_dir_in_path():
                            print(f"\n▲  {_get_wrapper_dir()} não está no seu PATH.")
                            print(
                                f"  Adicione à configuração do seu shell (~/.bashrc or ~/.zshrc):"
                            )
                            print(f'    export PATH="$HOME/.local/bin:$PATH"')

            # Profile dir for display
            try:
                profile_dir_display = "~/" + str(profile_dir.relative_to(Path.home()))
            except ValueError:
                profile_dir_display = str(profile_dir)

            # Next steps
            print(f"\nPróximos passos:")
            print(f"  {name} setup              Configurar chaves API e modelo")
            print(f"  {name} chat               Começar a conversar")
            print(f"  {name} gateway start      Iniciar o gateway de mensagens")
            if clone or clone_all:
                print(f"\n  Edite {profile_dir_display}/.env para chaves API diferentes")
                print(f"  Edite {profile_dir_display}/SOUL.md para uma personalidade diferente")
            else:
                print(
                    f"\n  ▲  Este perfil ainda não tem chaves API. Execute '{name} setup' primeiro,"
                )
                print(f"    ou ele herdará as chaves do ambiente do seu shell.")
                print(f"  Edite {profile_dir_display}/SOUL.md para personalizar a personalidade")
            print()

        except (ValueError, FileExistsError, FileNotFoundError) as e:
            print(f"Erro: {e}")
            sys.exit(1)

    elif action == "delete":
        name = args.profile_name
        yes = getattr(args, "yes", False)
        try:
            delete_profile(name, yes=yes)
        except (ValueError, FileNotFoundError) as e:
            print(f"Erro: {e}")
            sys.exit(1)

    elif action == "show":
        name = args.profile_name
        from ector_cli.profiles import (
            get_profile_dir,
            profile_exists,
            _read_config_model,
            _check_gateway_running,
            _count_skills,
        )

        if not profile_exists(name):
            print(f"Erro: Perfil '{name}' não existe.")
            sys.exit(1)
        profile_dir = get_profile_dir(name)
        model, provider = _read_config_model(profile_dir)
        gw = _check_gateway_running(profile_dir)
        skills = _count_skills(profile_dir)
        wrapper = _get_wrapper_dir() / name

        print(f"\nPerfil: {name}")
        print(f"Caminho:    {profile_dir}")
        if model:
            print(f"Modelo:   {model}" + (f" ({provider})" if provider else ""))
        print(f"Gateway: {'em execução' if gw else 'parado'}")
        print(f"Skills:  {skills}")
        print(
            f".env:    {'existe' if (profile_dir / '.env').exists() else 'não configurado'}"
        )
        print(
            f"SOUL.md: {'existe' if (profile_dir / 'SOUL.md').exists() else 'não configurado'}"
        )
        if wrapper.exists():
            print(f"Alias:   {wrapper}")
        print()

    elif action == "alias":
        name = args.profile_name
        remove = getattr(args, "remove", False)
        custom_name = getattr(args, "alias_name", None)

        from ector_cli.profiles import profile_exists

        if not profile_exists(name):
            print(f"Erro: Perfil '{name}' não existe.")
            sys.exit(1)

        alias_name = custom_name or name

        if remove:
            if remove_wrapper_script(alias_name):
                print(f"✔ Alias '{alias_name}' removido")
            else:
                print(f"Nenhum alias '{alias_name}' encontrado para remover.")
        else:
            collision = check_alias_collision(alias_name)
            if collision:
                print(f"Erro: {collision}")
                sys.exit(1)
            wrapper_path = create_wrapper_script(alias_name)
            if wrapper_path:
                # If custom name, write the profile name into the wrapper
                if custom_name:
                    wrapper_path.write_text(f'#!/bin/sh\nexec ector -p {name} "$@"\n')
                print(f"✔ Alias criado: {wrapper_path}")
                if not _is_wrapper_dir_in_path():
                    print(f"▲  {_get_wrapper_dir()} não está no seu PATH.")

    elif action == "rename":
        from ector_cli.profiles import rename_profile

        try:
            new_dir = rename_profile(args.old_name, args.new_name)
            print(f"\nPerfil renomeado: {args.old_name} → {args.new_name}")
            print(f"Caminho: {new_dir}\n")
        except (ValueError, FileExistsError, FileNotFoundError) as e:
            print(f"Erro: {e}")
            sys.exit(1)

    elif action == "export":
        from ector_cli.profiles import export_profile

        name = args.profile_name
        output = args.output or f"{name}.tar.gz"
        try:
            result_path = export_profile(name, output)
            print(f"✔ Exportou '{name}' para {result_path}")
        except (ValueError, FileNotFoundError) as e:
            print(f"Erro: {e}")
            sys.exit(1)

    elif action == "import":
        from ector_cli.profiles import import_profile

        try:
            profile_dir = import_profile(
                args.archive, name=getattr(args, "import_name", None)
            )
            name = profile_dir.name
            print(f"✔ Perfil '{name}' importado em {profile_dir}")

            # Offer to create alias
            collision = check_alias_collision(name)
            if not collision:
                wrapper_path = create_wrapper_script(name)
                if wrapper_path:
                    print(f"  Wrapper criado: {wrapper_path}")
            print()
        except (ValueError, FileExistsError, FileNotFoundError) as e:
            print(f"Erro: {e}")
            sys.exit(1)


def cmd_localhost(args):
    """Start the web UI server (prints an auth URL by default)."""
    from ector_cli.colors import Colors, color

    def _up_online_mode() -> bool:
        return bool(getattr(args, "up_online", False)) or getattr(
            args, "localhost_action", None
        ) in {"nginx-setup"}

    def _infer_primary_ip() -> str | None:
        """Best-effort inference of the server's primary IPv4."""
        try:
            import socket

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Doesn't require the remote host to be reachable; no packets need to be sent.
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                return ip if ip and ip != "0.0.0.0" else None
            finally:
                s.close()
        except Exception:
            return None

    if getattr(args, "localhost_action", None) == "kill":
        from ector_constants import display_ector_home
        from ector_cli.web_server import (
            _probe_ector_dashboard_http,
            find_dashboard_pids,
            stop_running_dashboard,
        )

        kill_port = int(getattr(args, "port", 9000) or 9000)
        stopped = stop_running_dashboard(timeout_seconds=5.0, port=kill_port)
        if stopped:
            print("✔ Painel local finalizado.")
        else:
            if find_dashboard_pids(port=kill_port):
                print(
                    f"Encontrei processo(s) do painel na porta {kill_port}, "
                    "mas não foi possível encerrá-los (permissão negada?)."
                )
            elif _probe_ector_dashboard_http(kill_port):
                print(
                    f"Há um serviço na porta {kill_port} que responde como painel Ector, "
                    "mas o PID não foi identificado. Tente: "
                    f"lsof -nP -iTCP:{kill_port} -sTCP:LISTEN"
                )
            else:
                print(
                    "Nenhum painel em execução encontrado "
                    f"(perfil {display_ector_home()}, porta {kill_port}; "
                    "PID file ausente, processo já finalizado, ou instância de outro perfil)."
                )

        # If nginx was configured for online mode, disable the proxy site too so
        # the instance is actually taken offline.
        if sys.platform == "linux":
            try:
                from ector_cli.nginx_setup import disable_nginx_ector_dashboard_site

                disabled = disable_nginx_ector_dashboard_site()
                if disabled:
                    print("✔ Nginx: site ector-dashboard desabilitado.")
            except Exception:
                # Best-effort; nginx may not be installed or sudo not available.
                pass
        return

    if _up_online_mode():
        import getpass

        from ector_cli.nginx_setup import NginxSetupOptions, setup_nginx_for_ector_dashboard

        server_name = (getattr(args, "server_name", None) or getattr(args, "domain", None) or "").strip() or "_"
        listen_port = int(getattr(args, "listen_port", 80))
        enable_tls = bool(getattr(args, "tls", False))
        email = (getattr(args, "email", None) or "").strip() or None
        enable_basic = bool(getattr(args, "basic_auth", False))
        basic_user = (getattr(args, "basic_user", None) or "ector").strip() or "ector"
        basic_password = None
        if enable_basic:
            basic_password = getpass.getpass("Senha do Basic Auth (Nginx): ")
            if not basic_password:
                print("Erro: senha vazia.")
                sys.exit(1)

        allow_ips = tuple(getattr(args, "allow_ip", []) or [])
        upstream_port = int(getattr(args, "upstream_port", 9000))
        if listen_port == upstream_port:
            # Avoid binding conflict: Nginx will listen on the public port, dashboard one below.
            upstream_port = upstream_port - 1

        try:
            setup_nginx_for_ector_dashboard(
                NginxSetupOptions(
                    server_name=server_name,
                    listen_port=listen_port,
                    upstream_host="127.0.0.1",
                    upstream_port=upstream_port,
                    email=email,
                    enable_tls=enable_tls,
                    enable_basic_auth=enable_basic,
                    basic_user=basic_user,
                    basic_password=basic_password,
                    allow_ips=allow_ips,
                )
            )
        except Exception as exc:
            print(f"✖ Falha ao configurar Nginx: {exc}")
            print()
            print("Checklist mínimo:")
            print("- Portas do Nginx (ex: 80/443) liberadas no firewall do provedor")
            print("- Se usar TLS, DNS precisa apontar o domínio para a VPS")
            print("- `sudo -n` configurado (ou rode os comandos manualmente)")
            sys.exit(1)

        print("✔ Nginx configurado.")
        scheme = "https" if enable_tls else "http"
        host_for_print = (getattr(args, "public_host", None) or os.environ.get("ECTOR_DASHBOARD_PUBLIC_HOST") or "").strip() or _infer_primary_ip() or "127.0.0.1"
        # Prefer printing server_name when it looks like a domain.
        printable_host = server_name if server_name not in {"_", "*"} else host_for_print
        public_suffix = "" if listen_port in {80, 443} else f":{listen_port}"
        public_base_url = f"{scheme}://{printable_host}{public_suffix}"
        print(f"Acesse: {public_base_url}")

        # Behind Nginx: bind loopback on upstream port; public URL uses the proxy.
        args.host = "127.0.0.1"
        args.insecure = False
        args.port = upstream_port
        args.public_host = printable_host
        args._localhost_public_base_url = public_base_url  # type: ignore[attr-defined]
        args.no_open = True  # browser open is meaningless on a VPS

    # Default: loopback-only unless --insecure.
    if not _up_online_mode():
        if not getattr(args, "insecure", False):
            args.host = "127.0.0.1"

    def _public_host_for_url(bound_host: str) -> str:
        from ector_cli.web_server import _LOOPBACK_HOST_VALUES, get_dashboard_local_hostname

        explicit = (getattr(args, "public_host", None) or os.environ.get("ECTOR_DASHBOARD_PUBLIC_HOST") or "").strip()
        if explicit:
            return explicit
        if bound_host in {"0.0.0.0", "::"}:
            return _infer_primary_ip() or "127.0.0.1"
        if bound_host.lower() in _LOOPBACK_HOST_VALUES:
            return get_dashboard_local_hostname() or "127.0.0.1"
        return bound_host

    def _url_scheme() -> str:
        explicit = (getattr(args, "scheme", None) or os.environ.get("ECTOR_DASHBOARD_URL_SCHEME") or "").strip().lower()
        if explicit in {"http", "https"}:
            return explicit
        if _up_online_mode():
            return "https" if bool(getattr(args, "tls", False)) else "http"
        return "http"

    def _maybe_open_firewall(port: int) -> None:
        """Best-effort: open the dashboard port on common Linux firewalls.

        Only runs when the user explicitly passes --open-firewall.
        Uses `sudo -n` (non-interactive). If sudo requires a password, we print
        the manual commands instead of blocking.
        """
        if not getattr(args, "open_firewall", False):
            return
        if sys.platform != "linux":
            return

        def _run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, capture_output=True, text=True, check=False)

        port_str = str(int(port))

        # Prefer ufw when active.
        ufw = shutil.which("ufw")
        if ufw:
            status = _run(["sudo", "-n", ufw, "status"])
            out = (status.stdout or "") + "\n" + (status.stderr or "")
            if "Status: active" in out:
                allow = _run(["sudo", "-n", ufw, "allow", f"{port_str}/tcp"])
                if allow.returncode == 0:
                    print(f"✔ Firewall (ufw): liberada a porta {port_str}/tcp")
                    return
                print(f"▲  Não foi possível liberar via ufw automaticamente.")
                print(f"    Execute: sudo ufw allow {port_str}/tcp")
                return

        # Try firewalld when available.
        fw = shutil.which("firewall-cmd")
        if fw:
            state = _run(["sudo", "-n", fw, "--state"])
            if (state.stdout or "").strip() == "running":
                add = _run(["sudo", "-n", fw, "--add-port", f"{port_str}/tcp", "--permanent"])
                reload = _run(["sudo", "-n", fw, "--reload"])
                if add.returncode == 0 and reload.returncode == 0:
                    print(f"✔ Firewall (firewalld): liberada a porta {port_str}/tcp")
                    return
                print("▲  Não foi possível liberar via firewalld automaticamente.")
                print(f"    Execute: sudo firewall-cmd --add-port={port_str}/tcp --permanent && sudo firewall-cmd --reload")
                return

        # Try nftables (common on modern Ubuntu) — best effort.
        nft = shutil.which("nft")
        if nft:
            # If the default inet/filter table exists, add a permissive rule.
            # This may fail on custom rulesets; that's OK (we fall through).
            add_rule = _run(
                [
                    "sudo",
                    "-n",
                    nft,
                    "add",
                    "rule",
                    "inet",
                    "filter",
                    "input",
                    "tcp",
                    "dport",
                    port_str,
                    "accept",
                ]
            )
            if add_rule.returncode == 0:
                print(f"✔ Firewall (nftables): liberada a porta {port_str}/tcp (regra adicionada)")
                print("▲  Observação: persistência depende do seu setup (nftables ruleset).")
                return

        # Try iptables (legacy but still common).
        ipt = shutil.which("iptables")
        if ipt:
            # Insert a rule at the top of INPUT chain.
            insert = _run(["sudo", "-n", ipt, "-I", "INPUT", "-p", "tcp", "--dport", port_str, "-j", "ACCEPT"])
            if insert.returncode == 0:
                print(f"✔ Firewall (iptables): liberada a porta {port_str}/tcp (regra adicionada)")
                print("▲  Observação: para persistir após reboot, instale `iptables-persistent`.")
                return

        # Could not auto-open at OS layer — print actionable instructions.
        print(f"▲  Não consegui liberar {port_str}/tcp automaticamente (ufw/firewalld/nft/iptables ausentes ou sudo exigiu senha).")
        print()
        print("  No Ubuntu, tente um destes:")
        print(f"    sudo ufw allow {port_str}/tcp && sudo ufw status")
        print(f"    sudo iptables -I INPUT -p tcp --dport {port_str} -j ACCEPT")
        print()
        print("  E no provedor (cloud), libere Inbound TCP na mesma porta (Security Group/Firewall).")

    # Default behavior: detach (do not block the terminal) unless --foreground.
    detach = not getattr(args, "foreground", False)

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        print("Dependências da interface Web não instaladas (necessita fastapi + uvicorn).")
        print(
            f"Reinstale o pacote neste interpretador para que as atualizações de metadados se apliquem:\n"
            f"  cd {PROJECT_ROOT}\n"
            f"  {sys.executable} -m pip install -e .\n"
            "Se o `pip` estiver faltando neste venv, use:  uv pip install -e ."
        )
        print(f"Erro de importação: {e}")
        sys.exit(1)

    if "ECTOR_WEB_DIST" not in os.environ:
        if not _build_web_ui(PROJECT_ROOT / "frontend" / "dashboard", fatal=True):
            sys.exit(1)

    from ector_cli.web_server import start_server

    if getattr(args, "no_auth", False):
        os.environ["ECTOR_DASHBOARD_AUTH"] = "0"

    open_url = None
    dash_auth_env = os.environ.get("ECTOR_DASHBOARD_AUTH", "").strip().lower()
    if dash_auth_env not in {"0", "false", "no", "off"}:
        os.environ["ECTOR_DASHBOARD_AUTH"] = "1"
        from ector_cli.dashboard_auth import create_dashboard_access_token

        token = create_dashboard_access_token(ttl_seconds=15 * 60)
        if _up_online_mode() and hasattr(args, "_localhost_public_base_url"):
            base_url = getattr(args, "_localhost_public_base_url")
            open_url = f"{base_url}/?token={token}"
        else:
            url_host = _public_host_for_url(str(args.host))
            open_url = f"{_url_scheme()}://{url_host}:{args.port}/?token={token}"
        print()
        print(color("┌─ Painel web", Colors.CYAN, Colors.BOLD))
        print(color("│", Colors.CYAN, Colors.BOLD) + "  " + color("🔗", Colors.GREEN, Colors.BOLD) + " " + color(open_url, Colors.WHITE, Colors.BOLD))
        print(color("└────────────────────────────────────────────────────────", Colors.CYAN, Colors.BOLD))
        print()

    # If we're binding publicly, optionally open the OS firewall.
    if getattr(args, "insecure", False) and str(args.host) in {"0.0.0.0", "::"}:
        _maybe_open_firewall(int(args.port))

    if detach:
        # Substitui instância anterior (mesma porta) para carregar código/UI novos.
        from ector_cli.web_server import stop_running_dashboard

        if stop_running_dashboard(timeout_seconds=3.0, port=int(args.port)):
            print("ℹ Painel anterior encerrado.")

        # Spawn a detached process that runs the server.
        env = os.environ.copy()
        env["ECTOR_DASHBOARD_HOST"] = str(args.host)
        env["ECTOR_DASHBOARD_PORT"] = str(int(args.port))
        env["ECTOR_DASHBOARD_INSECURE"] = "1" if getattr(args, "insecure", False) else "0"
        if open_url:
            env["ECTOR_DASHBOARD_OPEN_URL"] = open_url

        # Fully detach stdio so the caller terminal can be closed safely.
        subprocess.Popen(
            [sys.executable, "-m", "ector_cli.dashboard_daemon"],
            env=env,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("✔ Painel local iniciado em background.")
        if not args.no_open:
            from ector_cli.web_server import open_dashboard_browser

            open_dashboard_browser(
                open_url,
                host=str(args.host),
                port=int(args.port),
            )
        return

    start_server(
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
        allow_public=getattr(args, "insecure", False),
        open_url=open_url,
    )


def cmd_logs(args):
    """View and filter Ector log files."""
    from ector_cli.logs import clear_logs, list_logs, tail_log

    log_name = getattr(args, "log_name", "agent") or "agent"

    if log_name == "list":
        list_logs()
        return

    if log_name == "clear":
        if getattr(args, "follow", False):
            print("Erro: 'clear' não pode ser usado com --follow.")
            sys.exit(1)
        clear_logs(getattr(args, "clear_target", None))
        return

    tail_log(
        log_name,
        num_lines=getattr(args, "lines", 50),
        follow=getattr(args, "follow", False),
        level=getattr(args, "level", None),
        session=getattr(args, "session", None),
        since=getattr(args, "since", None),
        component=getattr(args, "component", None),
    )


def _cli_process_title_for_args(args) -> str:
    """OS-visible process name for the current CLI invocation."""
    cmd = getattr(args, "command", None)
    if cmd == "gateway":
        return "Ector Gateway"
    if cmd == "localhost":
        return "Ector Web"
    if cmd in (None, "chat"):
        return "Ector"
    return "Ector"


def main():
    """Main entry point for ector CLI."""
    from ector_cli.cli_parser import build_parser

    parser, subparsers = build_parser()


    # =========================================================================
    # Parse and execute
    # =========================================================================
    # Pre-process argv so unquoted multi-word session names after -c / -r
    # are merged into a single token before argparse sees them.
    # e.g. ``ector -c Demo Agent Dev`` → ``ector -c 'Demo Agent Dev'``
    # ── Container-aware routing ────────────────────────────────────────
    # When NixOS container mode is active, route ALL subcommands into
    # the managed container.  This MUST run before parse_args() so that
    # --help, unrecognised flags, and every subcommand are forwarded
    # transparently instead of being intercepted by argparse on the host.
    from ector_cli.config import get_container_exec_info

    container_info = get_container_exec_info()
    if container_info:
        _exec_in_container(container_info, sys.argv[1:])
        # Unreachable: os.execvp never returns on success (process is replaced)
        # and raises OSError on failure (which propagates as a traceback).
        sys.exit(1)

    _processed_argv = _coalesce_session_name_args(sys.argv[1:])

    # ── Defensive subparser routing (bpo-9338 workaround) ───────────
    # On some Python versions (notably <3.11), argparse fails to route
    # subcommand tokens when the parent parser has nargs='?' optional
    # arguments (--continue).  The symptom: "unrecognized arguments: model"
    # even though 'model' is a registered subcommand.
    #
    # Fix: when argv contains a token matching a known subcommand, set
    # subparsers.required=True to force deterministic routing.  If that
    # fails (e.g. 'ector -c model' where 'model' is consumed as the
    # session name for --continue), fall back to the default behaviour.
    import io as _io

    _known_cmds = (
        set(subparsers.choices.keys()) if hasattr(subparsers, "choices") else set()
    )
    _has_cmd_token = any(
        t in _known_cmds for t in _processed_argv if not t.startswith("-")
    )

    if _has_cmd_token:
        subparsers.required = True
        _saved_stderr = sys.stderr
        try:
            sys.stderr = _io.StringIO()
            args = parser.parse_args(_processed_argv)
            sys.stderr = _saved_stderr
        except SystemExit as exc:
            sys.stderr = _saved_stderr
            # Help/version flags (exit code 0) already printed output —
            # re-raise immediately to avoid a second parse_args printing
            # the same help text again (#10230).
            if exc.code == 0:
                raise
            # Subcommand name was consumed as a flag value (e.g. -c model).
            # Fall back to optional subparsers so argparse handles it normally.
            subparsers.required = False
            args = parser.parse_args(_processed_argv)
    else:
        subparsers.required = False
        args = parser.parse_args(_processed_argv)

    try:
        from ector_process import set_process_title

        set_process_title(_cli_process_title_for_args(args))
    except Exception:
        pass

    # Handle --version flag
    if args.version:
        cmd_version(args)
        return

    # Enforce Ector identity authentication (ector.cc).  Runs before any
    # agent-invoking command so the user cannot run the agent without an
    # active session.  Inspection / config / logs commands stay offline.
    _enforce_identity_auth(args)

    # Discover Python plugins and register shell hooks once, before any
    # command that can fire lifecycle hooks.  Both are idempotent; gated
    # so introspection/management commands (ector hooks list, cron
    # list, gateway status, mcp add, ...) don't pay discovery cost or
    # trigger consent prompts for hooks the user is still inspecting.
    # Groups with mixed admin/CRUD vs. agent-running entries narrow via
    # the nested subcommand (dest varies by parser).
    if _should_discover_plugins_and_hooks(args):
        _accept_hooks = bool(getattr(args, "accept_hooks", False))
        try:
            from ector_cli.plugins import discover_plugins
            discover_plugins()
        except Exception:
            logger.debug(
                "plugin discovery failed at CLI startup", exc_info=True,
            )
        try:
            from ector_cli.config import load_config
            from agent.shell_hooks import register_from_config
            register_from_config(load_config(), accept_hooks=_accept_hooks)
        except Exception:
            logger.debug(
                "shell-hook registration failed at CLI startup",
                exc_info=True,
            )

    # Handle top-level --oneshot / -z: single-shot mode, stdout = final
    # response only, nothing else. Bypasses cli.py entirely.
    if getattr(args, "oneshot", None):
        from ector_cli.oneshot import run_oneshot

        sys.exit(run_oneshot(
            args.oneshot,
            model=getattr(args, "model", None),
            provider=getattr(args, "provider", None),
        ))

    # Handle top-level --resume / --continue as shortcut to chat
    if (args.resume or args.continue_last) and args.command is None:
        args.command = "chat"
        for attr, default in [
            ("query", None),
            ("model", None),
            ("provider", None),
            ("toolsets", None),
            ("verbose", False),
            ("worktree", False),
        ]:
            if not hasattr(args, attr):
                setattr(args, attr, default)
        cmd_chat(args)
        return

    # Default: terminal chat (TUI on TTY). Web UI is explicit via `ector localhost`.
    if args.command is None:
        # Keep the predicate for future-proofing (it currently always routes to chat).
        if _bare_ector_should_use_chat(args):
            for attr, default in [
                ("query", None),
                ("model", None),
                ("provider", None),
                ("toolsets", None),
                ("verbose", False),
                ("resume", None),
                ("continue_last", None),
                ("worktree", False),
            ]:
                if not hasattr(args, attr):
                    setattr(args, attr, default)
            cmd_chat(args)
            return
        # Defensive fallback — should not trigger under current routing rules.
        parser.print_help()
        return

    # Execute the command
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
