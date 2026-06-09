"""Credential-pool auth subcommands."""

from __future__ import annotations

from getpass import getpass
import math
import sys
import time
from types import SimpleNamespace
import uuid

from agent.credential_pool import (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_OAUTH,
    CUSTOM_POOL_PREFIX,
    SOURCE_MANUAL,
    STATUS_EXHAUSTED,
    STRATEGY_FILL_FIRST,
    STRATEGY_ROUND_ROBIN,
    STRATEGY_RANDOM,
    STRATEGY_LEAST_USED,
    PooledCredential,
    _exhausted_until,
    _normalize_custom_pool_name,
    get_pool_strategy,
    label_from_token,
    list_custom_pool_providers,
    load_pool,
)
import ector_cli.auth as auth_mod
from ector_cli.auth import PROVIDER_REGISTRY
from ector_cli.colors import Colors, color, should_use_color
from ector_constants import OPENROUTER_BASE_URL


_AUTH_ACCENT = "#00D1FF"
_AUTH_TYPE_LABELS = {
    AUTH_TYPE_API_KEY: "chave API",
    AUTH_TYPE_OAUTH: "OAuth",
}
_STRATEGY_LABELS = {
    STRATEGY_FILL_FIRST: "fill-first",
    STRATEGY_ROUND_ROBIN: "round-robin",
    STRATEGY_LEAST_USED: "least-used",
    STRATEGY_RANDOM: "random",
}


def _rich_console():
    from rich.console import Console

    return Console(highlight=False)


def _auth_type_label(auth_type: str) -> str:
    return _AUTH_TYPE_LABELS.get(auth_type, auth_type)


def _strategy_label(strategy: str) -> str:
    return _STRATEGY_LABELS.get(strategy, strategy)


def _iter_configured_providers(provider_filter: str = "") -> list[str]:
    if provider_filter:
        return [provider_filter]
    return sorted({
        *PROVIDER_REGISTRY.keys(),
        "openrouter",
        *list_custom_pool_providers(),
    })


def _gather_pool_snapshot(provider_filter: str = "") -> list[dict]:
    """Collect credential rows grouped by provider for display."""
    snapshot: list[dict] = []
    for provider in _iter_configured_providers(provider_filter):
        pool = load_pool(provider)
        entries = pool.entries()
        if not entries:
            continue
        current = pool.peek()
        snapshot.append({
            "provider": provider,
            "strategy": get_pool_strategy(provider),
            "entries": [
                {
                    "index": idx,
                    "entry": entry,
                    "active": current is not None and entry.id == current.id,
                    "status": _format_exhausted_status(entry).strip(),
                    "source": _display_source(entry.source),
                }
                for idx, entry in enumerate(entries, start=1)
            ],
        })
    return snapshot


def _print_pool_status_plain(provider_filter: str = "") -> bool:
    """Plain-text pool listing (for pipes and non-TTY). Returns True if any rows."""
    shown = False
    for group in _gather_pool_snapshot(provider_filter):
        shown = True
        provider = group["provider"]
        entries = group["entries"]
        strategy = _strategy_label(group["strategy"])
        print(f"{provider} ({len(entries)} credenciais · {strategy}):")
        for row in entries:
            entry = row["entry"]
            status = row["status"] or ""
            active_tag = " ✔ Ativa" if row["active"] else ""
            print(
                f"  #{row['index']}  {entry.label:<20} "
                f"{_auth_type_label(entry.auth_type):<9} "
                f"{row['source']}{status}{active_tag}".rstrip()
            )
        print()
    return shown


