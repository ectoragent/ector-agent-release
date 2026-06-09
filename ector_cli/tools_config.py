"""
Unified tool configuration for Ector Agent.

`ector tools` and `ector setup tools` both enter this module.
Select a platform → toggle toolsets on/off → for newly enabled tools
that need API keys, run through provider-aware configuration.

Saves per-platform tool configuration to ~/.ector/config.yaml under
the `platform_toolsets` key.
"""

import json as _json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set


from ector_cli.config import (
    load_config, save_config, get_env_value, save_env_value,
)
from ector_cli.colors import Colors, color

from tools.tool_backend_helpers import fal_key_is_configured
from utils import base_url_hostname, is_truthy_value

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


# ─── UI Helpers (shared with setup.py) ────────────────────────────────────────

from ector_cli.cli_output import (  # noqa: E402 — late import block
    print_error as _print_error,
    print_info as _print_info,
    print_success as _print_success,
    print_warning as _print_warning,
    prompt as _prompt,
)

# ─── Toolset Registry ─────────────────────────────────────────────────────────

# Toolsets shown in the configurator, grouped for display.
# Each entry: (toolset_name, label, description_fallback)
# Descriptions shown in the dashboard/CLI prefer toolsets.TOOLSETS when present.
CONFIGURABLE_TOOLSETS = [
    (
        "web",
        "Busca web",
        "Pesquisar na internet e extrair conteúdo de páginas ou PDFs em texto utilizável.",
    ),
    (
        "browser",
        "Automação de navegador",
        "Controlar um navegador real: abrir sites, interagir com elementos e capturar o estado de páginas dinâmicas.",
    ),
    (
        "terminal",
        "Terminal e processos",
        "Executar comandos no sistema e gerir processos em background (logs, cancelar, aguardar conclusão).",
    ),
    (
        "file",
        "Ficheiros",
        "Ler, criar, editar e pesquisar ficheiros no projeto, com patches precisos e busca por conteúdo.",
    ),
    (
        "code_execution",
        "Execução de código",
        "Correr Python que invoca outras ferramentas num único passo, reduzindo idas e voltas ao modelo.",
    ),
    (
        "vision",
        "Visão",
        "Analisar imagens enviadas ou capturadas — screenshots, diagramas, interfaces e documentos visuais.",
    ),
    (
        "image_gen",
        "Geração de imagem",
        "Criar imagens a partir de prompts de texto com o provedor de imagem configurado.",
    ),
    (
        "moa",
        "Mixture of Agents",
        "Combinar várias perspectivas de modelos para problemas difíceis que beneficiam de raciocínio ampliado.",
    ),
    (
        "tts",
        "Texto para voz",
        "Converter respostas do agente em áudio (Edge TTS gratuito ou provedores premium).",
    ),
    (
        "skills",
        "Skills",
        "Instalar, listar e editar skills — conhecimento e fluxos reutilizáveis para o agente.",
    ),
    (
        "todo",
        "Planeamento",
        "Manter listas de tarefas multi-passo visíveis durante execuções longas ou complexas.",
    ),
    (
        "memory",
        "Memória",
        "Guardar preferências, factos e contexto importante entre sessões e conversas.",
    ),
    (
        "session_search",
        "Busca em sessões",
        "Pesquisar no histórico local de chats por palavras-chave, tema ou trecho de conversa.",
    ),
    (
        "wiser",
        "Wiser",
        "Pedir confirmação ou escolha ao utilizador antes de ações sensíveis ou ambíguas.",
    ),
    (
        "delegation",
        "Delegação",
        "Lançar subagentes com contexto isolado para subtarefas paralelas ou mais complexas.",
    ),
    (
        "cronjob",
        "Agendamentos",
        "Criar e gerir tarefas automáticas que o agente executa num horário definido.",
    ),
    (
        "messaging",
        "Mensagens",
        "Enviar mensagens através do gateway (Telegram, Discord, Slack, SMS e outros canais).",
    ),
    (
        "rl",
        "Treino RL",
        "Treinar e avaliar modelos com ambientes de reforço Tinker-Atropos.",
    ),
    (
        "homeassistant",
        "Home Assistant",
        "Monitorizar e controlar dispositivos de casa inteligente via Home Assistant.",
    ),
    (
        "discord",
        "Discord",
        "Ler canais, pesquisar membros e participar em conversas no Discord.",
    ),
    (
        "discord_admin",
        "Admin Discord",
        "Administrar servidor Discord: canais, cargos, mensagens fixadas e moderação.",
    ),
]

# Toolsets that are OFF by default for new installs.
# They're still in _ECTOR_CORE_TOOLS (available at runtime if enabled),
# but the setup checklist won't pre-select them for first-time users.
_DEFAULT_OFF_TOOLSETS = {"moa", "homeassistant", "rl", "discord", "discord_admin"}

# Platform-scoped toolsets: only appear in the `ector tools` checklist for
# these platforms, and only resolve/save for these platforms.  A toolset
# absent from this map is available on every platform (current behaviour).
#
# Use this for tools whose APIs only make sense on one platform (Discord
# server admin, Slack workspace admin, etc.).  Keeps every other platform's
# checklist from filling up with irrelevant toggles.
_TOOLSET_PLATFORM_RESTRICTIONS: Dict[str, Set[str]] = {
    "discord": {"discord"},
    "discord_admin": {"discord"},
}


def _toolset_allowed_for_platform(ts_key: str, platform: str) -> bool:
    """Return True if ``ts_key`` is configurable on ``platform``.

    Toolsets without a restriction entry are allowed everywhere (the default).
    """
    allowed = _TOOLSET_PLATFORM_RESTRICTIONS.get(ts_key)
    return allowed is None or platform in allowed


def _toolset_user_description(name: str, fallback: str) -> str:
    """Human-readable description for UI (dashboard, setup, ``ector tools``)."""
    fb = (fallback or "").strip()
    if fb:
        return fb
    try:
        from toolsets import TOOLSETS

        core = (TOOLSETS.get(name) or {}).get("description")
        if isinstance(core, str) and core.strip():
            return core.strip()
    except Exception:
        pass
    return name.replace("_", " ")


def _normalize_configurable_entry(entry: tuple) -> tuple:
    name, label, desc = entry
    return (name, label, _toolset_user_description(name, desc))


def _get_effective_configurable_toolsets():
    """Return CONFIGURABLE_TOOLSETS + any plugin-provided toolsets.

    Plugin toolsets are appended at the end so they appear after the
    built-in toolsets in the TUI checklist. A plugin whose toolset key
    already appears in ``CONFIGURABLE_TOOLSETS`` is skipped — bundled
    plugins may share a toolset key with a built-in row, and the
    built-in label/description wins. Without the dedupe,
    ``ector tools`` → "reconfigure existing" would list the same toolset twice.
    """
    result = [_normalize_configurable_entry(entry) for entry in CONFIGURABLE_TOOLSETS]
    seen = {ts_key for ts_key, _, _ in result}
    try:
        from ector_cli.plugins import discover_plugins, get_plugin_toolsets
        discover_plugins()  # idempotent — ensures plugins are loaded
        for entry in get_plugin_toolsets():
            if entry[0] in seen:
                continue
            seen.add(entry[0])
            result.append(_normalize_configurable_entry(entry))
    except Exception:
        pass
    return result


def _get_plugin_toolset_keys() -> set:
    """Return the set of toolset keys provided by plugins."""
    try:
        from ector_cli.plugins import discover_plugins, get_plugin_toolsets
        discover_plugins()  # idempotent — ensures plugins are loaded
        return {ts_key for ts_key, _, _ in get_plugin_toolsets()}
    except Exception:
        return set()

# Platform display config — derived from the canonical registry so every
# module shares the same data.  Kept as dict-of-dicts for backward
# compatibility with existing ``PLATFORMS[key]["label"]`` access patterns.
from ector_cli.platforms import PLATFORMS as _PLATFORMS_REGISTRY

PLATFORMS = {
    k: {"label": info.label, "default_toolset": info.default_toolset}
    for k, info in _PLATFORMS_REGISTRY.items()
}


# ─── Tool Categories (provider-aware configuration) ──────────────────────────
# Maps toolset keys to their provider options. When a toolset is newly enabled,
# we use this to show provider selection and prompt for the right API keys.
# Toolsets not in this map either need no config or use the simple fallback.

