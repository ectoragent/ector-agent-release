"""
Configuration management for ECTOR.

Config files are stored in ``~/.ector/`` by default (legacy installs may still use ``~/.ector/``):
- ``~/.ector/config.yaml``  - All settings (model, toolsets, terminal, etc.)
- ``~/.ector/.env``         - API keys and secrets

This module provides:
- ``ector config``          - Show current configuration
- ``ector config edit``     - Open config in editor
- ``ector config wizard``   - Re-run setup wizard
"""

import copy
import logging
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"
_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LAST_EXPANDED_CONFIG_BY_PATH: Dict[str, Any] = {}
# Env var names written to .env that aren't in OPTIONAL_ENV_VARS
# (managed by setup/provider flows directly).
_EXTRA_ENV_KEYS = frozenset({
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN",
    "DISCORD_HOME_CHANNEL", "TELEGRAM_HOME_CHANNEL",
    "SLACK_HOME_CHANNEL", "SLACK_HOME_CHANNEL_NAME",
    "WHATSAPP_MODE", "WHATSAPP_ENABLED", "WHATSAPP_ALLOWED_USERS",
    "WHATSAPP_HOME_CHANNEL", "WHATSAPP_HOME_CHANNEL_NAME",
    "TERMINAL_ENV", "TERMINAL_SSH_KEY", "TERMINAL_SSH_PORT",
    # Ector-prefixed tool/runtime env vars (also listed in OPTIONAL_ENV_VARS).
    "ECTOR_QWEN_BASE_URL",
    "ECTOR_DOCKER_BINARY",
    "ECTOR_HUMAN_DELAY_MODE", "ECTOR_HUMAN_DELAY_MIN_MS", "ECTOR_HUMAN_DELAY_MAX_MS",
})
import yaml

from ector_cli.colors import Colors, color
from ector_cli.default_soul import DEFAULT_SOUL_MD


# =============================================================================
# Managed mode (NixOS declarative config)
# =============================================================================

_MANAGED_TRUE_VALUES = ("true", "1", "yes")
_MANAGED_SYSTEM_NAMES = {
    "brew": "Homebrew",
    "homebrew": "Homebrew",
    "nix": "NixOS",
    "nixos": "NixOS",
}


def get_managed_system() -> Optional[str]:
    """Return the package manager owning this install, if any."""
    raw = os.getenv("ECTOR_MANAGED", "").strip()
    if raw:
        normalized = raw.lower()
        if normalized in _MANAGED_TRUE_VALUES:
            return "NixOS"
        return _MANAGED_SYSTEM_NAMES.get(normalized, raw)

    managed_marker = get_ector_home() / ".managed"
    if managed_marker.exists():
        return "NixOS"
    return None


def is_managed() -> bool:
    """Check if Ector is running in package-manager-managed mode.

    Two signals: the ECTOR_MANAGED env var (set by the systemd service),
    or a .managed marker file in ECTOR_HOME (set by the NixOS activation
    script, so interactive shells also see it).
    """
    return get_managed_system() is not None


def get_managed_update_command() -> Optional[str]:
    """Return the preferred upgrade command for a managed install."""
    managed_system = get_managed_system()
    if managed_system == "Homebrew":
        return "brew upgrade ector-agent"
    if managed_system == "NixOS":
        return "sudo nixos-rebuild switch"
    return None


def recommended_update_command() -> str:
    """Return the best upgrade hint for the current installation."""
    managed = get_managed_update_command()
    if managed:
        return managed
    try:
        from ector_cli.install_paths import resolve_install_dir

        if resolve_install_dir() is not None:
            return "ector update"
    except Exception:
        pass
    return "curl -fsSL https://ector.cc/install.sh | bash"


def format_managed_message(action: str = "modify this Ector installation") -> str:
    """Build a user-facing error for managed installs."""
    managed_system = get_managed_system() or "a package manager"
    raw = os.getenv("ECTOR_MANAGED", "").strip().lower()

    if managed_system == "NixOS":
        env_hint = "true" if raw in _MANAGED_TRUE_VALUES else raw or "true"
        return (
            f"Não é possível {action}: esta instalação do ECTOR é gerenciada pelo NixOS "
            f"(ECTOR_MANAGED={env_hint}).\n"
            "Edite services.ector-agent.settings no seu configuration.nix e execute:\n"
            "  sudo nixos-rebuild switch"
        )

    if managed_system == "Homebrew":
        env_hint = raw or "homebrew"
        return (
            f"Não é possível {action}: esta instalação do ECTOR é gerenciada pelo Homebrew "
            f"(ECTOR_MANAGED={env_hint}).\n"
            "Use:\n"
            "  brew upgrade ector-agent"
        )

    return (
        f"Não é possível {action}: esta instalação do ECTOR é gerenciada por {managed_system}.\n"
        "Use seu gerenciador de pacotes para atualizar ou reinstalar o Ector."
    )

def managed_error(action: str = "modificar a configuração"):
    """Exibe erro amigável para o modo gerenciado."""
    print(format_managed_message(action), file=sys.stderr)


# =============================================================================
# Container-aware CLI (NixOS container mode)
# =============================================================================