def _print_pool_status_rich(console, provider_filter: str = "") -> bool:
    """Rich pool table. Returns True if any credentials were shown."""
    from rich import box
    from rich.table import Table

    snapshot = _gather_pool_snapshot(provider_filter)
    if not snapshot:
        console.print()
        console.print(f"[bold {_AUTH_ACCENT}]Pool de credenciais[/bold {_AUTH_ACCENT}]")
        console.print("[dim]Nenhuma credencial no pool.[/dim]")
        console.print("[dim]Adicione com[/dim] [bold]ector auth add <provedor>[/bold]")
        return False

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Provedor", no_wrap=True, style="bold", ratio=1, max_width=18)
    table.add_column("#", justify="right", no_wrap=True, min_width=2)
    table.add_column("Rótulo", overflow="fold", ratio=2)
    table.add_column("Tipo", no_wrap=True, min_width=9)
    table.add_column("Origem", overflow="fold", ratio=2)
    table.add_column("Estado", overflow="fold", ratio=2, min_width=10)

    total = sum(len(group["entries"]) for group in snapshot)
    for group in snapshot:
        provider = group["provider"]
        first_in_group = True
        for row in group["entries"]:
            entry = row["entry"]
            if row["active"]:
                state = "[green]✔ Ativa[/green]"
            elif row["status"]:
                state = f"[yellow]{row['status'].strip()}[/yellow]"
            else:
                state = "[dim]ok[/dim]"
            table.add_row(
                provider if first_in_group else "",
                str(row["index"]),
                entry.label,
                _auth_type_label(entry.auth_type),
                row["source"],
                state,
            )
            first_in_group = False

    console.print()
    console.print(
        f"[bold {_AUTH_ACCENT}]Pool de credenciais[/bold {_AUTH_ACCENT}] "
        f"[dim]({total} no total)[/dim]"
    )
    console.print(table)
    return True


def _print_bedrock_status_plain() -> None:
    try:
        from agent.bedrock_adapter import (
            has_aws_credentials,
            resolve_aws_auth_env_var,
            resolve_bedrock_region,
        )
    except ImportError:
        return

    if not has_aws_credentials():
        return

    auth_source = resolve_aws_auth_env_var() or "desconhecido"
    region = resolve_bedrock_region()
    print("bedrock (cadeia de credenciais AWS SDK):")
    print(f"  Auth: {auth_source}")
    print(f"  Região: {region}")
    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        arn = identity.get("Arn", "desconhecido")
        print(f"  Identidade: {arn}")
    except Exception:
        print("  Identidade: (não foi possível resolver — falha na chamada boto3 STS)")
    print()


def _print_bedrock_status_rich(console) -> None:
    try:
        from agent.bedrock_adapter import (
            has_aws_credentials,
            resolve_aws_auth_env_var,
            resolve_bedrock_region,
        )
    except ImportError:
        return

    if not has_aws_credentials():
        return

    from rich.panel import Panel
    from rich.table import Table

    auth_source = resolve_aws_auth_env_var() or "desconhecido"
    region = resolve_bedrock_region()
    identity = None
    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity().get("Arn")
    except Exception:
        identity = None

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right", no_wrap=True)
    grid.add_column(overflow="fold")
    grid.add_row("Auth", auth_source)
    grid.add_row("Região", region)
    if identity:
        grid.add_row("Identidade", identity)
    else:
        grid.add_row("Identidade", "[dim](STS indisponível)[/dim]")

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold {_AUTH_ACCENT}]AWS Bedrock[/bold {_AUTH_ACCENT}]",
            subtitle="[dim]via cadeia de credenciais do AWS SDK (fora do pool)[/dim]",
            border_style=_AUTH_ACCENT,
            padding=(0, 1),
        )
    )


def _print_auth_menu_rich(console) -> None:
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    choices = [
        ("1", "Adicionar uma credencial", "ector auth add <provedor>"),
        ("2", "Remover uma credencial", "por índice, id ou rótulo"),
        ("3", "Resetar cooldowns", "limpa estado esgotado de um provedor"),
        ("4", "Estratégia de rotação", "fill-first, round-robin, …"),
        ("5", "Sair", ""),
    ]

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("", no_wrap=True, style="bold", width=3)
    table.add_column("Ação", ratio=2)
    table.add_column("Notas", style="dim", overflow="fold", ratio=3)
    for num, label, hint in choices:
        table.add_row(num, label, hint)

    console.print()
    console.print(
        Panel(
            table,
            title=f"[bold {_AUTH_ACCENT}]O que deseja fazer?[/bold {_AUTH_ACCENT}]",
            border_style=_AUTH_ACCENT,
            padding=(0, 1),
        )
    )
    console.print()