TOOL_CATEGORIES = {
    "tts": {
        "name": "Text-to-Speech",
        "icon": "🗣️",
        "providers": [
            {
                "name": "Microsoft Edge TTS",
                "badge": "★ recomendado · grátis",
                "tag": "Boa qualidade, sem necessidade de chave API",
                "env_vars": [],
                "tts_provider": "edge",
            },
            {
                "name": "OpenAI TTS",
                "badge": "pago",
                "tag": "Vozes de alta qualidade",
                "env_vars": [
                    {"key": "VOICE_TOOLS_OPENAI_KEY", "prompt": "OpenAI API key", "url": "https://platform.openai.com/api-keys"},
                ],
                "tts_provider": "openai",
            },
            {
                "name": "xAI TTS",
                "tag": "Vozes Grok - requer chave API da xAI",
                "env_vars": [
                    {"key": "XAI_API_KEY", "prompt": "xAI API key", "url": "https://console.x.ai/"},
                ],
                "tts_provider": "xai",
            },
            {
                "name": "ElevenLabs",
                "badge": "pago",
                "tag": "Vozes mais naturais",
                "env_vars": [
                    {"key": "ELEVENLABS_API_KEY", "prompt": "ElevenLabs API key", "url": "https://elevenlabs.io/app/settings/api-keys"},
                ],
                "tts_provider": "elevenlabs",
            },
            {
                "name": "Mistral (Voxtral TTS)",
                "badge": "pago",
                "tag": "Multilíngue, nativo Opus",
                "env_vars": [
                    {"key": "MISTRAL_API_KEY", "prompt": "Mistral API key", "url": "https://console.mistral.ai/"},
                ],
                "tts_provider": "mistral",
            },
            {
                "name": "Google Gemini TTS",
                "badge": "prévia",
                "tag": "30 vozes pré-construídas, controláveis via prompts",
                "env_vars": [
                    {"key": "GEMINI_API_KEY", "prompt": "Gemini API key", "url": "https://aistudio.google.com/app/apikey"},
                ],
                "tts_provider": "gemini",
            },
            {
                "name": "KittenTTS",
                "badge": "local · grátis",
                "tag": "TTS ONNX local leve (~25MB), sem chave API",
                "env_vars": [],
                "tts_provider": "kittentts",
                "post_setup": "kittentts",
            },
        ],
    },
    "web": {
        "name": "Busca Web & Extração",
        "setup_title": "Selecione o Provedor de Busca",
        "setup_note": "Uma habilidade de busca gratuita DuckDuckGo também está incluída — pule isto se não precisar de um provedor premium.",
        "icon": "🌍",
        "providers": [
            {
                "name": "Firecrawl Cloud",
                "badge": "★ recomendado",
                "tag": "Busca, extração e rastreamento (crawl) completos",
                "web_backend": "firecrawl",
                "env_vars": [
                    {"key": "FIRECRAWL_API_KEY", "prompt": "Firecrawl API key", "url": "https://firecrawl.dev"},
                ],
            },
            {
                "name": "Exa",
                "badge": "pago",
                "tag": "Busca neural com compreensão semântica",
                "web_backend": "exa",
                "env_vars": [
                    {"key": "EXA_API_KEY", "prompt": "Exa API key", "url": "https://exa.ai"},
                ],
            },
            {
                "name": "Parallel",
                "badge": "pago",
                "tag": "Busca e extração alimentadas por IA",
                "web_backend": "parallel",
                "env_vars": [
                    {"key": "PARALLEL_API_KEY", "prompt": "Parallel API key", "url": "https://parallel.ai"},
                ],
            },
            {
                "name": "Tavily",
                "badge": "nível gratuito",
                "tag": "Busca, extração e rastreamento — 1000 buscas grátis/mês",
                "web_backend": "tavily",
                "env_vars": [
                    {"key": "TAVILY_API_KEY", "prompt": "Tavily API key", "url": "https://app.tavily.com/home"},
                ],
            },
            {
                "name": "Firecrawl Self-Hosted",
                "badge": "grátis · auto-hospedado",
                "tag": "Execute sua própria instância do Firecrawl (Docker)",
                "web_backend": "firecrawl",
                "env_vars": [
                    {"key": "FIRECRAWL_API_URL", "prompt": "Your Firecrawl instance URL (e.g., http://localhost:3002)"},
                ],
            },
        ],
    },
    "image_gen": {
        "name": "Geração de Imagem",
        "icon": "🖼️",
        "providers": [
            {
                "name": "FAL.ai",
                "badge": "pago",
                "tag": "Escolha entre flux-2-klein, flux-2-pro, gpt-image, nano-banana, etc.",
                "env_vars": [
                    {"key": "FAL_KEY", "prompt": "FAL API key", "url": "https://fal.ai/dashboard/keys"},
                ],
                "imagegen_backend": "fal",
            },
        ],
    },
    "browser": {
        "name": "Automação de Navegador",
        "icon": "🧭",
        "providers": [
            {
                "name": "Navegador Local",
                "badge": "★ recomendado · grátis",
                "tag": "Chromium headless, sem necessidade de chave API",
                "env_vars": [],
                "browser_provider": "local",
                "post_setup": "agent_browser",
            },
            {
                "name": "Browserbase",
                "badge": "pago",
                "tag": "Navegador na nuvem com furtividade e proxies",
                "env_vars": [
                    {"key": "BROWSERBASE_API_KEY", "prompt": "Browserbase API key", "url": "https://browserbase.com"},
                    {"key": "BROWSERBASE_PROJECT_ID", "prompt": "Browserbase project ID"},
                ],
                "browser_provider": "browserbase",
                "post_setup": "agent_browser",
            },
            {
                "name": "Browser Use",
                "badge": "pago",
                "tag": "Navegador na nuvem com execução remota",
                "env_vars": [
                    {"key": "BROWSER_USE_API_KEY", "prompt": "Browser Use API key", "url": "https://browser-use.com"},
                ],
                "browser_provider": "browser-use",
                "post_setup": "agent_browser",
            },
            {
                "name": "Firecrawl",
                "badge": "pago",
                "tag": "Navegador na nuvem com execução remota",
                "env_vars": [
                    {"key": "FIRECRAWL_API_KEY", "prompt": "Firecrawl API key", "url": "https://firecrawl.dev"},
                ],
                "browser_provider": "firecrawl",
                "post_setup": "agent_browser",
            },
            {
                "name": "Camofox",
                "badge": "grátis · local",
                "tag": "Navegador anti-detecção (Firefox/Camoufox)",
                "env_vars": [
                    {"key": "CAMOFOX_URL", "prompt": "Camofox server URL", "default": "http://localhost:9377",
                     "url": "https://github.com/jo-inc/camofox-browser"},
                ],
                "browser_provider": "camofox",
                "post_setup": "camofox",
            },
        ],
    },
    "homeassistant": {
        "name": "Casa Inteligente",
        "icon": "🏡",
        "providers": [
            {
                "name": "Home Assistant",
                "tag": "Integração via REST API",
                "env_vars": [
                    {"key": "HASS_TOKEN", "prompt": "Home Assistant Long-Lived Access Token"},
                    {"key": "HASS_URL", "prompt": "Home Assistant URL", "default": "http://homeassistant.local:8123"},
                ],
            },
        ],
    },
    "rl": {
        "name": "Treinamento RL",
        "icon": "🧪",
        "requires_python": (3, 11),
        "providers": [
            {
                "name": "Tinker / Atropos",
                "tag": "Plataforma de treinamento RL",
                "env_vars": [
                    {"key": "TINKER_API_KEY", "prompt": "Tinker API key", "url": "https://tinker-console.thinkingmachines.ai/keys"},
                    {"key": "WANDB_API_KEY", "prompt": "WandB API key", "url": "https://wandb.ai/authorize"},
                ],
                "post_setup": "rl_training",
            },
        ],
    },
}

# Simple env-var requirements for toolsets NOT in TOOL_CATEGORIES.
# Used as a fallback for tools like vision/moa that just need an API key.
TOOLSET_ENV_REQUIREMENTS = {
    "vision":     [("OPENROUTER_API_KEY",   "https://openrouter.ai/keys")],
    "moa":        [("OPENROUTER_API_KEY",   "https://openrouter.ai/keys")],
}


# ─── Post-Setup Hooks ─────────────────────────────────────────────────────────

def _run_post_setup(post_setup_key: str):
    """Run post-setup hooks for tools that need extra installation steps."""
    import shutil
    if post_setup_key in ("agent_browser", "browserbase"):
        node_modules = PROJECT_ROOT / "node_modules" / "agent-browser"
        if not node_modules.exists() and shutil.which("npm"):
            _print_info("    Installing Node.js dependencies for browser tools...")
            import subprocess
            result = subprocess.run(
                ["npm", "install", "--silent"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT)
            )
            if result.returncode == 0:
                _print_success("    Node.js dependencies installed")
            else:
                from ector_constants import display_ector_home
                _print_warning(f"    npm install failed - run manually: cd {display_ector_home()}/ector-agent && npm install")
        elif not node_modules.exists():
            _print_warning("    Node.js not found - browser tools require: npm install (in ector-agent directory)")

    elif post_setup_key == "camofox":
        camofox_dir = PROJECT_ROOT / "node_modules" / "@askjo" / "camofox-browser"
        if not camofox_dir.exists() and shutil.which("npm"):
            _print_info("    Installing Camofox browser server...")
            import subprocess
            result = subprocess.run(
                ["npm", "install", "--silent"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT)
            )
            if result.returncode == 0:
                _print_success("    Camofox installed")
            else:
                _print_warning("    npm install failed - run manually: npm install")
        if camofox_dir.exists():
            _print_info("    Start the Camofox server:")
            _print_info("      npx @askjo/camofox-browser")
            _print_info("    First run downloads the Camoufox engine (~300MB)")
            _print_info("    Or use Docker: docker run -p 9377:9377 -e CAMOFOX_PORT=9377 jo-inc/camofox-browser")
        elif not shutil.which("npm"):
            _print_warning("    Node.js not found. Install Camofox via Docker:")
            _print_info("      docker run -p 9377:9377 -e CAMOFOX_PORT=9377 jo-inc/camofox-browser")

    elif post_setup_key == "kittentts":
        try:
            __import__("kittentts")
            _print_success("    kittentts is already installed")
            return
        except ImportError:
            pass
        import subprocess
        _print_info("    Installing kittentts (~25-80MB model, CPU-only)...")
        wheel_url = (
            "https://github.com/KittenML/KittenTTS/releases/download/"
            "0.8.1/kittentts-0.8.1-py3-none-any.whl"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", wheel_url, "soundfile", "--quiet"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                _print_success("    kittentts installed")
                _print_info("    Voices: Jasper, Bella, Luna, Bruno, Rosie, Hugo, Kiki, Leo")
                _print_info("    Models: KittenML/kitten-tts-nano-0.8-int8 (25MB), micro (41MB), mini (80MB)")
            else:
                _print_warning("    kittentts install failed:")
                _print_info(f"      {result.stderr.strip()[:300]}")
                _print_info(f"    Run manually: python -m pip install -U '{wheel_url}' soundfile")
        except subprocess.TimeoutExpired:
            _print_warning("    kittentts install timed out (>5min)")
            _print_info(f"    Run manually: python -m pip install -U '{wheel_url}' soundfile")

    elif post_setup_key == "rl_training":
        try:
            __import__("tinker_atropos")
        except ImportError:
            tinker_dir = PROJECT_ROOT / "tinker-atropos"
            if tinker_dir.exists() and (tinker_dir / "pyproject.toml").exists():
                _print_info("    Installing tinker-atropos submodule...")
                import subprocess
                uv_bin = shutil.which("uv")
                if uv_bin:
                    result = subprocess.run(
                        [uv_bin, "pip", "install", "--python", sys.executable, "-e", str(tinker_dir)],
                        capture_output=True, text=True
                    )
                else:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "-e", str(tinker_dir)],
                        capture_output=True, text=True
                    )
                if result.returncode == 0:
                    _print_success("    tinker-atropos installed")
                else:
                    _print_warning("    tinker-atropos install failed - run manually:")
                    _print_info('      uv pip install -e "./tinker-atropos"')
            else:
                _print_warning("    tinker-atropos submodule not found - run:")
                _print_info("      git submodule update --init --recursive")
                _print_info('      uv pip install -e "./tinker-atropos"')