def get_container_exec_info() -> Optional[dict]:
    """Read container mode metadata from ECTOR_HOME/.container-mode.

    Returns a dict with keys: backend, container_name, exec_user, ector_bin
    or None if container mode is not active, we're already inside the
    container, or ECTOR_DEV=1 is set.

    The .container-mode file is written by the NixOS activation script when
    container.enable = true. It tells the host CLI to exec into the container
    instead of running locally.
    """
    if os.environ.get("ECTOR_DEV") == "1":
        return None

    from ector_constants import is_container
    if is_container():
        return None

    container_mode_file = get_ector_home() / ".container-mode"

    try:
        info = {}
        with open(container_mode_file, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    info[key.strip()] = value.strip()
    except FileNotFoundError:
        return None
    # All other exceptions (PermissionError, malformed data, etc.) propagate

    backend = info.get("backend", "docker")
    container_name = info.get("container_name", "ector-agent")
    exec_user = info.get("exec_user", "ector")
    ector_bin = info.get("ector_bin", "/data/current-package/bin/ector")

    return {
        "backend": backend,
        "container_name": container_name,
        "exec_user": exec_user,
        "ector_bin": ector_bin,
    }


# =============================================================================
# Config paths
# =============================================================================

# Re-export from ector_constants — canonical definition lives there.
from ector_constants import display_ector_home, get_ector_home  # noqa: F811,E402

def get_config_path() -> Path:
    """Get the main config file path."""
    return get_ector_home() / "config.yaml"

def get_env_path() -> Path:
    """Get the .env file path (for API keys)."""
    return get_ector_home() / ".env"

def get_project_root() -> Path:
    """Get the project installation directory."""
    return Path(__file__).parent.parent.resolve()

def _secure_dir(path):
    """Set directory to owner-only access (0700 by default). No-op on Windows.

    Skipped in managed mode — the NixOS module sets group-readable
    permissions (0750) so interactive users in the ector group can
    share state with the gateway service.

    The mode can be overridden via the ECTOR_HOME_MODE environment variable
    (e.g. ECTOR_HOME_MODE=0701) for deployments where a web server (nginx,
    caddy, etc.) needs to traverse ECTOR_HOME to reach a served subdirectory.
    The execute-only bit on a directory permits cd-through without exposing
    directory listings.
    """
    if is_managed():
        return
    try:
        mode_str = os.environ.get("ECTOR_HOME_MODE", "").strip()
        mode = int(mode_str, 8) if mode_str else 0o700
    except ValueError:
        mode = 0o700
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _is_container() -> bool:
    """Detect if we're running inside a Docker/Podman/LXC container.

    When Ector runs in a container with volume-mounted config files, forcing
    0o600 permissions breaks multi-process setups where the gateway and
    dashboard run as different UIDs or the volume mount requires broader
    permissions.
    """
    # Explicit opt-out
    if os.environ.get("ECTOR_CONTAINER") or os.environ.get("ECTOR_SKIP_CHMOD"):
        return True
    # Docker / Podman marker file
    if os.path.exists("/.dockerenv"):
        return True
    # LXC / cgroup-based detection
    try:
        with open("/proc/1/cgroup", "r") as f:
            cgroup_content = f.read()
        if "docker" in cgroup_content or "lxc" in cgroup_content or "kubepods" in cgroup_content:
            return True
    except (OSError, IOError):
        pass
    return False


def _secure_file(path):
    """Set file to owner-only read/write (0600). No-op on Windows.

    Skipped in managed mode — the NixOS activation script sets
    group-readable permissions (0640) on config files.

    Skipped in containers — Docker/Podman volume mounts often need broader
    permissions.  Set ECTOR_SKIP_CHMOD=1 to force-skip on other systems.
    """
    if is_managed() or _is_container():
        return
    try:
        if os.path.exists(str(path)):
            os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


def _ensure_default_soul_md(home: Path) -> None:
    """Seed a default SOUL.md into ECTOR_HOME if the user doesn't have one yet."""
    soul_path = home / "SOUL.md"
    if soul_path.exists():
        return
    soul_path.write_text(DEFAULT_SOUL_MD, encoding="utf-8")
    _secure_file(soul_path)


def ensure_ector_home():
    """Ensure ~/.ector directory structure exists with secure permissions.

    In managed mode (NixOS), dirs are created by the activation script with
    setgid + group-writable (2770). We skip mkdir and set umask(0o007) so
    any files created (e.g. SOUL.md) are group-writable (0660).
    """
    home = get_ector_home()
    if is_managed():
        old_umask = os.umask(0o007)
        try:
            _ensure_ector_home_managed(home)
        finally:
            os.umask(old_umask)
    else:
        home.mkdir(parents=True, exist_ok=True)
        _secure_dir(home)
        for subdir in ("cron", "sessions", "logs", "memories"):
            d = home / subdir
            d.mkdir(parents=True, exist_ok=True)
            _secure_dir(d)
        _ensure_default_soul_md(home)


def _ensure_ector_home_managed(home: Path):
    """Managed-mode variant: verify dirs exist (activation creates them), seed SOUL.md."""
    if not home.is_dir():
        raise RuntimeError(
            f"ECTOR_HOME {home} não existe. "
            "Execute 'sudo nixos-rebuild switch' primeiro."
        )
    for subdir in ("cron", "sessions", "logs", "memories"):
        d = home / subdir
        if not d.is_dir():
            raise RuntimeError(
                f"{d} não existe. "
                "Execute 'sudo nixos-rebuild switch' primeiro."
            )
    # Inside umask(0o007) scope — SOUL.md will be created as 0660
    _ensure_default_soul_md(home)


# =============================================================================
# Config loading/saving
# =============================================================================

# Alinhado ao backend ector.cc (Profissional / Estratégico / Casual).
DEFAULT_AGENT_PERSONALITIES: Dict[str, str] = {
    "profissional": (
        "Você é um assistente profissional — direto, técnico, objetivo "
        "e focado em resultados."
    ),
    "estrategico": (
        "Você é um assistente estratégico — analítico, questionador, "
        "com visão de negócio e planejamento."
    ),
    "casual": (
        "Você é um assistente casual — leve, amigável, simples e fácil "
        "de entender (sempre respeitoso; nunca vulgar/grosseiro)."
    ),
}

_LEGACY_DISPLAY_PERSONALITIES = frozenset({"default", "none", "neutral", "kawaii"})


def is_legacy_display_personality(value: str) -> bool:
    """True for orphaned ``display.personality`` sentinel values."""
    return str(value or "").strip().lower() in _LEGACY_DISPLAY_PERSONALITIES


def resolve_display_personality_overlay(display_cfg: dict | None) -> str:
    """Return the active ``/personality`` overlay name, or ``\"\"``."""
    overlay = str((display_cfg or {}).get("personality") or "").strip().lower()
    if overlay and not is_legacy_display_personality(overlay):
        return overlay
    return ""


DEFAULT_CONFIG = {
    "model": "",
    "providers": {},
    "fallback_providers": [],
    "credential_pool_strategies": {},
    "toolsets": ["ector-cli"],
    "agent": {
        "max_turns": 90,
        # Inactivity timeout for gateway agent execution (seconds).
        # The agent can run indefinitely as long as it's actively calling
        # tools or receiving API responses.  Only fires when the agent has
        # been completely idle for this duration.  0 = unlimited.
        "gateway_timeout": 1800,
        # Graceful drain timeout for gateway stop/restart (seconds).
        # The gateway stops accepting new work, waits for running agents
        # to finish, then interrupts any remaining runs after the timeout.
        # 0 = no drain, interrupt immediately.
        "restart_drain_timeout": 60,
        # Max app-level retry attempts for API errors (connection drops,
        # provider timeouts, 5xx, etc.) before the agent surfaces the
        # failure.  The OpenAI SDK already does its own low-level retries
        # (max_retries=2 default) for transient network errors; this is
        # the Ector-level retry loop that wraps the whole call.  Lower
        # this to 1 if you use fallback providers and want fast failover
        # on flaky primaries; raise it if you prefer to tolerate longer
        # provider hiccups on a single provider.
        "api_max_retries": 3,
        "service_tier": "",
        # Tool-use enforcement: injects system prompt guidance that tells the
        # model to actually call tools instead of describing intended actions.
        # Values: "auto" (default — applies to gpt/codex models), true/false
        # (force on/off for all models), or a list of model-name substrings
        # to match (e.g. ["gpt", "codex", "gemini", "qwen"]).
        "tool_use_enforcement": "auto",
        # Staged inactivity warning: send a warning to the user at this
        # threshold before escalating to a full timeout.  The warning fires
        # once per run and does not interrupt the agent.  0 = disable warning.
        "gateway_timeout_warning": 900,
        # Periodic "still working" notification interval (seconds).
        # Sends a status message every N seconds so the user knows the
        # agent hasn't died during long tasks.  0 = disable notifications.
        # Lower values mean faster feedback on slow tasks but more chat
        # noise; 180s is a compromise that catches spinning weak-model runs
        # (60+ tool iterations with tiny output) before users assume the
        # bot is dead and /restart.
        "gateway_notify_interval": 180,
        "system_prompt": "",
        "reasoning_effort": "",
        "prefill_messages_file": "",
        # Personalidades predefinidas (``/personality``). String ou dict com
        # description/system_prompt/tone/style. Alinhado ao onboarding ector.cc.
        "personalities": dict(DEFAULT_AGENT_PERSONALITIES),
    },
    
    "wiser": {
        # Seconds to wait for a Wiser (wiser tool) answer before auto-proceeding.
        "timeout": 120,
    },

    "terminal": {
        "backend": "local",
        "modal_mode": "auto",
        "cwd": ".",  # Use current directory
        "timeout": 180,
        # Environment variables to pass through to sandboxed execution
        # (terminal and execute_code).  Skill-declared required_environment_variables
        # are passed through automatically; this list is for non-skill use cases.
        "env_passthrough": [],
        # Extra files to source in the login shell when building the
        # per-session environment snapshot.  Use this when tools like nvm,
        # pyenv, asdf, or custom PATH entries are registered by files that
        # a bash login shell would skip — most commonly ``~/.bashrc``
        # (bash doesn't source bashrc in non-interactive login mode) or
        # zsh-specific files like ``~/.zshrc`` / ``~/.zprofile``.
        # Paths support ``~`` / ``${VAR}``. Missing files are silently
        # skipped. When empty, Ector auto-sources ``~/.profile``,
        # ``~/.bash_profile``, and ``~/.bashrc`` (in that order) if the
        # snapshot shell is bash (this is the ``auto_source_bashrc``
        # behaviour — disable with that key if you want strict login-only
        # semantics).
        "shell_init_files": [],
        # When true (default), Ector sources the user's shell rc files
        # (``~/.profile``, ``~/.bash_profile``, ``~/.bashrc``) in the
        # login shell used to build the environment snapshot. This
        # captures PATH additions, shell functions, and aliases — which a
        # plain ``bash -l -c`` would otherwise miss because bash skips
        # bashrc in non-interactive login mode, and because a default
        # Debian/Ubuntu ``~/.bashrc`` short-circuits on non-interactive
        # sources. ``~/.profile`` and ``~/.bash_profile`` are tried first
        # because ``n`` / ``nvm`` / ``asdf`` installers typically write
        # their PATH exports there without an interactivity guard. Turn
        # this off if your rc files misbehave when sourced
        # non-interactively (e.g. one that hard-exits on TTY checks).
        "auto_source_bashrc": True,
        "docker_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        "docker_forward_env": [],
        # Explicit environment variables to set inside Docker containers.
        # Unlike docker_forward_env (which reads values from the host process),
        # docker_env lets you specify exact key-value pairs — useful when Ector
        # runs as a systemd service without access to the user's shell environment.
        # Example: {"SSH_AUTH_SOCK": "/run/user/1000/ssh-agent.sock"}
        "docker_env": {},
        "singularity_image": "docker://nikolaik/python-nodejs:python3.11-nodejs20",
        "modal_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        "daytona_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        # Container resource limits (docker, singularity, modal, daytona — ignored for local/ssh)
        "container_cpu": 1,
        "container_memory": 5120,       # MB (default 5GB)
        "container_disk": 51200,        # MB (default 50GB)
        "container_persistent": True,   # Persist filesystem across sessions
        # Docker volume mounts — share host directories with the container.
        # Each entry is "host_path:container_path" (standard Docker -v syntax).
        # Example:
        # ["/home/user/projects:/workspace/projects",
        #  "/home/user/.ector/cache/documents:/output"]
        # For gateway MEDIA delivery, write inside Docker to /output/... and emit
        # the host-visible path in MEDIA:, not the container path.
        "docker_volumes": [],
        # Explicit opt-in: mount the host cwd into /workspace for Docker sessions.
        # Default off because passing host directories into a sandbox weakens isolation.
        "docker_mount_cwd_to_workspace": False,
        # Persistent shell — keep a long-lived bash shell across execute() calls
        # so cwd/env vars/shell variables survive between commands.
        # Enabled by default for non-local backends (SSH); local is always opt-in
        # via TERMINAL_LOCAL_PERSISTENT env var.
        "persistent_shell": True,
    },
    
    "browser": {
        "inactivity_timeout": 120,
        "command_timeout": 30,  # Timeout for browser commands in seconds (screenshot, navigate, etc.)
        "record_sessions": False,  # Auto-record browser sessions as WebM videos
        "allow_private_urls": False,  # Allow navigating to private/internal IPs (localhost, 192.168.x.x, etc.)
        "auto_local_for_private_urls": True,  # When a cloud provider is set, auto-spawn local Chromium for LAN/localhost URLs instead of sending them to the cloud
        "cdp_url": "",  # Optional persistent CDP endpoint for attaching to an existing Chromium/Chrome
        # CDP supervisor — dialog + frame detection via a persistent WebSocket.
        # Active only when a CDP-capable backend is attached (Browserbase or
        # local Chrome via /browser connect). See
        # website/docs/developer-guide/browser-supervisor.md.
        "dialog_policy": "must_respond",  # must_respond | auto_dismiss | auto_accept
        "dialog_timeout_s": 300,  # Safety auto-dismiss after N seconds under must_respond
        "camofox": {
            # When true, Ector sends a stable profile-scoped userId to Camofox
            # so the server maps it to a persistent Firefox profile automatically.
            # When false (default), each session gets a random userId (ephemeral).
            "managed_persistence": False,
        },
    },

    # Filesystem checkpoints — automatic snapshots before destructive file ops.
    # When enabled, the agent takes a snapshot of the working directory once per
    # conversation turn (on first write_file/patch call).  Use /rollback to restore.
    "checkpoints": {
        "enabled": True,
        "max_snapshots": 50,  # Max checkpoints to keep per directory
        # Auto-maintenance: shadow repos accumulate forever under
        # ~/.ector/checkpoints/ (one per cd'd working directory). Field
        # reports put the typical offender at 1000+ repos / ~12 GB. When
        # auto_prune is on, ector sweeps at startup (at most once per
        # min_interval_hours) and deletes:
        #   * orphan repos: ECTOR_WORKDIR no longer exists on disk
        #   * stale repos:  newest mtime older than retention_days
        # Opt-in so users who rely on /rollback against long-ago sessions
        # never lose data silently.
        "auto_prune": False,
        "retention_days": 7,
        "delete_orphans": True,
        "min_interval_hours": 24,
    },

    # Maximum characters returned by a single read_file call.  Reads that
    # exceed this are rejected with guidance to use offset+limit.
    # 100K chars ≈ 25–35K tokens across typical tokenisers.
    "file_read_max_chars": 100_000,

    # Tool-output truncation thresholds. When terminal output or a
    # single read_file page exceeds these limits, Ector truncates the
    # payload sent to the model (keeping head + tail for terminal,
    # enforcing pagination for read_file). Tuning these trades context
    # footprint against how much raw output the model can see in one
    # shot. Ported from a public implementation.
    #
    # - max_bytes:       terminal_tool output cap, in chars
    #                    (default 50_000 ≈ 12-15K tokens).
    # - max_lines:       read_file pagination cap — the maximum `limit`
    #                    a single read_file call can request before
    #                    being clamped (default 2000).
    # - max_line_length: per-line cap applied when read_file emits a
    #                    line-numbered view (default 2000 chars).
    "tool_output": {
        "max_bytes": 50_000,
        "max_lines": 2000,
        "max_line_length": 2000,
    },

    "compression": {
        "enabled": True,
        "threshold": 0.50,            # compress when context usage exceeds this ratio
        "target_ratio": 0.20,         # fraction of threshold to preserve as recent tail
        "protect_last_n": 20,         # minimum recent messages to keep uncompressed

    },

    # Ephemeral per-turn context injected into the user message (memory/RAG/plugins).
    "context": {
        "ephemeral_injection_cap_percent": 0.15,
    },

    # Dynamic tool routing: filter the tools[] sent to the LLM per iteration
    # while keeping the full pool for dispatch. Enabled by default (cache-safe).
    # Set enabled: false in config.yaml to send the full tool surface every call.
    "tool_routing": {
        "enabled": True,
        "mode": "hybrid",  # keyword | hybrid | embedding
        "max_tools": 24,
        "bm25_candidates": 48,
        "pin_tools": [
            "todo", "memory", "session_search", "wiser",
            "skills_list", "skill_view", "skill_manage", "delegate_task",
        ],
        "pin_toolsets": ["skills", "delegation", "planning"],
        "expand_on_miss": True,
        "rerank_each_iteration": True,
        "min_score": 0.0,
        "min_pool_size": 15,
    },

    # Anthropic prompt caching (Claude via OpenRouter or native Anthropic API).
    # cache_ttl must be "5m" or "1h" (Anthropic-supported tiers); other values are ignored.
    "prompt_caching": {
        "cache_ttl": "5m",
    },

    # AWS Bedrock provider configuration.
    # Only used when model.provider is "bedrock".
    "bedrock": {
        "region": "",  # AWS region for Bedrock API calls (empty = AWS_REGION env var → us-east-1)
        "discovery": {
            "enabled": True,           # Auto-discover models via ListFoundationModels
            "provider_filter": [],     # Only show models from these providers (e.g. ["anthropic", "amazon"])
            "refresh_interval": 3600,  # Cache discovery results for this many seconds
        },
        "guardrail": {
            # Amazon Bedrock Guardrails — content filtering and safety policies.
            # Create a guardrail in the Bedrock console, then set the ID and version here.
            # See: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
            "guardrail_identifier": "",  # e.g. "abc123def456"
            "guardrail_version": "",     # e.g. "1" or "DRAFT"
            "stream_processing_mode": "async",  # "sync" or "async"
            "trace": "disabled",         # "enabled", "disabled", or "enabled_full"
        },
    },

    # Auxiliary model config — provider:model for each side task.
    # Format: provider is the provider name, model is the model slug.
    # "auto" for provider = auto-detect best available provider.
    # Empty model = use provider's default auxiliary model.
    # All tasks fall back to openrouter:google/gemini-3-flash-preview if
    # the configured provider is unavailable.
    "auxiliary": {
        "vision": {
            "provider": "auto",    # auto | openrouter | ector | codex | custom
            "model": "",           # e.g. "google/gemini-2.5-flash", "gpt-4o"
            "base_url": "",        # direct OpenAI-compatible endpoint (takes precedence over provider)
            "api_key": "",         # API key for base_url (falls back to OPENAI_API_KEY)
            "timeout": 120,        # seconds — LLM API call timeout; vision payloads need generous timeout
            "extra_body": {},      # OpenAI-compatible provider-specific request fields
            "download_timeout": 30,  # seconds — image HTTP download timeout; increase for slow connections
        },
        "web_extract": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 360,        # seconds (6min) — per-attempt LLM summarization timeout; increase for slow local models
            "extra_body": {},
        },
        "compression": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 120,        # seconds — compression summarises large contexts; increase for local models
            "extra_body": {},
        },
        "session_search": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
            "max_concurrency": 3,  # Clamp parallel summaries to avoid request-burst 429s on small providers
            # False = only local FTS snippets (fast, no auxiliary LLM). True = summarize each hit session.
            "summarize": False,
            "snippet_max_chars": 2400,
        },
        "skills_hub": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "approval": {
            "provider": "auto",
            "model": "",           # fast/cheap model recommended (e.g. gemini-flash, haiku)
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "mcp": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "title_generation": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "embedding": {
            "provider": "auto",
            "model": "text-embedding-3-small",
            "base_url": "",
            "api_key": "",
            "timeout": 15,
            "extra_body": {},
        },
    },

    # Local-first document extraction / OCR stack
    "documents": {
        "enabled": True,
        "preanalysis": "vision_then_ocr",  # vision_then_ocr | ocr_only | vision_only
        "dark_mode_boost": True,
        "max_pages": 100,
        "max_extract_bytes": 50 * 1024 * 1024,
        "cache_extracts": True,
        "heavy_tier": "auto",  # auto | off | marker
        "ocr_engine": "auto",  # auto | rapidocr | tesseract | ocrmac
    },
    
    "display": {
        "resume_display": "full",
        "busy_input_mode": "interrupt",  # interrupt | queue | steer
        # Gateway: em modo interrupt, não avisar no chat ocupado; perguntar no
        # home_channel da mesma plataforma (ref + ignorar / ref + texto).
        "busy_interrupt_ask_home_channel": False,
        "bell_on_complete": False,
        "show_reasoning": False,
        "streaming": True,
        "final_response_markdown": "strip",  # render | strip | raw
        "inline_diffs": True,     # Show inline diff previews for write actions (write_file, patch, skill_manage)
        "show_cost": False,       # Show $ cost in the status bar (off by default)
        "user_message_preview": {  # CLI: how many submitted user-message lines to echo back in scrollback
            "first_lines": 2,
            "last_lines": 2,
        },
        "interim_assistant_messages": True,  # Gateway: show natural mid-turn assistant status messages
        "tool_progress_command": False,  # Enable /verbose command in messaging gateway
        "tool_progress_overrides": {},  # DEPRECATED — use display.platforms instead
        "tool_preview_length": 0,  # Max chars for tool call previews (0 = no limit, show full paths/commands)
        "platforms": {},  # Per-platform display overrides: {"telegram": {"tool_progress": "all"}, "slack": {"tool_progress": "off"}}
        # Gateway: optional idle reminder after no user messages (messaging platforms).
        "presence_nudge": {
            "enabled": False,
            "idle_hours": 15,
            "check_interval_seconds": 1800,
            "message": "",
        },
    },

    # Web dashboard settings
    "dashboard": {
        "theme": "default",  # Dashboard visual theme: "default", "midnight", "ember", "mono", "cyberpunk", "rose"
        # Friendly URL for `ector localhost` (RFC 6761 *.localhost). Empty disables (127.0.0.1).
        "local_hostname": "ector.localhost",
        "smart_menu": True,  # Auto-collapse dashboard sidebar after inactivity (desktop only)
    },

    # Privacy settings
    "privacy": {
        "redact_pii": False,  # When True, hash user IDs and strip phone numbers from LLM context
    },
    
    # Text-to-speech configuration
    # Each provider supports an optional `max_text_length:` override for the
    # per-request input-character cap. Omit it to use the provider's documented
    # limit (OpenAI 4096, xAI 15000, MiniMax 10000, ElevenLabs 5k-40k model-aware,
    # Gemini 5000, Edge 5000, Mistral 4000, NeuTTS/KittenTTS 2000).
    "tts": {
        "provider": "edge",  # "edge" (free) | "elevenlabs" (premium) | "openai" | "xai" | "minimax" | "mistral" | "neutts" (local)
        "edge": {
            "voice": "pt-BR-FranciscaNeural",
            # Popular pt-BR: FranciscaNeural, AntonioNeural, ThalitaNeural
        },
        "elevenlabs": {
            "voice_id": "pNInz6obpgDQGcFmaJgB",  # Adam
            "model_id": "eleven_multilingual_v2",
        },
        "openai": {
            "model": "gpt-4o-mini-tts",
            "voice": "alloy",
            # Voices: alloy, echo, fable, onyx, nova, shimmer, …
            # Optional ``instructions`` (gpt-4o-mini-tts only): steers accent, e.g.
            # "Speak in Brazilian Portuguese with a natural accent."
        },
        "xai": {
            "voice_id": "eve",
            "language": "en",  # e.g. ``pt`` for Portuguese when supported by xAI TTS
            "sample_rate": 24000,
            "bit_rate": 128000,
        },
        "mistral": {
            "model": "voxtral-mini-tts-2603",
            "voice_id": "c69964a6-ab8b-4f8a-9465-ec0925096ec8",  # Paul - Neutral
        },
        "neutts": {
            "ref_audio": "",  # Path to reference voice audio (empty = bundled default)
            "ref_text": "",   # Path to reference voice transcript (empty = bundled default)
            "model": "neuphonic/neutts-air-q4-gguf",  # HuggingFace model repo
            "device": "cpu",  # cpu, cuda, or mps
        },
    },
    
    "stt": {
        "enabled": True,
        "provider": "local",  # "local" (free, faster-whisper) | "groq" | "openai" (Whisper API) | "mistral" (Voxtral Transcribe)
        "local": {
            "model": "base",  # tiny, base, small, medium, large-v3
            "language": "pt",  # Portuguese (pt-BR); use "auto" for auto-detect, or "en", "es", etc.
        },
        "openai": {
            "model": "whisper-1",  # whisper-1, gpt-4o-mini-transcribe, gpt-4o-transcribe
        },
        "mistral": {
            "model": "voxtral-mini-latest",  # voxtral-mini-latest, voxtral-mini-2602
        },
    },

    "voice": {
        "record_key": "ctrl+b",
        "max_recording_seconds": 120,
        "auto_tts": False,
        "beep_enabled": True,         # Play record start/stop beeps in CLI voice mode
        "silence_threshold": 200,     # RMS below this = silence (0-32767)
        "silence_duration": 3.0,      # Seconds of silence before auto-stop
    },
    
    "human_delay": {
        "mode": "off",
        "min_ms": 800,
        "max_ms": 2500,
    },
    
    # Context engine -- controls how the context window is managed when
    # approaching the model's token limit.
    # "compressor" = built-in lossy summarization (default).
    # Set to a plugin name to activate an alternative engine (e.g. "lcm"
    # for Lossless Context Management).  The engine must be installed as
    # a plugin in plugins/context_engine/<name>/ or ~/.ector/plugins/.
    "context": {
        "engine": "compressor",
    },

    # Persistent memory -- bounded curated memory injected into system prompt
    "memory": {
        "memory_enabled": True,
        "user_profile_enabled": True,
        "memory_char_limit": 10000,  # ~3.6k tokens
        "user_char_limit": 10000,    # ~3.6k tokens
        # Background memory review interval (turns). 0 disables nudges.
        "nudge_interval": 10,
        # Opt-in: inject writes from this session into the user message
        # (ephemeral). Default off — system prompt snapshot unchanged.
        "session_delta_injection": False,
        # External memory provider plugin (empty = built-in only).
        # Set memory.provider to the plugin id returned by `ector memory setup`.
        # Only ONE external provider is allowed at a time.
        "provider": "",
    },

    # Retrieval-Augmented Generation (RAG) over prior session transcripts.
    # Uses local SessionDB FTS retrieval and injects snippets ephemerally into
    # the current user turn (never persisted, never added to system prompt).
    "rag": {
        "enabled": True,
        "max_results": 4,      # Number of snippets to inject per turn (1..10)
        "max_chars": 2500,     # Total injected snippet budget
        "min_query_chars": 8,  # Skip retrieval for very short messages
    },

    # Subagent delegation — override the provider:model used by delegate_task
    # so child agents can run on a different (cheaper/faster) provider and model.
    # Uses the same runtime provider resolution as CLI/gateway startup, so all
    # configured providers (OpenRouter, Ector, Z.ai, Kimi, etc.) are supported.
    "delegation": {
        "model": "",       # e.g. "google/gemini-3-flash-preview" (empty = inherit parent model)
        "provider": "",    # e.g. "openrouter" (empty = inherit parent provider + credentials)
        "base_url": "",    # direct OpenAI-compatible endpoint for subagents
        "api_key": "",     # API key for delegation.base_url (falls back to OPENAI_API_KEY)
        # When delegate_task narrows child toolsets explicitly, preserve any
        # MCP toolsets the parent already has enabled. On by default so
        # narrowing (e.g. toolsets=["web","browser"]) expresses "I want these
        # extras" without silently stripping MCP tools the parent already has.
        # Set to false for strict intersection.
        "inherit_mcp_toolsets": True,
        "max_iterations": 50,  # per-subagent iteration cap (each subagent gets its own budget,
                               # independent of the parent's max_iterations)
        "child_timeout_seconds": 600,  # wall-clock timeout for each child agent (floor 30s,
                                       # no ceiling). High-reasoning models on large tasks
                                       # (e.g. gpt-5.5 xhigh, opus-4.6) need generous budgets;
                                       # raise if children time out before producing output.
        "reasoning_effort": "",  # reasoning effort for subagents: "xhigh", "high", "medium",
                                 # "low", "minimal", "none" (empty = inherit parent's level)
        "max_concurrent_children": 3,  # max parallel children per batch; floor of 1 enforced, no ceiling
        # Orchestrator role controls (see tools/delegate_tool.py:_get_max_spawn_depth
        # and _get_orchestrator_enabled).  Values are clamped to [1, 3] with a
        # warning log if out of range.
        "max_spawn_depth": 1,        # depth cap (1 = flat [default], 2 = orchestrator→leaf, 3 = three-level)
        "orchestrator_enabled": True,  # kill switch for role="orchestrator"
        # When a subagent hits a dangerous-command approval prompt, the parent's
        # prompt_toolkit TUI owns stdin — a thread-local input() call from the
        # subagent worker would deadlock the parent UI. To avoid the deadlock,
        # subagent threads ALWAYS resolve approvals non-interactively:
        #   false (default) → auto-deny with a logger.warning audit line (safe)
        #   true             → auto-approve "once" with a logger.warning audit line
        # Flip to true only if you trust delegated work to run dangerous cmds
        # without human review (cron pipelines, batch automation, etc.).
        "subagent_auto_approve": False,
    },

    # Ephemeral prefill messages file — JSON list of {role, content} dicts
    # injected at the start of every API call for few-shot priming.
    # Never saved to sessions, logs, or trajectories.
    "prefill_messages_file": "",
    
    # Skills — external skill directories for sharing skills across tools/agents.
    # Each path is expanded (~, ${VAR}) and resolved.  Read-only — skill creation
    # always goes to ~/.ector/skills/.
    "skills": {
        # Sincronização automática da biblioteca na nuvem (Hub / ector.cc) para
        # ~/.ector/skills/. ETag + intervalos + backoff protegem a API.
        "cloud_sync": True,
        "cloud_sync_interval_seconds": 300,
        # Mínimo entre tentativas automáticas (inclui arranque do agente/TUI).
        "cloud_sync_min_cooldown_seconds": 120,
        # Pausa entre GET /bundle consecutivos durante um sync.
        "cloud_sync_bundle_delay_seconds": 0.35,
        # Limite de bundles por execução; o restante fica para o próximo ciclo.
        "cloud_sync_max_bundles_per_run": 20,
        "external_dirs": [],   # e.g. ["~/.agents/skills", "/shared/team-skills"]
        # Substitute ${ECTOR_SKILL_DIR} and ${ECTOR_SESSION_ID} in SKILL.md
        # content with the absolute skill directory and the active session id
        # before the agent sees it.  Lets skill authors reference bundled
        # scripts without the agent having to join paths.
        "template_vars": True,
        # Pre-execute inline shell snippets written as !`cmd` in SKILL.md
        # body.  Their stdout is inlined into the skill message before the
        # agent reads it, so skills can inject dynamic context (dates, git
        # state, detected tool versions, …).  Off by default because any
        # content from the skill author runs on the host without approval;
        # only enable for skill sources you trust.
        "inline_shell": False,
        # Timeout (seconds) for each !`cmd` snippet when inline_shell is on.
        "inline_shell_timeout": 10,
        # Run the keyword/pattern security scanner on skills the agent
        # writes via skill_manage (create/edit/patch).  Off by default
        # because the agent can already execute the same code paths via
        # terminal() with no gate, so the scan adds friction (blocks
        # skills that mention risky keywords in prose) without meaningful
        # security.  Turn on if you want the belt-and-suspenders — a
        # dangerous verdict will then surface as a tool error to the
        # agent, which can retry with the flagged content removed.
        # External hub installs (trusted/community sources) are always
        # scanned regardless of this setting.
        "guard_agent_created": False,
        # A cada N iterações de ferramenta, o agente pode revisar a conversa e
        # salvar ou atualizar skills (background review em run_agent.py).
        "creation_nudge_interval": 10,
    },

    # IANA timezone (e.g. "Asia/Kolkata", "America/New_York").
    # Empty string means use server-local time.
    "timezone": "",

    # Discord platform settings (gateway mode)
    "discord": {
        "require_mention": True,       # Require @mention to respond in server channels
        "free_response_channels": "",  # Comma-separated channel IDs where bot responds without mention
        "allowed_channels": "",        # If set, bot ONLY responds in these channel IDs (whitelist)
        "auto_thread": True,           # Auto-create threads on @mention in channels (like Slack)
        "reactions": True,             # Add ◎/✔/✖ reactions to messages during processing
        "channel_prompts": {},         # Per-channel ephemeral system prompts (forum parents apply to child threads)
        # discord / discord_admin tools: restrict which actions the agent may call.
        # Default (empty) = all actions allowed (subject to bot privileged intents).
        # Accepts comma-separated string ("list_guilds,list_channels,fetch_messages")
        # or YAML list. Unknown names are dropped with a warning at load time.
        # Actions: list_guilds, server_info, list_channels, channel_info,
        # list_roles, member_info, search_members, fetch_messages, list_pins,
        # pin_message, unpin_message, create_thread, add_role, remove_role.
        "server_actions": "",
    },

    # WhatsApp platform settings (gateway mode)
    "whatsapp": {
        # Reply prefix prepended to every outgoing WhatsApp message (self-chat mode).
        # Empty string = no header (default). Supports \n, e.g. "🤖 *My Bot*\n──────\n"
        "reply_prefix": "",
    },

    # Telegram platform settings (gateway mode)
    "telegram": {
        "channel_prompts": {},         # Per-chat/topic ephemeral system prompts (topics inherit from parent group)
    },

    # Slack platform settings (gateway mode)
    "slack": {
        "channel_prompts": {},         # Per-channel ephemeral system prompts
    },

    # Mattermost platform settings (gateway mode)
    "mattermost": {
        "channel_prompts": {},         # Per-channel ephemeral system prompts
    },

    # Approval mode for dangerous commands:
    #   manual — always prompt the user (default)
    #   smart  — use auxiliary LLM to auto-approve low-risk commands, prompt for high-risk
    #   off    — skip all approval prompts (equivalent to --yolo)
    #
    # cron_mode — what to do when a cron job hits a dangerous command:
    #   deny    — block the command and let the agent find another way (default, safe)
    #   approve — auto-approve all dangerous commands in cron jobs
    "approvals": {
        "mode": "manual",
        "timeout": 60,
        "cron_mode": "deny",
    },

    # Permanently allowed dangerous command patterns (added via "always" approval)
    "command_allowlist": [],
    # User-defined quick commands that bypass the agent loop (type: exec only)
    "quick_commands": {},

    # Shell-script hooks — declarative bridge that invokes shell scripts
    # on plugin-hook events (pre_tool_call, post_tool_call, pre_llm_call,
    # subagent_stop, etc.).  Each entry maps an event name to a list of
    # {matcher, command, timeout} dicts.  First registration of a new
    # command prompts the user for consent; subsequent runs reuse the
    # stored approval from ~/.ector/shell-hooks-allowlist.json.
    # See `website/docs/user-guide/features/hooks.md` for schema + examples.
    "hooks": {},

    # Auto-accept shell-hook registrations without a TTY prompt.  Also
    # toggleable per-invocation via --accept-hooks or ECTOR_ACCEPT_HOOKS=1.
    # Gateway / cron / non-interactive runs need this (or one of the other
    # channels) to pick up newly-added hooks.
    "hooks_auto_accept": False,

    # Pre-exec security scanning via tirith
    "security": {
        "allow_private_urls": False,  # Allow requests to private/internal IPs (for OpenWrt, proxies, VPNs)
        "redact_secrets": True,
        "tirith_enabled": True,
        "tirith_path": "tirith",
        "tirith_timeout": 5,
        "tirith_fail_open": True,
        "website_blocklist": {
            "enabled": False,
            "domains": [],
            "shared_files": [],
        },
    },

    "cron": {
        # Scheduler engine mode:
        # - legacy: existing cron tick flow (default, safest).
        # - apscheduler: keeps legacy execution semantics and emits parity telemetry.
        # - shadow: same as apscheduler, explicit non-cutover validation mode.
        # Also overridable via ECTOR_CRON_ENGINE env var.
        "engine": "legacy",
        # Tick interval for the in-process gateway cron loop in seconds.
        # Lower values improve short reminder precision at the cost of more
        # frequent due-job checks. Range is clamped to [1, 300].
        # Also overridable via ECTOR_CRON_TICK_INTERVAL_SECONDS.
        "tick_interval_seconds": 60,
        # Legacy toggle for optional cron delivery framing. Delivered text is
        # post-processed for natural output; keep false for clean messages.
        "wrap_response": False,
        # Maximum number of due jobs to run in parallel per tick.
        # null/0 = unbounded (limited only by thread count).
        # 1 = serial (pre-v0.9 behaviour).
        # Also overridable via ECTOR_CRON_MAX_PARALLEL env var.
        "max_parallel_jobs": None,
    },

    # execute_code settings — controls the tool used for programmatic tool calls.
    "code_execution": {
        # Execution mode:
        #   project (default) — scripts run in the session's working directory
        #     with the active virtualenv/conda env's python, so project deps
        #     (pandas, torch, project packages) and relative paths resolve.
        #   strict            — scripts run in an isolated temp directory with
        #     ector-agent's own python (sys.executable). Maximum isolation
        #     and reproducibility; project deps and relative paths won't work.
        # Env scrubbing (strips *_API_KEY, *_TOKEN, *_SECRET, ...) and the
        # tool whitelist apply identically in both modes.
        "mode": "project",
    },

    # Logging — controls file logging to ~/.ector/logs/.
    # agent.log captures INFO+ (all agent activity); errors.log captures WARNING+.
    "logging": {
        "level": "INFO",       # Minimum level for agent.log: DEBUG, INFO, WARNING
        "max_size_mb": 5,      # Max size per log file before rotation
        "backup_count": 3,     # Number of rotated backup files to keep
    },



    # Network settings — workarounds for connectivity issues.
    "network": {
        # Force IPv4 connections.  On servers with broken or unreachable IPv6,
        # Python tries AAAA records first and hangs for the full TCP timeout
        # before falling back to IPv4.  Set to true to skip IPv6 entirely.
        "force_ipv4": False,
    },

    # Session storage — controls automatic cleanup of ~/.ector/state.db.
    # state.db accumulates every session, message, tool call, and FTS5 index
    # entry forever.  Without auto-pruning, a heavy user (gateway + cron)
    # reports 384MB+ databases with 68K+ messages, which slows down FTS5
    # inserts, /resume listing, and stats queries.
    "sessions": {
        # When true, prune ended sessions older than retention_days once
        # per (roughly) min_interval_hours at CLI/gateway/cron startup.
        # Only touches ended sessions — active sessions are always preserved.
        # Default false: session history is valuable for search recall, and
        # silently deleting it could surprise users.  Opt in explicitly.
        "auto_prune": False,
        # How many days of ended-session history to keep.  Matches the
        # default of ``ector sessions prune``.
        "retention_days": 90,
        # VACUUM after a prune that actually deleted rows.  SQLite does not
        # reclaim disk space on DELETE — freed pages are just reused on
        # subsequent INSERTs — so without VACUUM the file stays bloated
        # even after pruning.  VACUUM blocks writes for a few seconds per
        # 100MB, so it only runs at startup, and only when prune deleted
        # ≥1 session.
        "vacuum_after_prune": True,
        # Minimum hours between auto-maintenance runs (avoids repeating
        # the sweep on every CLI invocation).  Tracked via state_meta in
        # state.db itself, so it's shared across all processes.
        "min_interval_hours": 24,
    },

    # Contextual first-touch onboarding hints (see agent/onboarding.py).
    # Each hint is shown once per install and then latched here so it
    # never fires again.  Users can wipe the section to re-see all hints.
    "onboarding": {
        "seen": {},
    },

    # ``ector update`` behaviour.
    "updates": {
        # Run a lean zip of critical ECTOR_HOME state (config, credentials,
        # databases, pairing) before every ``ector update``.  Backups land in
        # ``<ECTOR_HOME>/backups/`` and can be restored with
        # ``ector import <path>``.  Set to false to skip the backup entirely;
        # use the ``--no-backup`` flag on a single update invocation to
        # override just that run.
        "pre_update_backup": True,
        # How many pre-update backup zips to retain.  Older ones are pruned
        # automatically after each successful backup.
        "backup_keep": 5,
    },

    # Ector identity authentication (ector.cc).  Distinct from provider
    # credentials in ~/.ector/auth.json — this controls the *user* session
    # used by `ector login` / `ector me` and gated by every agent run.
    "auth": {
        "base_url": "https://ector.cc",
        # How long to trust the cached /agent/auth/me response before
        # re-validating against the backend (detects disabled accounts
        # without waiting for the JWT to expire).
        "me_cache_seconds": 900,
        # Refresh the access token this many seconds before expiry.
        "refresh_skew_seconds": 300,
        # Maximum wait for the browser callback during `ector login`.
        "callback_timeout_seconds": 180,
        # Login mode: auto (SSH/headless → device code), loopback, or device.
        "login_mode": "auto",
        # Device-code flow (SSH): max wait and poll interval (seconds).
        "device_timeout_seconds": 900,
        "device_poll_interval_seconds": 5,
        # Host that the local HTTP callback server binds to during login.
        # 127.0.0.1 is recommended; do not expose this on a routable
        # interface.
        "callback_host": "127.0.0.1",
        # After a successful /me check, allow agent commands to proceed offline
        # for this many seconds when the backend is unreachable. Beyond this
        # window (or without any prior /me), re-validation is required.
        "offline_grace_seconds": 86400,
        # Poll interval while the Ink TUI gateway is running (detect logout /
        # account switch from another terminal).
        "tui_identity_poll_seconds": 5,
    },

    # User profile fetched from GET /agent/auth/me on login.  Populated
    # automatically by ector_cli.identity_auth — DO NOT edit by hand: the
    # next `ector me` / `ector login` will overwrite any local edits
    # with the backend's truth, and `ector logout` clears the whole block.
    # Consumed by agent/prompt_builder.py to build the per-session persona
    # block (replaces the legacy interview-style onboarding).
    "user": {
        "user_id": "",
        "email": "",
        "nickname": "",
        "personality": "",
        "personality_description": "",
        "behavior": "",
        "behavior_description": "",
        "custom_instructions": "",
        "timezone": "",
    },

    # Config schema version - bump this when adding new required fields
    "_config_version": 26,
}