def _print_auth_menu_plain() -> None:
    choices = [
        "Adicionar uma credencial",
        "Remover uma credencial",
        "Resetar cooldowns para um provedor",
        "Definir estratégia de rotação para um provedor",
        "Sair",
    ]
    print("O que você gostaria de fazer?")
    for i, choice in enumerate(choices, 1):
        print(f"  {i}. {choice}")
    print()


# Providers that support OAuth login in addition to API keys.
_OAUTH_CAPABLE_PROVIDERS = {"anthropic", "openai-codex", "qwen-oauth", "google-gemini-cli"}


def _provider_display_label(provider_key: str) -> str:
    """Human-readable label for a provider picker row."""
    if provider_key == "openrouter":
        return "OpenRouter  (openrouter) · chave API"
    if provider_key.startswith(CUSTOM_POOL_PREFIX):
        for display_name, pool_key, _pk in _get_custom_provider_names():
            if pool_key == provider_key:
                return f"{display_name}  ({provider_key}) · personalizado"
        return f"{provider_key} · personalizado"

    pconfig = PROVIDER_REGISTRY.get(provider_key)
    if not pconfig:
        return provider_key

    tags: list[str] = []
    if provider_key in _OAUTH_CAPABLE_PROVIDERS:
        tags.append("OAuth")
    if pconfig.auth_type == "api_key":
        tags.append("chave API")
    elif pconfig.auth_type == "oauth_external":
        if "OAuth" not in tags:
            tags.append("OAuth")
    elif pconfig.auth_type == "external_process":
        tags.append("externo")

    tag_text = f" · {', '.join(tags)}" if tags else ""
    return f"{pconfig.name}  ({provider_key}){tag_text}"


def _build_provider_choices(*, only_with_credentials: bool = False) -> list[tuple[str, str]]:
    """Return sorted (provider_key, display_label) pairs for pickers."""
    keys: set[str] = set(PROVIDER_REGISTRY.keys())
    keys.add("openrouter")
    for _name, pool_key, _provider_key in _get_custom_provider_names():
        keys.add(pool_key)

    choices: list[tuple[str, str]] = []
    for key in keys:
        if only_with_credentials and not load_pool(key).has_credentials():
            continue
        choices.append((key, _provider_display_label(key)))

    choices.sort(key=lambda item: item[1].lower())
    return choices


def _pick_provider(
    prompt: str = "Provedor",
    *,
    only_with_credentials: bool = False,
) -> str:
    """Interactive provider picker (searchable curses menu or numbered fallback)."""
    choices = _build_provider_choices(only_with_credentials=only_with_credentials)
    if not choices:
        if only_with_credentials:
            raise SystemExit("Nenhum provedor com credenciais configuradas.")
        raise SystemExit("Nenhum provedor disponível.")

    keys = [key for key, _label in choices]
    labels = [label for _key, label in choices]

    if sys.stdin.isatty():
        from ector_cli.curses_ui import curses_radiolist

        idx = curses_radiolist(
            prompt,
            labels,
            selected=0,
            cancel_returns=-1,
            description="↑↓ navegar · digite para filtrar · ENTER selecionar",
        )
    else:
        from ector_cli.curses_ui import _radio_numbered_fallback

        idx = _radio_numbered_fallback(prompt, labels, 0, -1)

    if idx < 0 or idx >= len(keys):
        raise SystemExit()
    return keys[idx]


def _pick_auth_type(provider: str) -> str | None:
    """Ask OAuth-capable providers which credential type to add."""
    if provider not in _OAUTH_CAPABLE_PROVIDERS:
        return AUTH_TYPE_API_KEY

    labels = [
        "Chave API — cole uma chave do painel do provedor",
        "Login OAuth — autenticar via navegador",
    ]
    if sys.stdin.isatty():
        from ector_cli.curses_ui import curses_radiolist

        idx = curses_radiolist(
            f"{provider}: tipo de credencial",
            labels,
            selected=0,
            cancel_returns=-1,
        )
    else:
        from ector_cli.curses_ui import _radio_numbered_fallback

        idx = _radio_numbered_fallback(f"{provider}: tipo de credencial", labels, 0, -1)

    if idx < 0:
        return None
    return AUTH_TYPE_OAUTH if idx == 1 else AUTH_TYPE_API_KEY