# ─── Platform / Toolset Helpers ───────────────────────────────────────────────

def _get_enabled_platforms() -> List[str]:
    """Return platform keys that are configured (have tokens or are CLI)."""
    enabled = ["cli"]
    if get_env_value("TELEGRAM_BOT_TOKEN"):
        enabled.append("telegram")
    if get_env_value("DISCORD_BOT_TOKEN"):
        enabled.append("discord")
    if get_env_value("SLACK_BOT_TOKEN"):
        enabled.append("slack")
    if get_env_value("WHATSAPP_ENABLED"):
        enabled.append("whatsapp")
    return enabled


def _platform_toolset_summary(config: dict, platforms: Optional[List[str]] = None) -> Dict[str, Set[str]]:
    """Return a summary of enabled toolsets per platform.

    When ``platforms`` is None, this uses ``_get_enabled_platforms`` to
    auto-detect platforms. Tests can pass an explicit list to avoid relying
    on environment variables.
    """
    if platforms is None:
        platforms = _get_enabled_platforms()

    summary: Dict[str, Set[str]] = {}
    for pkey in platforms:
        summary[pkey] = _get_platform_tools(config, pkey)
    return summary


def _parse_enabled_flag(value, default: bool = True) -> bool:
    """Parse bool-like config values used by tool/platform settings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _get_platform_tools(
    config: dict,
    platform: str,
    *,
    include_default_mcp_servers: bool = True,
) -> Set[str]:
    """Resolve which individual toolset names are enabled for a platform."""
    from toolsets import resolve_toolset, TOOLSETS

    # Web dashboard chat uses the same default tool surface as CLI.
    if platform == "web":
        platform = "cli"

    platform_toolsets = config.get("platform_toolsets") or {}
    toolset_names = platform_toolsets.get(platform)

    if toolset_names is None or not isinstance(toolset_names, list):
        default_ts = PLATFORMS[platform]["default_toolset"]
        toolset_names = [default_ts]

    # YAML may parse bare numeric names (e.g. ``12306:``) as int.
    # Normalise to str so downstream sorted() never mixes types.
    toolset_names = [str(ts) for ts in toolset_names]

    configurable_keys = {ts_key for ts_key, _, _ in CONFIGURABLE_TOOLSETS}
    plugin_ts_keys = _get_plugin_toolset_keys()
    platform_default_keys = {p["default_toolset"] for p in PLATFORMS.values()}

    # If the saved list contains any configurable keys directly, the user
    # has explicitly configured this platform — use direct membership.
    # This avoids the subset-inference bug where composite toolsets like
    # "ector-cli" (which include all _ECTOR_CORE_TOOLS) cause disabled
    # toolsets to re-appear as enabled.
    has_explicit_config = any(ts in configurable_keys for ts in toolset_names)

    if has_explicit_config:
        enabled_toolsets = {
            ts for ts in toolset_names
            if ts in configurable_keys and _toolset_allowed_for_platform(ts, platform)
        }
    else:
        # No explicit config — fall back to resolving composite toolset names
        # (e.g. "ector-cli") to individual tool names and reverse-mapping.
        all_tool_names = set()
        for ts_name in toolset_names:
            all_tool_names.update(resolve_toolset(ts_name))

        enabled_toolsets = set()
        for ts_key, _, _ in CONFIGURABLE_TOOLSETS:
            if not _toolset_allowed_for_platform(ts_key, platform):
                continue
            ts_tools = set(resolve_toolset(ts_key))
            if ts_tools and ts_tools.issubset(all_tool_names):
                enabled_toolsets.add(ts_key)

        default_off = set(_DEFAULT_OFF_TOOLSETS)
        # Legacy safety: if the platform's own name matches a default-off
        # toolset (e.g. `homeassistant` platform + `homeassistant` toolset),
        # keep that toolset enabled on first install.  Skip this dodge for
        # platform-restricted toolsets — those are always opt-in even on
        # their own platform (e.g. `discord` + `discord` should stay OFF).
        if platform in default_off and platform not in _TOOLSET_PLATFORM_RESTRICTIONS:
            default_off.remove(platform)
        # Home Assistant is already runtime-gated by its check_fn (requires
        # HASS_TOKEN to register any tools). When a user has configured
        # HASS_TOKEN, they've explicitly opted in — don't also strip it via
        # _DEFAULT_OFF_TOOLSETS, which would silently drop HA from platforms
        # (e.g. cron) that run through _get_platform_tools without an
        # explicit saved toolset list. Without this, Norbert's HA cron jobs
        # regressed after #14798 made cron honor per-platform tool config.
        if "homeassistant" in default_off and os.getenv("HASS_TOKEN"):
            default_off.remove("homeassistant")
        enabled_toolsets -= default_off

    # Recover non-configurable platform toolsets (e.g. discord).  These are part
    # of the platform's default composite but
    # absent from CONFIGURABLE_TOOLSETS, so they can't appear in the TUI
    # checklist or in a user-saved config.  Must run in BOTH branches —
    # otherwise saving via `ector tools` (which flips has_explicit_config
    # to True) silently drops them.
    platform_tool_universe = set(resolve_toolset(PLATFORMS[platform]["default_toolset"]))
    configurable_tool_universe = set()
    for ck in configurable_keys:
        configurable_tool_universe.update(resolve_toolset(ck))
    claimed = set()
    for ts_key in enabled_toolsets:
        claimed.update(resolve_toolset(ts_key))
    skip = configurable_keys | plugin_ts_keys | platform_default_keys
    skip |= {k for k in TOOLSETS if k.startswith("ector-")}
    skip |= set(_DEFAULT_OFF_TOOLSETS) - {platform}
    for ts_key, ts_def in TOOLSETS.items():
        if ts_key in skip:
            continue
        if ts_def.get("includes"):
            continue
        ts_tools = set(resolve_toolset(ts_key))
        if not ts_tools or not ts_tools.issubset(platform_tool_universe):
            continue
        if ts_tools.issubset(configurable_tool_universe):
            continue
        if not ts_tools.issubset(claimed):
            enabled_toolsets.add(ts_key)
            claimed.update(ts_tools)

    # Plugin toolsets: enabled by default unless explicitly disabled, or
    # unless the toolset is in _DEFAULT_OFF_TOOLSETS (opt-in defaults).
    # A plugin toolset is "known" for a platform once `ector tools`
    # has been saved for that platform (tracked via known_plugin_toolsets).
    # Unknown plugins default to enabled; known-but-absent = disabled.
    if plugin_ts_keys:
        known_map = config.get("known_plugin_toolsets", {})
        known_for_platform = set(known_map.get(platform, []))
        for pts in plugin_ts_keys:
            if pts in toolset_names:
                # Explicitly listed in config — enabled
                enabled_toolsets.add(pts)
            elif pts in _DEFAULT_OFF_TOOLSETS:
                # Opt-in plugin toolset — stay off until user picks it
                continue
            elif pts not in known_for_platform:
                # New plugin not yet seen by ector tools — default enabled
                enabled_toolsets.add(pts)
            # else: known but not in config = user disabled it

    # Preserve any explicit non-configurable toolset entries (for example,
    # custom toolsets or MCP server names saved in platform_toolsets).
    explicit_passthrough = {
        ts
        for ts in toolset_names
        if ts not in configurable_keys
        and ts not in plugin_ts_keys
        and ts not in platform_default_keys
    }

    # MCP servers are expected to be available on all platforms by default.
    # If the platform explicitly lists one or more MCP server names, treat that
    # as an allowlist. Otherwise include every globally enabled MCP server.
    # Special sentinel: "no_mcp" in the toolset list disables all MCP servers.
    mcp_servers = config.get("mcp_servers") or {}
    enabled_mcp_servers = {
        str(name)
        for name, server_cfg in mcp_servers.items()
        if isinstance(server_cfg, dict)
        and _parse_enabled_flag(server_cfg.get("enabled", True), default=True)
    }
    # Allow "no_mcp" sentinel to opt out of all MCP servers for this platform
    if "no_mcp" in toolset_names:
        explicit_mcp_servers = set()
        enabled_toolsets.update(explicit_passthrough - enabled_mcp_servers - {"no_mcp"})
    else:
        explicit_mcp_servers = explicit_passthrough & enabled_mcp_servers
        enabled_toolsets.update(explicit_passthrough - enabled_mcp_servers)
    if include_default_mcp_servers:
        if explicit_mcp_servers or "no_mcp" in toolset_names:
            enabled_toolsets.update(explicit_mcp_servers)
        else:
            enabled_toolsets.update(enabled_mcp_servers)
    else:
        enabled_toolsets.update(explicit_mcp_servers)

    return enabled_toolsets


def _save_platform_tools(config: dict, platform: str, enabled_toolset_keys: Set[str]):
    """Save the selected toolset keys for a platform to config.

    Preserves any non-configurable toolset entries (like MCP server names)
    that were already in the config for this platform.
    """
    config.setdefault("platform_toolsets", {})

    # Drop platform-scoped toolsets that don't apply here.  Prevents the
    # "Configure all platforms" checklist (or a hand-edited config.yaml)
    # from turning on, say, the `discord` toolset for Telegram.
    enabled_toolset_keys = {
        ts for ts in enabled_toolset_keys
        if _toolset_allowed_for_platform(ts, platform)
    }

    # Get the set of all configurable toolset keys (built-in + plugin)
    configurable_keys = {ts_key for ts_key, _, _ in CONFIGURABLE_TOOLSETS}
    plugin_keys = _get_plugin_toolset_keys()
    configurable_keys |= plugin_keys

    # Also exclude platform default toolsets (ector-cli, ector-telegram, etc.)
    # These are "super" toolsets that resolve to ALL tools, so preserving them
    # would silently override the user's unchecked selections on the next read.
    platform_default_keys = {p["default_toolset"] for p in PLATFORMS.values()}

    # Get existing toolsets for this platform
    existing_toolsets = config.get("platform_toolsets", {}).get(platform, [])
    if not isinstance(existing_toolsets, list):
        existing_toolsets = []
    existing_toolsets = [str(ts) for ts in existing_toolsets]

    # Preserve any entries that are NOT configurable toolsets and NOT platform
    # defaults (i.e. only MCP server names should be preserved)
    preserved_entries = {
        entry for entry in existing_toolsets
        if entry not in configurable_keys and entry not in platform_default_keys
    }
    # Opening `ector tools` is the user's opt-in to reconfigure tools, so treat
    # saving from the picker as consent to clear the "no_mcp" sentinel. The
    # picker has no checkbox for no_mcp, so without this users who once set it
    # by hand could never re-enable MCP servers through the UI.
    preserved_entries.discard("no_mcp")

    # Merge preserved entries with new enabled toolsets
    config["platform_toolsets"][platform] = sorted(enabled_toolset_keys | preserved_entries)

    # Track which plugin toolsets are "known" for this platform so we can
    # distinguish "new plugin, default enabled" from "user disabled it".
    if plugin_keys:
        config.setdefault("known_plugin_toolsets", {})
        config["known_plugin_toolsets"][platform] = sorted(plugin_keys)

    save_config(config)


def _toolset_has_keys(ts_key: str, config: dict = None) -> bool:
    """Check if a toolset's required API keys are configured."""
    if config is None:
        config = load_config()

    if ts_key == "vision":
        try:
            from agent.auxiliary_client import resolve_vision_provider_client

            _provider, client, _model = resolve_vision_provider_client()
            return client is not None
        except Exception:
            return False

    # Check TOOL_CATEGORIES first (provider-aware)
    cat = TOOL_CATEGORIES.get(ts_key)
    if cat:
        for provider in _visible_providers(cat, config):
            env_vars = provider.get("env_vars", [])
            if not env_vars:
                return True  # No-key provider (e.g. Local Browser, Edge TTS)
            if all(get_env_value(e["key"]) for e in env_vars):
                return True
        return False

    # Fallback to simple requirements
    requirements = TOOLSET_ENV_REQUIREMENTS.get(ts_key, [])
    if not requirements:
        return True
    return all(get_env_value(var) for var, _ in requirements)