# =============================================================================
# Config Migration System
# =============================================================================

# Track which env vars were introduced in each config version.
# Migration only mentions vars new since the user's previous version.
ENV_VARS_BY_VERSION: Dict[int, List[str]] = {
    3: ["FIRECRAWL_API_KEY", "BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "FAL_KEY"],
    4: ["VOICE_TOOLS_OPENAI_KEY", "ELEVENLABS_API_KEY"],
    5: ["WHATSAPP_ENABLED", "WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS",
        "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USERS"],
    10: ["TAVILY_API_KEY"],
    11: ["TERMINAL_MODAL_MODE"],
}

# Required environment variables with metadata for migration prompts.
# LLM provider is required but handled in the setup wizard's provider
# selection step (ector.cc / OpenRouter / Custom endpoint), so this
# dict is intentionally empty — no single env var is universally required.
REQUIRED_ENV_VARS = {}

# Optional environment variables that enhance functionality
OPTIONAL_ENV_VARS = {
    # ── Provider (handled in provider selection, not shown in checklists) ──
    "ECTOR_BASE_URL": {
        "description": "Sobrescrita da URL base do ector.cc",
        "prompt": "URL base do ector.cc (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "OPENROUTER_API_KEY": {
        "description": "Chave API do OpenRouter (para visão, auxiliares de raspagem web e MoA)",
        "prompt": "Chave API do OpenRouter",
        "url": "https://openrouter.ai/keys",
        "password": True,
        "tools": ["vision_analyze", "mixture_of_agents"],
        "category": "provider",
        "advanced": True,
    },
    "GOOGLE_API_KEY": {
        "description": "Chave API do Google AI Studio (também reconhecida como GEMINI_API_KEY)",
        "prompt": "Chave API do Google AI Studio",
        "url": "https://aistudio.google.com/app/apikey",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "GEMINI_API_KEY": {
        "description": "Chave API do Google AI Studio (alias para GOOGLE_API_KEY)",
        "prompt": "Chave API do Gemini",
        "url": "https://aistudio.google.com/app/apikey",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "GEMINI_BASE_URL": {
        "description": "Sobrescrita da URL base do Google AI Studio",
        "prompt": "URL base do Gemini (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "XAI_API_KEY": {
        "description": "Chave API da xAI",
        "prompt": "Chave API da xAI",
        "url": "https://console.x.ai/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "XAI_BASE_URL": {
        "description": "Sobrescrita da URL base da xAI",
        "prompt": "URL base da xAI (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "NVIDIA_API_KEY": {
        "description": "Chave API do NVIDIA NIM (build.nvidia.com ou endpoint NIM local)",
        "prompt": "Chave API do NVIDIA NIM",
        "url": "https://build.nvidia.com/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "NVIDIA_BASE_URL": {
        "description": "Sobrescrita da URL base do NVIDIA NIM (ex: http://localhost:8000/v1 para NIM local)",
        "prompt": "URL base do NVIDIA NIM (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "GLM_API_KEY": {
        "description": "Chave API da Z.AI / GLM (também reconhecida como ZAI_API_KEY / Z_AI_API_KEY)",
        "prompt": "Chave API da Z.AI / GLM",
        "url": "https://z.ai/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "ZAI_API_KEY": {
        "description": "Chave API da Z.AI (alias para GLM_API_KEY)",
        "prompt": "Chave API da Z.AI",
        "url": "https://z.ai/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "Z_AI_API_KEY": {
        "description": "Chave API da Z.AI (alias para GLM_API_KEY)",
        "prompt": "Chave API da Z.AI",
        "url": "https://z.ai/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "GLM_BASE_URL": {
        "description": "Sobrescrita da URL base da Z.AI / GLM",
        "prompt": "URL base da Z.AI / GLM (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "KIMI_API_KEY": {
        "description": "Chave API da Kimi / Moonshot",
        "prompt": "Chave API da Kimi",
        "url": "https://platform.moonshot.cn/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "KIMI_BASE_URL": {
        "description": "Sobrescrita da URL base da Kimi / Moonshot",
        "prompt": "URL base da Kimi (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "KIMI_CN_API_KEY": {
        "description": "Chave API da Kimi / Moonshot China",
        "prompt": "Chave API da Kimi (China)",
        "url": "https://platform.moonshot.cn/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "STEPFUN_API_KEY": {
        "description": "Chave API da StepFun Step Plan",
        "prompt": "Chave API da StepFun Step Plan",
        "url": "https://platform.stepfun.com/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "STEPFUN_BASE_URL": {
        "description": "Sobrescrita da URL base da StepFun Step Plan",
        "prompt": "URL base da StepFun Step Plan (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "ARCEEAI_API_KEY": {
        "description": "Chave API da Arcee AI",
        "prompt": "Chave API da Arcee AI",
        "url": "https://chat.arcee.ai/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "ARCEE_BASE_URL": {
        "description": "Sobrescrita da URL base da Arcee AI",
        "prompt": "URL base da Arcee (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "MINIMAX_API_KEY": {
        "description": "Chave API da MiniMax (internacional)",
        "prompt": "Chave API da MiniMax",
        "url": "https://www.minimax.io/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "MINIMAX_BASE_URL": {
        "description": "Sobrescrita da URL base da MiniMax",
        "prompt": "URL base da MiniMax (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "MINIMAX_CN_API_KEY": {
        "description": "Chave API da MiniMax (endpoint China)",
        "prompt": "Chave API da MiniMax (China)",
        "url": "https://www.minimaxi.com/",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "MINIMAX_CN_BASE_URL": {
        "description": "Sobrescrita da URL base da MiniMax (China)",
        "prompt": "URL base da MiniMax (China) (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "DEEPSEEK_API_KEY": {
        "description": "Chave API da DeepSeek para acesso direto à DeepSeek",
        "prompt": "Chave API da DeepSeek",
        "url": "https://platform.deepseek.com/api_keys",
        "password": True,
        "category": "provider",
    },
    "DEEPSEEK_BASE_URL": {
        "description": "URL base personalizada da API DeepSeek (avançado)",
        "prompt": "URL Base da DeepSeek",
        "url": "",
        "password": False,
        "category": "provider",
    },
    "DASHSCOPE_API_KEY": {
        "description": "Chave API da Alibaba Cloud DashScope (Qwen + modelos multi-provedor)",
        "prompt": "Chave API da DashScope",
        "url": "https://modelstudio.console.alibabacloud.com/",
        "password": True,
        "category": "provider",
    },
    "DASHSCOPE_BASE_URL": {
        "description": "URL base personalizada da DashScope (padrão: endpoint compatível com OpenAI coding-intl)",
        "prompt": "URL Base da DashScope",
        "url": "",
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "ECTOR_QWEN_BASE_URL": {
        "description": "Sobrescrita da URL base do Qwen Portal (padrão: https://portal.qwen.ai/v1).",
        "prompt": "URL base do Qwen Portal (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "ECTOR_GEMINI_CLIENT_ID": {
        "description": "ID do cliente Google OAuth para google-gemini-cli (opcional; padrão é o cliente público gemini-cli do Google)",
        "prompt": "ID do cliente Google OAuth (opcional — deixe vazio para usar o padrão público)",
        "url": "https://console.cloud.google.com/apis/credentials",
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "ECTOR_GEMINI_CLIENT_SECRET": {
        "description": "Segredo do cliente Google OAuth para google-gemini-cli (opcional)",
        "prompt": "Segredo do cliente Google OAuth (opcional)",
        "url": "https://console.cloud.google.com/apis/credentials",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "ECTOR_GEMINI_PROJECT_ID": {
        "description": "ID do projeto GCP para tiers pagos do Gemini (o tier gratuito auto-provisiona)",
        "prompt": "ID do projeto GCP para Gemini OAuth (deixe vazio para o tier gratuito)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "HF_TOKEN": {
        "description": "Token do Hugging Face para Provedores de Inferência (mais de 20 modelos abertos via router.huggingface.co)",
        "prompt": "Token do Hugging Face",
        "url": "https://huggingface.co/settings/tokens",
        "password": True,
        "category": "provider",
    },
    "HF_BASE_URL": {
        "description": "Sobrescrita da URL base do Hugging Face Inference Providers",
        "prompt": "URL base do HF (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "OLLAMA_API_KEY": {
        "description": "Chave API do Ollama Cloud (ollama.com — modelos abertos hospedados na nuvem)",
        "prompt": "Chave API do Ollama Cloud",
        "url": "https://ollama.com/settings",
        "password": True,
        "category": "provider",
        "advanced": True,
    },
    "OLLAMA_BASE_URL": {
        "description": "Sobrescrita da URL base do Ollama Cloud (padrão: https://ollama.com/v1)",
        "prompt": "URL base do Ollama (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "XIAOMI_API_KEY": {
        "description": "Chave API da Xiaomi MiMo para modelos MiMo (mimo-v2.5-pro, mimo-v2.5, mimo-v2-pro, mimo-v2-omni, mimo-v2-flash)",
        "prompt": "Chave API da Xiaomi MiMo",
        "url": "https://platform.xiaomimimo.com",
        "password": True,
        "category": "provider",
    },
    "XIAOMI_BASE_URL": {
        "description": "Sobrescrita da URL base da Xiaomi MiMo (padrão: https://api.xiaomimimo.com/v1)",
        "prompt": "URL base da Xiaomi (deixe vazio para o padrão)",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "AWS_REGION": {
        "description": "Região AWS para chamadas da API Bedrock (ex: us-east-1, eu-central-1)",
        "prompt": "Região AWS",
        "url": "https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html",
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "AWS_PROFILE": {
        "description": "Perfil nomeado da AWS para autenticação no Bedrock (de ~/.aws/credentials)",
        "prompt": "Perfil AWS",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "AZURE_FOUNDRY_API_KEY": {
        "description": "Chave API do Azure Foundry para endpoints personalizados do Azure",
        "prompt": "Chave API do Azure Foundry",
        "url": "https://ai.azure.com/",
        "password": True,
        "category": "provider",
    },
    "AZURE_FOUNDRY_BASE_URL": {
        "description": "URL base do Azure Foundry (definida via 'ector provider' para config específica de endpoint)",
        "prompt": "URL base do Azure Foundry",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },

    # ── Chaves API de Ferramentas ──
    "EXA_API_KEY": {
        "description": "Chave API da Exa para pesquisa e conteúdos web nativos de IA",
        "prompt": "Chave API da Exa",
        "url": "https://exa.ai/",
        "tools": ["web_search", "web_extract"],
        "password": True,
        "category": "tool",
    },
    "PARALLEL_API_KEY": {
        "description": "Chave API da Parallel para pesquisa e extração web nativa de IA",
        "prompt": "Chave API da Parallel",
        "url": "https://parallel.ai/",
        "tools": ["web_search", "web_extract"],
        "password": True,
        "category": "tool",
    },
    "FIRECRAWL_API_KEY": {
        "description": "Chave API da Firecrawl para pesquisa e raspagem web",
        "prompt": "Chave API da Firecrawl",
        "url": "https://firecrawl.dev/",
        "tools": ["web_search", "web_extract"],
        "password": True,
        "category": "tool",
    },
    "FIRECRAWL_API_URL": {
        "description": "URL da API Firecrawl para instâncias auto-hospedadas (opcional)",
        "prompt": "URL da API Firecrawl (deixe vazio para nuvem)",
        "url": None,
        "password": False,
        "category": "tool",
        "advanced": True,
    },
    "FIRECRAWL_GATEWAY_URL": {
        "description": "(deprecated) Managed tool gateway removed — use FIRECRAWL_API_KEY or FIRECRAWL_API_URL",
        "prompt": "URL do gateway Firecrawl (obsoleto)",
        "url": None,
        "password": False,
        "category": "tool",
        "advanced": True,
        "deprecated": True,
    },
    "TOOL_GATEWAY_DOMAIN": {
        "description": "(deprecated) Managed tool gateway removed — configure provider API keys directly",
        "prompt": "Sufixo de domínio do tool-gateway (obsoleto)",
        "url": None,
        "password": False,
        "category": "tool",
        "advanced": True,
        "deprecated": True,
    },
    "TOOL_GATEWAY_SCHEME": {
        "description": "(deprecated) Managed tool gateway removed",
        "prompt": "Esquema de URL do tool-gateway (obsoleto)",
        "url": None,
        "password": False,
        "category": "tool",
        "advanced": True,
        "deprecated": True,
    },
    "TOOL_GATEWAY_USER_TOKEN": {
        "description": "(deprecated) Managed tool gateway removed",
        "prompt": "Token de usuário do tool-gateway (obsoleto)",
        "url": None,
        "password": True,
        "category": "tool",
        "advanced": True,
        "deprecated": True,
    },
    "TAVILY_API_KEY": {
        "description": "Chave API da Tavily para pesquisa, extração e rastreamento web nativos de IA",
        "prompt": "Chave API da Tavily",
        "url": "https://app.tavily.com/home",
        "tools": ["web_search", "web_extract", "web_crawl"],
        "password": True,
        "category": "tool",
    },
    "BROWSERBASE_API_KEY": {
        "description": "Chave API da Browserbase para navegador na nuvem (opcional — navegador local funciona sem isso)",
        "prompt": "Chave API da Browserbase",
        "url": "https://browserbase.com/",
        "tools": ["browser_navigate", "browser_click"],
        "password": True,
        "category": "tool",
    },
    "BROWSERBASE_PROJECT_ID": {
        "description": "ID do projeto Browserbase (opcional — necessário apenas para navegador na nuvem)",
        "prompt": "ID do projeto Browserbase",
        "url": "https://browserbase.com/",
        "tools": ["browser_navigate", "browser_click"],
        "password": False,
        "category": "tool",
    },
    "BROWSER_USE_API_KEY": {
        "description": "Chave API da Browser Use para navegador na nuvem (opcional — navegador local funciona sem isso)",
        "prompt": "Chave API da Browser Use",
        "url": "https://browser-use.com/",
        "tools": ["browser_navigate", "browser_click"],
        "password": True,
        "category": "tool",
    },
    "FIRECRAWL_BROWSER_TTL": {
        "description": "TTL da sessão do navegador Firecrawl em segundos (opcional, padrão 300)",
        "prompt": "TTL da sessão do navegador (segundos)",
        "tools": ["browser_navigate", "browser_click"],
        "password": False,
        "category": "tool",
    },
    "CAMOFOX_URL": {
        "description": "URL do servidor de navegador Camofox para navegação local anti-detecção (ex: http://localhost:9377)",
        "prompt": "URL do servidor Camofox",
        "url": "https://github.com/jo-inc/camofox-browser",
        "tools": ["browser_navigate", "browser_click"],
        "password": False,
        "category": "tool",
    },
    "FAL_KEY": {
        "description": "Chave API da FAL para geração de imagens",
        "prompt": "Chave API da FAL",
        "url": "https://fal.ai/",
        "tools": ["image_generate"],
        "password": True,
        "category": "tool",
    },
    "TINKER_API_KEY": {
        "description": "Chave API da Tinker para treinamento RL",
        "prompt": "Chave API da Tinker",
        "url": "https://tinker-console.thinkingmachines.ai/keys",
        "tools": ["rl_start_training", "rl_check_status", "rl_stop_training"],
        "password": True,
        "category": "tool",
    },
    "WANDB_API_KEY": {
        "description": "Chave API da Weights & Biases para rastreamento de experimentos",
        "prompt": "Chave API da WandB",
        "url": "https://wandb.ai/authorize",
        "tools": ["rl_get_results", "rl_check_status"],
        "password": True,
        "category": "tool",
    },
    "VOICE_TOOLS_OPENAI_KEY": {
        "description": "Chave API da OpenAI para transcrição de voz (Whisper) e OpenAI TTS",
        "prompt": "Chave API da OpenAI (para Whisper STT + TTS)",
        "url": "https://platform.openai.com/api-keys",
        "tools": ["voice_transcription", "openai_tts"],
        "password": True,
        "category": "tool",
    },
    "ELEVENLABS_API_KEY": {
        "description": "Chave API da ElevenLabs para vozes premium de conversão de texto em fala",
        "prompt": "Chave API da ElevenLabs",
        "url": "https://elevenlabs.io/",
        "password": True,
        "category": "tool",
    },
    "MISTRAL_API_KEY": {
        "description": "Chave API da Mistral para Voxtral TTS e transcrição (STT)",
        "prompt": "Chave API da Mistral",
        "url": "https://console.mistral.ai/",
        "password": True,
        "category": "tool",
    },
    "GITHUB_TOKEN": {
        "description": "Token do GitHub para Skills Hub (limites de taxa de API maiores, publicação de skills)",
        "prompt": "Token do GitHub",
        "url": "https://github.com/settings/tokens",
        "password": True,
        "category": "tool",
    },

    # ── Skills integradas (opcionais: necessárias apenas se o usuário usar a skill) ──
    # Estas usam category="skill" (distinto de "tool") para que o bloco de lista negra
    # do sandbox em tools/environments/local.py NÃO as sobrescreva —
    # skills legitimamente precisam que estas sejam passadas para o curl via
    # tools/env_passthrough.py quando a skill do usuário faz chamadas externas.
    "NOTION_API_KEY": {
        "description": "Token de integração do Notion (usado pela skill `notion`) ",
        "prompt": "Chave API do Notion",
        "url": "https://www.notion.so/my-integrations",
        "password": True,
        "category": "skill",
        "advanced": True,
    },
    "LINEAR_API_KEY": {
        "description": "Chave API pessoal do Linear (usada pela skill `linear`) ",
        "prompt": "Chave API do Linear",
        "url": "https://linear.app/settings/api",
        "password": True,
        "category": "skill",
        "advanced": True,
    },
    "AIRTABLE_API_KEY": {
        "description": "Token de acesso pessoal do Airtable (usado pela skill `airtable`) ",
        "prompt": "Chave API do Airtable",
        "url": "https://airtable.com/create/tokens",
        "password": True,
        "category": "skill",
        "advanced": True,
    },
    "TENOR_API_KEY": {
        "description": "Chave API da Tenor para busca de GIFs (usada pela skill `gif-search`) ",
        "prompt": "Chave API da Tenor",
        "url": "https://developers.google.com/tenor/guides/quickstart",
        "password": True,
        "category": "skill",
        "advanced": True,
    },

    # ── Plataformas de Mensagens ──
    "TELEGRAM_BOT_TOKEN": {
        "description": "Token do bot do Telegram do @BotFather",
        "prompt": "Token do bot do Telegram",
        "url": "https://t.me/BotFather",
        "password": True,
        "category": "messaging",
    },
    "TELEGRAM_ALLOWED_USERS": {
        "description": "IDs de usuário do Telegram permitidos a usar o bot, separados por vírgula (obtenha o ID em @userinfobot)",
        "prompt": "IDs de usuário do Telegram permitidos (separados por vírgula)",
        "url": "https://t.me/userinfobot",
        "password": False,
        "category": "messaging",
    },
    "TELEGRAM_PROXY": {
        "description": "URL do proxy para conexões do Telegram (sobrescreve HTTPS_PROXY). Suporta http://, https://, socks5://",
        "prompt": "URL do proxy do Telegram (opcional)",
        "password": False,
        "category": "messaging",
    },
    "DISCORD_BOT_TOKEN": {
        "description": "Token do bot do Discord do Portal de Desenvolvedores",
        "prompt": "Token do bot do Discord",
        "url": "https://discord.com/developers/applications",
        "password": True,
        "category": "messaging",
    },
    "DISCORD_ALLOWED_USERS": {
        "description": "IDs de usuário do Discord permitidos a usar o bot, separados por vírgula",
        "prompt": "IDs de usuário do Discord permitidos (separados por vírgula)",
        "url": None,
        "password": False,
        "category": "messaging",
    },
    "DISCORD_REPLY_TO_MODE": {
        "description": "Modo de encadeamento de respostas do Discord: 'off' (sem referências de resposta), 'first' (responder apenas na primeira mensagem, padrão), 'all' (responder em cada bloco)",
        "prompt": "Modo de resposta do Discord (off/first/all)",
        "url": None,
        "password": False,
        "category": "messaging",
    },
    "SLACK_BOT_TOKEN": {
        "description": "Token do bot do Slack (xoxb-). Obtenha em OAuth & Permissions após instalar seu aplicativo. "
                       "Escopos necessários: chat:write, app_mentions:read, channels:history, groups:history, "
                       "im:history, im:read, im:write, users:read, files:read, files:write",
        "prompt": "Token do Bot do Slack (xoxb-...)",
        "url": "https://api.slack.com/apps",
        "password": True,
        "category": "messaging",
    },
    "SLACK_APP_TOKEN": {
        "description": "Token de nível de aplicativo do Slack (xapp-) para Socket Mode. Obtenha em Informações Básicas → "
                       "App-Level Tokens. Certifique-se também de que as Inscrições em Eventos incluam: message.im, "
                       "message.channels, message.groups, app_mention",
        "prompt": "Token do Aplicativo Slack (xapp-...)",
        "url": "https://api.slack.com/apps",
        "password": True,
        "category": "messaging",
    },
    "SLACK_ALLOWED_USERS": {
        "description": "IDs de usuário do Slack permitidos a usar o bot, separados por vírgula",
        "prompt": "IDs de usuário do Slack permitidos (separados por vírgula)",
        "url": None,
        "password": False,
        "category": "messaging",
    },
    "WHATSAPP_ENABLED": {
        "description": "Habilitar integração WhatsApp (true/false). Após habilitar, emparelhe em /channels.",
        "prompt": "Habilitar WhatsApp (true/false)",
        "url": None,
        "password": False,
        "category": "messaging",
    },
    "WHATSAPP_MODE": {
        "description": "Modo WhatsApp: self-chat (padrão) ou bot",
        "prompt": "Modo WhatsApp (self-chat/bot)",
        "url": None,
        "password": False,
        "category": "messaging",
        "advanced": True,
    },
    "WHATSAPP_ALLOWED_USERS": {
        "description": "Números WhatsApp permitidos (E.164, separados por vírgula)",
        "prompt": "Números WhatsApp permitidos",
        "url": None,
        "password": False,
        "category": "messaging",
    },
    "GATEWAY_ALLOW_ALL_USERS": {
        "description": "Allow all users to interact with messaging bots (true/false). Default: false.",
        "prompt": "Allow all users (true/false)",
        "url": None,
        "password": False,
        "category": "messaging",
        "advanced": True,
    },
    "GATEWAY_PROXY_URL": {
        "description": "URL of a remote Ector API server to forward messages to (proxy mode). When set, the gateway handles platform I/O only — all agent work is delegated to the remote server. Use for Docker E2EE containers that relay to a host agent. Also configurable via gateway.proxy_url in config.yaml.",
        "prompt": "Remote Ector API server URL (e.g. http://192.168.1.100:8642)",
        "url": None,
        "password": False,
        "category": "messaging",
        "advanced": True,
    },
    "GATEWAY_PROXY_KEY": {
        "description": "Bearer token for authenticating with the remote Ector API server (proxy mode). Must match the API_SERVER_KEY on the remote host.",
        "prompt": "Remote API server auth key",
        "url": None,
        "password": True,
        "category": "messaging",
        "advanced": True,
    },
    # Identity backend URL: use auth.base_url in config.yaml (not .env).
    # ECTOR_AUTH_BASE_URL is intentionally omitted from OPTIONAL_ENV_VARS.

    # ── Agent settings ──
    # NOTE: MESSAGING_CWD was removed here — use terminal.cwd in config.yaml
    # instead.  The gateway reads TERMINAL_CWD (bridged from terminal.cwd).
    "SUDO_PASSWORD": {
        "description": "Sudo password for terminal commands requiring root access; set to an explicit empty string to try empty without prompting",
        "prompt": "Sudo password",
        "url": None,
        "password": True,
        "category": "setting",
    },
    "ECTOR_MAX_ITERATIONS": {
        "description": "Maximum tool-calling iterations per conversation (default: 90)",
        "prompt": "Max iterations",
        "url": None,
        "password": False,
        "category": "setting",
    },
    # ECTOR_TOOL_PROGRESS and ECTOR_TOOL_PROGRESS_MODE are deprecated —
    # now configured via display.tool_progress in config.yaml (off|new|all|verbose).
    # Gateway falls back to these env vars for backward compatibility.
    "ECTOR_TOOL_PROGRESS": {
        "description": "(deprecated) Use display.tool_progress in config.yaml instead",
        "prompt": "Tool progress (deprecated — use config.yaml)",
        "url": None,
        "password": False,
        "category": "setting",
    },
    "ECTOR_TOOL_PROGRESS_MODE": {
        "description": "(deprecated) Use display.tool_progress in config.yaml instead",
        "prompt": "Progress mode (deprecated — use config.yaml)",
        "url": None,
        "password": False,
        "category": "setting",
    },
    "ECTOR_PREFILL_MESSAGES_FILE": {
        "description": "Path to JSON file with ephemeral prefill messages for few-shot priming",
        "prompt": "Prefill messages file path",
        "url": None,
        "password": False,
        "category": "setting",
    },
    "ECTOR_EPHEMERAL_SYSTEM_PROMPT": {
        "description": "Ephemeral system prompt injected at API-call time (never persisted to sessions)",
        "prompt": "Ephemeral system prompt",
        "url": None,
        "password": False,
        "category": "setting",
    },
}

# Tool Gateway env vars are always visible — they're useful for
# self-hosted / custom gateway setups regardless of subscription state.


def get_missing_env_vars(required_only: bool = False) -> List[Dict[str, Any]]:
    """
    Check which environment variables are missing.
    
    Returns list of dicts with var info for missing variables.
    """
    missing = []
    
    # Check required vars
    for var_name, info in REQUIRED_ENV_VARS.items():
        if not get_env_value(var_name):
            missing.append({"name": var_name, **info, "is_required": True})
    
    # Check optional vars (if not required_only)
    if not required_only:
        for var_name, info in OPTIONAL_ENV_VARS.items():
            if not get_env_value(var_name):
                missing.append({"name": var_name, **info, "is_required": False})
    
    return missing


def _set_nested(config: dict, dotted_key: str, value):
    """Set a value at an arbitrarily nested dotted key path.

    Creates intermediate dicts as needed, e.g. ``_set_nested(c, "a.b.c", 1)``
    ensures ``c["a"]["b"]["c"] == 1``.
    """
    parts = dotted_key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def get_missing_config_fields() -> List[Dict[str, Any]]:
    """
    Check which config fields are missing or outdated (recursive).
    
    Walks the DEFAULT_CONFIG tree at arbitrary depth and reports any keys
    present in defaults but absent from the user's loaded config.
    """
    config = load_config()
    missing = []

    def _check(defaults: dict, current: dict, prefix: str = ""):
        for key, default_value in defaults.items():
            if key.startswith('_'):
                continue
            full_key = key if not prefix else f"{prefix}.{key}"
            if key not in current:
                missing.append({
                    "key": full_key,
                    "default": default_value,
                    "description": f"Nova opção de configuração: {full_key}",
                })
            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
                _check(default_value, current[key], full_key)

    _check(DEFAULT_CONFIG, config)
    return missing


def get_missing_skill_config_vars() -> List[Dict[str, Any]]:
    """Return skill-declared config vars that are missing or empty in config.yaml.

    Scans all enabled skills for ``metadata.ector.config`` entries, then checks
    which ones are absent or empty under ``skills.config.<key>`` in the user's
    config.yaml.  Returns a list of dicts suitable for prompting.
    """
    try:
        from agent.skill_utils import discover_all_skill_config_vars, SKILL_CONFIG_PREFIX
    except Exception:
        return []

    all_vars = discover_all_skill_config_vars()
    if not all_vars:
        return []

    config = load_config()
    missing: List[Dict[str, Any]] = []
    for var in all_vars:
        # Skill config is stored under skills.config.<logical_key>
        storage_key = f"{SKILL_CONFIG_PREFIX}.{var['key']}"
        parts = storage_key.split(".")
        current = config
        value = None
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
                value = current
            else:
                value = None
                break
        # Missing = key doesn't exist or is empty string
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(var)
    return missing


def _normalize_custom_provider_entry(
    entry: Any,
    *,
    provider_key: str = "",
) -> Optional[Dict[str, Any]]:
    """Return a runtime-compatible custom provider entry or ``None``."""
    if not isinstance(entry, dict):
        return None

    # Accept camelCase aliases commonly used in hand-written configs.
    _CAMEL_ALIASES: Dict[str, str] = {
        "apiKey": "api_key",
        "baseUrl": "base_url",
        "apiMode": "api_mode",
        "keyEnv": "key_env",
        "defaultModel": "default_model",
        "contextLength": "context_length",
        "rateLimitDelay": "rate_limit_delay",
    }
    _KNOWN_KEYS = {
        "name", "api", "url", "base_url", "api_key", "key_env",
        "api_mode", "transport", "model", "default_model", "models",
        "context_length", "rate_limit_delay",
    }
    for camel, snake in _CAMEL_ALIASES.items():
        if camel in entry and snake not in entry:
            logger.warning(
                "providers.%s: chave camelCase '%s' mapeada automaticamente para '%s' "
                "(use snake_case para evitar este aviso)",
                provider_key or "?", camel, snake,
            )
            entry[snake] = entry[camel]
    unknown = set(entry.keys()) - _KNOWN_KEYS - set(_CAMEL_ALIASES.keys())
    if unknown:
        logger.warning(
            "providers.%s: chaves de configuração desconhecidas ignoradas: %s",
            provider_key or "?", ", ".join(sorted(unknown)),
        )

    from urllib.parse import urlparse

    base_url = ""
    for url_key in ("base_url", "url", "api"):
        raw_url = entry.get(url_key)
        if isinstance(raw_url, str) and raw_url.strip():
            candidate = raw_url.strip()
            parsed = urlparse(candidate)
            if parsed.scheme and parsed.netloc:
                base_url = candidate
                break
            else:
                logger.warning(
                    "providers.%s: valor '%s' de '%s' não é uma URL válida "
                    "(sem esquema ou host) — ignorado",
                    provider_key or "?", url_key, candidate,
                )
    if not base_url:
        return None

    name = ""
    raw_name = entry.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        name = raw_name.strip()
    elif provider_key.strip():
        name = provider_key.strip()
    if not name:
        return None

    normalized: Dict[str, Any] = {
        "name": name,
        "base_url": base_url,
    }

    provider_key = provider_key.strip()
    if provider_key:
        normalized["provider_key"] = provider_key

    api_key = entry.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        normalized["api_key"] = api_key.strip()

    key_env = entry.get("key_env")
    if isinstance(key_env, str) and key_env.strip():
        normalized["key_env"] = key_env.strip()

    api_mode = entry.get("api_mode") or entry.get("transport")
    if isinstance(api_mode, str) and api_mode.strip():
        normalized["api_mode"] = api_mode.strip()

    model_name = entry.get("model") or entry.get("default_model")
    if isinstance(model_name, str) and model_name.strip():
        normalized["model"] = model_name.strip()

    models = entry.get("models")
    if isinstance(models, dict) and models:
        normalized["models"] = models
    elif isinstance(models, list) and models:
        # Hand-edited configs (and older Ector versions) write ``models`` as
        # a plain list of model ids. Preserve them by converting to the dict
        # shape downstream code expects; otherwise normalize silently drops
        # the list and /provider shows the provider with (0) models.
        normalized["models"] = {
            str(m): {} for m in models if isinstance(m, str) and m.strip()
        }

    context_length = entry.get("context_length")
    if isinstance(context_length, int) and context_length > 0:
        normalized["context_length"] = context_length

    rate_limit_delay = entry.get("rate_limit_delay")
    if isinstance(rate_limit_delay, (int, float)) and rate_limit_delay >= 0:
        normalized["rate_limit_delay"] = rate_limit_delay

    return normalized


def providers_dict_to_custom_providers(providers_dict: Any) -> List[Dict[str, Any]]:
    """Normalize ``providers`` config entries into the legacy custom-provider shape."""
    if not isinstance(providers_dict, dict):
        return []

    custom_providers: List[Dict[str, Any]] = []
    for key, entry in providers_dict.items():
        normalized = _normalize_custom_provider_entry(entry, provider_key=str(key))
        if normalized is not None:
            custom_providers.append(normalized)

    return custom_providers


def get_compatible_custom_providers(
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return a deduplicated custom-provider view across legacy and v12+ config.

    ``custom_providers`` remains the on-disk legacy format, while ``providers``
    is the newer keyed schema.  Runtime and picker flows still need a single
    list-shaped view, but we should not materialise that compatibility layer
    back into config.yaml because it duplicates entries in UIs.
    """
    if config is None:
        config = load_config()

    compatible: List[Dict[str, Any]] = []
    seen_provider_keys: set = set()
    seen_name_url_pairs: set = set()

    def _append_if_new(entry: Optional[Dict[str, Any]]) -> None:
        if entry is None:
            return
        provider_key = str(entry.get("provider_key", "") or "").strip().lower()
        name = str(entry.get("name", "") or "").strip().lower()
        base_url = str(entry.get("base_url", "") or "").strip().rstrip("/").lower()
        model = str(entry.get("model", "") or "").strip().lower()
        pair = (name, base_url, model)

        if provider_key and provider_key in seen_provider_keys:
            return
        if name and base_url and pair in seen_name_url_pairs:
            return

        compatible.append(entry)
        if provider_key:
            seen_provider_keys.add(provider_key)
        if name and base_url:
            seen_name_url_pairs.add(pair)

    custom_providers = config.get("custom_providers")
    if custom_providers is not None:
        if not isinstance(custom_providers, list):
            return []
        for entry in custom_providers:
            _append_if_new(_normalize_custom_provider_entry(entry))

    for entry in providers_dict_to_custom_providers(config.get("providers")):
        _append_if_new(entry)

    return compatible


def get_custom_provider_context_length(
    model: str,
    base_url: str,
    custom_providers: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Look up a per-model ``context_length`` override from ``custom_providers``.

    Matches any entry whose ``base_url`` equals ``base_url`` (trailing-slash
    insensitive) and returns ``custom_providers[i].models.<model>.context_length``
    if present and valid.  Returns ``None`` when no override applies.

    This is the single source of truth for custom-provider context overrides,
    used by:
      * ``AIAgent.__init__`` (startup resolution)
      * ``AIAgent.switch_model`` (mid-session ``/provider`` switch)
      * ``ector_cli.model_switch.resolve_display_context_length`` (``/provider`` confirmation display)
      * ``gateway.run._format_session_info`` (``/info`` display)
      * ``agent.model_metadata.get_model_context_length`` (when custom_providers is threaded through)

    Before this helper existed, the lookup was duplicated in ``run_agent.py``'s
    startup path only; every other path (notably ``/provider`` switch) fell back
    to the 128K default.  See #15779.
    """
    if not model or not base_url:
        return None
    if custom_providers is None:
        try:
            custom_providers = get_compatible_custom_providers(config)
        except Exception:
            if config is None:
                return None
            raw = config.get("custom_providers")
            custom_providers = raw if isinstance(raw, list) else []
    if not isinstance(custom_providers, list):
        return None

    target_url = (base_url or "").rstrip("/")
    if not target_url:
        return None

    for entry in custom_providers:
        if not isinstance(entry, dict):
            continue
        entry_url = (entry.get("base_url") or "").rstrip("/")
        if not entry_url or entry_url != target_url:
            continue
        models = entry.get("models")
        if not isinstance(models, dict):
            continue
        model_cfg = models.get(model)
        if not isinstance(model_cfg, dict):
            continue
        raw_ctx = model_cfg.get("context_length")
        if raw_ctx is None:
            continue
        try:
            ctx = int(raw_ctx)
        except (TypeError, ValueError):
            continue
        if ctx > 0:
            return ctx
    return None


def check_config_version() -> Tuple[int, int]:
    """
    Check config version.
    
    Returns (current_version, latest_version).
    """
    config = load_config()
    current = config.get("_config_version", 0)
    latest = DEFAULT_CONFIG.get("_config_version", 1)
    return current, latest


# =============================================================================
# Config structure validation
# =============================================================================

# Fields that are valid at root level of config.yaml
_KNOWN_ROOT_KEYS = {
    "_config_version", "model", "providers", "fallback_model",
    "fallback_providers", "credential_pool_strategies", "toolsets",
    "agent", "terminal", "display", "compression", "delegation",
    "auxiliary", "custom_providers", "context", "memory", "gateway",
    "sessions",
}

# Valid fields inside a custom_providers list entry
_VALID_CUSTOM_PROVIDER_FIELDS = {
    "name", "base_url", "api_key", "api_mode", "model", "models",
    "context_length", "rate_limit_delay",
}

# Fields that look like they should be inside custom_providers, not at root
_CUSTOM_PROVIDER_LIKE_FIELDS = {"base_url", "api_key", "rate_limit_delay", "api_mode"}


@dataclass
class ConfigIssue:
    """A detected config structure problem."""

    severity: str  # "error", "warning"
    message: str
    hint: str


def validate_config_structure(config: Optional[Dict[str, Any]] = None) -> List["ConfigIssue"]:
    """Validate config.yaml structure and return a list of detected issues.

    Catches common YAML formatting mistakes that produce confusing runtime
    errors (like "Unknown provider") instead of clear diagnostics.

    Can be called with a pre-loaded config dict, or will load from disk.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            return [ConfigIssue("error", "Não foi possível carregar o config.yaml", "Execute 'ector setup' para criar uma configuração válida")]

    issues: List[ConfigIssue] = []

    # ── custom_providers must be a list, not a dict ──────────────────────
    cp = config.get("custom_providers")
    if cp is not None:
        if isinstance(cp, dict):
            issues.append(ConfigIssue(
                "error",
                "custom_providers é um dict — ele deve ser uma lista YAML (itens prefixados com '-')",
                "Altere para:\n"
                "  custom_providers:\n"
                "    - name: meu-provedor\n"
                "      base_url: https://...\n"
                "      api_key: ...",
            ))
            # Check if dict keys look like they should be list-entry fields
            cp_keys = set(cp.keys()) if isinstance(cp, dict) else set()
            suspicious = cp_keys & _CUSTOM_PROVIDER_LIKE_FIELDS
            if suspicious:
                issues.append(ConfigIssue(
                    "warning",
                    f"As chaves de nível raiz {sorted(suspicious)} parecem campos de entrada de custom_providers",
                    "Estes devem estar recuados sob uma entrada de lista '- name: ...', não no nível raiz",
                ))
        elif isinstance(cp, list):
            # Validate each entry in the list
            for i, entry in enumerate(cp):
                if not isinstance(entry, dict):
                    issues.append(ConfigIssue(
                        "warning",
                        f"custom_providers[{i}] não é um dict (recebeu {type(entry).__name__})",
                        "Cada entrada deve ter no mínimo: name, base_url",
                    ))
                    continue
                if not entry.get("name"):
                    issues.append(ConfigIssue(
                        "warning",
                        f"custom_providers[{i}] está faltando o campo 'name'",
                        "Adicione um nome, ex: name: meu-provedor",
                    ))
                if not entry.get("base_url"):
                    issues.append(ConfigIssue(
                        "warning",
                        f"custom_providers[{i}] está faltando o campo 'base_url'",
                        "Adicione a URL do endpoint da API, ex: base_url: https://api.exemplo.com/v1",
                    ))

    # ── fallback_model must be a top-level dict with provider + model ────
    fb = config.get("fallback_model")
    if fb is not None:
        if not isinstance(fb, dict):
            issues.append(ConfigIssue(
                "error",
                f"fallback_model deve ser um dict com 'provider' e 'model', recebeu {type(fb).__name__}",
                "Altere para:\n"
                "  fallback_model:\n"
                "    provider: openrouter\n"
                "    model: anthropic/claude-sonnet-4",
            ))
        elif fb:
            if not fb.get("provider"):
                issues.append(ConfigIssue(
                    "warning",
                    "fallback_model está faltando o campo 'provider' — o fallback será desativado",
                    "Adicione: provider: openrouter (ou outro provedor)",
                ))
            if not fb.get("model"):
                issues.append(ConfigIssue(
                    "warning",
                    "fallback_model está faltando o campo 'model' — o fallback será desativado",
                    "Adicione: model: anthropic/claude-sonnet-4 (ou outro modelo)",
                ))

    # ── Check for fallback_model accidentally nested inside custom_providers ──
    if isinstance(cp, dict) and "fallback_model" not in config and "fallback_model" in (cp or {}):
        issues.append(ConfigIssue(
            "error",
            "fallback_model aparece dentro de custom_providers em vez de no nível raiz",
            "Mova o fallback_model para o nível raiz do config.yaml (sem recuo)",
        ))

    # ── model section: should exist when custom_providers is configured ──
    model_cfg = config.get("model")
    if cp and not model_cfg:
        issues.append(ConfigIssue(
            "warning",
            "custom_providers definido mas nenhuma seção 'model' — o Ector não saberá qual provedor usar",
            "Adicione uma seção model:\n"
            "  model:\n"
            "    provider: custom\n"
            "    default: nome-do-seu-modelo\n"
            "    base_url: https://...",
        ))

    # ── Root-level keys that look misplaced ──────────────────────────────
    for key in config:
        if key.startswith("_"):
            continue
        if key not in _KNOWN_ROOT_KEYS and key in _CUSTOM_PROVIDER_LIKE_FIELDS:
            issues.append(ConfigIssue(
                "warning",
                f"A chave de nível raiz '{key}' parece deslocada — ela deveria estar sob 'model:' ou dentro de uma entrada 'custom_providers'?",
                f"Mova '{key}' para a seção apropriada",
            ))

    return issues


def print_config_warnings(config: Optional[Dict[str, Any]] = None) -> None:
    """Print config structure warnings to stderr at startup.

    Called early in CLI and gateway init so users see problems before
    they hit cryptic "Unknown provider" errors.  Prints nothing if
    config is healthy.
    """
    try:
        issues = validate_config_structure(config)
    except Exception:
        return
    if not issues:
        return

    lines = ["\033[33m▲ Problemas de config detectados no config.yaml:\033[0m"]
    for ci in issues:
        marker = "\033[31m✖\033[0m" if ci.severity == "error" else "\033[33m▲\033[0m"
        lines.append(f"  {marker} {ci.message}")
    lines.append("  \033[2mExecute 'ector doctor' para sugestões de correção.\033[0m")
    sys.stderr.write("\n".join(lines) + "\n\n")


def warn_deprecated_cwd_env_vars(config: Optional[Dict[str, Any]] = None) -> None:
    """Warn if MESSAGING_CWD or TERMINAL_CWD is set in .env instead of config.yaml.

    These env vars are deprecated — the canonical setting is terminal.cwd
    in config.yaml.  Prints a migration hint to stderr.
    """
    messaging_cwd = os.environ.get("MESSAGING_CWD")
    terminal_cwd_env = os.environ.get("TERMINAL_CWD")

    if config is None:
        try:
            config = load_config()
        except Exception:
            return

    terminal_cfg = config.get("terminal", {})
    config_cwd = terminal_cfg.get("cwd", ".") if isinstance(terminal_cfg, dict) else "."
    # Only warn if config.yaml doesn't have an explicit path
    config_has_explicit_cwd = config_cwd not in (".", "auto", "cwd", "")

    lines: list[str] = []
    if messaging_cwd:
        lines.append(
            f"  \033[33m▲\033[0m MESSAGING_CWD={messaging_cwd} encontrado no .env — "
            f"isso está obsoleto."
        )
    if terminal_cwd_env and not config_has_explicit_cwd:
        # TERMINAL_CWD in env but not from config bridge — likely from .env
        lines.append(
            f"  \033[33m▲\033[0m TERMINAL_CWD={terminal_cwd_env} encontrado no .env — "
            f"isso está obsoleto."
        )
    if lines:
        hint_path = os.environ.get("ECTOR_HOME", "~/.ector")
        lines.insert(0, "\033[33m▲ Configurações obsoletas no .env detectadas:\033[0m")
        lines.append(
            f"  \033[2mMova para o config.yaml em vez disso:  "
            f"terminal:\\n    cwd: /seu/caminho/do/projeto\033[0m"
        )
        lines.append(
            f"  \033[2mEm seguida, remova as entradas antigas de {hint_path}/.env\033[0m"
        )
        sys.stderr.write("\n".join(lines) + "\n\n")


def migrate_config(interactive: bool = True, quiet: bool = False) -> Dict[str, Any]:
    """
    Migrate config to latest version, prompting for new required fields.
    
    Args:
        interactive: If True, prompt user for missing values
        quiet: If True, suppress output
        
    Returns:
        Dict with migration results: {"env_added": [...], "config_added": [...], "warnings": [...]}
    """
    results = {"env_added": [], "config_added": [], "warnings": []}

    # ── Always: sanitize .env (split concatenated keys) ──
    try:
        fixes = sanitize_env_file()
        if fixes and not quiet:
            print(f"  ✔ Arquivo .env reparado ({fixes} entradas corrompidas fixadas)")
    except Exception:
        pass  # best-effort; don't block migration on sanitize failure

    # Check config version
    current_ver, latest_ver = check_config_version()
    
    # ── Version 3 → 4: migrate tool progress from .env to config.yaml ──
    if current_ver < 4:
        config = load_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        if "tool_progress" not in display:
            old_enabled = get_env_value("ECTOR_TOOL_PROGRESS")
            old_mode = get_env_value("ECTOR_TOOL_PROGRESS_MODE")
            if old_enabled and old_enabled.lower() in ("false", "0", "no"):
                display["tool_progress"] = "off"
                results["config_added"].append("display.tool_progress=off (from ECTOR_TOOL_PROGRESS=false)")
            elif old_mode and old_mode.lower() in ("new", "all"):
                display["tool_progress"] = old_mode.lower()
                results["config_added"].append(f"display.tool_progress={old_mode.lower()} (from ECTOR_TOOL_PROGRESS_MODE)")
            else:
                display["tool_progress"] = "all"
                results["config_added"].append("display.tool_progress=all (default)")
            config["display"] = display
            save_config(config)
            if not quiet:
                print(f"  ✔ Progresso da ferramenta migrado para config.yaml: {display['tool_progress']}")
    
    # ── Version 4 → 5: add timezone field ──
    if current_ver < 5:
        config = load_config()
        if "timezone" not in config:
            old_tz = os.getenv("ECTOR_TIMEZONE", "")
            if old_tz and old_tz.strip():
                config["timezone"] = old_tz.strip()
                results["config_added"].append(f"timezone={old_tz.strip()} (from ECTOR_TIMEZONE)")
            else:
                config["timezone"] = ""
                results["config_added"].append("timezone= (empty, uses server-local)")
            save_config(config)
            if not quiet:
                tz_display = config["timezone"] or "(servidor-local)"
                print(f"  ✔ Fuso horário adicionado ao config.yaml: {tz_display}")

    # ── Version 8 → 9: clear ANTHROPIC_TOKEN from .env ──
    # The new Anthropic auth flow no longer uses this env var.
    if current_ver < 9:
        try:
            old_token = get_env_value("ANTHROPIC_TOKEN")
            if old_token:
                save_env_value("ANTHROPIC_TOKEN", "")
                if not quiet:
                    print("  ✔ ANTHROPIC_TOKEN removido do .env (não é mais usado)")
        except Exception:
            pass

    # ── Version 11 → 12: migrate custom_providers list → providers dict ──
    if current_ver < 12:
        config = load_config()
        custom_list = config.get("custom_providers")
        if isinstance(custom_list, list) and custom_list:
            providers_dict = config.get("providers", {})
            if not isinstance(providers_dict, dict):
                providers_dict = {}
            migrated_count = 0
            for entry in custom_list:
                if not isinstance(entry, dict):
                    continue
                old_name = entry.get("name", "")
                old_url = entry.get("base_url", "") or entry.get("url", "") or ""
                old_key = entry.get("api_key", "")
                if not old_url:
                    continue  # skip entries with no URL

                # Generate a kebab-case key from the display name
                key = old_name.strip().lower().replace(" ", "-").replace("(", "").replace(")", "")
                # Remove consecutive hyphens and trailing hyphens
                while "--" in key:
                    key = key.replace("--", "-")
                key = key.strip("-")
                if not key:
                    # Fallback: derive from URL hostname
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(old_url)
                        key = (parsed.hostname or "endpoint").replace(".", "-")
                    except Exception:
                        key = f"endpoint-{migrated_count}"

                # Don't overwrite existing entries
                if key in providers_dict:
                    key = f"{key}-{migrated_count}"

                new_entry = {"api": old_url}
                if old_name:
                    new_entry["name"] = old_name
                if old_key and old_key not in ("no-key", "no-key-required", ""):
                    new_entry["api_key"] = old_key

                # Carry over model and api_mode if present
                if entry.get("model"):
                    new_entry["default_model"] = entry["model"]
                if entry.get("api_mode"):
                    new_entry["transport"] = entry["api_mode"]

                providers_dict[key] = new_entry
                migrated_count += 1

            if migrated_count > 0:
                config["providers"] = providers_dict
                # Remove the old list — runtime reads via get_compatible_custom_providers()
                config.pop("custom_providers", None)
                save_config(config)
                if not quiet:
                    print(f"  ✔ Migrado(s) {migrated_count} provedor(es) personalizado(s) para a seção providers:")
                    for key in list(providers_dict.keys())[-migrated_count:]:
                        ep = providers_dict[key]
                        print(f"    → {key}: {ep.get('api', '')}")

    # ── Version 12 → 13: clear dead LLM_MODEL / OPENAI_MODEL from .env ──
    # These env vars were written by the old setup wizard but nothing reads
    # them anymore (config.yaml is the sole source of truth since March 2026).
    # Stale entries cause user confusion — see issue report.
    if current_ver < 13:
        for dead_var in ("LLM_MODEL", "OPENAI_MODEL"):
            try:
                old_val = get_env_value(dead_var)
                if old_val:
                    save_env_value(dead_var, "")
                    if not quiet:
                        print(f"  ✔ {dead_var} removido do .env (não é mais usado — config.yaml é a fonte da verdade)")
            except Exception:
                pass

    # ── Version 13 → 14: migrate legacy flat stt.model to provider section ──
    # Old configs (and cli-config.yaml.example) had a flat `stt.model` key
    # that was provider-agnostic.  When the provider was "local" this caused
    # OpenAI model names (e.g. "whisper-1") to be fed to faster-whisper,
    # crashing with "Invalid model size".  Move the value into the correct
    # provider-specific section and remove the flat key.
    if current_ver < 14:
        # Read raw config (no defaults merged) to check what the user actually
        # wrote, then apply changes to the merged config for saving.
        raw = read_raw_config()
        raw_stt = raw.get("stt", {})
        if isinstance(raw_stt, dict) and "model" in raw_stt:
            legacy_model = raw_stt["model"]
            provider = raw_stt.get("provider", "local")
            config = load_config()
            stt = config.get("stt", {})
            # Remove the legacy flat key
            stt.pop("model", None)
            # Place it in the appropriate provider section only if the
            # user didn't already set a model there
            if provider in ("local", "local_command"):
                # Don't migrate an OpenAI model name into the local section
                _local_models = {
                    "tiny.en", "tiny", "base.en", "base", "small.en", "small",
                    "medium.en", "medium", "large-v1", "large-v2", "large-v3",
                    "large", "distil-large-v2", "distil-medium.en",
                    "distil-small.en", "distil-large-v3", "distil-large-v3.5",
                    "large-v3-turbo", "turbo",
                }
                if legacy_model in _local_models:
                    # Check raw config — only set if user didn't already
                    # have a nested local.model
                    raw_local = raw_stt.get("local", {})
                    if not isinstance(raw_local, dict) or "model" not in raw_local:
                        local_cfg = stt.setdefault("local", {})
                        local_cfg["model"] = legacy_model
                # else: drop it — it was an OpenAI model name, local section
                # already defaults to "base" via DEFAULT_CONFIG
            else:
                # Cloud provider — put it in that provider's section only
                # if user didn't already set a nested model
                raw_provider = raw_stt.get(provider, {})
                if not isinstance(raw_provider, dict) or "model" not in raw_provider:
                    provider_cfg = stt.setdefault(provider, {})
                    provider_cfg["model"] = legacy_model
            config["stt"] = stt
            save_config(config)
            if not quiet:
                print(f"  ✔ stt.model legado migrado para configuração específica do provedor")

    # ── Version 14 → 15: add explicit gateway interim-message gate ──
    if current_ver < 15:
        config = read_raw_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        if "interim_assistant_messages" not in display:
            display["interim_assistant_messages"] = True
            config["display"] = display
            results["config_added"].append("display.interim_assistant_messages=true (default)")
            save_config(config)
            if not quiet:
                print("  ✔ Adicionado display.interim_assistant_messages=true")

    # ── Version 15 → 16: migrate tool_progress_overrides into display.platforms ──
    if current_ver < 16:
        config = read_raw_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        old_overrides = display.get("tool_progress_overrides")
        if isinstance(old_overrides, dict) and old_overrides:
            platforms = display.get("platforms", {})
            if not isinstance(platforms, dict):
                platforms = {}
            for plat, mode in old_overrides.items():
                if plat not in platforms:
                    platforms[plat] = {}
                if "tool_progress" not in platforms[plat]:
                    platforms[plat]["tool_progress"] = mode
            display["platforms"] = platforms
            config["display"] = display
            save_config(config)
            if not quiet:
                migrated = ", ".join(f"{p}={m}" for p, m in old_overrides.items())
                print(f"  ✔ Migrado tool_progress_overrides → display.platforms: {migrated}")
            results["config_added"].append("display.platforms (migrated from tool_progress_overrides)")

    # ── Version 16 → 17: remove legacy compression.summary_* keys ──
    if current_ver < 17:
        config = read_raw_config()
        comp = config.get("compression", {})
        if isinstance(comp, dict):
            s_model = comp.pop("summary_model", None)
            s_provider = comp.pop("summary_provider", None)
            s_base_url = comp.pop("summary_base_url", None)
            migrated_keys = []
            # Migrate non-empty, non-default values to auxiliary.compression
            if s_model and str(s_model).strip():
                aux = config.setdefault("auxiliary", {})
                aux_comp = aux.setdefault("compression", {})
                if not aux_comp.get("model"):
                    aux_comp["model"] = str(s_model).strip()
                    migrated_keys.append(f"model={s_model}")
            if s_provider and str(s_provider).strip() not in ("", "auto"):
                aux = config.setdefault("auxiliary", {})
                aux_comp = aux.setdefault("compression", {})
                if not aux_comp.get("provider") or aux_comp.get("provider") == "auto":
                    aux_comp["provider"] = str(s_provider).strip()
                    migrated_keys.append(f"provider={s_provider}")
            if s_base_url and str(s_base_url).strip():
                aux = config.setdefault("auxiliary", {})
                aux_comp = aux.setdefault("compression", {})
                if not aux_comp.get("base_url"):
                    aux_comp["base_url"] = str(s_base_url).strip()
                    migrated_keys.append(f"base_url={s_base_url}")
            if migrated_keys or s_model is not None or s_provider is not None or s_base_url is not None:
                config["compression"] = comp
                save_config(config)
                if not quiet:
                    if migrated_keys:
                        print(f"  ✔ Migrado compression.summary_* → auxiliary.compression: {', '.join(migrated_keys)}")
                    else:
                        print("  ✔ Removidas chaves compression.summary_* não usadas")

    # ── Version 20 → 21: plugins are now opt-in; grandfather existing user plugins ──
    # The loader now requires plugins to appear in ``plugins.enabled`` before
    # loading. Existing installs had all discovered plugins loading by default
    # (minus anything in ``plugins.disabled``). To avoid silently breaking
    # those setups on upgrade, populate ``plugins.enabled`` with the set of
    # currently-installed user plugins that aren't already disabled.
    #
    # Bundled plugins (shipped in the repo itself) are NOT grandfathered —
    # they ship off for everyone, including existing users, so any user who
    # wants one has to opt in explicitly.
    if current_ver < 21:
        config = read_raw_config()
        plugins_cfg = config.get("plugins")
        if not isinstance(plugins_cfg, dict):
            plugins_cfg = {}
        # Only migrate if the enabled allow-list hasn't been set yet.
        if "enabled" not in plugins_cfg:
            disabled = plugins_cfg.get("disabled", []) or []
            if not isinstance(disabled, list):
                disabled = []
            disabled_set = set(disabled)

            # Scan ``$ECTOR_HOME/plugins/`` for currently installed user plugins.
            grandfathered: List[str] = []
            try:
                user_plugins_dir = get_ector_home() / "plugins"
                if user_plugins_dir.is_dir():
                    for child in sorted(user_plugins_dir.iterdir()):
                        if not child.is_dir():
                            continue
                        manifest_file = child / "plugin.yaml"
                        if not manifest_file.exists():
                            manifest_file = child / "plugin.yml"
                        if not manifest_file.exists():
                            continue
                        try:
                            with open(manifest_file) as _mf:
                                manifest = yaml.safe_load(_mf) or {}
                        except Exception:
                            manifest = {}
                        name = manifest.get("name") or child.name
                        if name in disabled_set:
                            continue
                        grandfathered.append(name)
            except Exception:
                grandfathered = []

            plugins_cfg["enabled"] = grandfathered
            config["plugins"] = plugins_cfg
            save_config(config)
            results["config_added"].append(
                f"plugins.enabled (lista de permissão opt-in, {len(grandfathered)} migrados)"
            )
            if not quiet:
                if grandfathered:
                    print(
                        f"  ✔ Plugins now opt-in: grandfathered "
                        f"{len(grandfathered)} existing plugin(s) into plugins.enabled"
                    )
                else:
                    print(
                        "  ✔ Plugins now opt-in: no existing plugins to grandfather. "
                        "Use `ector plugins enable <name>` to activate."
                    )

    # ── Version 23 → 24: drop embedding models from chat auxiliary tasks ──
    if current_ver < 24:
        config = read_raw_config()
        aux = config.get("auxiliary")
        cleared: list[str] = []
        if isinstance(aux, dict):
            chat_tasks = (
                "compression",
                "vision",
                "web_extract",
                "session_search",
                "skills_hub",
                "approval",
                "mcp",
                "title_generation",
            )
            for task_name in chat_tasks:
                entry = aux.get(task_name)
                if not isinstance(entry, dict):
                    continue
                model = str(entry.get("model", "") or "").strip()
                if model and "embedding" in model.lower():
                    entry["model"] = ""
                    cleared.append(f"auxiliary.{task_name}.model")
            if cleared:
                save_config(config)
                results["config_added"].extend(cleared)
                if not quiet:
                    print(
                        "  ✔ Modelos de embedding removidos de tarefas auxiliares de chat: "
                        + ", ".join(cleared)
                    )

    # ── Version 22 → 23: clear legacy use_gateway (managed tool gateway removed) ──
    if current_ver < 23:
        from utils import is_truthy_value

        config = load_config()
        gateway_sections = ("web", "image_gen", "tts", "browser")
        cleared: list[str] = []
        for section_name in gateway_sections:
            section = config.get(section_name)
            if not isinstance(section, dict):
                continue
            if is_truthy_value(section.get("use_gateway"), default=False):
                section["use_gateway"] = False
                cleared.append(f"{section_name}.use_gateway")
        if cleared:
            save_config(config)
            results["config_added"].extend(cleared)
            if not quiet:
                print(
                    "  ✔ Gateway gerenciado removido: desativado "
                    + ", ".join(cleared)
                    + " — configure chaves BYOK (ector tools)."
                )

    # ── Version 25 → 26: personality config cleanup ──
    # - root-level ``personalities`` → ``agent.personalities``
    # - remove legacy ``display.personality`` sentinels (e.g. kawaii)
    if current_ver < 26:
        config = read_raw_config()
        changed = False

        root_personalities = config.pop("personalities", None)
        if isinstance(root_personalities, dict) and root_personalities:
            agent = config.get("agent")
            if not isinstance(agent, dict):
                agent = {}
                config["agent"] = agent
            existing = agent.get("personalities")
            if not isinstance(existing, dict) or not existing:
                agent["personalities"] = dict(root_personalities)
                changed = True
                results["config_added"].append(
                    "agent.personalities (migrated from root personalities)"
                )

        display = config.get("display")
        if isinstance(display, dict):
            overlay = str(display.get("personality") or "").strip().lower()
            if overlay and is_legacy_display_personality(overlay):
                display.pop("personality", None)
                changed = True
                results["config_added"].append(
                    "display.personality (removed legacy sentinel)"
                )

        if changed:
            save_config(config)
            if not quiet:
                print("  ✔ Personalidade: chaves legadas migradas ou removidas")

    if current_ver < latest_ver and not quiet:
        print(f"Versão da config: {current_ver} → {latest_ver}")
    
    # Check for missing required env vars
    missing_env = get_missing_env_vars(required_only=True)
    
    if missing_env and not quiet:
        print("\n▲  Variáveis de ambiente obrigatórias ausentes:")
        for var in missing_env:
            print(f"   • {var['name']}: {var['description']}")
    
    if interactive and missing_env:
        print("\nVamos configurá-las agora:\n")
        for var in missing_env:
            if var.get("url"):
                print(f"  Obtenha sua chave em: {var['url']}")
            
            if var.get("password"):
                import getpass
                value = getpass.getpass(f"  {var['prompt']}: ")
            else:
                value = input(f"  {var['prompt']}: ").strip()
            
            if value:
                save_env_value(var["name"], value)
                results["env_added"].append(var["name"])
                print(f"  ✔ Salvo {var['name']}")
            else:
                results["warnings"].append(f"Pulado {var['name']} - algumas funcionalidades podem não funcionar")
            print()
    
    # Check for missing optional env vars and offer to configure interactively
    # Skip "advanced" vars (like OPENAI_BASE_URL) -- those are for power users
    missing_optional = get_missing_env_vars(required_only=False)
    required_names = {v["name"] for v in missing_env} if missing_env else set()
    missing_optional = [
        v for v in missing_optional
        if v["name"] not in required_names and not v.get("advanced")
    ]
    
    # Only offer to configure env vars that are NEW since the user's previous version
    new_var_names = set()
    for ver in range(current_ver + 1, latest_ver + 1):
        new_var_names.update(ENV_VARS_BY_VERSION.get(ver, []))

    if new_var_names and interactive and not quiet:
        new_and_unset = [
            (name, OPTIONAL_ENV_VARS[name])
            for name in sorted(new_var_names)
            if not get_env_value(name) and name in OPTIONAL_ENV_VARS
        ]
        if new_and_unset:
            print(f"\n  {len(new_and_unset)} nova(s) chave(s) opcional(is) nesta atualização:")
            for name, info in new_and_unset:
                print(f"    • {name} — {info.get('description', '')}")
            print()
            try:
                answer = input("  Configurar novas chaves? (s/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"

            if answer in ("s", "sim", "y", "yes"):
                print()
                for name, info in new_and_unset:
                    if info.get("url"):
                        print(f"  {info.get('description', name)}")
                        print(f"  Obtenha sua chave em: {info['url']}")
                    else:
                        print(f"  {info.get('description', name)}")
                    if info.get("password"):
                        import getpass
                        value = getpass.getpass(f"  {info.get('prompt', name)} (Enter para pular): ")
                    else:
                        value = input(f"  {info.get('prompt', name)} (Enter para pular): ").strip()
                    if value:
                        save_env_value(name, value)
                        results["env_added"].append(name)
                        print(f"  ✔ Saved {name}")
                    print()
            else:
                print("  Configure mais tarde com: ector config edit")
    
    # Check for missing config fields
    missing_config = get_missing_config_fields()
    
    if missing_config:
        config = load_config()
        
        for field in missing_config:
            key = field["key"]
            default = field["default"]
            
            _set_nested(config, key, default)
            results["config_added"].append(key)
            if not quiet:
                print(f"  ✔ Added {key} = {default}")
        
        # Update version and save
        config["_config_version"] = latest_ver
        save_config(config)
    elif current_ver < latest_ver:
        # Just update version
        config = load_config()
        config["_config_version"] = latest_ver
        save_config(config)

    # ── Skill-declared config vars ──────────────────────────────────────
    # Skills can declare config.yaml settings they need via
    # metadata.ector.config in their SKILL.md frontmatter.
    # Prompt for any that are missing/empty.
    missing_skill_config = get_missing_skill_config_vars()
    if missing_skill_config and interactive and not quiet:
        print(f"\n  {len(missing_skill_config)} configuração(ões) de skill não configurada(s):")
        for var in missing_skill_config:
            skill_name = var.get("skill", "desconhecida")
            print(f"    • {var['key']} — {var['description']} (da skill: {skill_name})")
        print()
        try:
            answer = input("  Configurar as definições da skill? (s/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in ("s", "sim", "y", "yes"):
            print()
            config = load_config()
            try:
                from agent.skill_utils import SKILL_CONFIG_PREFIX
            except Exception:
                SKILL_CONFIG_PREFIX = "skills.config"
            for var in missing_skill_config:
                default = var.get("default", "")
                default_hint = f" (default: {default})" if default else ""
                value = input(f"  {var['prompt']}{default_hint}: ").strip()
                if not value and default:
                    value = str(default)
                if value:
                    storage_key = f"{SKILL_CONFIG_PREFIX}.{var['key']}"
                    _set_nested(config, storage_key, value)
                    results["config_added"].append(var["key"])
                    print(f"  ✔ Salvo {var['key']} = {value}")
                else:
                    results["warnings"].append(
                        f"Pulado {var['key']} — a skill '{var.get('skill', '?')}' pode perguntar por isso mais tarde"
                    )
                print()
            save_config(config)
        else:
            print("  Configure mais tarde com: ector config edit")

    return results


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, preserving nested defaults.

    Keys in *override* take precedence. If both values are dicts the merge
    recurses, so a user who overrides only ``tts.elevenlabs.voice_id`` will
    keep the default ``tts.elevenlabs.model_id`` intact.
    """
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand_env_vars(obj):
    """Recursively expand ``${VAR}`` references in config values.

    Only string values are processed; dict keys, numbers, booleans, and
    None are left untouched.  Unresolved references (variable not in
    ``os.environ``) are kept verbatim so callers can detect them.
    """
    if isinstance(obj, str):
        return re.sub(
            r"\${([^}]+)}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def _items_by_unique_name(items):
    """Return a name-indexed dict only when all items have unique string names."""
    if not isinstance(items, list):
        return None
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return None
        name = item["name"]
        if name in indexed:
            return None
        indexed[name] = item
    return indexed


def _preserve_env_ref_templates(current, raw, loaded_expanded=None):
    """Restore raw ``${VAR}`` templates when a value is otherwise unchanged.

    ``load_config()`` expands env refs for runtime use. When a caller later
    persists that config after modifying some unrelated setting, keep the
    original on-disk template instead of writing the expanded plaintext
    secret back to ``config.yaml``.

    Prefer preserving the raw template when ``current`` still matches either
    the value previously returned by ``load_config()`` for this config path or
    the current environment expansion of ``raw``. This handles env-var
    rotation between load and save while still treating mixed literal/template
    string edits as caller-owned once their rendered value diverges.
    """
    if isinstance(current, str) and isinstance(raw, str) and re.search(r"\${[^}]+}", raw):
        if current == raw:
            return raw
        if isinstance(loaded_expanded, str) and current == loaded_expanded:
            return raw
        if _expand_env_vars(raw) == current:
            return raw
        return current

    if isinstance(current, dict) and isinstance(raw, dict):
        return {
            key: _preserve_env_ref_templates(
                value,
                raw.get(key),
                loaded_expanded.get(key) if isinstance(loaded_expanded, dict) else None,
            )
            for key, value in current.items()
        }

    if isinstance(current, list) and isinstance(raw, list):
        # Prefer matching named config objects (e.g. custom_providers) by name
        # so harmless reordering doesn't drop the original template. If names
        # are duplicated, fall back to positional matching instead of silently
        # shadowing one entry.
        current_by_name = _items_by_unique_name(current)
        raw_by_name = _items_by_unique_name(raw)
        loaded_by_name = _items_by_unique_name(loaded_expanded)
        if current_by_name is not None and raw_by_name is not None:
            return [
                _preserve_env_ref_templates(
                    item,
                    raw_by_name.get(item.get("name")),
                    loaded_by_name.get(item.get("name")) if loaded_by_name is not None else None,
                )
                for item in current
            ]
        return [
            _preserve_env_ref_templates(
                item,
                raw[index] if index < len(raw) else None,
                loaded_expanded[index]
                if isinstance(loaded_expanded, list) and index < len(loaded_expanded)
                else None,
            )
            for index, item in enumerate(current)
        ]

    return current


def _normalize_root_model_keys(config: Dict[str, Any]) -> Dict[str, Any]:
    """Move stale root-level provider/base_url into model section.

    Some users (or older code) placed ``provider:`` and ``base_url:`` at the
    config root instead of inside ``model:``.  These root-level keys are only
    used as a fallback when the corresponding ``model.*`` key is empty — they
    never override an existing ``model.provider`` or ``model.base_url``.
    After migration the root-level keys are removed so they can't cause
    confusion on subsequent loads.
    """
    # Only act if there are root-level keys to migrate
    has_root = any(config.get(k) for k in ("provider", "base_url"))
    if not has_root:
        return config

    config = dict(config)
    model = config.get("model")
    if not isinstance(model, dict):
        model = {"default": model} if model else {}
        config["model"] = model

    for key in ("provider", "base_url"):
        root_val = config.get(key)
        if root_val and not model.get(key):
            model[key] = root_val
        config.pop(key, None)

    return config


def _normalize_max_turns_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy root-level max_turns into agent.max_turns."""
    config = dict(config)
    agent_config = dict(config.get("agent") or {})

    if "max_turns" in config and "max_turns" not in agent_config:
        agent_config["max_turns"] = config["max_turns"]

    if "max_turns" not in agent_config:
        agent_config["max_turns"] = DEFAULT_CONFIG["agent"]["max_turns"]

    config["agent"] = agent_config
    config.pop("max_turns", None)
    return config


def _normalize_personality_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Hoist legacy root ``personalities`` and strip orphaned display overlays."""
    config = dict(config)
    root_personalities = config.pop("personalities", None)
    agent = dict(config.get("agent") or {})

    if isinstance(root_personalities, dict) and root_personalities:
        existing = agent.get("personalities")
        if not isinstance(existing, dict) or not existing:
            agent["personalities"] = dict(root_personalities)
        else:
            merged = dict(root_personalities)
            merged.update(existing)
            agent["personalities"] = merged

    display = config.get("display")
    if isinstance(display, dict):
        display = dict(display)
        overlay = str(display.get("personality") or "").strip().lower()
        if overlay and is_legacy_display_personality(overlay):
            display.pop("personality", None)
        config["display"] = display

    config["agent"] = agent
    return config



def read_raw_config() -> Dict[str, Any]:
    """Read ~/.ector/config.yaml as-is, without merging defaults or migrating.

    Returns the raw YAML dict, or ``{}`` if the file doesn't exist or can't
    be parsed.  Use this for lightweight config reads where you just need a
    single value and don't want the overhead of ``load_config()``'s deep-merge
    + migration pipeline.
    """
    try:
        config_path = get_config_path()
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def load_config() -> Dict[str, Any]:
    """Load configuration from ~/.ector/config.yaml."""
    ensure_ector_home()
    config_path = get_config_path()
    
    config = copy.deepcopy(DEFAULT_CONFIG)
    
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}

            if "max_turns" in user_config:
                agent_user_config = dict(user_config.get("agent") or {})
                if agent_user_config.get("max_turns") is None:
                    agent_user_config["max_turns"] = user_config["max_turns"]
                user_config["agent"] = agent_user_config
                user_config.pop("max_turns", None)

            config = _deep_merge(config, user_config)
        except Exception as e:
            print(f"Aviso: Falha ao carregar a configuração: {e}")

    normalized = _normalize_root_model_keys(
        _normalize_personality_config(_normalize_max_turns_config(config))
    )
    expanded = _expand_env_vars(normalized)
    _LAST_EXPANDED_CONFIG_BY_PATH[str(config_path)] = copy.deepcopy(expanded)
    return expanded


_SECURITY_COMMENT = """
# ── Security ──────────────────────────────────────────────────────────
# API keys, tokens, and passwords are redacted from tool output by default.
# Set to false to see full values (useful for debugging auth issues).
# tirith pre-exec scanning is enabled by default when the tirith binary
# is available. Configure via security.tirith_* keys or env vars
# (TIRITH_ENABLED, TIRITH_BIN, TIRITH_TIMEOUT, TIRITH_FAIL_OPEN).
#
# security:
#   redact_secrets: false
#   tirith_enabled: true
#   tirith_path: "tirith"
#   tirith_timeout: 5
#   tirith_fail_open: true
"""

_FALLBACK_COMMENT = """
# ── Fallback Model ────────────────────────────────────────────────────
# Automatic provider failover when primary is unavailable.
# Uncomment and configure to enable. Triggers on rate limits (429),
# overload (529), service errors (503), or connection failures.
#
# Supported providers:
#   openrouter   (OPENROUTER_API_KEY)  — routes to any model
#   openai-codex (OAuth — ector auth) — OpenAI Codex
#   ector         (OAuth — ector auth) — ector.cc catalog
#   zai          (ZAI_API_KEY)         — Z.AI / GLM
#   kimi-coding  (KIMI_API_KEY)        — Kimi / Moonshot
#   kimi-coding-cn (KIMI_CN_API_KEY)   — Kimi / Moonshot (China)
#   minimax      (MINIMAX_API_KEY)     — MiniMax
#   minimax-cn   (MINIMAX_CN_API_KEY)  — MiniMax (China)
#
# For custom OpenAI-compatible endpoints, add base_url and key_env.
#
# fallback_model:
#   provider: openrouter
#   model: anthropic/claude-sonnet-4
"""


_COMMENTED_SECTIONS = """
# ── Security ──────────────────────────────────────────────────────────
# API keys, tokens, and passwords are redacted from tool output by default.
# Set to false to see full values (useful for debugging auth issues).
#
# security:
#   redact_secrets: false

# ── Fallback Model ────────────────────────────────────────────────────
# Automatic provider failover when primary is unavailable.
# Uncomment and configure to enable. Triggers on rate limits (429),
# overload (529), service errors (503), or connection failures.
#
# Supported providers:
#   openrouter   (OPENROUTER_API_KEY)  — routes to any model
#   openai-codex (OAuth — ector auth) — OpenAI Codex
#   ector         (OAuth — ector auth) — ector.cc catalog
#   zai          (ZAI_API_KEY)         — Z.AI / GLM
#   kimi-coding  (KIMI_API_KEY)        — Kimi / Moonshot
#   kimi-coding-cn (KIMI_CN_API_KEY)   — Kimi / Moonshot (China)
#   minimax      (MINIMAX_API_KEY)     — MiniMax
#   minimax-cn   (MINIMAX_CN_API_KEY)  — MiniMax (China)
#
# For custom OpenAI-compatible endpoints, add base_url and key_env.
#
# fallback_model:
#   provider: openrouter
#   model: anthropic/claude-sonnet-4
"""


def save_config(config: Dict[str, Any]):
    """Save configuration to ~/.ector/config.yaml."""
    if is_managed():
        managed_error("save configuration")
        return
    from utils import atomic_yaml_write

    ensure_ector_home()
    config_path = get_config_path()
    current_normalized = _normalize_root_model_keys(_normalize_max_turns_config(config))
    normalized = current_normalized
    raw_existing = _normalize_root_model_keys(_normalize_max_turns_config(read_raw_config()))
    if raw_existing:
        normalized = _preserve_env_ref_templates(
            normalized,
            raw_existing,
            _LAST_EXPANDED_CONFIG_BY_PATH.get(str(config_path)),
        )

    # Build optional commented-out sections for features that are off by
    # default or only relevant when explicitly configured.
    parts = []
    sec = normalized.get("security", {})
    if not sec or sec.get("redact_secrets") is None:
        parts.append(_SECURITY_COMMENT)
    fb = normalized.get("fallback_model", {})
    if not fb or not isinstance(fb, dict) or not (fb.get("provider") and fb.get("model")):
        parts.append(_FALLBACK_COMMENT)

    atomic_yaml_write(
        config_path,
        normalized,
        extra_content="".join(parts) if parts else None,
    )
    _secure_file(config_path)
    _LAST_EXPANDED_CONFIG_BY_PATH[str(config_path)] = copy.deepcopy(current_normalized)


def save_config_value(key_path: str, value: Any) -> bool:
    """
    Save a value to the active config file at the specified key path.

    Args:
        key_path: Dot-separated path like "agent.system_prompt"
        value: Value to save

    Returns:
        True if successful, False otherwise
    """
    try:
        # Load existing config
        config = load_config()

        # Navigate to the key and set value
        keys = key_path.split(".")
        current = config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

        # Save back
        save_config(config)
        return True
    except Exception as e:
        logger.error("Failed to save config value %s: %s", key_path, e)
        return False


def load_env() -> Dict[str, str]:
    """Load environment variables from ~/.ector/.env.

    Sanitizes lines before parsing so that corrupted files (e.g.
    concatenated KEY=VALUE pairs on a single line) are handled
    gracefully instead of producing mangled values such as duplicated
    bot tokens.  See #8908.
    """
    env_path = get_env_path()
    env_vars = {}
    
    if env_path.exists():
        # On Windows, open() defaults to the system locale (cp1252) which can
        # fail on UTF-8 .env files. Use explicit UTF-8 only on Windows.
        open_kw = {"encoding": "utf-8", "errors": "replace"} if _IS_WINDOWS else {}
        with open(env_path, **open_kw) as f:
            raw_lines = f.readlines()
        # Sanitize before parsing: split concatenated lines & drop stale
        # placeholders so corrupted .env files don't produce invalid tokens.
        lines = _sanitize_env_lines(raw_lines)
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                env_vars[key.strip()] = value.strip().strip('"\'')
    
    return env_vars


def _sanitize_env_lines(lines: list) -> list:
    """Fix corrupted .env lines before reading or writing.

    Handles two known corruption patterns:
    1. Concatenated KEY=VALUE pairs on a single line (missing newline between
       entries, e.g. ``ANTHROPIC_API_KEY=sk-...OPENAI_BASE_URL=https://...``).
    2. Stale ``KEY=***`` placeholder entries left by incomplete setup runs.

    Uses a known-keys set (OPTIONAL_ENV_VARS + _EXTRA_ENV_KEYS) so we only
    split on real Ector env var names, avoiding false positives from values
    that happen to contain uppercase text with ``=``.
    """
    # Build the known keys set lazily from OPTIONAL_ENV_VARS + extras.
    # Done inside the function so OPTIONAL_ENV_VARS is guaranteed to be defined.
    known_keys = set(OPTIONAL_ENV_VARS.keys()) | _EXTRA_ENV_KEYS

    sanitized: list[str] = []
    for line in lines:
        raw = line.rstrip("\r\n")
        stripped = raw.strip()

        # Preserve blank lines and comments
        if not stripped or stripped.startswith("#"):
            sanitized.append(raw + "\n")
            continue

        # Detect concatenated KEY=VALUE pairs on one line.
        # Search for known KEY= patterns at any position in the line.
        split_positions = []
        for key_name in known_keys:
            needle = key_name + "="
            idx = stripped.find(needle)
            while idx >= 0:
                split_positions.append(idx)
                idx = stripped.find(needle, idx + len(needle))

        if len(split_positions) > 1:
            split_positions.sort()
            # Deduplicate (shouldn't happen, but be safe)
            split_positions = sorted(set(split_positions))
            for i, pos in enumerate(split_positions):
                end = split_positions[i + 1] if i + 1 < len(split_positions) else len(stripped)
                part = stripped[pos:end].strip()
                if part:
                    sanitized.append(part + "\n")
        else:
            sanitized.append(stripped + "\n")

    return sanitized


def sanitize_env_file() -> int:
    """Read, sanitize, and rewrite ~/.ector/.env in place.

    Returns the number of lines that were fixed (concatenation splits +
    placeholder removals).  Returns 0 when no changes are needed.
    """
    env_path = get_env_path()
    if not env_path.exists():
        return 0

    read_kw = {"encoding": "utf-8", "errors": "replace"} if _IS_WINDOWS else {}
    write_kw = {"encoding": "utf-8"} if _IS_WINDOWS else {}

    with open(env_path, **read_kw) as f:
        original_lines = f.readlines()

    sanitized = _sanitize_env_lines(original_lines)

    if sanitized == original_lines:
        return 0

    # Count fixes: difference in line count (from splits) + removed lines
    fixes = abs(len(sanitized) - len(original_lines))
    if fixes == 0:
        # Lines changed content (e.g. *** removal) even if count is same
        fixes = sum(1 for a, b in zip(original_lines, sanitized) if a != b)
        fixes += abs(len(sanitized) - len(original_lines))

    fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix=".tmp", prefix=".env_")
    try:
        with os.fdopen(fd, "w", **write_kw) as f:
            f.writelines(sanitized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, env_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _secure_file(env_path)
    return fixes


def _check_non_ascii_credential(key: str, value: str) -> str:
    """Warn and strip non-ASCII characters from credential values.

    API keys and tokens must be pure ASCII — they are sent as HTTP header
    values which httpx/httpcore encode as ASCII.  Non-ASCII characters
    (commonly introduced by copy-pasting from rich-text editors or PDFs
    that substitute lookalike Unicode glyphs for ASCII letters) cause
    ``UnicodeEncodeError: 'ascii' codec can't encode character`` at
    request time.

    Returns the sanitized (ASCII-only) value.  Prints a warning if any
    non-ASCII characters were found and removed.
    """
    try:
        value.encode("ascii")
        return value  # all ASCII — nothing to do
    except UnicodeEncodeError:
        pass

    # Build a readable list of the offending characters
    bad_chars: list[str] = []
    for i, ch in enumerate(value):
        if ord(ch) > 127:
            bad_chars.append(f"  position {i}: {ch!r} (U+{ord(ch):04X})")
    sanitized = value.encode("ascii", errors="ignore").decode("ascii")

    print(
        f"\n  Warning: {key} contains non-ASCII characters that will break API requests.\n"
        f"  This usually happens when copy-pasting from a PDF, rich-text editor,\n"
        f"  or web page that substitutes lookalike Unicode glyphs for ASCII letters.\n"
        f"\n"
        + "\n".join(f"  {line}" for line in bad_chars[:5])
        + ("\n  ... and more" if len(bad_chars) > 5 else "")
        + f"\n\n  The non-ASCII characters have been stripped automatically.\n"
        f"  If authentication fails, re-copy the key from the provider's dashboard.\n",
        file=sys.stderr,
    )
    return sanitized


def save_env_value(key: str, value: str):
    """Save or update a value in ~/.ector/.env."""
    if is_managed():
        managed_error(f"set {key}")
        return
    if not _ENV_VAR_NAME_RE.match(key):
        raise ValueError(f"Invalid environment variable name: {key!r}")
    value = value.replace("\n", "").replace("\r", "")
    # API keys / tokens must be ASCII — strip non-ASCII with a warning.
    value = _check_non_ascii_credential(key, value)
    ensure_ector_home()
    env_path = get_env_path()
    
    # On Windows, open() defaults to the system locale (cp1252) which can
    # cause OSError errno 22 on UTF-8 .env files.
    read_kw = {"encoding": "utf-8", "errors": "replace"} if _IS_WINDOWS else {}
    write_kw = {"encoding": "utf-8"} if _IS_WINDOWS else {}

    lines = []
    if env_path.exists():
        with open(env_path, **read_kw) as f:
            lines = f.readlines()
        # Sanitize on every read: split concatenated keys, drop stale placeholders
        lines = _sanitize_env_lines(lines)
    
    # Find and update or append
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    
    if not found:
        # Ensure there's a newline at the end of the file before appending
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    
    fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix='.tmp', prefix='.env_')
    # Preserve original permissions so Docker volume mounts aren't clobbered.
    original_mode = None
    if env_path.exists():
        try:
            original_mode = stat.S_IMODE(env_path.stat().st_mode)
        except OSError:
            pass
    try:
        with os.fdopen(fd, 'w', **write_kw) as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, env_path)
        # Restore original permissions before _secure_file may tighten them.
        if original_mode is not None:
            try:
                os.chmod(env_path, original_mode)
            except OSError:
                pass
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _secure_file(env_path)

    os.environ[key] = value


def remove_env_value(key: str) -> bool:
    """Remove a key from ~/.ector/.env and os.environ.

    Returns True if the key was found and removed, False otherwise.
    """
    if is_managed():
        managed_error(f"remove {key}")
        return False
    if not _ENV_VAR_NAME_RE.match(key):
        raise ValueError(f"Invalid environment variable name: {key!r}")
    env_path = get_env_path()
    if not env_path.exists():
        os.environ.pop(key, None)
        return False

    read_kw = {"encoding": "utf-8", "errors": "replace"} if _IS_WINDOWS else {}
    write_kw = {"encoding": "utf-8"} if _IS_WINDOWS else {}

    with open(env_path, **read_kw) as f:
        lines = f.readlines()
    lines = _sanitize_env_lines(lines)

    new_lines = [line for line in lines if not line.strip().startswith(f"{key}=")]
    found = len(new_lines) < len(lines)

    if found:
        fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix='.tmp', prefix='.env_')
        # Preserve original permissions so Docker volume mounts aren't clobbered.
        original_mode = None
        try:
            original_mode = stat.S_IMODE(env_path.stat().st_mode)
        except OSError:
            pass
        try:
            with os.fdopen(fd, 'w', **write_kw) as f:
                f.writelines(new_lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, env_path)
            if original_mode is not None:
                try:
                    os.chmod(env_path, original_mode)
                except OSError:
                    pass
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _secure_file(env_path)

    os.environ.pop(key, None)
    return found


def save_anthropic_oauth_token(value: str, save_fn=None):
    """Persist an Anthropic OAuth/setup token and clear the API-key slot."""
    writer = save_fn or save_env_value
    writer("ANTHROPIC_TOKEN", value)
    writer("ANTHROPIC_API_KEY", "")


def use_anthropic_claude_code_credentials(save_fn=None):
    """Use Claude Code's own credential files instead of persisting env tokens."""
    writer = save_fn or save_env_value
    writer("ANTHROPIC_TOKEN", "")
    writer("ANTHROPIC_API_KEY", "")


def save_anthropic_api_key(value: str, save_fn=None):
    """Persist an Anthropic API key and clear the OAuth/setup-token slot."""
    writer = save_fn or save_env_value
    writer("ANTHROPIC_API_KEY", value)
    writer("ANTHROPIC_TOKEN", "")


def save_env_value_secure(key: str, value: str) -> Dict[str, Any]:
    save_env_value(key, value)
    return {
        "success": True,
        "stored_as": key,
        "validated": False,
    }



def reload_env() -> int:
    """Re-read ~/.ector/.env into os.environ. Returns count of vars updated.

    Adds/updates vars that changed and removes vars that were deleted from
    the .env file (but only vars known to Ector — OPTIONAL_ENV_VARS and
    _EXTRA_ENV_KEYS — to avoid clobbering unrelated environment).
    """
    env_vars = load_env()
    known_keys = set(OPTIONAL_ENV_VARS.keys()) | _EXTRA_ENV_KEYS
    count = 0
    for key, value in env_vars.items():
        if os.environ.get(key) != value:
            os.environ[key] = value
            count += 1
    # Remove known Ector vars that are no longer in .env
    for key in known_keys:
        if key not in env_vars and key in os.environ:
            del os.environ[key]
            count += 1
    return count


def get_env_value(key: str) -> Optional[str]:
    """Get a value from ~/.ector/.env or environment."""
    # Check environment first
    if key in os.environ:
        return os.environ[key]
    
    # Then check .env file
    env_vars = load_env()
    return env_vars.get(key)


# =============================================================================
# Config display
# =============================================================================

def redact_key(key: str) -> str:
    """Redact an API key for display."""
    if not key:
        return color("(não definido)", Colors.DIM)
    if len(key) < 12:
        return "***"
    return key[:4] + "..." + key[-4:]


_SHOW_CONFIG_LABEL_WIDTH = 18


def _print_config_rows(rows: list[tuple[str, str]]) -> None:
    for label, value in rows:
        print(f"  {label:<{_SHOW_CONFIG_LABEL_WIDTH}} {value}")


def _format_personality_summary(config: Dict[str, Any]) -> str:
    """Human-readable personality line for ``show_config()``."""
    display = config.get("display") if isinstance(config.get("display"), dict) else {}
    user = config.get("user") if isinstance(config.get("user"), dict) else {}
    overlay = resolve_display_personality_overlay(display)
    profile = str((user or {}).get("personality") or "").strip()
    if overlay:
        return overlay
    if profile:
        return profile
    return "(nenhuma)"


def model_config_display_lines(config: Dict[str, Any]) -> list[tuple[str, str]]:
    """Key/value rows for the Model section in ``show_config()``."""
    model_cfg = config.get("model")
    lines: list[tuple[str, str]] = []

    if isinstance(model_cfg, dict):
        model_name = str(model_cfg.get("default") or model_cfg.get("name") or "").strip()
        lines.append(
            (
                "Modelo",
                model_name or color("(não definido)", Colors.DIM),
            )
        )
        provider = str(model_cfg.get("provider") or "").strip()
        if provider:
            from ector_cli.models import provider_label

            lines.append(("Provedor", provider_label(provider)))
        base_url = str(model_cfg.get("base_url") or "").strip()
        if base_url:
            lines.append(("URL base", base_url))
        api_mode = str(model_cfg.get("api_mode") or "").strip()
        if api_mode:
            lines.append(("Modo API", api_mode))
    elif isinstance(model_cfg, str):
        model_name = model_cfg.strip()
        lines.append(
            (
                "Modelo",
                model_name or color("(não definido)", Colors.DIM),
            )
        )
        try:
            from ector_cli.models import provider_label, resolve_display_provider_id

            effective = resolve_display_provider_id(config)
            if effective:
                lines.append(("Provedor", provider_label(effective)))
        except Exception:
            pass
    else:
        lines.append(("Modelo", color("(não definido)", Colors.DIM)))

    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    max_turns = agent.get("max_turns", DEFAULT_CONFIG["agent"]["max_turns"])
    lines.append(("Máx. turnos", str(max_turns)))
    return lines


def show_config():
    """Display current configuration."""
    config = load_config()
    
    print()
    
    # Paths
    print()
    print(color("◆ Caminhos", Colors.CYAN, Colors.BOLD))
    _print_config_rows([
        ("Configuração", f"{display_ector_home()}/config.yaml"),
        ("Segredos", f"{display_ector_home()}/.env"),
    ])
    
    # API Keys
    print()
    print(color("◆ Chaves de API", Colors.CYAN, Colors.BOLD))
    
    keys = [
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("VOICE_TOOLS_OPENAI_KEY", "OpenAI (STT/TTS)"),
        ("EXA_API_KEY", "Exa"),
        ("PARALLEL_API_KEY", "Parallel"),
        ("FIRECRAWL_API_KEY", "Firecrawl"),
        ("TAVILY_API_KEY", "Tavily"),
        ("BROWSERBASE_API_KEY", "Browserbase"),
        ("BROWSER_USE_API_KEY", "Browser Use"),
        ("FAL_KEY", "FAL"),
    ]
    
    for env_key, name in keys:
        value = get_env_value(env_key)
        print(f"  {name:<{_SHOW_CONFIG_LABEL_WIDTH}} {redact_key(value)}")
    from ector_cli.auth import get_anthropic_key
    anthropic_value = get_anthropic_key()
    print(f"  {'Anthropic':<{_SHOW_CONFIG_LABEL_WIDTH}} {redact_key(anthropic_value)}")
    
    # Model settings
    print()
    print(color("◆ Modelo", Colors.CYAN, Colors.BOLD))
    _print_config_rows(model_config_display_lines(config))
    
    # Display
    print()
    print(color("◆ Exibição", Colors.CYAN, Colors.BOLD))
    display = config.get('display', {})
    _print_config_rows([
        ("Personalidade", _format_personality_summary(config)),
        (
            "Raciocínio",
            "ligado" if display.get("show_reasoning", False) else "desligado",
        ),
        (
            "Notificação sonora",
            "ligado" if display.get("bell_on_complete", False) else "desligado",
        ),
    ])
    ump = display.get('user_message_preview', {}) if isinstance(display.get('user_message_preview', {}), dict) else {}
    ump_first = ump.get('first_lines', 2)
    ump_last = ump.get('last_lines', 2)
    print(
        f"  Prévia de mensagens: primeiras {ump_first} linha(s), "
        f"últimas {ump_last} linha(s)"
    )

    # Terminal
    print()
    print(color("◆ Terminal", Colors.CYAN, Colors.BOLD))
    terminal = config.get('terminal', {})
    terminal_rows: list[tuple[str, str]] = [
        ("Backend", str(terminal.get("backend", "local"))),
        ("Diretório", str(terminal.get("cwd", "."))),
        ("Tempo limite", f"{terminal.get('timeout', 60)}s"),
    ]
    
    if terminal.get('backend') == 'docker':
        terminal_rows.append(
            (
                "Imagem Docker",
                str(
                    terminal.get(
                        "docker_image",
                        "nikolaik/python-nodejs:python3.11-nodejs20",
                    )
                ),
            )
        )
    elif terminal.get('backend') == 'singularity':
        terminal_rows.append(
            (
                "Imagem",
                str(
                    terminal.get(
                        "singularity_image",
                        "docker://nikolaik/python-nodejs:python3.11-nodejs20",
                    )
                ),
            )
        )
    elif terminal.get('backend') == 'modal':
        terminal_rows.extend([
            (
                "Imagem Modal",
                str(
                    terminal.get(
                        "modal_image",
                        "nikolaik/python-nodejs:python3.11-nodejs20",
                    )
                ),
            ),
            (
                "Token Modal",
                "configurado" if get_env_value("MODAL_TOKEN_ID") else "(não definido)",
            ),
        ])
    elif terminal.get('backend') == 'daytona':
        terminal_rows.extend([
            (
                "Imagem Daytona",
                str(
                    terminal.get(
                        "daytona_image",
                        "nikolaik/python-nodejs:python3.11-nodejs20",
                    )
                ),
            ),
            (
                "Chave API",
                "configurada" if get_env_value("DAYTONA_API_KEY") else "(não definida)",
            ),
        ])
    elif terminal.get('backend') == 'ssh':
        ssh_host = get_env_value('TERMINAL_SSH_HOST')
        ssh_user = get_env_value('TERMINAL_SSH_USER')
        terminal_rows.extend([
            ("Host SSH", ssh_host or "(não definido)"),
            ("Usuário SSH", ssh_user or "(não definido)"),
        ])
    _print_config_rows(terminal_rows)
    
    # Timezone
    print()
    print(color("◆ Fuso horário", Colors.CYAN, Colors.BOLD))
    tz = config.get('timezone', '')
    if tz:
        _print_config_rows([("Fuso horário", tz)])
    else:
        _print_config_rows([("Fuso horário", color("(local do servidor)", Colors.DIM))])

    # Compression
    print()
    print(color("◆ Compressão de contexto", Colors.CYAN, Colors.BOLD))
    compression = config.get('compression', {})
    enabled = compression.get('enabled', True)
    compression_rows: list[tuple[str, str]] = [
        ("Habilitado", "sim" if enabled else "não"),
    ]
    if enabled:
        threshold_pct = compression.get("threshold", 0.50) * 100
        compression_rows.extend([
            (
                "Limite",
                f"{threshold_pct:.0f}% do contexto preservado",
            ),
            (
                "Proteger",
                f"{compression.get('protect_last_n', 20)} mensagens finais",
            ),
        ])
        _aux_comp = config.get('auxiliary', {}).get('compression', {})
        _sm = _aux_comp.get('model', '') or '(automático)'
        compression_rows.append(("Modelo", str(_sm)))
        comp_provider = _aux_comp.get('provider', 'auto')
        if comp_provider and comp_provider != 'auto':
            from ector_cli.models import provider_label

            compression_rows.append(("Provedor", provider_label(str(comp_provider))))
    _print_config_rows(compression_rows)
    
    # Auxiliary models
    auxiliary = config.get('auxiliary', {})
    aux_tasks = {
        "Visão": auxiliary.get('vision', {}),
        "Extração web": auxiliary.get('web_extract', {}),
    }
    has_overrides = any(
        t.get('provider', 'auto') != 'auto' or t.get('model', '')
        for t in aux_tasks.values()
    )
    if has_overrides:
        print()
        print(color("◆ Modelos auxiliares (sobrescritas)", Colors.CYAN, Colors.BOLD))
        for label, task_cfg in aux_tasks.items():
            prov = task_cfg.get('provider', 'auto')
            mdl = task_cfg.get('model', '')
            if prov != 'auto' or mdl:
                parts = [f"provedor={prov}"]
                if mdl:
                    parts.append(f"modelo={mdl}")
                print(f"  {label:<{_SHOW_CONFIG_LABEL_WIDTH}} {', '.join(parts)}")
    
    # Messaging
    print()
    print(color("◆ Canais", Colors.CYAN, Colors.BOLD))
    
    telegram_token = get_env_value('TELEGRAM_BOT_TOKEN')
    discord_token = get_env_value('DISCORD_BOT_TOKEN')
    
    _print_config_rows([
        (
            "Telegram",
            "configurado" if telegram_token else color("não configurado", Colors.DIM),
        ),
        (
            "Discord",
            "configurado" if discord_token else color("não configurado", Colors.DIM),
        ),
    ])
    
    # Skill config
    try:
        from agent.skill_utils import discover_all_skill_config_vars, resolve_skill_config_values
        skill_vars = discover_all_skill_config_vars()
        if skill_vars:
            resolved = resolve_skill_config_values(skill_vars)
            print()
            print(color("◆ Configurações de Habilidades", Colors.CYAN, Colors.BOLD))
            for var in skill_vars:
                key = var["key"]
                value = resolved.get(key, "")
                skill_name = var.get("skill", "")
                display_val = str(value) if value else color("(não definido)", Colors.DIM)
                print(f"  {key:<20s} {display_val}  {color(f'[{skill_name}]', Colors.DIM)}")
    except Exception:
        pass

    print()
    print(color("─" * 60, Colors.DIM))
    print(color("  ector config edit     # Editar arquivo de configuração", Colors.DIM))
    print(color("  ector setup           # Executar assistente de configuração", Colors.DIM))
    print()


def edit_config():
    """Open config file in user's editor."""
    if is_managed():
        managed_error("edit configuration")
        return
    config_path = get_config_path()
    
    # Ensure config exists
    if not config_path.exists():
        save_config(DEFAULT_CONFIG)
        print(f"Criado {config_path}")
    
    # Find editor
    editor = os.getenv('EDITOR') or os.getenv('VISUAL')
    
    if not editor:
        # Try common editors
        for cmd in ['nano', 'vim', 'vi', 'code', 'notepad']:
            import shutil
            if shutil.which(cmd):
                editor = cmd
                break
    
    if not editor:
        print("Nenhum editor encontrado. O arquivo de configuração está em:")
        print(f"  {config_path}")
        return
    
    print(f"Abrindo {config_path} em {editor}...")
    subprocess.run([editor, str(config_path)])


# =============================================================================
# Config status presentation
# =============================================================================

_CONFIG_STATUS_CATEGORIES = (
    ("provider", "Provedor"),
    ("tool", "Ferramentas"),
    ("skill", "Skills"),
    ("messaging", "Mensagens"),
    ("setting", "Configurações"),
)


def print_config_status() -> None:
    """Render ``ector config status`` with Rich panels and tables."""
    from collections import defaultdict

    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ector_cli.provider_check import has_any_provider_configured
    from ector_constants import display_ector_home

    console = Console()
    current_ver, latest_ver = check_config_version()
    missing_config = get_missing_config_fields()
    dhh = display_ector_home()

    overview = Table.grid(padding=(0, 2))
    overview.add_column(style="dim", justify="right", no_wrap=True)
    overview.add_column()

    overview.add_row("Config", f"{dhh}/config.yaml")
    overview.add_row(".env", f"{dhh}/.env")

    if current_ver >= latest_ver:
        ver_cell = f"v{current_ver} [green]✔[/green]"
    else:
        ver_cell = (
            f"v{current_ver} → v{latest_ver} "
            "[#00D1FF](atualização disponível)[/#00D1FF]"
        )
    overview.add_row("Versão", ver_cell)

    if has_any_provider_configured():
        overview.add_row("Inferência", "[green]configurado[/green]")
    else:
        overview.add_row(
            "Inferência",
            "[red]não configurado[/red] [dim]→ ector provider[/dim]",
        )

    configured_count = sum(
        1 for name in OPTIONAL_ENV_VARS if get_env_value(name)
    )
    overview.add_row(
        "Variáveis .env",
        f"{configured_count}/{len(OPTIONAL_ENV_VARS)} configuradas",
    )

    if missing_config:
        overview.add_row(
            "Schema",
            f"[yellow]{len(missing_config)} nova(s) opção(ões)[/yellow]",
        )

    console.print()
    console.print(
        Panel(
            overview,
            title="[bold #00D1FF]Status da configuração[/bold #00D1FF]",
            border_style="#00D1FF",
            padding=(1, 2),
        ),
    )

    if REQUIRED_ENV_VARS:
        req_table = Table(
            title="[bold]Obrigatório[/bold]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            expand=True,
            padding=(0, 1),
            title_justify="left",
        )
        req_table.add_column("Variável", no_wrap=True, ratio=2)
        req_table.add_column("Estado", no_wrap=True, min_width=14)
        for var_name in REQUIRED_ENV_VARS:
            if get_env_value(var_name):
                req_table.add_row(var_name, "[green]✔ configurado[/green]")
            else:
                req_table.add_row(var_name, "[red]✖ ausente[/red]")
        console.print()
        console.print(req_table)

    by_category: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for var_name, info in OPTIONAL_ENV_VARS.items():
        by_category[info.get("category", "setting")].append((var_name, info))

    omitted_advanced = 0
    for cat_key, cat_label in _CONFIG_STATUS_CATEGORIES:
        items = sorted(by_category.get(cat_key, []), key=lambda row: row[0])
        visible_items: list[tuple[str, dict]] = []
        for var_name, info in items:
            if info.get("advanced") and not get_env_value(var_name):
                omitted_advanced += 1
                continue
            visible_items.append((var_name, info))
        if not visible_items:
            continue

        table = Table(
            title=f"[bold]{cat_label}[/bold]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            expand=True,
            padding=(0, 1),
            title_justify="left",
        )
        table.add_column("Variável", no_wrap=True, ratio=2)
        table.add_column("Estado", no_wrap=True, min_width=14)
        table.add_column("Notas", overflow="fold", ratio=3, style="dim")

        for var_name, info in visible_items:
            if get_env_value(var_name):
                status = "[green]✔ configurado[/green]"
            else:
                status = "[dim]○ ausente[/dim]"

            notes = (info.get("description") or "").strip()
            tools = info.get("tools", [])
            if tools and not get_env_value(var_name):
                tools_hint = ", ".join(tools[:3])
                notes = f"{notes} → {tools_hint}" if notes else f"→ {tools_hint}"
            table.add_row(var_name, status, notes or "—")

        console.print()
        console.print(table)

    if omitted_advanced:
        console.print()
        console.print(
            f"[dim]{omitted_advanced} variável(is) avançada(s) ausente(s) omitida(s). "
            "Use ector config show para ver tudo.[/dim]"
        )

    if missing_config:
        console.print()
        console.print(
            f"[yellow]▲[/yellow]  {len(missing_config)} nova(s) opção(ões) em config.yaml "
            "[dim]→ ector config migrate[/dim]"
        )

    console.print()
    console.print(
        "[dim]Editar: ector config edit  ·  "
        "Assistente: ector setup  ·  "
        "Atualizar schema: ector config migrate[/dim]"
    )
    console.print()


# =============================================================================
# Command handler
# =============================================================================

def config_command(args):
    """Handle config subcommands."""
    subcmd = getattr(args, 'config_command', None)
    
    if subcmd is None or subcmd == "show":
        show_config()
    
    elif subcmd == "edit":
        edit_config()
    
    elif subcmd == "path":
        print(get_config_path())
    
    elif subcmd == "env-path":
        print(get_env_path())
    
    elif subcmd == "migrate":
        print()
        print(color("🔄 Verificando atualizações na configuração...", Colors.CYAN, Colors.BOLD))
        print()
        
        # Check what's missing
        missing_env = get_missing_env_vars(required_only=False)
        missing_config = get_missing_config_fields()
        current_ver, latest_ver = check_config_version()
        
        if not missing_env and not missing_config and current_ver >= latest_ver:
            print(color("✔ A configuração está atualizada!", Colors.GREEN))
            print()
            return
        
        # Show what needs to be updated
        if current_ver < latest_ver:
            print(f"  Config version: {current_ver} → {latest_ver}")
        
        if missing_config:
            print(f"\n  {len(missing_config)} new config option(s) will be added with defaults")
        
        required_missing = [v for v in missing_env if v.get("is_required")]
        optional_missing = [
            v for v in missing_env
            if not v.get("is_required") and not v.get("advanced")
        ]
        
        if required_missing:
            print(f"\n  ▲  {len(required_missing)} required API key(s) missing:")
            for var in required_missing:
                print(f"     • {var['name']}")
        
        if optional_missing:
            print(f"\n  ℹ️  {len(optional_missing)} optional API key(s) not configured:")
            for var in optional_missing:
                tools = var.get("tools", [])
                tools_str = f" (enables: {', '.join(tools[:2])})" if tools else ""
                print(f"     • {var['name']}{tools_str}")
        
        print()
        
        # Run migration
        results = migrate_config(interactive=True, quiet=False)
        
        print()
        if results["env_added"] or results["config_added"]:
            print(color("✔ Configuração atualizada!", Colors.GREEN))
        
        if results["warnings"]:
            print()
            for warning in results["warnings"]:
                print(color(f"  ▲  {warning}", Colors.YELLOW))
        
        print()
    
    elif subcmd == "status":
        print_config_status()
    
    else:
        print(f"Comando de configuração desconhecido: {subcmd}")
        print()
        print("Comandos disponíveis:")
        print("  ector config           Mostra a configuração atual")
        print("  ector config edit      Abre a configuração no editor")
        print("  ector config status    Mostra status da configuração")
        print("  ector config migrate   Atualiza a configuração com novas opções")
        print("  ector config path      Mostra o caminho do arquivo de configuração")
        print("  ector config env-path  Mostra o caminho do arquivo .env")
        sys.exit(1)