def _pick_rotation_strategy(provider: str, current: str) -> str | None:
    """Interactive rotation strategy picker."""
    strategies = [STRATEGY_FILL_FIRST, STRATEGY_ROUND_ROBIN, STRATEGY_LEAST_USED, STRATEGY_RANDOM]
    descriptions = {
        STRATEGY_FILL_FIRST: "usar primeira chave até esgotar, depois a próxima",
        STRATEGY_ROUND_ROBIN: "alternar entre as chaves uniformemente",
        STRATEGY_LEAST_USED: "sempre escolher a chave menos usada",
        STRATEGY_RANDOM: "seleção aleatória",
    }
    labels = [
        f"{s} — {descriptions[s]}{'  ← atual' if s == current else ''}"
        for s in strategies
    ]
    default_idx = strategies.index(current) if current in strategies else 0

    if sys.stdin.isatty():
        from ector_cli.curses_ui import curses_radiolist

        idx = curses_radiolist(
            f"Estratégia de rotação · {provider}",
            labels,
            selected=default_idx,
            cancel_returns=-1,
            description=f"Atual: {current}",
        )
    else:
        from ector_cli.curses_ui import _radio_numbered_fallback

        idx = _radio_numbered_fallback(
            f"Estratégia de rotação · {provider}",
            labels,
            default_idx,
            -1,
        )

    if idx < 0 or idx >= len(strategies):
        return None
    return strategies[idx]


def _print_remove_targets_rich(console, provider: str, pool) -> None:
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("#", justify="right", no_wrap=True, width=3)
    table.add_column("Rótulo", overflow="fold", ratio=2)
    table.add_column("Tipo", no_wrap=True, min_width=9)
    table.add_column("Origem", overflow="fold", ratio=2)
    table.add_column("id", no_wrap=True, style="dim")

    for i, entry in enumerate(pool.entries(), 1):
        status = _format_exhausted_status(entry).strip()
        label = entry.label
        if status:
            label = f"{label}  [dim]({status})[/dim]"
        table.add_row(
            str(i),
            label,
            _auth_type_label(entry.auth_type),
            _display_source(entry.source),
            entry.id,
        )

    console.print()
    console.print(
        Panel(
            table,
            title=f"[bold {_AUTH_ACCENT}]Remover credencial · {provider}[/bold {_AUTH_ACCENT}]",
            border_style=_AUTH_ACCENT,
            padding=(0, 1),
        )
    )


def _get_custom_provider_names() -> list:
    """Return list of (display_name, pool_key, provider_key) tuples."""
    try:
        from ector_cli.config import get_compatible_custom_providers, load_config

        config = load_config()
    except Exception:
        return []
    result = []
    for entry in get_compatible_custom_providers(config):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        pool_key = f"{CUSTOM_POOL_PREFIX}{_normalize_custom_pool_name(name)}"
        provider_key = str(entry.get("provider_key", "") or "").strip()
        result.append((name.strip(), pool_key, provider_key))
    return result


def _resolve_custom_provider_input(raw: str) -> str | None:
    """If raw input matches a custom_providers entry name (case-insensitive), return its pool key."""
    normalized = (raw or "").strip().lower().replace(" ", "-")
    if not normalized:
        return None
    # Direct match on 'custom:name' format
    if normalized.startswith(CUSTOM_POOL_PREFIX):
        return normalized
    for display_name, pool_key, provider_key in _get_custom_provider_names():
        if _normalize_custom_pool_name(display_name) == normalized:
            return pool_key
        if provider_key and provider_key.strip().lower() == normalized:
            return pool_key
    return None


