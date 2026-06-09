"""
Dump command for ector CLI.

Outputs a compact summary of the user's Ector setup for support and debugging.
Rich panels in the terminal; plain text with ``--plain`` for copy/paste or pipes.
"""

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ector_cli.config import get_ector_home, get_env_path, get_project_root, load_config
from ector_constants import display_ector_home

_ECTOR_ACCENT = "#00D1FF"

_API_KEYS = (
    ("OPENROUTER_API_KEY", "openrouter"),
    ("OPENAI_API_KEY", "openai"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("ANTHROPIC_TOKEN", "anthropic_token"),
    ("ECTOR_API_KEY", "ector"),
    ("GOOGLE_API_KEY", "google/gemini"),
    ("GEMINI_API_KEY", "gemini"),
    ("GLM_API_KEY", "glm/zai"),
    ("ZAI_API_KEY", "zai"),
    ("KIMI_API_KEY", "kimi"),
    ("MINIMAX_API_KEY", "minimax"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("DASHSCOPE_API_KEY", "dashscope"),
    ("HF_TOKEN", "huggingface"),
    ("NVIDIA_API_KEY", "nvidia"),
    ("AI_GATEWAY_API_KEY", "ai_gateway"),
    ("KILOCODE_API_KEY", "kilocode"),
    ("FIRECRAWL_API_KEY", "firecrawl"),
    ("TAVILY_API_KEY", "tavily"),
    ("BROWSERBASE_API_KEY", "browserbase"),
    ("FAL_KEY", "fal"),
    ("ELEVENLABS_API_KEY", "elevenlabs"),
    ("GITHUB_TOKEN", "github"),
)


@dataclass
class DumpSnapshot:
    version: str
    os_info: str
    python: str
    openai_sdk: str
    profile: str
    ector_home: str
    model: str
    provider: str
    terminal: str
    api_keys: list[tuple[str, str]]
    toolsets: str
    mcp_servers: int
    memory_provider: str
    gateway: str
    platforms: str
    cron_jobs: str
    skills: int
    overrides: dict[str, str]


def _get_git_commit(project_root: Path) -> str:
    """Return short git commit hash, or '(unknown)'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(project_root),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "(unknown)"


def _redact(value: str) -> str:
    """Redact all but first 4 and last 4 chars."""
    if not value:
        return ""
    if len(value) < 12:
        return "***"
    return value[:4] + "..." + value[-4:]


def _gateway_status() -> str:
    """Return a short gateway status string."""
    try:
        from ector_cli.gateway import get_gateway_runtime_snapshot

        snapshot = get_gateway_runtime_snapshot()
        if snapshot.running:
            mode = snapshot.manager
            if snapshot.has_process_service_mismatch:
                mode = "manual"
            return f"running ({mode}, pid {snapshot.gateway_pids[0]})"
        if snapshot.service_installed and not snapshot.service_running:
            return f"stopped ({snapshot.manager})"
        return f"stopped ({snapshot.manager})"
    except Exception:
        return "unknown" if sys.platform.startswith(("linux", "darwin")) else "N/A"


def _count_skills(ector_home: Path) -> int:
    """Count installed skills."""
    skills_dir = ector_home / "skills"
    if not skills_dir.is_dir():
        return 0
    return sum(1 for _ in skills_dir.rglob("SKILL.md"))


def _count_mcp_servers(config: dict) -> int:
    """Count configured MCP servers."""
    mcp = config.get("mcp", {})
    servers = mcp.get("servers", {})
    return len(servers)


def _cron_summary(ector_home: Path) -> str:
    """Return cron jobs summary."""
    jobs_file = ector_home / "cron" / "jobs.json"
    if not jobs_file.exists():
        return "0"
    try:
        with open(jobs_file, encoding="utf-8") as f:
            data = json.load(f)
        jobs = data.get("jobs", [])
        active = sum(1 for j in jobs if j.get("enabled", True))
        return f"{active} active / {len(jobs)} total"
    except Exception:
        return "(error reading)"


def _configured_platforms() -> list[str]:
    """Return list of configured messaging platform names."""
    checks = {
        "telegram": "TELEGRAM_BOT_TOKEN",
        "discord": "DISCORD_BOT_TOKEN",
        "slack": "SLACK_BOT_TOKEN",
        "whatsapp": "WHATSAPP_ENABLED",
    }
    return [name for name, env in checks.items() if os.getenv(env)]


def _memory_provider(config: dict) -> str:
    """Return the active memory provider name."""
    mem = config.get("memory", {})
    provider = mem.get("provider", "")
    return provider if provider else "built-in"


def _get_model_and_provider(config: dict) -> tuple[str, str]:
    """Extract model and provider from config."""
    model_cfg = config.get("model", "")
    if isinstance(model_cfg, dict):
        model = (
            model_cfg.get("default")
            or model_cfg.get("model")
            or model_cfg.get("name")
            or "(not set)"
        )
        provider = model_cfg.get("provider") or "(auto)"
    elif isinstance(model_cfg, str):
        model = model_cfg or "(not set)"
        provider = "(auto)"
    else:
        model = "(not set)"
        provider = "(auto)"
    return model, provider


def _config_overrides(config: dict) -> dict[str, str]:
    """Find non-default config values worth reporting."""
    from ector_cli.config import DEFAULT_CONFIG

    overrides = {}
    interesting_paths = [
        ("agent", "max_turns"),
        ("agent", "gateway_timeout"),
        ("agent", "tool_use_enforcement"),
        ("terminal", "backend"),
        ("terminal", "docker_image"),
        ("terminal", "persistent_shell"),
        ("browser", "allow_private_urls"),
        ("compression", "enabled"),
        ("compression", "threshold"),
        ("display", "streaming"),
        ("display", "show_reasoning"),
        ("privacy", "redact_pii"),
        ("tts", "provider"),
    ]

    for section, key in interesting_paths:
        default_section = DEFAULT_CONFIG.get(section, {})
        user_section = config.get(section, {})
        if not isinstance(default_section, dict) or not isinstance(user_section, dict):
            continue
        default_val = default_section.get(key)
        user_val = user_section.get(key)
        if user_val is not None and user_val != default_val:
            overrides[f"{section}.{key}"] = str(user_val)

    default_toolsets = DEFAULT_CONFIG.get("toolsets", [])
    user_toolsets = config.get("toolsets", [])
    if user_toolsets != default_toolsets:
        overrides["toolsets"] = str(user_toolsets)

    fallbacks = config.get("fallback_providers", [])
    if fallbacks:
        overrides["fallback_providers"] = str(fallbacks)

    return overrides


def _load_runtime_env() -> None:
    """Load ~/.ector/.env (and dev project .env) into os.environ."""
    from dotenv import load_dotenv

    env_path = get_env_path()
    if env_path.exists():
        try:
            load_dotenv(env_path, encoding="utf-8")
        except UnicodeDecodeError:
            load_dotenv(env_path, encoding="latin-1")
    load_dotenv(get_project_root() / ".env", override=False, encoding="utf-8")


def collect_dump_snapshot(*, show_keys: bool = False) -> DumpSnapshot:
    """Gather setup facts for display or plain-text export."""
    _load_runtime_env()

    project_root = get_project_root()
    ector_home = get_ector_home()

    try:
        from ector_cli import __version__, __version_code__, __version_name__
    except ImportError:
        __version__ = "(unknown)"
        __version_name__ = "(unknown)"
        __version_code__ = 0

    commit = _get_git_commit(project_root)

    try:
        config = load_config()
    except Exception:
        config = {}

    model, provider = _get_model_and_provider(config)

    try:
        from ector_cli.profiles import get_active_profile_name

        profile = get_active_profile_name() or "(default)"
    except Exception:
        profile = "(default)"

    terminal_cfg = config.get("terminal", {})
    backend = terminal_cfg.get("backend", "local")

    try:
        import openai

        openai_ver = openai.__version__
    except ImportError:
        openai_ver = "not installed"

    ver_str = f"{__version_name__ or __version__}"
    if __version_code__:
        ver_str += f" ({__version_code__})"
    ver_str += f" [{commit}]"

    api_keys: list[tuple[str, str]] = []
    for env_var, label in _API_KEYS:
        val = os.getenv(env_var, "")
        if show_keys and val:
            display = _redact(val)
        else:
            display = "set" if val else "not set"
        api_keys.append((label, display))

    toolsets = config.get("toolsets", ["ector-cli"])
    platforms = _configured_platforms()

    return DumpSnapshot(
        version=ver_str,
        os_info=f"{platform.system()} {platform.release()} {platform.machine()}",
        python=sys.version.split()[0],
        openai_sdk=openai_ver,
        profile=profile,
        ector_home=display_ector_home(),
        model=model,
        provider=provider,
        terminal=backend,
        api_keys=api_keys,
        toolsets=", ".join(toolsets) if toolsets else "(default)",
        mcp_servers=_count_mcp_servers(config),
        memory_provider=_memory_provider(config),
        gateway=_gateway_status(),
        platforms=", ".join(platforms) if platforms else "none",
        cron_jobs=_cron_summary(ector_home),
        skills=_count_skills(ector_home),
        overrides=_config_overrides(config),
    )


def build_dump_text(*, show_keys: bool = False) -> str:
    """Return plain-text dump suitable for support tickets and pipes."""
    snap = collect_dump_snapshot(show_keys=show_keys)

    lines = [
        "--- ector dump ---",
        f"version:          {snap.version}",
        f"os:               {snap.os_info}",
        f"python:           {snap.python}",
        f"openai_sdk:       {snap.openai_sdk}",
        f"profile:          {snap.profile}",
        f"ector_home:      {snap.ector_home}",
        f"model:            {snap.model}",
        f"provider:         {snap.provider}",
        f"terminal:         {snap.terminal}",
        "",
        "api_keys:",
    ]
    for label, display in snap.api_keys:
        lines.append(f"  {label:<20} {display}")

    lines.extend(
        [
            "",
            "features:",
            f"  toolsets:           {snap.toolsets}",
            f"  mcp_servers:        {snap.mcp_servers}",
            f"  memory_provider:    {snap.memory_provider}",
            f"  gateway:            {snap.gateway}",
            f"  platforms:          {snap.platforms}",
            f"  cron_jobs:          {snap.cron_jobs}",
            f"  skills:             {snap.skills}",
        ]
    )

    if snap.overrides:
        lines.extend(["", "config_overrides:"])
        for key, val in snap.overrides.items():
            lines.append(f"  {key}: {val}")

    lines.append("--- end dump ---")
    return "\n".join(lines)


def _gateway_cell(status: str) -> str:
    if status.startswith("running"):
        return f"[green]{status}[/green]"
    if status.startswith("stopped"):
        return f"[dim]{status}[/dim]"
    return status


def print_dump_rich(*, show_keys: bool = False) -> None:
    """Render dump as Rich panels in the terminal."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    snap = collect_dump_snapshot(show_keys=show_keys)
    console = Console()

    env_grid = Table.grid(padding=(0, 2))
    env_grid.add_column(style="dim", justify="right", no_wrap=True)
    env_grid.add_column()
    env_grid.add_row("Versão", snap.version)
    env_grid.add_row("SO", snap.os_info)
    env_grid.add_row("Python", snap.python)
    env_grid.add_row("OpenAI SDK", snap.openai_sdk)
    env_grid.add_row("Perfil", f"[bold green]◆ {snap.profile}[/bold green]")
    env_grid.add_row("Pasta", snap.ector_home)
    env_grid.add_row("Modelo", snap.model)
    env_grid.add_row("Provedor", snap.provider)
    env_grid.add_row("Terminal", snap.terminal)

    keys_table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
    )
    keys_table.add_column("Chave", no_wrap=True, ratio=2)
    keys_table.add_column("Estado", no_wrap=True, min_width=14)
    configured = 0
    for label, display in snap.api_keys:
        if display == "set" or (show_keys and display not in ("not set", "")):
            configured += 1
            state = (
                f"[green]✔ {display}[/green]"
                if show_keys and display not in ("set", "not set")
                else "[green]configurada[/green]"
            )
        else:
            state = "[dim]ausente[/dim]"
        keys_table.add_row(label, state)

    feat_grid = Table.grid(padding=(0, 2))
    feat_grid.add_column(style="dim", justify="right", no_wrap=True)
    feat_grid.add_column()
    feat_grid.add_row("Toolsets", snap.toolsets)
    feat_grid.add_row("MCP", str(snap.mcp_servers))
    feat_grid.add_row("Memória", snap.memory_provider)
    feat_grid.add_row("Gateway", _gateway_cell(snap.gateway))
    feat_grid.add_row("Plataformas", snap.platforms)
    feat_grid.add_row("Cron", snap.cron_jobs)
    feat_grid.add_row("Skills", str(snap.skills))

    console.print()
    console.print(
        Panel(
            env_grid,
            title=f"[bold {_ECTOR_ACCENT}]Ambiente[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(1, 2),
        ),
    )
    console.print()
    console.print(
        Panel(
            keys_table,
            title=(
                f"[bold {_ECTOR_ACCENT}]Chaves API[/bold {_ECTOR_ACCENT}] "
                f"[dim]({configured}/{len(snap.api_keys)} configuradas)[/dim]"
            ),
            border_style=_ECTOR_ACCENT,
            padding=(0, 1),
        ),
    )
    console.print()
    console.print(
        Panel(
            feat_grid,
            title=f"[bold {_ECTOR_ACCENT}]Recursos[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(1, 2),
        ),
    )

    if snap.overrides:
        override_table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            expand=True,
            padding=(0, 1),
            border_style=_ECTOR_ACCENT,
        )
        override_table.add_column("Opção", no_wrap=True, ratio=2)
        override_table.add_column("Valor", overflow="fold", ratio=3)
        for key, val in snap.overrides.items():
            override_table.add_row(key, val)
        console.print()
        console.print(
            Panel(
                override_table,
                title=f"[bold {_ECTOR_ACCENT}]Overrides de config[/bold {_ECTOR_ACCENT}]",
                border_style=_ECTOR_ACCENT,
                padding=(0, 1),
            ),
        )

    console.print()
    console.print(
        "[dim]Copiar para suporte: [bold]ector dump --plain[/bold]  ·  "
        "Prévia parcial de chaves: [bold]ector dump --show-keys[/bold][/dim]"
    )
    console.print()


def run_dump(args) -> None:
    """Output setup summary for support/debugging."""
    show_keys = bool(getattr(args, "show_keys", False))
    plain = bool(getattr(args, "plain", False))

    if plain:
        print(build_dump_text(show_keys=show_keys))
        return

    print_dump_rich(show_keys=show_keys)