# ─── Menu Helpers ─────────────────────────────────────────────────────────────

def _prompt_choice(question: str, choices: list, default: int = 0) -> int:
    """Single-select menu (arrow keys). Delegates to curses_radiolist."""
    from ector_cli.curses_ui import curses_radiolist
    return curses_radiolist(question, choices, selected=default, cancel_returns=default)


# ─── Token Estimation ────────────────────────────────────────────────────────

# Module-level cache so discovery + tokenization runs at most once per process.
_tool_token_cache: Optional[Dict[str, int]] = None


def _estimate_tool_tokens() -> Dict[str, int]:
    """Return estimated token counts per individual tool name.

    Uses tiktoken (cl100k_base) to count tokens in the JSON-serialised
    OpenAI-format tool schema.  Triggers tool discovery on first call,
    then caches the result for the rest of the process.

    Returns an empty dict when tiktoken or the registry is unavailable.
    """
    global _tool_token_cache
    if _tool_token_cache is not None:
        return _tool_token_cache

    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        logger.debug("tiktoken unavailable; skipping tool token estimation")
        _tool_token_cache = {}
        return _tool_token_cache

    try:
        # Trigger full tool discovery (imports all tool modules).
        import model_tools  # noqa: F401
        from tools.registry import registry
    except Exception:
        logger.debug("Tool registry unavailable; skipping token estimation")
        _tool_token_cache = {}
        return _tool_token_cache

    counts: Dict[str, int] = {}
    for name in registry.get_all_tool_names():
        schema = registry.get_schema(name)
        if schema:
            # Mirror what gets sent to the API:
            # {"type": "function", "function": <schema>}
            text = _json.dumps({"type": "function", "function": schema})
            counts[name] = len(enc.encode(text))
    _tool_token_cache = counts
    return _tool_token_cache


def _prompt_toolset_checklist(platform_label: str, enabled: Set[str], platform: str = "cli") -> Set[str]:
    """Multi-select checklist of toolsets. Returns set of selected toolset keys."""
    from ector_cli.curses_ui import curses_checklist
    from toolsets import resolve_toolset

    # Pre-compute per-tool token counts (cached after first call).
    tool_tokens = _estimate_tool_tokens()

    effective_all = _get_effective_configurable_toolsets()
    # Drop platform-scoped toolsets that don't apply to this platform.
    effective = [
        (k, l, d) for (k, l, d) in effective_all
        if _toolset_allowed_for_platform(k, platform)
    ]

    labels = []
    for ts_key, ts_label, ts_desc in effective:
        suffix = ""
        if not _toolset_has_keys(ts_key) and (TOOL_CATEGORIES.get(ts_key) or TOOLSET_ENV_REQUIREMENTS.get(ts_key)):
            suffix = "  [no API key]"
        labels.append(f"{ts_label}  ({ts_desc}){suffix}")

    pre_selected = {
        i for i, (ts_key, _, _) in enumerate(effective)
        if ts_key in enabled
    }

    # Build a live status function that shows deduplicated total token cost.
    status_fn = None
    if tool_tokens:
        ts_keys = [ts_key for ts_key, _, _ in effective]

        def status_fn(chosen: set) -> str:
            # Collect unique tool names across all selected toolsets
            all_tools: set = set()
            for idx in chosen:
                all_tools.update(resolve_toolset(ts_keys[idx]))
            total = sum(tool_tokens.get(name, 0) for name in all_tools)
            if total >= 1000:
                return f"Contexto est. de ferramentas: ~{total / 1000:.1f}k tokens"
            return f"Contexto est. de ferramentas: ~{total} tokens"

    chosen = curses_checklist(
        f"Ferramentas para {platform_label}",
        labels,
        pre_selected,
        cancel_returns=pre_selected,
        status_fn=status_fn,
    )
    return {effective[i][0] for i in chosen}


# ─── Provider-Aware Configuration ────────────────────────────────────────────

def _configure_toolset(ts_key: str, config: dict):
    """Configure a toolset - provider selection + API keys.
    
    Uses TOOL_CATEGORIES for provider-aware config, falls back to simple
    env var prompts for toolsets not in TOOL_CATEGORIES.
    """
    cat = TOOL_CATEGORIES.get(ts_key)

    if cat:
        _configure_tool_category(ts_key, cat, config)
    else:
        # Simple fallback for vision, moa, etc.
        _configure_simple_requirements(ts_key)


def _plugin_image_gen_providers() -> list[dict]:
    """Build picker-row dicts from plugin-registered image gen providers.

    Each returned dict looks like a regular ``TOOL_CATEGORIES`` provider
    row but carries an ``image_gen_plugin_name`` marker so downstream
    code (config writing, model picker) knows to route through the
    plugin registry instead of the in-tree FAL backend.

    FAL is skipped — it's already exposed by the hardcoded
    ``TOOL_CATEGORIES["image_gen"]`` entries. When FAL gets ported to
    a plugin in a follow-up PR, the hardcoded entries go away and this
    function surfaces it alongside OpenAI automatically.
    """
    try:
        from agent.image_gen_registry import list_providers
        from ector_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        providers = list_providers()
    except Exception:
        return []

    rows: list[dict] = []
    for provider in providers:
        if getattr(provider, "name", None) == "fal":
            # FAL has its own hardcoded rows today.
            continue
        try:
            schema = provider.get_setup_schema()
        except Exception:
            continue
        if not isinstance(schema, dict):
            continue
        rows.append(
            {
                "name": schema.get("name", provider.display_name),
                "badge": schema.get("badge", ""),
                "tag": schema.get("tag", ""),
                "env_vars": schema.get("env_vars", []),
                "image_gen_plugin_name": provider.name,
            }
        )
    return rows


def _identity_logged_in() -> bool:
    try:
        from ector_cli import identity_auth

        return identity_auth.is_logged_in()
    except Exception:
        return False


def _visible_providers(cat: dict, config: dict) -> list[dict]:
    """Return provider entries visible for the current auth/config state."""
    visible = []
    for provider in cat.get("providers", []):
        if provider.get("requires_identity_auth") and not _identity_logged_in():
            continue
        visible.append(provider)

    # Inject plugin-registered image_gen backends (OpenAI today, more later).
    if cat.get("name") == "Image Generation":
        visible.extend(_plugin_image_gen_providers())

    return visible


def _toolset_needs_configuration_prompt(ts_key: str, config: dict) -> bool:
    """Return True when enabling this toolset should open provider setup."""
    cat = TOOL_CATEGORIES.get(ts_key)
    if not cat:
        return not _toolset_has_keys(ts_key, config)

    if ts_key == "tts":
        tts_cfg = config.get("tts", {})
        return not isinstance(tts_cfg, dict) or "provider" not in tts_cfg
    if ts_key == "web":
        web_cfg = config.get("web", {})
        return not isinstance(web_cfg, dict) or "backend" not in web_cfg
    if ts_key == "browser":
        browser_cfg = config.get("browser", {})
        return not isinstance(browser_cfg, dict) or "cloud_provider" not in browser_cfg
    if ts_key == "image_gen":
        # Satisfied when the in-tree FAL backend is configured OR any
        # plugin-registered image gen provider is available.
        if fal_key_is_configured():
            return False
        try:
            from agent.image_gen_registry import list_providers
            from ector_cli.plugins import _ensure_plugins_discovered

            _ensure_plugins_discovered()
            for provider in list_providers():
                try:
                    if provider.is_available():
                        return False
                except Exception:
                    continue
        except Exception:
            pass
        return True

    return not _toolset_has_keys(ts_key, config)