def _normalize_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"or", "open-router"}:
        return "openrouter"
    # Check if it matches a custom provider name
    custom_key = _resolve_custom_provider_input(normalized)
    if custom_key:
        return custom_key
    return normalized


def _provider_base_url(provider: str) -> str:
    if provider == "openrouter":
        return OPENROUTER_BASE_URL
    if provider.startswith(CUSTOM_POOL_PREFIX):
        from agent.credential_pool import _get_custom_provider_config

        cp_config = _get_custom_provider_config(provider)
        if cp_config:
            return str(cp_config.get("base_url") or "").strip()
        return ""
    pconfig = PROVIDER_REGISTRY.get(provider)
    return pconfig.inference_base_url if pconfig else ""


def _oauth_default_label(provider: str, count: int) -> str:
    return f"{provider}-oauth-{count}"


def _api_key_default_label(count: int) -> str:
    return f"api-key-{count}"


def _display_source(source: str) -> str:
    return source.split(":", 1)[1] if source.startswith("manual:") else source


def _classify_exhausted_status(entry) -> tuple[str, bool]:
    code = getattr(entry, "last_error_code", None)
    reason = str(getattr(entry, "last_error_reason", "") or "").strip().lower()
    message = str(getattr(entry, "last_error_message", "") or "").strip().lower()

    if code == 429 or any(token in reason for token in ("rate_limit", "usage_limit", "quota", "exhausted")) or any(
        token in message for token in ("rate limit", "usage limit", "quota", "too many requests")
    ):
        return "limite de taxa atingido", True

    if code in {401, 403} or any(token in reason for token in ("invalid_token", "invalid_grant", "unauthorized", "forbidden", "auth")) or any(
        token in message for token in ("unauthorized", "forbidden", "expired", "revoked", "invalid token", "authentication")
    ):
        return "autenticação falhou", False

    return "esgotado", True



def _format_exhausted_status(entry) -> str:
    if entry.last_status != STATUS_EXHAUSTED:
        return ""
    label, show_retry_window = _classify_exhausted_status(entry)
    reason = getattr(entry, "last_error_reason", None)
    reason_text = f" {reason}" if isinstance(reason, str) and reason.strip() else ""
    code = f" ({entry.last_error_code})" if entry.last_error_code else ""
    if not show_retry_window:
        return f" {label}{reason_text}{code} (re-autenticação pode ser necessária)"
    exhausted_until = _exhausted_until(entry)
    if exhausted_until is None:
        return f" {label}{reason_text}{code}"
    remaining = max(0, int(math.ceil(exhausted_until - time.time())))
    if remaining <= 0:
        return f" {label}{reason_text}{code} (pronto para tentar novamente)"
    minutes, seconds = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        wait = f"{days}d {hours}h"
    elif hours:
        wait = f"{hours}h {minutes}m"
    elif minutes:
        wait = f"{minutes}m {seconds}s"
    else:
        wait = f"{seconds}s"
    return f" {label}{reason_text}{code} (faltam {wait})"


