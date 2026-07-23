"""
Doctor command for Ector CLI.

Diagnoses issues with Ector Agent setup.
"""

import os
import sys
import subprocess
import shutil
import stat
from pathlib import Path

from ector_cli.config import get_project_root, get_ector_home, get_env_path
from ector_constants import display_ector_home

PROJECT_ROOT = get_project_root()
ECTOR_HOME = get_ector_home()
_DHH = display_ector_home()  # user-facing display path (e.g. ~/.ector or ~/.ector/profiles/coder)

# Load environment variables from ~/.ector/.env so API key checks work
from dotenv import load_dotenv
_env_path = get_env_path()
if _env_path.exists():
    try:
        load_dotenv(_env_path, encoding="utf-8")
    except UnicodeDecodeError:
        load_dotenv(_env_path, encoding="latin-1")
# Also try project .env as dev fallback
try:
    load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8")
except UnicodeDecodeError:
    load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="latin-1")

from ector_cli.colors import Colors, color
from ector_cli.models import _ECTOR_USER_AGENT
from ector_constants import OPENROUTER_MODELS_URL
from utils import base_url_host_matches


_PROVIDER_ENV_HINTS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_TOKEN",
    "OPENAI_BASE_URL",
    "ECTOR_API_KEY",
    "GLM_API_KEY",
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
    "ZHIPU_API_KEY",
    "KIMI_API_KEY",
    "KIMI_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "KILOCODE_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "HF_TOKEN",
    "AI_GATEWAY_API_KEY",
    "XIAOMI_API_KEY",
)


from ector_constants import is_termux as _is_termux


def _python_install_cmd() -> str:
    return "python -m pip install" if _is_termux() else "uv pip install"


def _system_package_install_cmd(pkg: str) -> str:
    if _is_termux():
        return f"pkg install {pkg}"
    if sys.platform == "darwin":
        return f"brew install {pkg}"
    return f"sudo apt install {pkg}"


def _termux_browser_setup_steps(node_installed: bool) -> list[str]:
    steps: list[str] = []
    step = 1
    if not node_installed:
        steps.append(f"{step}) pkg install nodejs")
        step += 1
    steps.append(f"{step}) npm install -g agent-browser")
    steps.append(f"{step + 1}) agent-browser install")
    return steps


def _has_provider_env_config(content: str) -> bool:
    """Return True when ~/.ector/.env contains provider auth/base URL settings."""
    return any(key in content for key in _PROVIDER_ENV_HINTS)