def _configure_tool_category(ts_key: str, cat: dict, config: dict):
    """Configure a tool category with provider selection."""
    icon = cat.get("icon", "")
    name = cat["name"]
    providers = _visible_providers(cat, config)

    # Check Python version requirement
    if cat.get("requires_python"):
        req = cat["requires_python"]
        if sys.version_info < req:
            print()
            _print_error(f"  {name} requer Python {req[0]}.{req[1]}+ (atual: {sys.version_info.major}.{sys.version_info.minor})")
            _print_info("  Atualize o Python e reinstale para ativar esta ferramenta.")
            return

    if len(providers) == 1:
        # Single provider - configure directly
        provider = providers[0]
        print()
        print(color(f"  --- {icon} {name} ({provider['name']}) ---", Colors.CYAN))
        if provider.get("tag"):
            _print_info(f"  {provider['tag']}")
        # For single-provider tools, show a note if available
        if cat.get("setup_note"):
            _print_info(f"  {cat['setup_note']}")
        _configure_provider(provider, config)
    else:
        # Multiple providers - let user choose
        print()
        # Use custom title if provided (e.g. "Select Search Provider")
        title = cat.get("setup_title", "Escolha um provedor")
        print(color(f"  --- {icon} {name} - {title} ---", Colors.CYAN))
        if cat.get("setup_note"):
            _print_info(f"  {cat['setup_note']}")
        print()

        # Plain text labels only (no ANSI codes in menu items)
        provider_choices = []
        for p in providers:
            badge = f" [{p['badge']}]" if p.get("badge") else ""
            tag = f" — {p['tag']}" if p.get("tag") else ""
            configured = ""
            env_vars = p.get("env_vars", [])
            if not env_vars or all(get_env_value(v["key"]) for v in env_vars):
                if _is_provider_active(p, config):
                    configured = " [active]"
                elif not env_vars:
                    configured = ""
                else:
                    configured = " [configured]"
            provider_choices.append(f"{p['name']}{badge}{tag}{configured}")

        # Add skip option
        provider_choices.append("Pular — manter padrões / configurar depois")

        # Detect current provider as default
        default_idx = _detect_active_provider_index(providers, config)

        provider_idx = _prompt_choice(f"  {title}:", provider_choices, default_idx)

        # Skip selected
        if provider_idx >= len(providers):
            _print_info(f"  Pulado {name}")
            return

        _configure_provider(providers[provider_idx], config)


def _is_provider_active(provider: dict, config: dict) -> bool:
    """Check if a provider entry matches the currently active config."""
    plugin_name = provider.get("image_gen_plugin_name")
    if plugin_name:
        image_cfg = config.get("image_gen", {})
        return isinstance(image_cfg, dict) and image_cfg.get("provider") == plugin_name

    if provider.get("tts_provider"):
        return config.get("tts", {}).get("provider") == provider["tts_provider"]
    if "browser_provider" in provider:
        current = config.get("browser", {}).get("cloud_provider")
        return provider["browser_provider"] == current
    if provider.get("web_backend"):
        current = config.get("web", {}).get("backend")
        return current == provider["web_backend"]
    if provider.get("imagegen_backend"):
        image_cfg = config.get("image_gen", {})
        if not isinstance(image_cfg, dict):
            return False
        configured_provider = image_cfg.get("provider")
        return (
            provider["imagegen_backend"] == "fal"
            and configured_provider in (None, "", "fal")
            and not is_truthy_value(image_cfg.get("use_gateway"), default=False)
        )
    return False


def _detect_active_provider_index(providers: list, config: dict) -> int:
    """Return the index of the currently active provider, or 0."""
    for i, p in enumerate(providers):
        if _is_provider_active(p, config):
            return i
        # Fallback: env vars present → likely configured
        env_vars = p.get("env_vars", [])
        if env_vars and all(get_env_value(v["key"]) for v in env_vars):
            return i
    return 0


# ─── Image Generation Model Pickers ───────────────────────────────────────────
#
# IMAGEGEN_BACKENDS is a per-backend catalog. Each entry exposes:
#   - config_key:        top-level config.yaml key for this backend's settings
#   - model_catalog_fn:  returns an OrderedDict-like {model_id: metadata}
#   - default_model:     fallback when nothing is configured
#
# This prepares for future imagegen backends (Replicate, Stability, etc.):
# each new backend registers its own entry; the FAL provider entry in
# TOOL_CATEGORIES tags itself with `imagegen_backend: "fal"` to select the
# right catalog at picker time.


def _fal_model_catalog():
    """Lazy-load the FAL model catalog from the tool module."""
    from tools.image_generation_tool import FAL_MODELS, DEFAULT_MODEL
    return FAL_MODELS, DEFAULT_MODEL


IMAGEGEN_BACKENDS = {
    "fal": {
        "display": "FAL.ai",
        "config_key": "image_gen",
        "catalog_fn": _fal_model_catalog,
    },
}


def _format_imagegen_model_row(model_id: str, meta: dict, widths: dict) -> str:
    """Format a single picker row with column-aligned speed / strengths / price."""
    return (
        f"{model_id:<{widths['model']}}  "
        f"{meta.get('speed', ''):<{widths['speed']}}  "
        f"{meta.get('strengths', ''):<{widths['strengths']}}  "
        f"{meta.get('price', '')}"
    )


def _configure_imagegen_model(backend_name: str, config: dict) -> None:
    """Prompt the user to pick a model for the given imagegen backend.

    Writes selection to ``config[backend_config_key]["model"]``. Safe to
    call even when stdin is not a TTY — curses_radiolist falls back to
    keeping the current selection.
    """
    backend = IMAGEGEN_BACKENDS.get(backend_name)
    if not backend:
        return

    catalog, default_model = backend["catalog_fn"]()
    if not catalog:
        return

    cfg_key = backend["config_key"]
    cur_cfg = config.setdefault(cfg_key, {})
    if not isinstance(cur_cfg, dict):
        cur_cfg = {}
        config[cfg_key] = cur_cfg
    current_model = cur_cfg.get("model") or default_model
    if current_model not in catalog:
        current_model = default_model

    model_ids = list(catalog.keys())
    # Put current model at the top so the cursor lands on it by default.
    ordered = [current_model] + [m for m in model_ids if m != current_model]

    # Column widths
    widths = {
        "model": max(len(m) for m in model_ids),
        "speed": max((len(catalog[m].get("speed", "")) for m in model_ids), default=6),
        "strengths": max((len(catalog[m].get("strengths", "")) for m in model_ids), default=0),
    }

    print()
    header = (
        f"  {'Modelo':<{widths['model']}}  "
        f"{'Velocidade':<{widths['speed']}}  "
        f"{'Pontos Fortes':<{widths['strengths']}}  "
        f"Preço"
    )
    print(color(header, Colors.CYAN))

    rows = []
    for mid in ordered:
        row = _format_imagegen_model_row(mid, catalog[mid], widths)
        if mid == current_model:
            row += "  ← atualmente em uso"
        rows.append(row)

    idx = _prompt_choice(
        f"  Escolha o modelo do {backend['display']}:",
        rows,
        default=0,
    )

    chosen = ordered[idx]
    cur_cfg["model"] = chosen
    _print_success(f"  Modelo definido para: {chosen}")


def _plugin_image_gen_catalog(plugin_name: str):
    """Return ``(catalog_dict, default_model_id)`` for a plugin provider.

    ``catalog_dict`` is shaped like the legacy ``FAL_MODELS`` table —
    ``{model_id: {"display", "speed", "strengths", "price", ...}}`` —
    so the existing picker code paths work without change. Returns
    ``({}, None)`` if the provider isn't registered or has no models.
    """
    try:
        from agent.image_gen_registry import get_provider
        from ector_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        provider = get_provider(plugin_name)
    except Exception:
        return {}, None
    if provider is None:
        return {}, None
    try:
        models = provider.list_models() or []
        default = provider.default_model()
    except Exception:
        return {}, None
    catalog = {m["id"]: m for m in models if isinstance(m, dict) and "id" in m}
    return catalog, default


def _configure_imagegen_model_for_plugin(plugin_name: str, config: dict) -> None:
    """Prompt the user to pick a model for a plugin-registered backend.

    Writes selection to ``image_gen.model``. Mirrors
    :func:`_configure_imagegen_model` but sources its catalog from the
    plugin registry instead of :data:`IMAGEGEN_BACKENDS`.
    """
    catalog, default_model = _plugin_image_gen_catalog(plugin_name)
    if not catalog:
        return

    cur_cfg = config.setdefault("image_gen", {})
    if not isinstance(cur_cfg, dict):
        cur_cfg = {}
        config["image_gen"] = cur_cfg
    current_model = cur_cfg.get("model") or default_model
    if current_model not in catalog:
        current_model = default_model

    model_ids = list(catalog.keys())
    ordered = [current_model] + [m for m in model_ids if m != current_model]

    widths = {
        "model": max(len(m) for m in model_ids),
        "speed": max((len(catalog[m].get("speed", "")) for m in model_ids), default=6),
        "strengths": max((len(catalog[m].get("strengths", "")) for m in model_ids), default=0),
    }

    print()
    header = (
        f"  {'Modelo':<{widths['model']}}  "
        f"{'Velocidade':<{widths['speed']}}  "
        f"{'Pontos Fortes':<{widths['strengths']}}  "
        f"Preço"
    )
    print(color(header, Colors.CYAN))

    rows = []
    for mid in ordered:
        row = _format_imagegen_model_row(mid, catalog[mid], widths)
        if mid == current_model:
            row += "  ← atualmente em uso"
        rows.append(row)

    idx = _prompt_choice(
        f"  Escolha o modelo do {plugin_name}:",
        rows,
        default=0,
    )

    chosen = ordered[idx]
    cur_cfg["model"] = chosen
    _print_success(f"  Modelo definido para: {chosen}")


def _select_plugin_image_gen_provider(plugin_name: str, config: dict) -> None:
    """Persist a plugin-backed image generation provider selection."""
    img_cfg = config.setdefault("image_gen", {})
    if not isinstance(img_cfg, dict):
        img_cfg = {}
        config["image_gen"] = img_cfg
    img_cfg["provider"] = plugin_name
    img_cfg["use_gateway"] = False
    _print_success(f"  image_gen.provider definido como: {plugin_name}")
    _configure_imagegen_model_for_plugin(plugin_name, config)