def auth_add_command(args) -> None:
    provider = _normalize_provider(getattr(args, "provider", ""))
    if provider not in PROVIDER_REGISTRY and provider != "openrouter" and not provider.startswith(CUSTOM_POOL_PREFIX):
        raise SystemExit(f"Provedor desconhecido: {provider}")

    requested_type = str(getattr(args, "auth_type", "") or "").strip().lower()
    if requested_type in {AUTH_TYPE_API_KEY, "api-key"}:
        requested_type = AUTH_TYPE_API_KEY
    if not requested_type:
        if provider.startswith(CUSTOM_POOL_PREFIX):
            requested_type = AUTH_TYPE_API_KEY
        else:
            requested_type = AUTH_TYPE_OAUTH if provider in {"anthropic", "openai-codex", "qwen-oauth", "google-gemini-cli"} else AUTH_TYPE_API_KEY

    pool = load_pool(provider)

    # Clear ALL suppressions for this provider — re-adding a credential is
    # a strong signal the user wants auth re-enabled.  This covers env:*
    # (shell-exported vars), gh_cli (copilot), claude_code, qwen-cli,
    # device_code (codex), etc.  One consistent re-engagement pattern.
    # Matches the Codex device_code re-link pattern that predates this.
    if not provider.startswith(CUSTOM_POOL_PREFIX):
        try:
            from ector_cli.auth import (
                _load_auth_store,
                unsuppress_credential_source,
            )
            suppressed = _load_auth_store().get("suppressed_sources", {})
            for src in list(suppressed.get(provider, []) or []):
                unsuppress_credential_source(provider, src)
        except Exception:
            pass

    if requested_type == AUTH_TYPE_API_KEY:
        token = (getattr(args, "api_key", None) or "").strip()
        if not token:
            token = getpass("Cole sua chave API: ").strip()
        if not token:
            raise SystemExit("Nenhuma chave API fornecida.")
        default_label = _api_key_default_label(len(pool.entries()) + 1)
        label = (getattr(args, "label", None) or "").strip()
        if not label:
            if sys.stdin.isatty():
                label = input(f"Rótulo (opcional, padrão: {default_label}): ").strip() or default_label
            else:
                label = default_label
        entry = PooledCredential(
            provider=provider,
            id=uuid.uuid4().hex[:6],
            label=label,
            auth_type=AUTH_TYPE_API_KEY,
            priority=0,
            source=SOURCE_MANUAL,
            access_token=token,
            base_url=_provider_base_url(provider),
        )
        pool.add_entry(entry)
        print(f'Credencial #{len(pool.entries())} de {provider} adicionada: "{label}"')
        return

    if provider == "anthropic":
        from agent import anthropic_adapter as anthropic_mod

        creds = anthropic_mod.run_ector_oauth_login_pure()
        if not creds:
            raise SystemExit("O login OAuth da Anthropic não retornou credenciais.")
        label = (getattr(args, "label", None) or "").strip() or label_from_token(
            creds["access_token"],
            _oauth_default_label(provider, len(pool.entries()) + 1),
        )
        entry = PooledCredential(
            provider=provider,
            id=uuid.uuid4().hex[:6],
            label=label,
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:ector_pkce",
            access_token=creds["access_token"],
            refresh_token=creds.get("refresh_token"),
            expires_at_ms=creds.get("expires_at_ms"),
            base_url=_provider_base_url(provider),
        )
        pool.add_entry(entry)
        print(f'Credencial OAuth #{len(pool.entries())} de {provider} adicionada: "{entry.label}"')
        return

    if provider == "openai-codex":
        # Clear any existing suppression marker so a re-link after `ector auth
        # remove openai-codex` works without the new tokens being skipped.
        auth_mod.unsuppress_credential_source(provider, "device_code")
        creds = auth_mod._codex_device_code_login()
        label = (getattr(args, "label", None) or "").strip() or label_from_token(
            creds["tokens"]["access_token"],
            _oauth_default_label(provider, len(pool.entries()) + 1),
        )
        entry = PooledCredential(
            provider=provider,
            id=uuid.uuid4().hex[:6],
            label=label,
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:device_code",
            access_token=creds["tokens"]["access_token"],
            refresh_token=creds["tokens"].get("refresh_token"),
            base_url=creds.get("base_url"),
            last_refresh=creds.get("last_refresh"),
        )
        pool.add_entry(entry)
        print(f'Credencial OAuth #{len(pool.entries())} de {provider} adicionada: "{entry.label}"')
        return

    if provider == "google-gemini-cli":
        from agent.google_oauth import run_gemini_oauth_login_pure

        creds = run_gemini_oauth_login_pure()
        label = (getattr(args, "label", None) or "").strip() or (
            creds.get("email") or _oauth_default_label(provider, len(pool.entries()) + 1)
        )
        entry = PooledCredential(
            provider=provider,
            id=uuid.uuid4().hex[:6],
            label=label,
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:google_pkce",
            access_token=creds["access_token"],
            refresh_token=creds.get("refresh_token"),
        )
        pool.add_entry(entry)
        print(f'Credencial OAuth #{len(pool.entries())} de {provider} adicionada: "{entry.label}"')
        return

    if provider == "qwen-oauth":
        creds = auth_mod.resolve_qwen_runtime_credentials(refresh_if_expiring=False)
        label = (getattr(args, "label", None) or "").strip() or label_from_token(
            creds["api_key"],
            _oauth_default_label(provider, len(pool.entries()) + 1),
        )
        entry = PooledCredential(
            provider=provider,
            id=uuid.uuid4().hex[:6],
            label=label,
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:qwen_cli",
            access_token=creds["api_key"],
            base_url=creds.get("base_url"),
        )
        pool.add_entry(entry)
        print(f'Credencial OAuth #{len(pool.entries())} de {provider} adicionada: "{entry.label}"')
        return

    raise SystemExit(f"`ector auth add {provider}` is not implemented for auth type {requested_type} yet.")