def _read_text_with_fallback(path: Path) -> tuple[str | None, str | None]:
    """Read text with UTF-8 first, then latin-1 fallback."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1"), None
        except Exception as e:
            return None, str(e)
    except Exception as e:
        return None, str(e)


def _is_valid_command_wrapper(path: Path) -> bool:
    """Best-effort validation for non-symlink `ector` wrappers."""
    if not path.is_file():
        return False
    try:
        mode = path.stat().st_mode
    except OSError:
        return False

    if not (mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        return False

    content, _ = _read_text_with_fallback(path)
    if not content:
        # Binary launcher or unreadable script: keep warning, don't treat as valid.
        return False

    markers = (
        "#!/usr/bin/env",
        "#!/bin/",
        "python",
        "ector -p",
        "from ector_cli",
        "console_scripts",
    )
    lowered = content.lower()
    return any(marker.lower() in lowered for marker in markers)


def check_ok(text: str, detail: str = ""):
    print(f"  {color('✔', Colors.GREEN)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_warn(text: str, detail: str = ""):
    print(f"  {color('▲', Colors.YELLOW)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_fail(text: str, detail: str = ""):
    print(f"  {color('✖', Colors.RED)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_info(text: str):
    print(f"    {color('→', Colors.CYAN)} {text}")


def _effective_terminal_backend() -> str:
    """Return the active terminal backend (env var overrides config.yaml)."""
    terminal_env = os.getenv("TERMINAL_ENV", "").strip()
    if terminal_env:
        return terminal_env
    try:
        from ector_cli.config import load_config

        cfg = load_config()
        terminal_cfg = cfg.get("terminal") or {}
        if isinstance(terminal_cfg, dict):
            return str(terminal_cfg.get("backend") or "local")
    except Exception:
        pass
    return "local"


def _check_gateway_and_channels(issues: list[str], manual_issues: list[str]) -> None:
    """Check gateway liveness, runtime health, messaging channels, and systemd linger."""
    print()
    print(color("◆ Gateway e Canais", Colors.CYAN, Colors.BOLD))

    gateway_running = False
    try:
        from ector_cli.gateway import _format_gateway_pids, get_gateway_runtime_snapshot

        snapshot = get_gateway_runtime_snapshot()
        gateway_running = snapshot.running
        if snapshot.running:
            pid_detail = ""
            if snapshot.gateway_pids:
                pid_detail = f", PID {_format_gateway_pids(snapshot.gateway_pids)}"
            check_ok("Gateway em execução", f"({snapshot.manager}{pid_detail})")
        else:
            check_warn("Gateway parado", f"({snapshot.manager})")
            check_info("Inicie com: ector gateway run  ou  ector gateway start")

        if snapshot.has_process_service_mismatch:
            check_warn(
                "Serviço instalado, mas não gerencia o gateway atual",
                "(processo manual em execução fora do systemd/launchd)",
            )
            manual_issues.append(
                "Pare o gateway manual ou reinicie via ector gateway restart para alinhar serviço e processo"
            )
    except Exception as e:
        check_warn("Status do gateway", f"(não foi possível verificar: {e})")

    try:
        from gateway.status import read_runtime_status

        runtime = read_runtime_status() or {}
        gateway_state = runtime.get("gateway_state")
        exit_reason = runtime.get("exit_reason")

        if gateway_state == "startup_failed":
            reason = exit_reason or "motivo desconhecido"
            check_fail("Última inicialização do gateway falhou", f"({reason})")
            issues.append(
                f"Gateway falhou ao iniciar: {reason}. Veja `ector logs --follow` ou `ector gateway status`"
            )
        elif gateway_state == "draining":
            action = "restart" if runtime.get("restart_requested") else "shutdown"
            count = int(runtime.get("active_agents") or 0)
            check_info(f"Gateway esvaziando para {action} ({count} agente(s) ativo(s))")
        elif gateway_state == "stopped" and exit_reason:
            check_warn("Último encerramento do gateway", f"({exit_reason})")

        for plat_key, pdata in (runtime.get("platforms") or {}).items():
            if not isinstance(pdata, dict):
                continue
            state = pdata.get("state")
            if state == "fatal":
                msg = pdata.get("error_message") or "erro desconhecido"
                check_fail(f"Canal {plat_key}", f"({msg})")
                issues.append(
                    f"{plat_key}: {msg} — verifique credenciais com `ector gateway setup` ou /channels"
                )
            elif state == "disconnected":
                msg = pdata.get("error_message") or "desconectado"
                check_warn(f"Canal {plat_key}", f"({msg})")
    except Exception:
        pass

    configured_channels: list[str] = []
    partial_channels: list[str] = []
    try:
        from gateway.platform_catalog import list_platforms

        for platform in list_platforms():
            label = platform.get("label") or platform.get("key", "?")
            state = platform.get("state", "not_configured")
            status_text = platform.get("status_text") or state

            if state == "not_configured":
                check_info(f"{label}: não configurado")
                continue

            if state in ("configured", "paired"):
                configured_channels.append(label)
                check_ok(label, f"({status_text})")
            elif state == "partial":
                partial_channels.append(label)
                check_warn(label, f"({status_text})")
                issues.append(f"Conclua a configuração de {label}: ector gateway setup")
            else:
                check_warn(label, f"({status_text})")
    except Exception as e:
        check_warn("Canais de mensagem", f"(não foi possível verificar: {e})")

    if configured_channels and not gateway_running:
        check_warn(
            "Canal(is) configurado(s), mas gateway parado",
            f"({', '.join(configured_channels)})",
        )
        issues.append("Inicie o gateway: ector gateway start")

    try:
        from ector_cli.config import get_env_value

        whatsapp_enabled = (get_env_value("WHATSAPP_ENABLED") or "").lower() == "true"
        if whatsapp_enabled or partial_channels:
            bridge_dir = PROJECT_ROOT / "scripts" / "whatsapp-bridge"
            if whatsapp_enabled:
                if not shutil.which("node"):
                    check_fail("Node.js necessário para WhatsApp", "(instale Node.js 18+)")
                    issues.append("Instale Node.js para o bridge WhatsApp")
                elif not (bridge_dir / "node_modules").exists():
                    check_warn(
                        "Deps da ponte WhatsApp não instaladas",
                        "(cd scripts/whatsapp-bridge && pnpm install)",
                    )
                    issues.append(
                        "Instale deps da ponte WhatsApp: cd scripts/whatsapp-bridge && pnpm install"
                    )
                else:
                    check_ok("Ponte WhatsApp (deps Node.js)")
    except Exception:
        pass

    try:
        from ector_cli.gateway import (
            get_systemd_linger_status,
            get_systemd_unit_path,
            is_linux,
        )
    except Exception as e:
        check_warn("Linger do serviço gateway", f"(não foi possível importar ajudantes do gateway: {e})")
        return

    if not is_linux():
        return

    unit_path = get_systemd_unit_path()
    if not unit_path.exists():
        return

    linger_enabled, linger_detail = get_systemd_linger_status()
    if linger_enabled is True:
        check_ok("Linger do systemd habilitado", "(serviço gateway sobrevive ao logout)")
    elif linger_enabled is False:
        check_warn("Linger do systemd desabilitado", "(gateway pode parar após o logout)")
        check_info("Execute: sudo loginctl enable-linger $USER")
        issues.append("Habilitar linger para o serviço de usuário gateway: sudo loginctl enable-linger $USER")
    else:
        check_warn("Não foi possível verificar o linger do systemd", f"({linger_detail})")


def run_doctor(args):
    """Run diagnostic checks."""
    should_fix = getattr(args, 'fix', False)

    # Doctor runs from the interactive CLI, so CLI-gated tool availability
    # checks (like cronjob management) should see the same context as `ector`.
    os.environ.setdefault("ECTOR_INTERACTIVE", "1")
    
    issues = []
    manual_issues = []  # issues that can't be auto-fixed
    fixed_count = 0
    
    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│                 🩺 Ector Doctor                        │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))
    
    # =========================================================================
    # Check: Python version
    # =========================================================================
    print()
    print(color("◆ Ambiente Python", Colors.CYAN, Colors.BOLD))
    
    py_version = sys.version_info
    if py_version >= (3, 11):
        check_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    elif py_version >= (3, 10):
        check_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
        check_warn("Python 3.11+ recomendado para ferramentas de Treinamento RL (tinker requer >= 3.11)")
    elif py_version >= (3, 8):
        check_warn(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}", "(3.10+ recomendado)")
    else:
        check_fail(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}", "(3.10+ necessário)")
        issues.append("Atualize o Python para 3.10+")
    
    # Check if in virtual environment
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        check_ok("Ambiente virtual ativo")
    else:
        check_warn("Não está em um ambiente virtual", "(recomendado)")
    
    # =========================================================================
    # Check: Required packages
    # =========================================================================
    print()
    print(color("◆ Pacotes Necessários", Colors.CYAN, Colors.BOLD))
    
    required_packages = [
        ("openai", "OpenAI SDK"),
        ("rich", "Rich (terminal UI)"),
        ("dotenv", "python-dotenv"),
        ("yaml", "PyYAML"),
        ("httpx", "HTTPX"),
    ]
    
    optional_packages = [
        ("croniter", "Croniter (expressões cron)"),
        ("telegram", "python-telegram-bot"),
        ("discord", "discord.py"),
    ]
    
    for module, name in required_packages:
        try:
            __import__(module)
            check_ok(name)
        except ImportError:
            check_fail(name, "(ausente)")
            issues.append(f"Instale {name}: {_python_install_cmd()} {module}")
    
    for module, name in optional_packages:
        try:
            __import__(module)
            check_ok(name, "(opcional)")
        except ImportError:
            check_warn(name, "(opcional, não instalado)")

    # =========================================================================
    # Check: Document extraction stack (local OCR)
    # =========================================================================
    print()
    print(color("◆ Stack de Documentos/OCR", Colors.CYAN, Colors.BOLD))
    try:
        from agent.document_stack.probe import probe_document_stack

        doc_report = probe_document_stack()
        if doc_report.get("available"):
            tier = doc_report.get("recommended_tier", "lite")
            check_ok("Backends locais de documento disponíveis", f"(tier recomendado: {tier})")
        else:
            check_warn("Nenhum backend local de documento disponível")
            issues.append("Instale um backend de documentos: uv pip install 'ector-agent[documents-lite]'")

        free_disk = doc_report.get("system", {}).get("free_disk_gb")
        if isinstance(free_disk, (float, int)):
            check_ok("Disco livre", f"({free_disk:.2f} GB)")

        engines = doc_report.get("engines", {})
        ocr_engines = []
        if engines.get("rapidocr"):
            ocr_engines.append("RapidOCR")
        if engines.get("tesseract"):
            ocr_engines.append("Tesseract")
        if engines.get("ocrmac"):
            ocr_engines.append("ocrmac")
        if ocr_engines:
            check_ok("Motores OCR detectados", f"({', '.join(ocr_engines)})")
        else:
            check_info(
                "OCR local sob demanda",
                "(RapidOCR é auto-instalado na 1ª análise de imagem)",
            )

        if engines.get("florence"):
            check_ok("Florence-2 (VLM local)", "(documents-vision)")
        else:
            check_info("Florence-2 não instalado — opcional: pip install 'ector-agent[documents-vision]'")

        for hint in doc_report.get("install_hints", [])[:2]:
            check_info(hint)
    except Exception as e:
        check_warn("Falha ao diagnosticar stack de documentos", f"({e})")
    
    # =========================================================================
    # Check: Configuration files
    # =========================================================================
    print()
    print(color("◆ Arquivos de Configuração", Colors.CYAN, Colors.BOLD))
    
    # Check ~/.ector/.env (primary location for user config)
    env_path = ECTOR_HOME / '.env'
    if env_path.exists():
        check_ok(f"Arquivo {_DHH}/.env existe")
        
        # Check for common issues
        content, read_error = _read_text_with_fallback(env_path)
        if content is None:
            check_warn(f"Não foi possível ler {_DHH}/.env", f"({read_error})")
            issues.append(f"Corrija o encoding/permissões de {_DHH}/.env para o diagnóstico funcionar")
        elif _has_provider_env_config(content):
            check_ok("Chave API ou endpoint personalizado configurado")
        else:
            check_warn(f"Nenhuma chave API encontrada em {_DHH}/.env")
            issues.append("Execute 'ector setup' para configurar as chaves API")
    else:
        # Also check project root as fallback
        fallback_env = PROJECT_ROOT / '.env'
        if fallback_env.exists():
            check_ok("Arquivo .env existe (no diretório do projeto)")
        else:
            check_fail(f"Arquivo {_DHH}/.env ausente")
            if should_fix:
                env_path.parent.mkdir(parents=True, exist_ok=True)
                env_path.touch()
                check_ok(f"Criou {_DHH}/.env vazio")
                check_info("Execute 'ector setup' para configurar as chaves API")
                fixed_count += 1
            else:
                check_info("Execute 'ector setup' para criar um")
                issues.append("Execute 'ector setup' para criar o .env")
    
    # Check ~/.ector/config.yaml (primary) or project cli-config.yaml (fallback)
    config_path = ECTOR_HOME / 'config.yaml'
    if config_path.exists():
        check_ok(f"Arquivo {_DHH}/config.yaml existe")

        # Validate model.provider and model.default values
        try:
            import yaml as _yaml
            cfg = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            model_section = cfg.get("model") or {}
            provider_raw = (model_section.get("provider") or "").strip()
            provider = provider_raw.lower()
            default_model = (model_section.get("default") or model_section.get("model") or "").strip()

            known_providers: set = set()
            try:
                from ector_cli.auth import PROVIDER_REGISTRY
                known_providers = set(PROVIDER_REGISTRY.keys()) | {"openrouter", "custom", "auto"}
            except Exception:
                pass
            try:
                from ector_cli.config import get_compatible_custom_providers as _compatible_custom_providers
                from ector_cli.providers import resolve_provider_full as _resolve_provider_full
            except Exception:
                _compatible_custom_providers = None
                _resolve_provider_full = None

            custom_providers = []
            if _compatible_custom_providers is not None:
                try:
                    custom_providers = _compatible_custom_providers(cfg)
                except Exception:
                    custom_providers = []

            user_providers = cfg.get("providers")
            if isinstance(user_providers, dict):
                known_providers.update(str(name).strip().lower() for name in user_providers if str(name).strip())
            for entry in custom_providers:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                if name:
                    known_providers.add("custom:" + name.lower().replace(" ", "-"))

            canonical_provider = provider
            if (
                provider
                and _resolve_provider_full is not None
                and provider not in ("auto", "custom")
            ):
                provider_def = _resolve_provider_full(provider, user_providers, custom_providers)
                canonical_provider = provider_def.id if provider_def is not None else None

            if provider and provider != "auto":
                if canonical_provider is None or (known_providers and canonical_provider not in known_providers):
                    known_list = ", ".join(sorted(known_providers)) if known_providers else "(indisponível)"
                    check_fail(
                        f"model.provider '{provider_raw}' não é um provedor reconhecido",
                        f"(conhecidos: {known_list})",
                    )
                    issues.append(
                        f"model.provider '{provider_raw}' é desconhecido. "
                        f"Provedores válidos: {known_list}. "
                        f"Correção: execute 'ector provider' ou edite model.provider em config.yaml"
                    )

            # Warn if model is set to a provider-prefixed name on a provider that doesn't use them
            if default_model and "/" in default_model and canonical_provider and canonical_provider not in ("openrouter", "custom", "auto", "ai-gateway", "kilocode", "huggingface", "ector"):
                check_warn(
                    f"model.default '{default_model}' usa um slug vendor/model, mas o provedor é '{provider_raw}'",
                    "(slugs com prefixo de vendor pertencem a agregadores como openrouter)",
                )
                issues.append(
                    f"model.default '{default_model}' tem prefixo de vendor, mas model.provider é '{provider_raw}'. "
                    "Ou defina model.provider como 'openrouter', ou remova o prefixo de vendor."
                )

            # Check credentials for the configured provider.
            # Limit to API-key providers in PROVIDER_REGISTRY — other provider
            # types (OAuth, SDK, openrouter/anthropic/custom/auto) have their
            # own env-var checks elsewhere in doctor, and get_auth_status()
            # returns a bare {logged_in: False} for anything it doesn't
            # explicitly dispatch, which would produce false positives.
            if canonical_provider and canonical_provider not in ("auto", "custom", "openrouter"):
                try:
                    from ector_cli.auth import PROVIDER_REGISTRY, get_auth_status
                    pconfig = PROVIDER_REGISTRY.get(canonical_provider)
                    if pconfig and getattr(pconfig, "auth_type", "") == "api_key":
                        status = get_auth_status(canonical_provider) or {}
                        configured = bool(status.get("configured") or status.get("logged_in") or status.get("api_key"))
                        if not configured:
                            check_fail(
                                f"model.provider '{canonical_provider}' está definido, mas nenhuma chave API está configurada",
                                "(verifique ~/.ector/.env ou execute 'ector setup')",
                            )
                            issues.append(
                                f"Nenhuma credencial encontrada para o provedor '{canonical_provider}'. "
                                f"Execute 'ector setup' ou defina a chave API do provedor em {_DHH}/.env, "
                                f"ou mude de provedor com 'ector provider'"
                            )
                except Exception:
                    pass

        except Exception as e:
            check_warn("Não foi possível validar a configuração de modelo/provedor", f"({e})")
    else:
        fallback_config = PROJECT_ROOT / 'cli-config.yaml'
        if fallback_config.exists():
            check_ok("Arquivo cli-config.yaml existe (no diretório do projeto)")
        else:
            example_config = PROJECT_ROOT / 'cli-config.yaml.example'
            if should_fix and example_config.exists():
                config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(example_config), str(config_path))
                check_ok(f"Criou {_DHH}/config.yaml a partir de cli-config.yaml.example")
                fixed_count += 1
            elif should_fix:
                check_warn("config.yaml não encontrado e não há exemplo para copiar")
                manual_issues.append(f"Crie {_DHH}/config.yaml manualmente")
            else:
                check_warn("config.yaml não encontrado", "(usando padrões)")

    # Check config version and stale keys
    config_path = ECTOR_HOME / 'config.yaml'
    if config_path.exists():
        try:
            from ector_cli.config import check_config_version, migrate_config
            current_ver, latest_ver = check_config_version()
            if current_ver < latest_ver:
                check_warn(
                    f"Versão da configuração desatualizada (v{current_ver} → v{latest_ver})",
                    "(novas configurações disponíveis)"
                )
                if should_fix:
                    try:
                        migrate_config(interactive=False, quiet=False)
                        check_ok("Configuração migrada para a versão mais recente")
                        fixed_count += 1
                    except Exception as mig_err:
                        check_warn(f"Migração automática falhou: {mig_err}")
                        issues.append("Execute 'ector setup' para migrar a configuração")
                else:
                    issues.append("Execute 'ector doctor --fix' ou 'ector setup' para migrar a configuração")
            else:
                check_ok(f"Versão da configuração atualizada (v{current_ver})")
        except Exception:
            pass

        # Detect stale root-level model keys (known bug source — PR #4329)
        try:
            import yaml
            with open(config_path) as f:
                raw_config = yaml.safe_load(f) or {}
            stale_root_keys = [k for k in ("provider", "base_url") if k in raw_config and isinstance(raw_config[k], str)]
            if stale_root_keys:
                check_warn(
                    f"Chaves de configuração obsoletas na raiz: {', '.join(stale_root_keys)}",
                    "(devem estar sob a seção 'model:')"
                )
                if should_fix:
                    model_section = raw_config.setdefault("model", {})
                    for k in stale_root_keys:
                        if not model_section.get(k):
                            model_section[k] = raw_config.pop(k)
                        else:
                            raw_config.pop(k)
                    from utils import atomic_yaml_write
                    atomic_yaml_write(config_path, raw_config)
                    check_ok("Migrou chaves obsoletas na raiz para a seção model")
                    fixed_count += 1
                else:
                    issues.append("Chaves provider/base_url obsoletas na raiz do config.yaml — execute 'ector doctor --fix'")
        except Exception:
            pass

        # Validate config structure (catches malformed custom_providers, etc.)
        try:
            from ector_cli.config import validate_config_structure
            config_issues = validate_config_structure()
            if config_issues:
                print()
                print(color("◆ Estrutura do Config", Colors.CYAN, Colors.BOLD))
                for ci in config_issues:
                    if ci.severity == "error":
                        check_fail(ci.message)
                    else:
                        check_warn(ci.message)
                    # Show the hint indented
                    for hint_line in ci.hint.splitlines():
                        check_info(hint_line)
                    issues.append(ci.message)
        except Exception:
            pass

        # Deprecated cwd env vars (MESSAGING_CWD / TERMINAL_CWD in .env)
        try:
            from ector_cli.config import load_config

            _cfg_for_cwd = load_config()
            _messaging_cwd = os.environ.get("MESSAGING_CWD")
            _terminal_cwd = os.environ.get("TERMINAL_CWD")
            _terminal_cfg = _cfg_for_cwd.get("terminal") or {}
            _config_cwd = (
                _terminal_cfg.get("cwd", ".") if isinstance(_terminal_cfg, dict) else "."
            )
            _config_has_explicit_cwd = _config_cwd not in (".", "auto", "cwd", "")
            if _messaging_cwd:
                check_warn(
                    "MESSAGING_CWD no .env está obsoleto",
                    "(use terminal.cwd em config.yaml)",
                )
                issues.append(
                    f"Migre MESSAGING_CWD para terminal.cwd em {_DHH}/config.yaml"
                )
            if _terminal_cwd and not _config_has_explicit_cwd:
                check_warn(
                    "TERMINAL_CWD no .env está obsoleto",
                    "(use terminal.cwd em config.yaml)",
                )
                issues.append(
                    f"Migre TERMINAL_CWD para terminal.cwd em {_DHH}/config.yaml"
                )
        except Exception:
            pass

    # =========================================================================
    # Check: Auth providers
    # =========================================================================
    print()
    print(color("◆ Provedores de Autenticação", Colors.CYAN, Colors.BOLD))

    try:
        from ector_cli import identity_auth
        from ector_cli.auth import (
            get_codex_auth_status,
            get_gemini_oauth_auth_status,
        )

        if identity_auth.is_logged_in():
            check_ok("Identidade Ector (ector.cc)", "(logado)")
        else:
            check_warn("Identidade Ector (ector.cc)", "(não logado — execute: ector login)")

        codex_status = get_codex_auth_status()
        if codex_status.get("logged_in"):
            check_ok("Autenticação OpenAI Codex", "(logado)")
        else:
            check_warn("Autenticação OpenAI Codex", "(não logado)")
            if codex_status.get("error"):
                check_info(codex_status["error"])

        gemini_status = get_gemini_oauth_auth_status()
        if gemini_status.get("logged_in"):
            email = gemini_status.get("email") or ""
            project = gemini_status.get("project_id") or ""
            pieces = []
            if email:
                pieces.append(email)
            if project:
                pieces.append(f"project={project}")
            suffix = f" ({', '.join(pieces)})" if pieces else ""
            check_ok("Google Gemini OAuth", f"(logado{suffix})")
        else:
            check_warn("Google Gemini OAuth", "(não logado)")
    except Exception as e:
        check_warn("Status do provedor de auth", f"(não foi possível verificar: {e})")

    if shutil.which("codex"):
        check_ok("CLI codex")
    else:
        check_warn("CLI codex não encontrado", "(necessário para login openai-codex)")

    # =========================================================================
    # Check: Directory structure
    # =========================================================================
    print()
    print(color("◆ Estrutura de Diretórios", Colors.CYAN, Colors.BOLD))
    
    ector_home = ECTOR_HOME
    if ector_home.exists():
        check_ok(f"Diretório {_DHH} existe")
    else:
        if should_fix:
            ector_home.mkdir(parents=True, exist_ok=True)
            check_ok(f"Criou o diretório {_DHH}")
            fixed_count += 1
        else:
            check_warn(f"{_DHH} não encontrado", "(será criado no primeiro uso)")
    
    # Check expected subdirectories
    expected_subdirs = ["cron", "sessions", "logs", "skills", "memories"]
    for subdir_name in expected_subdirs:
        subdir_path = ector_home / subdir_name
        if subdir_path.exists():
            check_ok(f"Diretório {_DHH}/{subdir_name}/ existe")
        else:
            if should_fix:
                subdir_path.mkdir(parents=True, exist_ok=True)
                check_ok(f"Criou o diretório {_DHH}/{subdir_name}/")
                fixed_count += 1
            else:
                check_warn(f"Diretório {_DHH}/{subdir_name}/ não encontrado", "(será criado no primeiro uso)")
    
    # Check for SOUL.md persona file
    soul_path = ector_home / "SOUL.md"
    if soul_path.exists():
        content = soul_path.read_text(encoding="utf-8").strip()
        # Check if it's just the template comments (no real content)
        lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith(("<!--", "-->", "#"))]
        if lines:
            check_ok(f"{_DHH}/SOUL.md existe (persona configurada)")
        else:
            check_info(f"{_DHH}/SOUL.md existe mas está vazio — edite-o para personalizar a personalidade")
    else:
        check_warn(f"{_DHH}/SOUL.md não encontrado", "(crie-o para dar ao Ector uma personalidade personalizada)")
        if should_fix:
            soul_path.parent.mkdir(parents=True, exist_ok=True)
            soul_path.write_text(
                "# Persona do Agente Ector\n\n"
                "<!-- Edite este arquivo para personalizar como o Ector se comunica. -->\n\n"
                "Você é o Ector, um assistente de IA prestativo.\n",
                encoding="utf-8",
            )
            check_ok(f"Criou {_DHH}/SOUL.md com template básico")
            fixed_count += 1
    
    # Check memory directory
    memories_dir = ector_home / "memories"
    if memories_dir.exists():
        check_ok(f"Diretório {_DHH}/memories/ existe")
        memory_file = memories_dir / "MEMORY.md"
        user_file = memories_dir / "USER.md"
        if memory_file.exists():
            size = len(memory_file.read_text(encoding="utf-8").strip())
            check_ok(f"MEMORY.md existe ({size} caracteres)")
        else:
            check_info("MEMORY.md ainda não foi criado (será criado quando o agente escrever a primeira memória)")
        if user_file.exists():
            size = len(user_file.read_text(encoding="utf-8").strip())
            check_ok(f"USER.md existe ({size} caracteres)")
        else:
            check_info("USER.md ainda não foi criado (será criado quando o agente escrever a primeira memória)")
    else:
        check_warn(f"{_DHH}/memories/ não encontrado", "(será criado no primeiro uso)")
        if should_fix:
            memories_dir.mkdir(parents=True, exist_ok=True)
            check_ok(f"Criou {_DHH}/memories/")
            fixed_count += 1
    
    # Check SQLite session store
    state_db_path = ector_home / "state.db"
    if state_db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(state_db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            count = cursor.fetchone()[0]
            conn.close()
            check_ok(f"{_DHH}/state.db existe ({count} sessões)")
        except Exception as e:
            check_warn(f"{_DHH}/state.db existe mas tem problemas: {e}")
    else:
        check_info(f"{_DHH}/state.db ainda não foi criado (será criado na primeira sessão)")

    # Check WAL file size (unbounded growth indicates missed checkpoints)
    wal_path = ector_home / "state.db-wal"
    if wal_path.exists():
        try:
            wal_size = wal_path.stat().st_size
            if wal_size > 50 * 1024 * 1024:  # 50 MB
                check_warn(
                    f"Arquivo WAL é grande ({wal_size // (1024*1024)} MB)",
                    "(pode indicar falta de checkpoints)"
                )
                if should_fix:
                    if state_db_path.exists() and state_db_path.is_file():
                        import sqlite3
                        conn = sqlite3.connect(str(state_db_path))
                        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                        conn.close()
                        new_size = wal_path.stat().st_size if wal_path.exists() else 0
                        check_ok(f"Checkpoint WAL realizado ({wal_size // 1024}K → {new_size // 1024}K)")
                        fixed_count += 1
                    else:
                        check_warn(
                            "WAL presente sem state.db correspondente",
                            "(checkpoint automático ignorado para evitar criar um novo banco vazio)"
                        )
                        manual_issues.append(
                            f"Inconsistência no store SQLite ({_DHH}/state.db-wal sem state.db) — faça backup e recrie o store com segurança"
                        )
                else:
                    issues.append("Arquivo WAL grande — execute 'ector doctor --fix' para realizar o checkpoint")
            elif wal_size > 10 * 1024 * 1024:  # 10 MB
                check_info(f"Arquivo WAL tem {wal_size // (1024*1024)} MB (normal para sessões ativas)")
        except Exception:
            pass

    _check_gateway_and_channels(issues, manual_issues)

    # =========================================================================
    # Check: Command installation (ector bin symlink)
    # =========================================================================
    if sys.platform != "win32":
        print()
        print(color("◆ Instalação do Comando", Colors.CYAN, Colors.BOLD))

        # Determine the venv entry point location
        _venv_bin = None
        for _venv_name in ("venv", ".venv"):
            _candidate = PROJECT_ROOT / _venv_name / "bin" / "ector"
            if _candidate.exists():
                _venv_bin = _candidate
                break

        # Determine the expected command link directory (mirrors install.sh logic)
        _prefix = os.environ.get("PREFIX", "")
        _is_termux_env = bool(os.environ.get("TERMUX_VERSION")) or "com.termux/files/usr" in _prefix
        if _is_termux_env and _prefix:
            _cmd_link_dir = Path(_prefix) / "bin"
            _cmd_link_display = "$PREFIX/bin"
        else:
            _cmd_link_dir = Path.home() / ".local" / "bin"
            _cmd_link_display = "~/.local/bin"
        _cmd_link = _cmd_link_dir / "ector"

        if _venv_bin is None:
            check_warn(
                "Ponto de entrada do venv não encontrado",
                "(ector não está em venv/bin/ ou .venv/bin/ — reinstale com pip install -e '.[all]')"
            )
            manual_issues.append(
                f"Reinstale o ponto de entrada: cd {PROJECT_ROOT} && source venv/bin/activate && pip install -e '.[all]'"
            )
        else:
            check_ok(f"Ponto de entrada do venv existe ({_venv_bin.relative_to(PROJECT_ROOT)})")

            # Check the symlink at the command link location
            if _cmd_link.is_symlink():
                _target = _cmd_link.resolve()
                _expected = _venv_bin.resolve()
                if _target == _expected:
                    check_ok(f"{_cmd_link_display}/ector → destino correto")
                else:
                    check_warn(
                        f"{_cmd_link_display}/ector aponta para o destino errado",
                        f"(→ {_target}, esperado → {_expected})"
                    )
                    if should_fix:
                        _cmd_link.unlink()
                        _cmd_link.symlink_to(_venv_bin)
                        check_ok(f"Symlink corrigido: {_cmd_link_display}/ector → {_venv_bin}")
                        fixed_count += 1
                    else:
                        issues.append(f"Symlink quebrado em {_cmd_link_display}/ector — execute 'ector doctor --fix'")
            elif _cmd_link.exists():
                # It's a regular file, not a symlink — possibly a wrapper script
                if _is_valid_command_wrapper(_cmd_link):
                    check_ok(f"{_cmd_link_display}/ector existe (wrapper executável não-symlink)")
                else:
                    check_warn(
                        f"{_cmd_link_display}/ector existe, mas não parece um wrapper executável válido",
                        "(não será sobrescrito automaticamente)"
                    )
                    issues.append(
                        f"Valide/reinstale {_cmd_link_display}/ector para apontar ao entrypoint correto "
                        f"(esperado: {_venv_bin})"
                    )
            else:
                check_fail(
                    f"{_cmd_link_display}/ector não encontrado",
                    "(o comando ector pode não funcionar fora do venv)"
                )
                if should_fix:
                    _cmd_link_dir.mkdir(parents=True, exist_ok=True)
                    _cmd_link.symlink_to(_venv_bin)
                    check_ok(f"Criou symlink: {_cmd_link_display}/ector → {_venv_bin}")
                    fixed_count += 1

                    # Check if the link dir is on PATH
                    _path_dirs = os.environ.get("PATH", "").split(os.pathsep)
                    if str(_cmd_link_dir) not in _path_dirs:
                        check_warn(
                            f"{_cmd_link_display} não está no seu PATH",
                            "(adicione-o à configuração do seu shell: export PATH=\"$HOME/.local/bin:$PATH\")"
                        )
                        manual_issues.append(f"Adicione {_cmd_link_display} ao seu PATH")
                else:
                    issues.append(f"Symlink {_cmd_link_display}/ector ausente — execute 'ector doctor --fix'")

    # =========================================================================
    # Check: External tools
    # =========================================================================
    print()
    print(color("◆ Ferramentas Externas", Colors.CYAN, Colors.BOLD))
    
    # Git
    if shutil.which("git"):
        check_ok("git")
    else:
        check_warn("git não encontrado", "(opcional)")
    
    # ripgrep (optional, for faster file search)
    if shutil.which("rg"):
        check_ok("ripgrep (rg)", "(busca de arquivos mais rápida)")
    else:
        check_warn("ripgrep (rg) não encontrado", "(a busca de arquivos usa o fallback grep)")
        check_info(f"Instale para uma busca mais rápida: {_system_package_install_cmd('ripgrep')}")
    
    # Docker (optional)
    terminal_env = _effective_terminal_backend()
    if terminal_env == "docker":
        if shutil.which("docker"):
            # Check if docker daemon is running
            try:
                result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                check_ok("docker", "(daemon em execução)")
            else:
                check_fail("daemon do docker não está em execução")
                issues.append("Inicie o daemon do Docker")
        else:
            check_fail("docker não encontrado", "(necessário para TERMINAL_ENV=docker)")
            issues.append("Instale o Docker ou mude TERMINAL_ENV")
    else:
        if shutil.which("docker"):
            check_ok("docker", "(opcional)")
        else:
            if _is_termux():
                check_info("O backend Docker não está disponível dentro do Termux (esperado no Android)")
            else:
                check_warn("docker não encontrado", "(opcional)")
    
    # SSH (if using ssh backend)
    if terminal_env == "ssh":
        from ector_cli.config import get_env_value

        ssh_host = get_env_value("TERMINAL_SSH_HOST") or os.getenv("TERMINAL_SSH_HOST")
        if ssh_host:
            # Try to connect
            try:
                result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", ssh_host, "echo ok"],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                check_ok(f"Conexão SSH para {ssh_host}")
            else:
                check_fail(f"Conexão SSH para {ssh_host}")
                issues.append(f"Verifique a configuração SSH para {ssh_host}")
        else:
            check_fail("TERMINAL_SSH_HOST não definido", "(necessário para TERMINAL_ENV=ssh)")
            issues.append("Defina TERMINAL_SSH_HOST no .env")
    
    # Daytona (if using daytona backend)
    if terminal_env == "daytona":
        daytona_key = os.getenv("DAYTONA_API_KEY")
        if daytona_key:
            check_ok("Chave API Daytona", "(configurada)")
        else:
            check_fail("DAYTONA_API_KEY não definida", "(necessário para TERMINAL_ENV=daytona)")
            issues.append("Defina a variável de ambiente DAYTONA_API_KEY")
        try:
            from daytona import Daytona  # noqa: F401 — SDK presence check
            check_ok("SDK daytona", "(instalado)")
        except ImportError:
            check_fail("SDK daytona não instalado", "(pip install daytona)")
            issues.append("Instale o SDK daytona: pip install daytona")

    # Node.js + agent-browser (for browser automation tools)
    if shutil.which("node"):
        check_ok("Node.js")
        # Check if agent-browser is installed
        agent_browser_path = PROJECT_ROOT / "node_modules" / "agent-browser"
        if agent_browser_path.exists():
            check_ok("agent-browser (Node.js)", "(automação de navegador)")
        else:
            if _is_termux():
                check_info("agent-browser não está instalado (esperado no caminho do Termux testado)")
                check_info("Instale-o manualmente depois com: npm install -g agent-browser && agent-browser install")
                check_info("Configuração do navegador Termux:")
                for step in _termux_browser_setup_steps(node_installed=True):
                    check_info(step)
            else:
                check_warn("agent-browser não instalado", "(execute: npm install)")
    else:
        if _is_termux():
            check_info("Node.js não encontrado (ferramentas de navegador são opcionais no caminho do Termux testado)")
            check_info("Instale o Node.js no Termux com: pkg install nodejs")
            check_info("Configuração do navegador Termux:")
            for step in _termux_browser_setup_steps(node_installed=False):
                check_info(step)
        else:
            check_warn("Node.js não encontrado", "(opcional, necessário para ferramentas de navegador)")
    
    # npm audit for all Node.js packages
    if shutil.which("npm"):
        npm_dirs = [
            (PROJECT_ROOT, "Ferramentas de navegador (agent-browser)"),
            (PROJECT_ROOT / "scripts" / "whatsapp-bridge", "Ponte WhatsApp"),
        ]
        for npm_dir, label in npm_dirs:
            if not (npm_dir / "node_modules").exists():
                continue
            try:
                audit_result = subprocess.run(
                    ["npm", "audit", "--json"],
                    cwd=str(npm_dir),
                    capture_output=True, text=True, timeout=30,
                )
                import json as _json
                audit_data = _json.loads(audit_result.stdout) if audit_result.stdout.strip() else {}
                vuln_count = audit_data.get("metadata", {}).get("vulnerabilities", {})
                critical = vuln_count.get("critical", 0)
                high = vuln_count.get("high", 0)
                moderate = vuln_count.get("moderate", 0)
                total = critical + high + moderate
                if total == 0:
                    check_ok(f"Deps {label}", "(nenhuma vulnerabilidade conhecida)")
                elif critical > 0 or high > 0:
                    check_warn(
                        f"Deps {label}",
                        f"({critical} críticas, {high} altas, {moderate} moderadas — execute: cd {npm_dir} && npm audit fix)"
                    )
                    issues.append(f"{label} tem {total} vulnerabilidade(s) npm")
                else:
                    check_ok(f"Deps {label}", f"({moderate} vulnerabilidade(s) moderada(s))")
            except Exception:
                pass

    # =========================================================================
    # Check: API connectivity
    # =========================================================================
    print()
    print(color("◆ Conectividade da API", Colors.CYAN, Colors.BOLD))
    
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        print("  Verificando API OpenRouter...", end="", flush=True)
        try:
            import httpx
            response = httpx.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {openrouter_key}"},
                timeout=10
            )
            if response.status_code == 200:
                print(f"\r  {color('✔', Colors.GREEN)} OpenRouter API                          ")
            elif response.status_code == 401:
                print(f"\r  {color('✖', Colors.RED)} API OpenRouter {color('(chave API inválida)', Colors.DIM)}                ")
                issues.append("Verifique OPENROUTER_API_KEY no .env")
            elif response.status_code == 402:
                print(f"\r  {color('✖', Colors.RED)} API OpenRouter {color('(sem créditos — pagamento necessário)', Colors.DIM)}")
                issues.append(
                    "A conta OpenRouter possui créditos insuficientes. "
                    "Correção: execute 'ector provider' para mudar de provedor, "
                    "ou adicione fundos à sua conta OpenRouter em https://openrouter.ai/settings/credits"
                )
            elif response.status_code == 429:
                print(f"\r  {color('✖', Colors.RED)} API OpenRouter {color('(limite de taxa atingido)', Colors.DIM)}                ")
                issues.append("Limite de taxa da OpenRouter atingido — considere mudar para um provedor diferente ou aguardar")
            else:
                print(f"\r  {color('✖', Colors.RED)} API OpenRouter {color(f'(HTTP {response.status_code})', Colors.DIM)}                ")
        except Exception as e:
            print(f"\r  {color('✖', Colors.RED)} API OpenRouter {color(f'({e})', Colors.DIM)}                ")
            issues.append("Verifique a conectividade de rede")
    else:
        check_warn("API OpenRouter", "(não configurada)")
    
    from ector_cli.auth import get_anthropic_key
    anthropic_key = get_anthropic_key()
    if anthropic_key:
        print("  Verificando API Anthropic...", end="", flush=True)
        try:
            import httpx
            from agent.anthropic_adapter import _is_oauth_token, _COMMON_BETAS, _OAUTH_ONLY_BETAS

            headers = {"anthropic-version": "2023-06-01"}
            if _is_oauth_token(anthropic_key):
                headers["Authorization"] = f"Bearer {anthropic_key}"
                headers["anthropic-beta"] = ",".join(_COMMON_BETAS + _OAUTH_ONLY_BETAS)
            else:
                headers["x-api-key"] = anthropic_key
            response = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers=headers,
                timeout=10
            )
            if response.status_code == 200:
                print(f"\r  {color('✔', Colors.GREEN)} API Anthropic                           ")
            elif response.status_code == 401:
                print(f"\r  {color('✖', Colors.RED)} API Anthropic {color('(chave API inválida)', Colors.DIM)}                 ")
            else:
                msg = "(não foi possível verificar)"
                print(f"\r  {color('▲', Colors.YELLOW)} API Anthropic {color(msg, Colors.DIM)}                 ")
        except Exception as e:
            print(f"\r  {color('▲', Colors.YELLOW)} API Anthropic {color(f'({e})', Colors.DIM)}                 ")

    # -- API-key providers --
    # Tuple: (name, env_vars, default_url, base_env, supports_models_endpoint)
    # If supports_models_endpoint is False, we skip the health check and just show "configured"
    _apikey_providers = [
        ("Z.AI / GLM",      ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY", "ZHIPU_API_KEY"), "https://api.z.ai/api/paas/v4/models", "GLM_BASE_URL", True),
        ("Kimi / Moonshot",  ("KIMI_API_KEY",),                              "https://api.moonshot.ai/v1/models",   "KIMI_BASE_URL", True),
        ("StepFun Step Plan",   ("STEPFUN_API_KEY",),                           "https://api.stepfun.ai/step_plan/v1/models", "STEPFUN_BASE_URL", True),
        ("Kimi / Moonshot (China)", ("KIMI_CN_API_KEY",),                    "https://api.moonshot.cn/v1/models",   None, True),
        ("Arcee AI",         ("ARCEEAI_API_KEY",),                            "https://api.arcee.ai/api/v1/models",  "ARCEE_BASE_URL", True),
        ("DeepSeek",         ("DEEPSEEK_API_KEY",),                           "https://api.deepseek.com/v1/models",  "DEEPSEEK_BASE_URL", True),
        ("Hugging Face",     ("HF_TOKEN",),                                   "https://router.huggingface.co/v1/models", "HF_BASE_URL", True),
        ("NVIDIA NIM",       ("NVIDIA_API_KEY",),                             "https://integrate.api.nvidia.com/v1/models", "NVIDIA_BASE_URL", True),
        ("Alibaba/DashScope", ("DASHSCOPE_API_KEY",),                         "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models", "DASHSCOPE_BASE_URL", True),
        # MiniMax: the /anthropic endpoint doesn't support /models, but the /v1 endpoint does.
        ("MiniMax",          ("MINIMAX_API_KEY",),                            "https://api.minimax.io/v1/models",    "MINIMAX_BASE_URL", True),
        ("MiniMax (China)",  ("MINIMAX_CN_API_KEY",),                         "https://api.minimaxi.com/v1/models",  "MINIMAX_CN_BASE_URL", True),
        ("Vercel AI Gateway",       ("AI_GATEWAY_API_KEY",),                          "https://ai-gateway.vercel.sh/v1/models", "AI_GATEWAY_BASE_URL", True),
        ("Kilo Code",        ("KILOCODE_API_KEY",),                            "https://api.kilo.ai/api/gateway/models",  "KILOCODE_BASE_URL", True),
    ]
    for _pname, _env_vars, _default_url, _base_env, _supports_health_check in _apikey_providers:
        _key = ""
        for _ev in _env_vars:
            _key = os.getenv(_ev, "")
            if _key:
                break
        if _key:
            _label = _pname.ljust(20)
            # Some providers (like MiniMax) don't support /models endpoint
            if not _supports_health_check:
                print(f"  {color('✔', Colors.GREEN)} {_label} {color('(chave configurada)', Colors.DIM)}")
                continue
            print(f"  Verificando API {_pname}...", end="", flush=True)
            try:
                import httpx
                _base = os.getenv(_base_env, "") if _base_env else ""
                # Auto-detect Kimi Code keys (sk-kimi-) → api.kimi.com/coding/v1
                # (OpenAI-compat surface, which exposes /models for health check).
                if not _base and _key.startswith("sk-kimi-"):
                    _base = "https://api.kimi.com/coding/v1"
                # Anthropic-compat endpoints (/anthropic, api.kimi.com/coding
                # with no /v1) don't support /models.  Rewrite to the OpenAI-compat
                # /v1 surface for health checks.
                if _base and _base.rstrip("/").endswith("/anthropic"):
                    from agent.auxiliary_client import _to_openai_base_url
                    _base = _to_openai_base_url(_base)
                if base_url_host_matches(_base, "api.kimi.com") and _base.rstrip("/").endswith("/coding"):
                    _base = _base.rstrip("/") + "/v1"
                _url = (_base.rstrip("/") + "/models") if _base else _default_url
                _headers = {
                    "Authorization": f"Bearer {_key}",
                    "User-Agent": _ECTOR_USER_AGENT,
                }
                if base_url_host_matches(_base, "api.kimi.com"):
                    _headers["User-Agent"] = "claude-code/0.1.0"
                _resp = httpx.get(
                    _url,
                    headers=_headers,
                    timeout=10,
                )
                if _resp.status_code == 200:
                    print(f"\r  {color('✔', Colors.GREEN)} {_label}                          ")
                elif _resp.status_code == 401:
                    print(f"\r  {color('✖', Colors.RED)} {_label} {color('(chave API inválida)', Colors.DIM)}           ")
                    issues.append(f"Verifique {_env_vars[0]} no .env")
                else:
                    print(f"\r  {color('▲', Colors.YELLOW)} {_label} {color(f'(HTTP {_resp.status_code})', Colors.DIM)}           ")
            except Exception as _e:
                print(f"\r  {color('▲', Colors.YELLOW)} {_label} {color(f'({_e})', Colors.DIM)}           ")

    # -- AWS Bedrock --
    # Bedrock uses the AWS SDK credential chain, not API keys.
    try:
        from agent.bedrock_adapter import has_aws_credentials, resolve_aws_auth_env_var, resolve_bedrock_region
        if has_aws_credentials():
            _auth_var = resolve_aws_auth_env_var()
            _region = resolve_bedrock_region()
            _label = "AWS Bedrock".ljust(20)
            print(f"  Verificando AWS Bedrock...", end="", flush=True)
            try:
                import boto3
                _br_client = boto3.client("bedrock", region_name=_region)
                _br_resp = _br_client.list_foundation_models()
                _model_count = len(_br_resp.get("modelSummaries", []))
                print(f"\r  {color('✔', Colors.GREEN)} {_label} {color(f'({_auth_var}, {_region}, {_model_count} modelos)', Colors.DIM)}           ")
            except ImportError:
                print(f"\r  {color('▲', Colors.YELLOW)} {_label} {color(f'(boto3 não instalado — {sys.executable} -m pip install boto3)', Colors.DIM)}           ")
                issues.append(f"Instale boto3 para Bedrock: {sys.executable} -m pip install boto3")
            except Exception as _e:
                _err_name = type(_e).__name__
                print(f"\r  {color('▲', Colors.YELLOW)} {_label} {color(f'({_err_name}: {_e})', Colors.DIM)}           ")
                issues.append(f"AWS Bedrock: {_err_name} — verifique as permissões IAM para bedrock:ListFoundationModels")
    except ImportError:
        pass  # bedrock_adapter not available — skip silently

    # =========================================================================
    # Check: Submodules
    # =========================================================================
    print()
    print(color("◆ Submódulos", Colors.CYAN, Colors.BOLD))
    
    # tinker-atropos (RL training backend)
    tinker_dir = PROJECT_ROOT / "tinker-atropos"
    if tinker_dir.exists() and (tinker_dir / "pyproject.toml").exists():
        if py_version >= (3, 11):
            try:
                __import__("tinker_atropos")
                check_ok("tinker-atropos", "(backend de treinamento RL)")
            except ImportError:
                install_cmd = f"{_python_install_cmd()} -e ./tinker-atropos"
                check_warn("tinker-atropos encontrado, mas não instalado", f"(execute: {install_cmd})")
                issues.append(f"Instale tinker-atropos: {install_cmd}")
        else:
            check_warn("tinker-atropos requer Python 3.11+", f"(atual: {py_version.major}.{py_version.minor})")
    else:
        check_warn("tinker-atropos não encontrado", "(execute: git submodule update --init --recursive)")
    
    # =========================================================================
    # Check: Tool Availability
    # =========================================================================
    print()
    print(color("◆ Disponibilidade de Ferramentas", Colors.CYAN, Colors.BOLD))
    
    try:
        # Add project root to path for imports
        sys.path.insert(0, str(PROJECT_ROOT))
        from model_tools import check_tool_availability, TOOLSET_REQUIREMENTS
        
        available, unavailable = check_tool_availability()
        
        for tid in available:
            info = TOOLSET_REQUIREMENTS.get(tid, {})
            check_ok(info.get("name", tid))
        
        for item in unavailable:
            env_vars = item.get("missing_vars") or item.get("env_vars") or []
            if env_vars:
                vars_str = ", ".join(env_vars)
                check_warn(item["name"], f"(faltando {vars_str})")
            else:
                check_warn(item["name"], "(dependência do sistema não atendida)")

        # Count disabled tools with API key requirements
        api_disabled = [u for u in unavailable if (u.get("missing_vars") or u.get("env_vars"))]
        if api_disabled:
            issues.append("Execute 'ector setup' para configurar as chaves API ausentes para acesso total às ferramentas")
    except Exception as e:
        check_warn("Não foi possível verificar a disponibilidade das ferramentas", f"({e})")
    
    # =========================================================================
    # Check: Skills Hub
    # =========================================================================
    print()
    print(color("◆ Skills Hub", Colors.CYAN, Colors.BOLD))

    hub_dir = ECTOR_HOME / "skills" / ".hub"
    if hub_dir.exists():
        check_ok("Diretório Skills Hub existe")
        lock_file = hub_dir / "lock.json"
        if lock_file.exists():
            try:
                import json
                lock_data = json.loads(lock_file.read_text())
                count = len(lock_data.get("installed", {}))
                check_ok(f"Arquivo lock OK ({count} habilidade(s) instalada(s) via hub)")
            except Exception:
                check_warn("Arquivo lock", "(corrompido ou ilegível)")
        quarantine = hub_dir / "quarantine"
        q_count = sum(1 for d in quarantine.iterdir() if d.is_dir()) if quarantine.exists() else 0
        if q_count > 0:
            check_warn(f"{q_count} habilidade(s) em quarentena", "(aguardando revisão)")
    else:
        check_warn("Diretório Skills Hub não inicializado", "(execute: ector skills list)")

    from ector_cli.config import get_env_value
    github_token = get_env_value("GITHUB_TOKEN") or get_env_value("GH_TOKEN")
    if github_token:
        check_ok("Token GitHub configurado (acesso autenticado à API)")
    else:
        check_warn("Sem GITHUB_TOKEN", f"(limite de taxa de 60 req/h — defina em {_DHH}/.env para melhores taxas)")

    # =========================================================================
    # Memory Provider (only check the active provider, if any)
    # =========================================================================
    print()
    print(color("◆ Provedor de Memória", Colors.CYAN, Colors.BOLD))

    _active_memory_provider = ""
    try:
        import yaml as _yaml
        _mem_cfg_path = ECTOR_HOME / "config.yaml"
        if _mem_cfg_path.exists():
            with open(_mem_cfg_path) as _f:
                _raw_cfg = _yaml.safe_load(_f) or {}
            _active_memory_provider = (_raw_cfg.get("memory") or {}).get("provider", "")
    except Exception:
        pass

    if not _active_memory_provider:
        check_ok("Memória embutida ativa", "(nenhum provedor externo configurado — isso é normal)")
    elif _active_memory_provider == "mem0":
        try:
            from plugins.memory.mem0 import _load_config as _load_mem0_config
            mem0_cfg = _load_mem0_config()
            mem0_key = mem0_cfg.get("api_key", "")
            if mem0_key:
                check_ok("Chave API Mem0 configurada")
                check_info(f"user_id={mem0_cfg.get('user_id', '?')}  agent_id={mem0_cfg.get('agent_id', '?')}")
            else:
                check_fail("Chave API Mem0 não definida", "(defina MEM0_API_KEY no .env ou execute ector memory setup)")
                issues.append("Mem0 está definido como provedor de memória, mas a chave API está faltando")
        except ImportError:
            check_fail("Plugin Mem0 não carregável", "pip install mem0ai")
            issues.append("Mem0 está definido como provedor de memória, mas mem0ai não está instalado")
        except Exception as _e:
            check_warn("Verificação do Mem0 falhou", str(_e))
    else:
        # Generic check for other memory providers
        try:
            from plugins.memory import load_memory_provider
            _provider = load_memory_provider(_active_memory_provider)
            if _provider and _provider.is_available():
                check_ok(f"Provedor {_active_memory_provider} ativo")
            elif _provider:
                check_warn(f"{_active_memory_provider} configurado, mas não disponível", "execute: ector memory status")
            else:
                check_warn(f"Plugin {_active_memory_provider} não encontrado", "execute: ector memory setup")
        except Exception as _e:
            check_warn(f"Verificação de {_active_memory_provider} falhou", str(_e))

    # =========================================================================
    # Profiles
    # =========================================================================
    try:
        from ector_cli.profiles import list_profiles, _get_wrapper_dir, profile_exists
        import re as _re

        named_profiles = [p for p in list_profiles() if not p.is_default]
        if named_profiles:
            print()
            print(color("◆ Perfis", Colors.CYAN, Colors.BOLD))
            check_ok(f"{len(named_profiles)} perfil(is) encontrado(s)")
            wrapper_dir = _get_wrapper_dir()
            for p in named_profiles:
                parts = []
                if p.gateway_running:
                    parts.append("gateway em execução")
                if p.model:
                    parts.append(p.model[:30])
                if not (p.path / "config.yaml").exists():
                    parts.append("▲ config ausente")
                if not (p.path / ".env").exists():
                    parts.append("sem .env")
                wrapper = wrapper_dir / p.name
                if not wrapper.exists():
                    parts.append("sem alias")
                status = ", ".join(parts) if parts else "configurado"
                check_ok(f"  {p.name}: {status}")

            # Check for orphan wrappers
            if wrapper_dir.is_dir():
                for wrapper in wrapper_dir.iterdir():
                    if not wrapper.is_file():
                        continue
                    try:
                        content = wrapper.read_text()
                        if "ector -p" in content:
                            _m = _re.search(r"ector -p (\S+)", content)
                            if _m and not profile_exists(_m.group(1)):
                                check_warn(f"Alias órfão: {wrapper.name} → perfil '{_m.group(1)}' não existe mais")
                    except Exception:
                        pass
    except ImportError:
        pass
    except Exception:
        pass

    # =========================================================================
    # Summary
    # =========================================================================
    print()
    remaining_issues = issues + manual_issues
    if should_fix and fixed_count > 0:
        print(color("─" * 60, Colors.GREEN))
        print(color(f"  Corrigiu {fixed_count} problema(s).", Colors.GREEN, Colors.BOLD), end="")
        if remaining_issues:
            print(color(f" {len(remaining_issues)} problema(s) requerem intervenção manual.", Colors.YELLOW, Colors.BOLD))
        else:
            print()
        print()
        if remaining_issues:
            for i, issue in enumerate(remaining_issues, 1):
                print(f"  {i}. {issue}")
            print()
    elif remaining_issues:
        print(color("─" * 60, Colors.YELLOW))
        print(color(f"  Encontrou {len(remaining_issues)} problema(s) para resolver:", Colors.YELLOW, Colors.BOLD))
        print()
        for i, issue in enumerate(remaining_issues, 1):
            print(f"  {i}. {issue}")
        print()
        if not should_fix:
            print(color("  Dica: execute 'ector doctor --fix' para auto-corrigir o que for possível.", Colors.DIM))
    else:
        print(color("─" * 60, Colors.GREEN))
        print(color("  Todos os testes passaram! 🎉", Colors.GREEN, Colors.BOLD))
    
    print()