def _configure_provider(provider: dict, config: dict):
    """Configure a single provider - prompt for API keys and set config."""
    env_vars = provider.get("env_vars", [])

    if provider.get("requires_identity_auth") and not _identity_logged_in():
        _print_warning("  Este provedor requer `ector login` (identidade em ector.cc).")
        return

    # Set TTS provider in config if applicable
    if provider.get("tts_provider"):
        tts_cfg = config.setdefault("tts", {})
        tts_cfg["provider"] = provider["tts_provider"]
        tts_cfg["use_gateway"] = False

    # Set browser cloud provider in config if applicable
    if "browser_provider" in provider:
        bp = provider["browser_provider"]
        browser_cfg = config.setdefault("browser", {})
        if bp == "local":
            browser_cfg["cloud_provider"] = "local"
            _print_success("  Navegador definido para modo local")
        elif bp:
            browser_cfg["cloud_provider"] = bp
            _print_success(f"  Provedor de nuvem do navegador definido como: {bp}")
        browser_cfg["use_gateway"] = False

    # Set web search backend in config if applicable
    if provider.get("web_backend"):
        web_cfg = config.setdefault("web", {})
        web_cfg["backend"] = provider["web_backend"]
        web_cfg["use_gateway"] = False
        _print_success(f"  Backend web definido como: {provider['web_backend']}")

    # Clear legacy use_gateway when picking a direct provider.
    for cat_key, cat in TOOL_CATEGORIES.items():
        if provider in cat.get("providers", []):
            section = config.get(cat_key)
            if isinstance(section, dict) and section.get("use_gateway"):
                section["use_gateway"] = False
            break

    if not env_vars:
        if provider.get("post_setup"):
            _run_post_setup(provider["post_setup"])
        _print_success(f"  {provider['name']} - nenhuma configuração necessária!")
        # Plugin-registered image_gen provider: write image_gen.provider
        # and route model selection to the plugin's own catalog.
        plugin_name = provider.get("image_gen_plugin_name")
        if plugin_name:
            _select_plugin_image_gen_provider(plugin_name, config)
            return
        # Imagegen backends prompt for model selection after backend pick.
        backend = provider.get("imagegen_backend")
        if backend:
            _configure_imagegen_model(backend, config)
            # In-tree FAL is the only non-plugin backend today. Keep
            # image_gen.provider clear so the dispatch shim falls through
            # to the legacy FAL path.
            img_cfg = config.setdefault("image_gen", {})
            if isinstance(img_cfg, dict) and img_cfg.get("provider") not in (None, "", "fal"):
                img_cfg["provider"] = "fal"
        return

    # Prompt for each required env var
    all_configured = True
    for var in env_vars:
        existing = get_env_value(var["key"])
        if existing:
            _print_success(f"  {var['key']}: já configurado")
            # Don't ask to update - this is a new enable flow.
            # Reconfigure is handled separately.
        else:
            url = var.get("url", "")
            if url:
                _print_info(f"  Obtenha a sua em: {url}")

            default_val = var.get("default", "")
            if default_val:
                value = _prompt(f"    {var.get('prompt', var['key'])}", default_val)
            else:
                value = _prompt(f"    {var.get('prompt', var['key'])}", password=True)

            if value:
                save_env_value(var["key"], value)
                _print_success("    Salvo")
            else:
                _print_warning("    Pulado")
                all_configured = False

    # Run post-setup hooks if needed
    if provider.get("post_setup") and all_configured:
        _run_post_setup(provider["post_setup"])

    if all_configured:
        _print_success(f"  {provider['name']} configurado!")
        plugin_name = provider.get("image_gen_plugin_name")
        if plugin_name:
            _select_plugin_image_gen_provider(plugin_name, config)
            return
        # Imagegen backends prompt for model selection after env vars are in.
        backend = provider.get("imagegen_backend")
        if backend:
            _configure_imagegen_model(backend, config)
            img_cfg = config.setdefault("image_gen", {})
            if isinstance(img_cfg, dict) and img_cfg.get("provider") not in (None, "", "fal"):
                img_cfg["provider"] = "fal"


def _configure_simple_requirements(ts_key: str):
    """Simple fallback for toolsets that just need env vars (no provider selection)."""
    if ts_key == "vision":
        if _toolset_has_keys("vision"):
            return
        print()
        print(color("  Visão / Análise de Imagem requer um backend multimodal:", Colors.YELLOW))
        choices = [
            "OpenRouter — usa Gemini",
            "Endpoint compatível com OpenAI — URL base, chave API e modelo de visão",
            "Pular",
        ]
        idx = _prompt_choice("  Configurar backend de visão", choices, 2)
        if idx == 0:
            _print_info("  Obtenha a chave em: https://openrouter.ai/keys")
            value = _prompt("    OPENROUTER_API_KEY", password=True)
            if value and value.strip():
                save_env_value("OPENROUTER_API_KEY", value.strip())
                _print_success("    Salvo")
            else:
                _print_warning("    Pulado")
        elif idx == 1:
            base_url = _prompt("    OPENAI_BASE_URL (blank for OpenAI)").strip() or "https://api.openai.com/v1"
            is_native_openai = base_url_hostname(base_url) == "api.openai.com"
            key_label = "    OPENAI_API_KEY" if is_native_openai else "    API key"
            api_key = _prompt(key_label, password=True)
            if api_key and api_key.strip():
                save_env_value("OPENAI_API_KEY", api_key.strip())
                # Save vision base URL to config (not .env — only secrets go there)
                _cfg = load_config()
                _aux = _cfg.setdefault("auxiliary", {}).setdefault("vision", {})
                _aux["base_url"] = base_url
                save_config(_cfg)
                if is_native_openai:
                    save_env_value("AUXILIARY_VISION_MODEL", "gpt-4o-mini")
                _print_success("    Salvo")
            else:
                _print_warning("    Pulado")
        return

    requirements = TOOLSET_ENV_REQUIREMENTS.get(ts_key, [])
    if not requirements:
        return

    missing = [(var, url) for var, url in requirements if not get_env_value(var)]
    if not missing:
        return

    ts_label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts_key), ts_key)
    print()
    print(color(f"  {ts_label} requer configuração:", Colors.YELLOW))

    for var, url in missing:
        if url:
            _print_info(f"  Get key at: {url}")
        value = _prompt(f"    {var}", password=True)
        if value and value.strip():
            save_env_value(var, value.strip())
            _print_success("    Salvo")
        else:
            _print_warning("    Pulado")


def _reconfigure_tool(config: dict):
    """Let user reconfigure an existing tool's provider or API key."""
    # Build list of configurable tools that are currently set up
    configurable = []
    for ts_key, ts_label, _ in _get_effective_configurable_toolsets():
        cat = TOOL_CATEGORIES.get(ts_key)
        reqs = TOOLSET_ENV_REQUIREMENTS.get(ts_key)
        if cat or reqs:
            if _toolset_has_keys(ts_key, config):
                configurable.append((ts_key, ts_label))

    if not configurable:
        _print_info("Nenhuma ferramenta configurada para reconfigurar.")
        return

    choices = [label for _, label in configurable]
    choices.append("Cancelar")

    idx = _prompt_choice("  Qual ferramenta você gostaria de reconfigurar?", choices, len(choices) - 1)

    if idx >= len(configurable):
        return  # Cancel

    ts_key, ts_label = configurable[idx]
    cat = TOOL_CATEGORIES.get(ts_key)

    if cat:
        _configure_tool_category_for_reconfig(ts_key, cat, config)
    else:
        _reconfigure_simple_requirements(ts_key)

    save_config(config)


def _configure_tool_category_for_reconfig(ts_key: str, cat: dict, config: dict):
    """Reconfigure a tool category - provider selection + API key update."""
    icon = cat.get("icon", "")
    name = cat["name"]
    providers = _visible_providers(cat, config)

    if len(providers) == 1:
        provider = providers[0]
        print()
        print(color(f"  --- {icon} {name} ({provider['name']}) ---", Colors.CYAN))
        _reconfigure_provider(provider, config)
    else:
        print()
        print(color(f"  --- {icon} {name} - Escolha um provedor ---", Colors.CYAN))
        print()

        provider_choices = []
        for p in providers:
            badge = f" [{p['badge']}]" if p.get("badge") else ""
            tag = f" — {p['tag']}" if p.get("tag") else ""
            configured = ""
            env_vars = p.get("env_vars", [])
            if not env_vars or all(get_env_value(v["key"]) for v in env_vars):
                if _is_provider_active(p, config):
                    configured = " [ativo]"
                elif not env_vars:
                    configured = ""
                else:
                    configured = " [configurado]"
            provider_choices.append(f"{p['name']}{badge}{tag}{configured}")

        default_idx = _detect_active_provider_index(providers, config)

        provider_idx = _prompt_choice("  Selecione o provedor:", provider_choices, default_idx)
        _reconfigure_provider(providers[provider_idx], config)


def _reconfigure_provider(provider: dict, config: dict):
    """Reconfigure a provider - update API keys."""
    env_vars = provider.get("env_vars", [])

    if provider.get("requires_identity_auth") and not _identity_logged_in():
        _print_warning("  Este provedor requer `ector login` (identidade em ector.cc).")
        return

    if provider.get("tts_provider"):
        config.setdefault("tts", {})["provider"] = provider["tts_provider"]
        _print_success(f"  Provedor TTS definido como: {provider['tts_provider']}")

    if "browser_provider" in provider:
        bp = provider["browser_provider"]
        if bp == "local":
            config.setdefault("browser", {})["cloud_provider"] = "local"
            _print_success("  Browser set to local mode")
        elif bp:
            config.setdefault("browser", {})["cloud_provider"] = bp
            _print_success(f"  Provedor de nuvem do navegador definido como: {bp}")

    # Set web search backend in config if applicable
    if provider.get("web_backend"):
        config.setdefault("web", {})["backend"] = provider["web_backend"]
        _print_success(f"  Web backend set to: {provider['web_backend']}")

    for cat_key, cat in TOOL_CATEGORIES.items():
        if provider in cat.get("providers", []):
            section = config.get(cat_key)
            if isinstance(section, dict) and section.get("use_gateway"):
                section["use_gateway"] = False
            break

    if not env_vars:
        if provider.get("post_setup"):
            _run_post_setup(provider["post_setup"])
        _print_success(f"  {provider['name']} - nenhuma configuração necessária!")
        plugin_name = provider.get("image_gen_plugin_name")
        if plugin_name:
            _select_plugin_image_gen_provider(plugin_name, config)
            return
        # Imagegen backends prompt for model selection on reconfig too.
        backend = provider.get("imagegen_backend")
        if backend:
            _configure_imagegen_model(backend, config)
            if backend == "fal":
                img_cfg = config.setdefault("image_gen", {})
                if isinstance(img_cfg, dict):
                    img_cfg["provider"] = "fal"
                    img_cfg["use_gateway"] = False
        return

    for var in env_vars:
        existing = get_env_value(var["key"])
        if existing:
            _print_info(f"  {var['key']}: configurado ({existing[:8]}...)")
        url = var.get("url", "")
        if url:
            _print_info(f"  Obtenha a sua em: {url}")
        default_val = var.get("default", "")
        value = _prompt(f"    {var.get('prompt', var['key'])} (Enter para manter atual)", password=not default_val)
        if value and value.strip():
            save_env_value(var["key"], value.strip())
            _print_success("    Atualizado")
        else:
            _print_info("    Mantido atual")

    # Imagegen backends prompt for model selection on reconfig too.
    plugin_name = provider.get("image_gen_plugin_name")
    if plugin_name:
        _select_plugin_image_gen_provider(plugin_name, config)
        return

    backend = provider.get("imagegen_backend")
    if backend:
        _configure_imagegen_model(backend, config)
        if backend == "fal":
            img_cfg = config.setdefault("image_gen", {})
            if isinstance(img_cfg, dict):
                img_cfg["provider"] = "fal"
                img_cfg["use_gateway"] = False