def auth_list_command(args) -> None:
    provider_filter = _normalize_provider(getattr(args, "provider", "") or "")
    if should_use_color():
        console = _rich_console()
        _print_pool_status_rich(console, provider_filter)
        _print_bedrock_status_rich(console)
        console.print()
        return
    _print_pool_status_plain(provider_filter)
    _print_bedrock_status_plain()


def auth_remove_command(args) -> None:
    provider = _normalize_provider(getattr(args, "provider", ""))
    target = getattr(args, "target", None)
    if target is None:
        target = getattr(args, "index", None)
    pool = load_pool(provider)
    index, matched, error = pool.resolve_target(target)
    if matched is None or index is None:
        raise SystemExit(f"{error} Provider: {provider}.")
    removed = pool.remove_index(index)
    if removed is None:
        raise SystemExit(f'Nenhuma credencial correspondente a "{target}" para o provedor {provider}.')
    print(f"Credencial #{index} de {provider} removida ({removed.label})")

    # Unified removal dispatch.  Every credential source Ector reads from
    # (env vars, external OAuth files, auth.json blocks, custom config)
    # has a RemovalStep registered in agent.credential_sources.  The step
    # handles its source-specific cleanup and we centralise suppression +
    # user-facing output here so every source behaves identically from
    # the user's perspective.
    from agent.credential_sources import find_removal_step
    from ector_cli.auth import suppress_credential_source

    step = find_removal_step(provider, removed.source)
    if step is None:
        # Unregistered source — e.g. "manual", which has nothing external
        # to clean up.  The pool entry is already gone; we're done.
        return

    result = step.remove_fn(provider, removed)
    for line in result.cleaned:
        print(line)
    if result.suppress:
        suppress_credential_source(provider, removed.source)
    for line in result.hints:
        print(line)


def auth_reset_command(args) -> None:
    provider = _normalize_provider(getattr(args, "provider", ""))
    pool = load_pool(provider)
    count = pool.reset_statuses()
    print(f"Status resetado em {count} credenciais de {provider}")


def auth_status_command(args) -> None:
    provider = _normalize_provider(getattr(args, "provider", "") or "")
    if not provider:
        raise SystemExit("O provedor é obrigatório. Exemplo: `ector auth status openai-codex`.")
    status = auth_mod.get_auth_status(provider)
    if not status.get("logged_in"):
        reason = status.get("error")
        if reason:
            print(f"{provider}: deslogado ({reason})")
        else:
            print(f"{provider}: deslogado")
        return

    print(f"{provider}: logado")
    for key in ("auth_type", "client_id", "redirect_uri", "scope", "expires_at", "api_base_url"):
        value = status.get(key)
        if value:
            print(f"  {key}: {value}")


def auth_logout_command(args) -> None:
    auth_mod.logout_command(SimpleNamespace(provider=getattr(args, "provider", None)))