def _reconfigure_simple_requirements(ts_key: str):
    """Reconfigure simple env var requirements."""
    requirements = TOOLSET_ENV_REQUIREMENTS.get(ts_key, [])
    if not requirements:
        return

    ts_label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts_key), ts_key)
    print()
    print(color(f"  {ts_label}:", Colors.CYAN))

    for var, url in requirements:
        existing = get_env_value(var)
        if existing:
            _print_info(f"  {var}: configurado ({existing[:8]}...)")
        if url:
            _print_info(f"  Obtenha a chave em: {url}")
        value = _prompt(f"    {var} (Enter para manter atual)", password=True)
        if value and value.strip():
            save_env_value(var, value.strip())
            _print_success("    Atualizado")
        else:
            _print_info("    Mantido atual")


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def tools_command(args=None, first_install: bool = False, config: dict = None):
    """Entry point for `ector tools` and `ector setup tools`.

    Args:
        first_install: When True (set by the setup wizard on fresh installs),
            skip the platform menu, go straight to the CLI checklist, and
            prompt for API keys on all enabled tools that need them.
        config: Optional config dict to use.  When called from the setup
            wizard, the wizard passes its own dict so that platform_toolsets
            are written into it and survive the wizard's final save_config().
    """
    if config is None:
        config = load_config()
    enabled_platforms = _get_enabled_platforms()

    print()

    # Non-interactive summary mode for CLI usage
    if getattr(args, "summary", False):
        total = len(_get_effective_configurable_toolsets())
        print(color("Resumo de Ferramentas", Colors.CYAN, Colors.BOLD))
        print()
        summary = _platform_toolset_summary(config, enabled_platforms)
        for pkey in enabled_platforms:
            pinfo = PLATFORMS[pkey]
            enabled = summary.get(pkey, set())
            count = len(enabled)
            print(color(f"  {pinfo['label']}", Colors.BOLD) + color(f"  ({count}/{total})", Colors.DIM))
            if enabled:
                for ts_key in sorted(enabled):
                    label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts_key), ts_key)
                    print(color(f"    ✔ {label}", Colors.GREEN))
            else:
                print(color("    (nenhuma ativada)", Colors.DIM))
        print()
        return
    print(color("Configuração de Ferramentas Ector", Colors.CYAN, Colors.BOLD))
    print(color("  Ative ou desative ferramentas por plataforma.", Colors.DIM))
    print(color("  Ferramentas que precisam de chaves API serão configuradas ao serem ativadas.", Colors.DIM))
    print(color("  Guia: https://ector.cc/docs/user-guide/features/tools", Colors.DIM))
    print()

    # ── First-time install: linear flow, no platform menu ──
    if first_install:
        for pkey in enabled_platforms:
            pinfo = PLATFORMS[pkey]
            current_enabled = _get_platform_tools(config, pkey, include_default_mcp_servers=False)

            # Uncheck toolsets that should be off by default
            checklist_preselected = current_enabled - _DEFAULT_OFF_TOOLSETS

            # Show checklist
            new_enabled = _prompt_toolset_checklist(pinfo["label"], checklist_preselected, pkey)

            added = new_enabled - current_enabled
            removed = current_enabled - new_enabled
            if added:
                for ts in sorted(added):
                    label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts), ts)
                    print(color(f"  + {label}", Colors.GREEN))
            if removed:
                for ts in sorted(removed):
                    label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts), ts)
                    print(color(f"  - {label}", Colors.RED))

            # Walk through ALL selected tools that have provider options or
            # need API keys.  This ensures browser (Local vs Browserbase),
            # TTS (Edge vs OpenAI vs ElevenLabs), etc. are shown even when
            # a free provider exists.
            to_configure = [
                ts_key for ts_key in sorted(new_enabled)
                if TOOL_CATEGORIES.get(ts_key) or TOOLSET_ENV_REQUIREMENTS.get(ts_key)
            ]

            if to_configure:
                print()
                print(color(f"  Configurando {len(to_configure)} ferramenta(s):", Colors.DIM))
                for ts_key in to_configure:
                    label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts_key), ts_key)
                    print(color(f"    • {label}", Colors.DIM))
                print(color("  Você pode pular qualquer ferramenta que não precise agora.", Colors.DIM))
                print()
                for ts_key in to_configure:
                    _configure_toolset(ts_key, config)

            _save_platform_tools(config, pkey, new_enabled)
            save_config(config)
            _print_success(f"  ✔ Salva configuração de ferramentas do {pinfo['label']}")
            print()

        return

    # ── Returning user: platform menu loop ──
    # Build platform choices
    platform_choices = []
    platform_keys = []
    for pkey in enabled_platforms:
        pinfo = PLATFORMS[pkey]
        current = _get_platform_tools(config, pkey, include_default_mcp_servers=False)
        count = len(current)
        total = len(_get_effective_configurable_toolsets())
        platform_choices.append(f"Configurar {pinfo['label']}  ({count}/{total} ativadas)")
        platform_keys.append(pkey)

    if len(platform_keys) > 1:
        platform_choices.append("Configurar todas as plataformas (global)")
    platform_choices.append("Reconfigurar o provedor ou chave API de uma ferramenta existente")

    # Show MCP option if any MCP servers are configured
    _has_mcp = bool(config.get("mcp_servers"))
    if _has_mcp:
        platform_choices.append("Configurar ferramentas do servidor MCP")

    platform_choices.append("Concluído")

    # Index offsets for the extra options after per-platform entries
    _global_idx = len(platform_keys) if len(platform_keys) > 1 else -1
    _reconfig_idx = len(platform_keys) + (1 if len(platform_keys) > 1 else 0)
    _mcp_idx = (_reconfig_idx + 1) if _has_mcp else -1
    _done_idx = _reconfig_idx + (2 if _has_mcp else 1)

    while True:
        idx = _prompt_choice("Selecione uma opção:", platform_choices, default=0)

        # "Done" selected
        if idx == _done_idx:
            break

        # "Reconfigure" selected
        if idx == _reconfig_idx:
            _reconfigure_tool(config)
            print()
            continue

        # "Configure MCP tools" selected
        if idx == _mcp_idx:
            _configure_mcp_tools_interactive(config)
            print()
            continue

        # "Configure all platforms (global)" selected
        if idx == _global_idx:
            # Use the union of all platforms' current tools as the starting state
            all_current = set()
            for pk in platform_keys:
                all_current |= _get_platform_tools(config, pk, include_default_mcp_servers=False)
            new_enabled = _prompt_toolset_checklist("All platforms", all_current)
            if new_enabled != all_current:
                for pk in platform_keys:
                    prev = _get_platform_tools(config, pk, include_default_mcp_servers=False)
                    added = new_enabled - prev
                    removed = prev - new_enabled
                    pinfo_inner = PLATFORMS[pk]
                    if added or removed:
                        print(color(f"  {pinfo_inner['label']}:", Colors.DIM))
                        for ts in sorted(added):
                            label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts), ts)
                            print(color(f"    + {label}", Colors.GREEN))
                        for ts in sorted(removed):
                            label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts), ts)
                            print(color(f"    - {label}", Colors.RED))
                    # Configure API keys for newly enabled tools
                    for ts_key in sorted(added):
                        if (TOOL_CATEGORIES.get(ts_key) or TOOLSET_ENV_REQUIREMENTS.get(ts_key)):
                            if _toolset_needs_configuration_prompt(ts_key, config):
                                _configure_toolset(ts_key, config)
                    _save_platform_tools(config, pk, new_enabled)
                save_config(config)
                print(color("  ✔ Configuração salva para todas as plataformas", Colors.GREEN))
                # Update choice labels
                for ci, pk in enumerate(platform_keys):
                    new_count = len(_get_platform_tools(config, pk, include_default_mcp_servers=False))
                    total = len(_get_effective_configurable_toolsets())
                    platform_choices[ci] = f"Configure {PLATFORMS[pk]['label']}  ({new_count}/{total} enabled)"
            else:
                print(color("  Nenhuma alteração", Colors.DIM))
            print()
            continue

        pkey = platform_keys[idx]
        pinfo = PLATFORMS[pkey]

        # Get current enabled toolsets for this platform
        current_enabled = _get_platform_tools(config, pkey, include_default_mcp_servers=False)

        # Show checklist
        new_enabled = _prompt_toolset_checklist(pinfo["label"], current_enabled)

        if new_enabled != current_enabled:
            added = new_enabled - current_enabled
            removed = current_enabled - new_enabled

            if added:
                for ts in sorted(added):
                    label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts), ts)
                    print(color(f"  + {label}", Colors.GREEN))
            if removed:
                for ts in sorted(removed):
                    label = next((l for k, l, _ in _get_effective_configurable_toolsets() if k == ts), ts)
                    print(color(f"  - {label}", Colors.RED))

            # Configure newly enabled toolsets that need API keys
            for ts_key in sorted(added):
                if (TOOL_CATEGORIES.get(ts_key) or TOOLSET_ENV_REQUIREMENTS.get(ts_key)):
                    if _toolset_needs_configuration_prompt(ts_key, config):
                        _configure_toolset(ts_key, config)

            _save_platform_tools(config, pkey, new_enabled)
            save_config(config)
            print(color(f"  ✔ Configuração do {pinfo['label']} salva", Colors.GREEN))
        else:
            print(color(f"  Nenhuma alteração no {pinfo['label']}", Colors.DIM))

        print()

        # Update the choice label with new count
        new_count = len(_get_platform_tools(config, pkey, include_default_mcp_servers=False))
        total = len(_get_effective_configurable_toolsets())
        platform_choices[idx] = f"Configurar {pinfo['label']}  ({new_count}/{total} ativadas)"

    print()
    from ector_constants import display_ector_home
    print(color(f"  Configuração de ferramentas salva em {display_ector_home()}/config.yaml", Colors.DIM))
    print(color("  As alterações entram em vigor na próxima reinicialização do 'ector' ou do gateway.", Colors.DIM))
    print()


# ─── MCP Tools Interactive Configuration ─────────────────────────────────────


def _configure_mcp_tools_interactive(config: dict):
    """Probe MCP servers for available tools and let user toggle them on/off.

    Connects to each configured MCP server, discovers tools, then shows
    a per-server curses checklist.  Writes changes back as ``tools.exclude``
    entries in config.yaml.
    """
    from ector_cli.curses_ui import curses_checklist

    mcp_servers = config.get("mcp_servers") or {}
    if not mcp_servers:
        _print_info("Nenhum servidor MCP configurado.")
        return

    # Count enabled servers
    enabled_names = [
        k for k, v in mcp_servers.items()
        if v.get("enabled", True) not in (False, "false", "0", "no", "off")
    ]
    if not enabled_names:
        _print_info("Todos os servidores MCP estão desativados.")
        return

    print()
    print(color("  Descobrindo ferramentas nos servidores MCP...", Colors.YELLOW))
    print(color(f"  Conectando a {len(enabled_names)} servidor(es): {', '.join(enabled_names)}", Colors.DIM))

    try:
        from tools.mcp_tool import probe_mcp_server_tools
        server_tools = probe_mcp_server_tools()
    except Exception as exc:
        _print_error(f"Falha ao sondar servidores MCP: {exc}")
        return

    if not server_tools:
        _print_warning("Não foi possível descobrir ferramentas de nenhum servidor MCP.")
        _print_info("Verifique se os comandos/URLs do servidor estão corretos e as dependências estão instaladas.")
        return

    # Report discovery results
    failed = [n for n in enabled_names if n not in server_tools]
    if failed:
        for name in failed:
            _print_warning(f"  Não foi possível conectar a '{name}'")

    total_tools = sum(len(tools) for tools in server_tools.values())
    print(color(f"  Encontrada(s) {total_tools} ferramenta(s) em {len(server_tools)} servidor(es)", Colors.GREEN))
    print()

    any_changes = False

    for server_name, tools in server_tools.items():
        if not tools:
            _print_info(f"  {server_name}: no tools found")
            continue

        srv_cfg = mcp_servers.get(server_name, {})
        tools_cfg = srv_cfg.get("tools") or {}
        include_list = tools_cfg.get("include") or []
        exclude_list = tools_cfg.get("exclude") or []

        # Build checklist labels
        labels = []
        for tool_name, description in tools:
            desc_short = description[:70] + "..." if len(description) > 70 else description
            if desc_short:
                labels.append(f"{tool_name}  ({desc_short})")
            else:
                labels.append(tool_name)

        # Determine which tools are currently enabled
        pre_selected: Set[int] = set()
        tool_names = [t[0] for t in tools]
        for i, tool_name in enumerate(tool_names):
            if include_list:
                # Include mode: only included tools are selected
                if tool_name in include_list:
                    pre_selected.add(i)
            elif exclude_list:
                # Exclude mode: everything except excluded
                if tool_name not in exclude_list:
                    pre_selected.add(i)
            else:
                # No filter: all enabled
                pre_selected.add(i)

        chosen = curses_checklist(
            f"Servidor MCP: {server_name}  ({len(tools)} ferramentas)",
            labels,
            pre_selected,
            cancel_returns=pre_selected,
        )

        if chosen == pre_selected:
            _print_info(f"  {server_name}: nenhuma alteração")
            continue

        # Compute new exclude list based on unchecked tools
        new_exclude = [tool_names[i] for i in range(len(tool_names)) if i not in chosen]

        # Update config
        srv_cfg = mcp_servers.setdefault(server_name, {})
        tools_cfg = srv_cfg.setdefault("tools", {})

        if new_exclude:
            tools_cfg["exclude"] = new_exclude
            # Remove include if present — we're switching to exclude mode
            tools_cfg.pop("include", None)
        else:
            # All tools enabled — clear filters
            tools_cfg.pop("exclude", None)
            tools_cfg.pop("include", None)

        enabled_count = len(chosen)
        disabled_count = len(tools) - enabled_count
        _print_success(
            f"  {server_name}: {enabled_count} enabled, {disabled_count} disabled"
        )
        any_changes = True

    if any_changes:
        save_config(config)
        print()
        print(color("  ✔ Configuração de ferramentas MCP salva", Colors.GREEN))
    else:
        print(color("  Nenhuma alteração nas ferramentas MCP", Colors.DIM))


# ─── Non-interactive disable/enable ──────────────────────────────────────────


def _apply_toolset_change(config: dict, platform: str, toolset_names: List[str], action: str):
    """Add or remove built-in toolsets for a platform."""
    enabled = _get_platform_tools(config, platform, include_default_mcp_servers=False)
    if action == "disable":
        updated = enabled - set(toolset_names)
    else:
        updated = enabled | set(toolset_names)
    _save_platform_tools(config, platform, updated)


def _apply_mcp_change(config: dict, targets: List[str], action: str) -> Set[str]:
    """Add or remove specific MCP tools from a server's exclude list.

    Returns the set of server names that were not found in config.
    """
    failed_servers: Set[str] = set()
    mcp_servers = config.get("mcp_servers") or {}

    for target in targets:
        server_name, tool_name = target.split(":", 1)
        if server_name not in mcp_servers:
            failed_servers.add(server_name)
            continue
        tools_cfg = mcp_servers[server_name].setdefault("tools", {})
        exclude = list(tools_cfg.get("exclude") or [])
        if action == "disable":
            if tool_name not in exclude:
                exclude.append(tool_name)
        else:
            exclude = [t for t in exclude if t != tool_name]
        tools_cfg["exclude"] = exclude

    return failed_servers


def _print_tools_list(enabled_toolsets: set, mcp_servers: dict, platform: str = "cli"):
    """Print a summary of enabled/disabled toolsets and MCP tool filters."""
    effective_all = _get_effective_configurable_toolsets()
    effective = [
        (k, l, d) for (k, l, d) in effective_all
        if _toolset_allowed_for_platform(k, platform)
    ]
    builtin_keys = {ts_key for ts_key, _, _ in CONFIGURABLE_TOOLSETS}

    print(f"Conjuntos de ferramentas integrados ({platform}):")
    for ts_key, label, _ in effective:
        if ts_key not in builtin_keys:
            continue
        status = (color("✔ enabled", Colors.GREEN) if ts_key in enabled_toolsets
                  else color("✖ disabled", Colors.RED))
        print(f"  {status}  {ts_key}  {color(label, Colors.DIM)}")

    # Plugin toolsets
    plugin_entries = [(k, l) for k, l, _ in effective if k not in builtin_keys]
    if plugin_entries:
        print()
        print(f"Plugin toolsets ({platform}):")
        for ts_key, label in plugin_entries:
            status = (color("✔ enabled", Colors.GREEN) if ts_key in enabled_toolsets
                      else color("✖ disabled", Colors.RED))
            print(f"  {status}  {ts_key}  {color(label, Colors.DIM)}")

    if mcp_servers:
        print()
        print("MCP servers:")
        for srv_name, srv_cfg in mcp_servers.items():
            tools_cfg = srv_cfg.get("tools") or {}
            exclude = tools_cfg.get("exclude") or []
            include = tools_cfg.get("include") or []
            if include:
                _print_info(f"{srv_name}  [include only: {', '.join(include)}]")
            elif exclude:
                _print_info(f"{srv_name}  [excluded: {color(', '.join(exclude), Colors.YELLOW)}]")
            else:
                _print_info(f"{srv_name}  {color('all tools enabled', Colors.DIM)}")


def tools_disable_enable_command(args):
    """Enable, disable, or list tools for a platform.

    Built-in toolsets use plain names (e.g. ``web``, ``memory``).
    MCP tools use ``server:tool`` notation (e.g. ``github:create_issue``).
    """
    action = args.tools_action
    platform = getattr(args, "platform", "cli")
    config = load_config()

    if platform not in PLATFORMS:
        _print_error(f"Plataforma desconhecida '{platform}'. Válidas: {', '.join(PLATFORMS)}")
        return

    if action == "list":
        _print_tools_list(_get_platform_tools(config, platform, include_default_mcp_servers=False),
                          config.get("mcp_servers") or {}, platform)
        return

    targets: List[str] = args.names
    toolset_targets = [t for t in targets if ":" not in t]
    mcp_targets = [t for t in targets if ":" in t]

    valid_toolsets = {ts_key for ts_key, _, _ in CONFIGURABLE_TOOLSETS} | _get_plugin_toolset_keys()
    unknown_toolsets = [t for t in toolset_targets if t not in valid_toolsets]
    if unknown_toolsets:
        for name in unknown_toolsets:
            _print_error(f"Conjunto de ferramentas desconhecido '{name}'")
        toolset_targets = [t for t in toolset_targets if t in valid_toolsets]

    # Reject platform-scoped toolsets on platforms that don't allow them.
    restricted_targets = [
        t for t in toolset_targets
        if not _toolset_allowed_for_platform(t, platform)
    ]
    if restricted_targets:
        for name in restricted_targets:
            allowed = sorted(_TOOLSET_PLATFORM_RESTRICTIONS.get(name) or set())
            _print_error(
                f"Conjunto de ferramentas '{name}' não está disponível na plataforma '{platform}' "
                f"(apenas: {', '.join(allowed)})"
            )
        toolset_targets = [t for t in toolset_targets if t not in restricted_targets]

    if toolset_targets:
        _apply_toolset_change(config, platform, toolset_targets, action)

    failed_servers: Set[str] = set()
    if mcp_targets:
        failed_servers = _apply_mcp_change(config, mcp_targets, action)
        for srv in failed_servers:
            _print_error(f"MCP server '{srv}' not found in config")

    save_config(config)

    successful = [
        t for t in targets
        if t not in unknown_toolsets and (":" not in t or t.split(":")[0] not in failed_servers)
    ]
    if successful:
        verb = "Disabled" if action == "disable" else "Enabled"
        _print_success(f"{verb}: {', '.join(successful)}")