def _interactive_auth() -> None:
    """Interactive credential pool management when `ector auth` is called bare."""
    use_rich = should_use_color()
    console = _rich_console() if use_rich else None

    if use_rich:
        _print_pool_status_rich(console)
        _print_bedrock_status_rich(console)
        _print_auth_menu_rich(console)
    else:
        print("Status do Pool de Credenciais")
        print("=" * 50)
        print()
        _print_pool_status_plain()
        _print_bedrock_status_plain()
        _print_auth_menu_plain()

    try:
        prompt = color("\nEscolha: ", Colors.CYAN) if use_rich else "\nEscolha: "
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    choices_count = 5
    if not raw or raw == str(choices_count):
        return

    if raw == "1":
        _interactive_add()
    elif raw == "2":
        _interactive_remove()
    elif raw == "3":
        _interactive_reset()
    elif raw == "4":
        _interactive_strategy()


def _interactive_add() -> None:
    try:
        provider = _pick_provider("Provedor para adicionar credencial")
    except SystemExit:
        return

    if provider not in PROVIDER_REGISTRY and provider != "openrouter" and not provider.startswith(CUSTOM_POOL_PREFIX):
        raise SystemExit(f"Provedor desconhecido: {provider}")

    auth_type = _pick_auth_type(provider)
    if auth_type is None:
        return

    label = None
    try:
        typed_label = input(
            color("Rótulo / nome da conta (opcional): ", Colors.CYAN)
            if should_use_color()
            else "Rótulo / nome da conta (opcional): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return
    if typed_label:
        label = typed_label

    auth_add_command(SimpleNamespace(
        provider=provider, auth_type=auth_type, label=label, api_key=None,
        portal_url=None, inference_url=None, client_id=None, scope=None,
        no_browser=False, timeout=None, insecure=False, ca_bundle=None,
    ))


def _interactive_remove() -> None:
    try:
        provider = _pick_provider(
            "Provedor para remover credencial",
            only_with_credentials=True,
        )
    except SystemExit:
        return

    pool = load_pool(provider)
    if not pool.has_credentials():
        print(f"Nenhuma credencial para {provider}.")
        return

    if should_use_color():
        _print_remove_targets_rich(_rich_console(), provider, pool)
    else:
        for i, entry in enumerate(pool.entries(), 1):
            exhausted = _format_exhausted_status(entry)
            print(
                f"  #{i}  {entry.label:25s} "
                f"{_auth_type_label(entry.auth_type):10s} "
                f"{entry.source}{exhausted} [id:{entry.id}]"
            )

    try:
        prompt = (
            color("Remover #, id ou rótulo (vazio para cancelar): ", Colors.CYAN)
            if should_use_color()
            else "Remover #, id ou rótulo (vazio para cancelar): "
        )
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not raw:
        return

    auth_remove_command(SimpleNamespace(provider=provider, target=raw))


def _interactive_reset() -> None:
    try:
        provider = _pick_provider(
            "Provedor para resetar cooldowns",
            only_with_credentials=True,
        )
    except SystemExit:
        return

    auth_reset_command(SimpleNamespace(provider=provider))


def _interactive_strategy() -> None:
    try:
        provider = _pick_provider("Provedor para definir estratégia")
    except SystemExit:
        return

    current = get_pool_strategy(provider)
    strategy = _pick_rotation_strategy(provider, current)
    if strategy is None:
        return

    from ector_cli.config import load_config, save_config
    cfg = load_config()
    pool_strategies = cfg.get("credential_pool_strategies") or {}
    if not isinstance(pool_strategies, dict):
        pool_strategies = {}
    pool_strategies[provider] = strategy
    cfg["credential_pool_strategies"] = pool_strategies
    save_config(cfg)
    print(
        color(f"Estratégia de {provider} definida para: {strategy}", Colors.GREEN)
        if should_use_color()
        else f"Estratégia de {provider} definida para: {strategy}"
    )


def auth_command(args) -> None:
    action = getattr(args, "auth_action", "")
    if action == "add":
        auth_add_command(args)
        return
    if action == "list":
        auth_list_command(args)
        return
    if action == "remove":
        auth_remove_command(args)
        return
    if action == "reset":
        auth_reset_command(args)
        return
    if action == "status":
        auth_status_command(args)
        return
    if action == "logout":
        auth_logout_command(args)
        return
    # No subcommand — launch interactive mode
    _interactive_auth()
