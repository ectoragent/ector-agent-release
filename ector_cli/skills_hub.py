#!/usr/bin/env python3
"""
Skills Hub CLI — Unified interface for the Ector Skills Hub.

Powers both:
  - `ector skills <subcommand>` (CLI argparse entry point)
  - `/skills <subcommand>` (slash command in the interactive chat)

All logic lives in shared do_* functions. The CLI entry point and slash command
handler are thin wrappers that parse args and delegate.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Lazy imports to avoid circular dependencies and slow startup.
# tools.skills_hub and tools.skills_guard are imported inside functions.
from ector_constants import display_ector_home

_console = Console()


# ---------------------------------------------------------------------------
# Shared do_* functions
# ---------------------------------------------------------------------------

def _resolve_short_name(name: str, sources, console: Console) -> str:
    """
    Resolve a short skill name (e.g. 'pptx') to a full identifier by searching
    all sources. If exactly one match is found, returns its identifier. If multiple
    matches exist, shows them and asks the user to use the full identifier.
    Returns empty string if nothing found or ambiguous.
    """
    from tools.skills_hub import unified_search

    c = console or _console
    c.print(f"[dim]Resolvendo '{name}'...[/]")

    results = unified_search(name, sources, source_filter="all", limit=20)

    # Filter to exact name matches (case-insensitive)
    exact = [r for r in results if r.name.lower() == name.lower()]

    if len(exact) == 1:
        c.print(f"[dim]Resolvido para: {exact[0].identifier}[/]")
        return exact[0].identifier

    if len(exact) > 1:
        c.print(f"\n[yellow]Múltiplas habilidades chamadas '{name}' encontradas:[/]")
        table = Table()
        table.add_column("Fonte", style="dim")
        table.add_column("Confiança", style="dim")
        table.add_column("Identificador", style="bold cyan")
        for r in exact:
            trust_style = {"builtin": "bright_cyan", "trusted": "green", "community": "yellow"}.get(r.trust_level, "dim")
            trust_label = "official" if r.source == "official" else r.trust_level
            table.add_row(r.source, f"[{trust_style}]{trust_label}[/]", r.identifier)
        c.print(table)
        c.print("[bold]Use o identificador completo para instalar uma específica.[/]\n")
        return ""

    # No exact match — check if there are partial matches to suggest
    if results:
        c.print(f"[yellow]Nenhuma correspondência exata para '{name}'. Você quis dizer uma destas?[/]")
        for r in results[:5]:
            c.print(f"  [cyan]{r.name}[/] — {r.identifier}")
        c.print()
        return ""

    c.print(f"[bold red]Erro:[/] Nenhuma habilidade chamada '{name}' encontrada em nenhuma fonte.\n")
    return ""


def _format_extra_metadata_lines(extra: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not extra:
        return lines

    if extra.get("repo_url"):
        lines.append(f"[bold]Repo:[/] {extra['repo_url']}")
    if extra.get("detail_url"):
        lines.append(f"[bold]Detail Page:[/] {extra['detail_url']}")
    if extra.get("index_url"):
        lines.append(f"[bold]Index:[/] {extra['index_url']}")
    if extra.get("endpoint"):
        lines.append(f"[bold]Endpoint:[/] {extra['endpoint']}")
    if extra.get("install_command"):
        lines.append(f"[bold]Comando de Instalação:[/] {extra['install_command']}")
    if extra.get("installs") is not None:
        lines.append(f"[bold]Instalações:[/] {extra['installs']}")
    if extra.get("weekly_installs"):
        lines.append(f"[bold]Instalações Semanais:[/] {extra['weekly_installs']}")

    security = extra.get("security_audits")
    if isinstance(security, dict) and security:
        ordered = ", ".join(f"{name}={status}" for name, status in sorted(security.items()))
        lines.append(f"[bold]Segurança:[/] {ordered}")

    return lines


_SOURCE_LABELS: Dict[str, str] = {
    "official": "Ector oficial",
    "ector-index": "Ector Hub",
    "github": "GitHub",
    "skills-sh": "skills.sh",
    "well-known": "Well-known",
    "clawhub": "ClawHub",
    "claude-marketplace": "Claude Marketplace",
    "lobehub": "LobeHub",
}


def _skill_source_label(source: str) -> str:
    return _SOURCE_LABELS.get(source, source)


def _skill_trust_badge(source: str, trust_level: str) -> str:
    if source in ("official", "ector-index") or trust_level == "builtin":
        return "[bright_cyan]★ oficial[/]"
    trust_style = {
        "trusted": "green",
        "community": "yellow",
    }.get(trust_level, "dim")
    trust_labels = {
        "trusted": "confiável",
        "community": "comunidade",
    }
    label = trust_labels.get(trust_level, trust_level)
    return f"[{trust_style}]{label}[/]"


def _skill_install_ref(meta) -> str:
    extra = meta.extra or {}
    hub_slug = str(extra.get("hub_slug") or "").strip()
    if hub_slug:
        return hub_slug
    if "/" not in meta.identifier:
        return meta.identifier
    return meta.name


def _print_search_header(
    c: Console,
    query: str,
    source: str,
    result_count: int,
) -> None:
    source_hint = ""
    if source != "all":
        if source == "hub":
            label = "Ector Hub"
        elif source == "builtin":
            label = "Ector oficial"
        else:
            label = _skill_source_label(source)
        source_hint = f" · {label}"
    c.print()
    c.print(f"[bold]Skills Hub[/][dim]{source_hint}[/]")
    if result_count == 0:
        c.print(f"[dim]Nenhum resultado para[/] [bold]{query}[/]")
    elif result_count == 1:
        c.print(f"[dim]1 resultado para[/] [bold]{query}[/]")
    else:
        c.print(f"[dim]{result_count} resultados para[/] [bold]{query}[/]")
    c.print()


def _render_search_result_card(meta) -> Panel:
    from rich import box

    install_ref = _skill_install_ref(meta)
    badge = _skill_trust_badge(meta.source, meta.trust_level)
    border_style = "cyan" if meta.source in ("official", "ector-index") else "blue"
    body = "\n".join(
        [
            meta.description.strip() or "[dim]Sem descrição.[/]",
            "",
            f"[dim]{_skill_source_label(meta.source)}[/]",
            f"[cyan]{meta.identifier}[/]",
        ]
    )
    return Panel(
        body,
        title=f"[bold cyan]{meta.name}[/]  {badge}",
        subtitle=f"[dim]instalar:[/] [bold]ector skills install {install_ref}[/]",
        border_style=border_style,
        box=box.ROUNDED,
        expand=True,
        padding=(0, 1),
    )


def _print_search_footer(c: Console) -> None:
    c.print("[dim]Próximos passos[/]")
    c.print("  [cyan]ector skills inspect <identificador>[/]  pré-visualizar conteúdo")
    c.print("  [cyan]ector skills install <identificador>[/]   instalar localmente")
    c.print()


def _resolve_source_meta_and_bundle(identifier: str, sources):
    """Resolve metadata and bundle for a specific identifier."""
    meta = None
    bundle = None
    matched_source = None

    for src in sources:
        if meta is None:
            try:
                meta = src.inspect(identifier)
                if meta:
                    matched_source = src
            except Exception:
                meta = None
        try:
            bundle = src.fetch(identifier)
        except Exception:
            bundle = None
        if bundle:
            matched_source = src
            if meta is None:
                try:
                    meta = src.inspect(identifier)
                except Exception:
                    meta = None
            break

    return meta, bundle, matched_source


def _derive_category_from_install_path(install_path: str) -> str:
    path = Path(install_path)
    parent = str(path.parent)
    return "" if parent == "." else parent


def _library_slug_from_bundle(bundle, meta) -> str:
    meta_extra = dict(getattr(meta, "extra", {}) or {})
    bundle_meta = dict(getattr(bundle, "metadata", {}) or {})
    for candidate in (
        meta_extra.get("hub_slug"),
        bundle_meta.get("hub_slug"),
        bundle.identifier if "/" not in (bundle.identifier or "") else "",
    ):
        slug = str(candidate or "").strip()
        if slug:
            return slug
    return ""


def _sync_install_with_cloud_library(bundle, meta, console: Console) -> None:
    """Best-effort: `skills install` também registra a skill na biblioteca cloud."""
    from ector_cli.identity_auth import get_access_token, get_auth_base_url
    from tools.cloud_skills_sync import schedule_cloud_skills_sync
    import httpx

    slug = _library_slug_from_bundle(bundle, meta)
    if not slug:
        return
    token = get_access_token(auto_refresh=True)
    if not token:
        return

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.post(
                f"{get_auth_base_url().rstrip('/')}/agent/me/skills/{slug}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if 200 <= int(resp.status_code) < 300:
            console.print("[dim]Biblioteca cloud atualizada para esta skill.[/]")
            schedule_cloud_skills_sync(quiet=True)
    except Exception:
        # Não bloqueia instalação local por falha de rede/cloud.
        pass


# ---------------------------------------------------------------------------
# Interactive name/category resolution for URL-installed skills
# ---------------------------------------------------------------------------

_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_VALID_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_/-]*$")


def _is_valid_installed_skill_name(name: str) -> bool:
    """Accept identifier-shaped names, reject empty / sentinel-y values."""
    if not isinstance(name, str):
        return False
    candidate = name.strip().lower()
    if not candidate or candidate in {"skill", "readme", "index", "unnamed-skill"}:
        return False
    return bool(_VALID_NAME_RE.match(candidate))


def _existing_categories() -> List[str]:
    """Return sorted subdirectory names under ``~/.ector/skills/`` that look
    like category buckets (contain at least one ``SKILL.md`` somewhere below).

    Used to suggest reusable categories when interactively installing from a
    URL. Hidden dirs (``.hub``, ``.trash``) are skipped.
    """
    from tools.skills_hub import SKILLS_DIR
    out: List[str] = []
    try:
        for entry in SKILLS_DIR.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            # Only count as a category if it contains skills, not if it IS a skill.
            # Heuristic: if ``<entry>/SKILL.md`` exists, it's a skill at the
            # top level (no category); otherwise treat as a category bucket.
            if (entry / "SKILL.md").exists():
                continue
            # Has at least one nested SKILL.md?
            try:
                if any(entry.rglob("SKILL.md")):
                    out.append(entry.name)
            except OSError:
                continue
    except (FileNotFoundError, OSError):
        return []
    return sorted(set(out))


def _prompt_for_skill_name(c: Console, url: str, default: str = "") -> Optional[str]:
    """Prompt interactively for a skill name. Returns None on cancel/EOF."""
    c.print()
    c.print(
        f"[yellow]O arquivo SKILL.md em {url} não declara um `name:` em seu "
        f"frontmatter,[/]\n[yellow]e o caminho do URL também não produz um "
        f"identificador válido.[/]"
    )
    default_hint = f" [{default}]" if default else ""
    c.print(
        f"[bold]Digite o nome da habilidade{default_hint}:[/] "
        f"[dim](letras minúsculas, dígitos, hífens, underscores; começa com uma letra)[/]"
    )
    try:
        answer = input("Nome: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not answer and default:
        answer = default
    if not _is_valid_installed_skill_name(answer):
        c.print(f"[bold red]Nome inválido:[/] {answer!r}. Abortando instalação.\n")
        return None
    return answer


def _prompt_for_category(c: Console, existing: List[str]) -> str:
    """Prompt interactively for a category. Empty/None input means flat install."""
    c.print()
    if existing:
        c.print(
            "[bold]Escolha uma categoria[/] "
            "[dim](reutilize uma existente, digite uma nova ou pressione Enter para instalação direta)[/]"
        )
        c.print(f"[dim]Existentes: {', '.join(existing)}[/]")
    else:
        c.print(
            "[bold]Categoria[/] [dim](opcional — pressione Enter para instalar em ~/.ector/skills/<nome>/)[/]"
        )
    try:
        answer = input("Categoria: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not answer:
        return ""
    if not _VALID_CATEGORY_RE.match(answer):
        c.print(f"[dim]Categoria inválida {answer!r} — instalando sem categoria.[/]")
        return ""
    return answer


def do_search(query: str, source: str = "all", limit: int = 10,
              console: Optional[Console] = None) -> None:
    """Search registries and display results as readable cards."""
    from tools.skills_hub import GitHubAuth, create_source_router, unified_search

    c = console or _console

    auth = GitHubAuth()
    sources = create_source_router(auth)
    with c.status("[bold]Pesquisando nos registros..."):
        results = unified_search(query, sources, source_filter=source, limit=limit)

    if not results:
        _print_search_header(c, query, source, 0)
        c.print("[dim]Tente outro termo ou use[/] [bold]ector skills browse[/][dim] para ver o catálogo.[/]\n")
        return

    _print_search_header(c, query, source, len(results))

    for i, meta in enumerate(results):
        if i:
            c.print()
        c.print(_render_search_result_card(meta))

    c.print()
    _print_search_footer(c)


def do_browse(page: int = 1, page_size: int = 20, source: str = "all",
              console: Optional[Console] = None) -> None:
    """Browse all available skills across registries, paginated.

    Official skills are always shown first, regardless of source filter.
    """
    from tools.skills_hub import (
        GitHubAuth, create_source_router, parallel_search_sources,
    )

    # Clamp page_size to safe range
    page_size = max(1, min(page_size, 100))

    c = console or _console

    auth = GitHubAuth()
    sources = create_source_router(auth)

    # Collect results from all (or filtered) sources in parallel.
    # Per-source limits are generous — parallelism + 30s timeout cap prevents hangs.
    _TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1}
    _PER_SOURCE_LIMIT = {
        "official": 200, "skills-sh": 200, "well-known": 50,
        "github": 200, "clawhub": 500, "claude-marketplace": 100,
        "lobehub": 500,
    }

    with c.status("[bold]Buscando habilidades nos registros..."):
        all_results, source_counts, timed_out = parallel_search_sources(
            sources,
            query="",
            per_source_limits=_PER_SOURCE_LIMIT,
            source_filter=source,
            overall_timeout=30,
        )

    if not all_results:
        c.print("[dim]Nenhuma habilidade encontrada no Skills Hub.[/]\n")
        return

    # Deduplicate by name, preferring higher trust
    seen: dict = {}
    for r in all_results:
        rank = _TRUST_RANK.get(r.trust_level, 0)
        if r.name not in seen or rank > _TRUST_RANK.get(seen[r.name].trust_level, 0):
            seen[r.name] = r
    deduped = list(seen.values())

    # Sort: official first, then by trust level (desc), then alphabetically
    deduped.sort(key=lambda r: (
        -_TRUST_RANK.get(r.trust_level, 0),
        r.source != "official",
        r.name.lower(),
    ))

    # Paginate
    total = len(deduped)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    page_items = deduped[start:end]

    # Count official vs other
    official_count = sum(1 for r in deduped if r.source == "official")

    # Build header
    source_label = f"— {source}" if source != "all" else "— todas as fontes"
    loaded_label = f"{total} habilidades carregadas"
    if timed_out:
        loaded_label += f", {len(timed_out)} fonte(s) ainda carregando"
    c.print(f"\n[bold]Skills Hub — Navegar {source_label}[/]"
            f"  [dim]({loaded_label}, página {page}/{total_pages})[/]")
    if official_count > 0 and page == 1:
        c.print(f"[bright_cyan]★ {official_count} habilidade(s) opcional(is) oficial(is) da Ector[/]")
    c.print()

    # Build table
    from rich import box

    table = Table(
        show_header=True,
        header_style="bold",
        box=box.ROUNDED,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Skill", style="bold cyan", no_wrap=True, ratio=2)
    table.add_column("Descrição", overflow="fold", ratio=4)
    table.add_column("Origem", style="dim", no_wrap=True, ratio=1)

    for i, r in enumerate(page_items, start=start + 1):
        badge = _skill_trust_badge(r.source, r.trust_level)
        origin = f"{_skill_source_label(r.source)}\n{badge}"

        table.add_row(
            str(i),
            r.name,
            r.description.strip() or "—",
            origin,
        )

    c.print(table)

    # Navigation hints
    nav_parts = []
    if page > 1:
        nav_parts.append(f"[cyan]--page {page - 1}[/] ← anterior")
    if page < total_pages:
        nav_parts.append(f"[cyan]--page {page + 1}[/] → próxima")

    if nav_parts:
        c.print(f"  {' | '.join(nav_parts)}")

    # Source summary
    if source == "all" and source_counts:
        parts = [f"{sid}: {ct}" for sid, ct in sorted(source_counts.items())]
        c.print(f"  [dim]Sources: {', '.join(parts)}[/]")

    if timed_out:
        c.print(f"  [yellow]⚡ Fontes lentas ignoradas: {', '.join(timed_out)} "
                f"— execute novamente para resultados em cache[/]")

    c.print("[dim]Dica: 'ector skills search <query>' pesquisa mais profundamente em todos os registros[/]\n")


def do_install(identifier: str, category: str = "", force: bool = False,
               console: Optional[Console] = None, skip_confirm: bool = False,
               invalidate_cache: bool = True,
               name_override: str = "") -> None:
    """Fetch, quarantine, scan, confirm, and install a skill.

    ``name_override`` lets non-interactive callers (slash commands, gateway,
    scripts) supply a skill name when the upstream SKILL.md lacks a valid
    ``name:`` frontmatter field. On interactive TTY surfaces, a missing name
    triggers a prompt instead; ``skip_confirm=True`` means "non-interactive"
    (so pair it with ``name_override`` when installing from a URL that has
    no frontmatter).
    """
    from tools.skills_hub import (
        GitHubAuth, create_source_router, ensure_hub_dirs,
        quarantine_bundle, install_from_quarantine, HubLockFile,
    )
    from tools.skills_guard import scan_skill, should_allow_install, format_scan_report

    c = console or _console
    ensure_hub_dirs()

    # Resolve which source adapter handles this identifier
    auth = GitHubAuth()
    sources = create_source_router(auth)

    # If identifier looks like a short name (no slashes), resolve it via search
    if "/" not in identifier:
        identifier = _resolve_short_name(identifier, sources, c)
        if not identifier:
            return

    c.print(f"\n[bold]Buscando:[/] {identifier}")

    meta, bundle, _matched_source = _resolve_source_meta_and_bundle(identifier, sources)

    if not bundle:
        # Check if any source hit GitHub API rate limit
        rate_limited = any(
            getattr(src, "is_rate_limited", False)
            or getattr(getattr(src, "github", None), "is_rate_limited", False)
            for src in sources
        )
        c.print(f"[bold red]Erro:[/] Não foi possível buscar '{identifier}' em nenhuma fonte.")
        if rate_limited:
            c.print(
                "[yellow]Dica:[/] Limite de taxa da API do GitHub esgotado "
                "(não autenticado: 60 requisições/hora).\n"
                "Defina [bold]GITHUB_TOKEN[/] no seu .env ou instale a "
                "CLI [bold]gh[/] e execute [bold]gh auth login[/] "
                "para aumentar o limite para 5.000/hr.\n"
            )
        else:
            c.print()
        return

    # URL-sourced skills may arrive with an empty name when SKILL.md has no
    # ``name:`` in frontmatter AND the URL path doesn't yield a valid
    # identifier. Resolve by (1) --name override, (2) interactive prompt on
    # a TTY, (3) refuse with an actionable error on non-interactive surfaces.
    bundle_meta = getattr(bundle, "metadata", {}) or {}
    if bundle.source == "url" and (not bundle.name or bundle_meta.get("awaiting_name")):
        if name_override and _is_valid_installed_skill_name(name_override):
            bundle.name = name_override.strip()
            bundle_meta["awaiting_name"] = False
        elif name_override:
            c.print(
                f"[bold red]--name inválido:[/] {name_override!r}. "
                "Deve ser um identificador em minúsculas (letras, dígitos, hífens, "
                "underscores; começa com uma letra).\n"
            )
            return
        elif skip_confirm:
            # Non-interactive surface (slash command / TUI / gateway). Can't
            # prompt — emit an actionable error.
            url = bundle_meta.get("url") or identifier
            c.print(
                f"[bold red]Não é possível instalar pelo URL:[/] {url}\n"
                "[yellow]O SKILL.md não possui `name:` no frontmatter, "
                "e o caminho do URL não produz um identificador válido.[/]\n\n"
                "Tente novamente com um nome explícito:\n"
                f"  [bold]/skills install {url} --name <seu-nome>[/]\n"
                f"  [bold]ector skills install {url} --name <seu-nome>[/]\n\n"
                "[dim]Ou peça ao autor do SKILL.md para adicionar um campo `name:` "
                "ao seu frontmatter YAML.[/]\n"
            )
            return
        else:
            # Interactive TTY — prompt.
            url = bundle_meta.get("url") or identifier
            chosen = _prompt_for_skill_name(c, url)
            if not chosen:
                c.print("[dim]Instalação cancelada.[/]\n")
                return
            bundle.name = chosen
            bundle_meta["awaiting_name"] = False
        # Keep SkillMeta in sync so downstream "already installed" checks,
        # audit logs, and display all see the final name.
        if meta is not None:
            meta.name = bundle.name
            meta.path = bundle.name

    # URL-sourced skills: offer to pick a category interactively when the
    # caller didn't specify one (TTY only — non-interactive installs fall
    # through to flat install, matching all other sources).
    if bundle.source == "url" and not category and not skip_confirm:
        category = _prompt_for_category(c, _existing_categories())

    # Auto-detect category for official skills (e.g. "official/autonomous-ai-agents/blackbox")
    if bundle.source == "official" and not category:
        bundle_meta = getattr(bundle, "metadata", {}) or {}
        meta_category = str(bundle_meta.get("category") or "").strip()
        if meta_category:
            category = meta_category
        else:
            id_parts = bundle.identifier.split("/")  # ["official", "category", "skill"]
            if len(id_parts) >= 3:
                category = id_parts[1]

    # Check if already installed
    lock = HubLockFile()
    existing = lock.get_installed(bundle.name)
    if existing:
        c.print(f"[yellow]Aviso:[/] '{bundle.name}' já está instalada em {existing['install_path']}")
        if not force:
            c.print("Use --force para reinstalar.\n")
            return

    extra_metadata = dict(getattr(meta, "extra", {}) or {})
    extra_metadata.update(getattr(bundle, "metadata", {}) or {})

    # Quarantine the bundle
    try:
        q_path = quarantine_bundle(bundle)
    except ValueError as exc:
        c.print(f"[bold red]Instalação bloqueada:[/] {exc}\n")
        from tools.skills_hub import append_audit_log
        append_audit_log("BLOCKED", bundle.name, bundle.source,
                         bundle.trust_level, "invalid_path", str(exc))
        return
    c.print(f"[dim]Quarentena em {q_path.relative_to(q_path.parent.parent.parent)}[/]")

    # Scan
    c.print("[bold]Executando verificação de segurança...[/]")
    scan_source = getattr(bundle, "identifier", "") or getattr(meta, "identifier", "") or identifier
    result = scan_skill(q_path, source=scan_source)
    c.print(format_scan_report(result))

    # Check install policy
    allowed, reason = should_allow_install(result, force=force)
    if not allowed:
        c.print(f"\n[bold red]Instalação bloqueada:[/] {reason}")
        # Clean up quarantine
        shutil.rmtree(q_path, ignore_errors=True)
        from tools.skills_hub import append_audit_log
        append_audit_log("BLOCKED", bundle.name, bundle.source,
                         bundle.trust_level, result.verdict,
                         f"{len(result.findings)}_findings")
        return

    if extra_metadata:
        metadata_lines = _format_extra_metadata_lines(extra_metadata)
        if metadata_lines:
            c.print(Panel("\n".join(metadata_lines), title="Metadados da Origem", border_style="blue"))

    # Confirm with user — show appropriate warning based on source
    # skip_confirm bypasses the prompt (needed in TUI mode where input() hangs)
    if not force and not skip_confirm:
        c.print()
        if bundle.source == "official":
            c.print(Panel(
                "[bold bright_cyan]Esta é uma habilidade opcional oficial mantida pela Ector.[/]\n\n"
                "Ela vem com o ector-agent mas não é ativada por padrão.\n"
                "A instalação a copiará para o seu diretório de habilidades onde o agente poderá usá-la.\n\n"
                f"Os arquivos estarão em: [cyan]{display_ector_home()}/skills/{category + '/' if category else ''}{bundle.name}/[/]",
                title="Habilidade Oficial",
                border_style="bright_cyan",
            ))
        else:
            c.print(Panel(
                "[bold yellow]Você está instalando uma habilidade de terceiros por sua conta e risco.[/]\n\n"
                "Habilidades externas podem conter instruções que influenciam o comportamento do agente,\n"
                "comandos de shell e scripts. Mesmo após a verificação automática, você deve\n"
                "revisar os arquivos instalados antes de usar.\n\n"
                f"Os arquivos estarão em: [cyan]{display_ector_home()}/skills/{category + '/' if category else ''}{bundle.name}/[/]",
                title="Aviso Legal",
                border_style="yellow",
            ))
        c.print(f"[bold]Instalar '{bundle.name}'?[/]")
        try:
            answer = input("Confirmar (s/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("s", "sim", "y", "yes"):
            c.print("[dim]Instalação cancelada.[/]\n")
            shutil.rmtree(q_path, ignore_errors=True)
            return

    # Install
    try:
        install_dir = install_from_quarantine(q_path, bundle.name, category, bundle, result)
    except ValueError as exc:
        c.print(f"[bold red]Instalação bloqueada:[/] {exc}\n")
        shutil.rmtree(q_path, ignore_errors=True)
        from tools.skills_hub import append_audit_log
        append_audit_log("BLOCKED", bundle.name, bundle.source,
                         bundle.trust_level, "invalid_path", str(exc))
        return
    from tools.skills_hub import SKILLS_DIR
    c.print(f"[bold green]Instalada:[/] {install_dir.relative_to(SKILLS_DIR)}")
    c.print(f"[dim]Arquivos: {', '.join(bundle.files.keys())}[/]\n")
    _sync_install_with_cloud_library(bundle, meta, c)

    try:
        from agent.skill_commands import notify_skill_commands_changed

        notify_skill_commands_changed()
        c.print("[dim]Comandos /skill-name atualizados neste processo.[/]")
    except Exception:
        pass

    if invalidate_cache:
        # Invalidate the skills prompt cache so the new skill appears immediately
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass
    else:
        c.print("[dim]A habilidade estará disponível em sua próxima sessão.[/]")
        c.print("[dim]Use /reset para iniciar uma nova sessão agora, ou --now para ativar imediatamente (invalida o cache de prompts).[/]\n")


def do_inspect(identifier: str, console: Optional[Console] = None) -> None:
    """Preview a skill's SKILL.md content without installing."""
    from tools.skills_hub import GitHubAuth, create_source_router

    c = console or _console
    auth = GitHubAuth()
    sources = create_source_router(auth)

    if "/" not in identifier:
        identifier = _resolve_short_name(identifier, sources, c)
        if not identifier:
            return

    meta, bundle, _matched_source = _resolve_source_meta_and_bundle(identifier, sources)

    if not meta:
        c.print(f"[bold red]Erro:[/] Não foi possível encontrar '{identifier}' em nenhuma fonte.\n")
        return

    c.print()
    trust_style = {"builtin": "bright_cyan", "trusted": "green", "community": "yellow"}.get(meta.trust_level, "dim")
    trust_label = "official" if meta.source == "official" else meta.trust_level

    info_lines = [
        f"[bold]Nome:[/] {meta.name}",
        f"[bold]Descrição:[/] {meta.description}",
        f"[bold]Fonte:[/] {meta.source}",
        f"[bold]Confiança:[/] [{trust_style}]{trust_label}[/]",
        f"[bold]Identificador:[/] {meta.identifier}",
    ]
    if meta.tags:
        info_lines.append(f"[bold]Tags:[/] {', '.join(meta.tags)}")
    info_lines.extend(_format_extra_metadata_lines(meta.extra))

    c.print(Panel("\n".join(info_lines), title=f"Skill: {meta.name}"))

    if bundle and "SKILL.md" in bundle.files:
        content = bundle.files["SKILL.md"]
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        # Show first 50 lines as preview
        lines = content.split("\n")
        preview = "\n".join(lines[:50])
        if len(lines) > 50:
            preview += f"\n\n... ({len(lines) - 50} linhas extras)"
        c.print(Panel(preview, title="Visualização do SKILL.md", subtitle="ector skills install <id> para instalar"))

    c.print()


def browse_skills(page: int = 1, page_size: int = 20, source: str = "all") -> dict:
    """Paginated hub browse for programmatic callers (e.g. TUI gateway).

    Returns ``{"items": [...], "page": int, "total_pages": int, "total": int}``.
    """
    from tools.skills_hub import GitHubAuth, create_source_router

    page_size = max(1, min(page_size, 100))
    _TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1}
    _PER_SOURCE_LIMIT = {
        "official": 100,
        "ector-index": 100,
        "skills-sh": 100,
        "well-known": 25,
        "github": 100,
        "clawhub": 50,
        "claude-marketplace": 50,
        "lobehub": 50,
    }
    auth = GitHubAuth()
    sources = create_source_router(auth)
    all_results: list = []
    for src in sources:
        sid = src.source_id()
        from tools.skills_hub import _source_matches_filter

        if not _source_matches_filter(sid, source):
            continue
        try:
            limit = _PER_SOURCE_LIMIT.get(sid, 50)
            all_results.extend(src.search("", limit=limit))
        except Exception:
            continue
    if not all_results:
        return {"items": [], "page": 1, "total_pages": 1, "total": 0}
    seen: dict = {}
    for r in all_results:
        rank = _TRUST_RANK.get(r.trust_level, 0)
        if r.name not in seen or rank > _TRUST_RANK.get(seen[r.name].trust_level, 0):
            seen[r.name] = r
    deduped = list(seen.values())
    deduped.sort(key=lambda r: (-_TRUST_RANK.get(r.trust_level, 0), r.source != "official", r.name.lower()))
    total = len(deduped)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    page_items = deduped[start : min(start + page_size, total)]
    return {
        "items": [{"name": r.name, "description": r.description, "source": r.source,
                    "trust": r.trust_level} for r in page_items],
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }


def inspect_skill(identifier: str) -> Optional[dict]:
    """Skill metadata (+ SKILL.md preview) for programmatic callers."""
    from tools.skills_hub import GitHubAuth, create_source_router

    class _Q:
        def print(self, *a, **k):
            pass

    c = _Q()
    auth = GitHubAuth()
    sources = create_source_router(auth)
    ident = identifier
    if "/" not in ident:
        ident = _resolve_short_name(ident, sources, c)
        if not ident:
            return None
    meta, bundle, _ = _resolve_source_meta_and_bundle(ident, sources)
    if not meta:
        return None
    out: dict = {
        "name": meta.name,
        "description": meta.description,
        "source": meta.source,
        "identifier": meta.identifier,
        "tags": list(meta.tags) if meta.tags else [],
    }
    if bundle and "SKILL.md" in bundle.files:
        content = bundle.files["SKILL.md"]
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        lines = content.split("\n")
        preview = "\n".join(lines[:50])
        if len(lines) > 50:
            preview += f"\n\n... ({len(lines) - 50} more lines)"
        out["skill_md_preview"] = preview
    return out


def _default_skill_template(name: str, description: str = "") -> str:
    """Minimal SKILL.md scaffold for ``ector skills create``."""
    desc = (description or f"Procedimento reutilizável: {name}").replace('"', "'")
    title = name.replace("-", " ").replace("_", " ").title()
    return f"""---
name: {name}
description: "{desc}"
---

# {title}

## Quando usar

- Descreva as condições que disparam esta skill.

## Passos

1. Primeiro passo
2. Segundo passo

## Armadilhas

- Erros comuns e como evitá-los.

## Verificação

- Como confirmar que a tarefa foi concluída corretamente.
"""


def _find_editor() -> Optional[str]:
    import os
    import shutil

    editor = os.getenv("EDITOR") or os.getenv("VISUAL")
    if editor:
        return editor
    for cmd in ("nano", "vim", "vi", "code"):
        if shutil.which(cmd):
            return cmd
    return None


def do_create(
    name: str = "",
    *,
    category: str = "",
    description: str = "",
    skip_edit: bool = False,
    skip_confirm: bool = False,
    console: Optional[Console] = None,
) -> bool:
    """Create a new local skill with a SKILL.md scaffold."""
    import os
    import subprocess
    import tempfile

    from tools.skill_manager_tool import _validate_name, skill_manage

    c = console or _console

    slug = (name or "").strip().lower()
    if not slug:
        slug = c.input("[bold]Nome da skill[/] (ex.: deploy-nextjs): ").strip().lower()

    err = _validate_name(slug)
    if err:
        c.print(f"[red]{err}[/]")
        return False

    cat = (category or "").strip() or None
    if cat is None and not skip_confirm and not skip_edit:
        cat_input = c.input("[dim]Categoria[/] (opcional, Enter para pular): ").strip()
        cat = cat_input or None

    desc = (description or "").strip()
    if not desc and not skip_edit and not skip_confirm:
        desc = c.input("[dim]Descrição curta[/] (opcional): ").strip()

    content = _default_skill_template(slug, desc)

    if not skip_edit:
        editor = _find_editor()
        if editor:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            c.print(f"[dim]Abrindo {tmp_path} em {editor}...[/]")
            subprocess.run([editor, tmp_path], check=False)
            try:
                content = Path(tmp_path).read_text(encoding="utf-8")
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            c.print("[yellow]Nenhum $EDITOR encontrado — usando template padrão.[/]")
            c.print("[dim]Edite depois no dashboard ou peça ao agente.[/]")

    if not skip_confirm:
        confirm = c.input(f"Criar skill [bold]{slug}[/]? [y/N] ").strip().lower()
        if confirm not in ("y", "yes", "s", "sim"):
            c.print("[dim]Cancelado.[/]")
            return False

    raw = skill_manage(action="create", name=slug, content=content, category=cat)
    result = json.loads(raw)
    if not result.get("success"):
        c.print(f"[red]{result.get('error', 'Falha ao criar skill')}[/]")
        return False

    rel_path = result.get("path", slug)
    c.print(
        f"[green]✓[/] Skill criada em "
        f"[bold]{display_ector_home()}/skills/{rel_path}/SKILL.md[/]"
    )
    hint = result.get("hint")
    if hint:
        c.print(f"[dim]{hint}[/]")
    c.print()
    return True


def do_list(source_filter: str = "all",
            enabled_only: bool = False,
            console: Optional[Console] = None) -> None:
    """List installed skills, distinguishing hub and local skills.

    Args:
        source_filter: ``all`` | ``hub`` | ``local``.
        enabled_only: If True, hide disabled skills from the output.

    Enabled/disabled state is resolved against the currently active profile's
    config — ``ector -p <profile> skills list`` reads that profile's
    ``skills.disabled`` list because ``-p`` swaps ``ECTOR_HOME`` at process
    start.  No explicit profile flag needed here.
    """
    from rich import box

    from tools.skills_hub import HubLockFile, ensure_hub_dirs
    from tools.skills_tool import _find_all_skills
    from agent.skill_utils import get_disabled_skill_names

    primary = "#2DD8FC"
    c = console or _console

    try:
        from tools.cloud_skills_sync import prime_cloud_skills_for_skills_cli

        prime_cloud_skills_for_skills_cli()
    except Exception:
        pass

    ensure_hub_dirs()
    lock = HubLockFile()
    hub_installed = {e["name"]: e for e in lock.list_installed()}

    # Pull ALL skills (including disabled ones) so we can annotate status.
    all_skills = _find_all_skills(skip_disabled=True)
    disabled_names = get_disabled_skill_names()

    def _origin_order(st: str) -> int:
        return {"hub": 0, "local": 1}.get(st, 9)

    rows: list[tuple] = []
    hub_count = 0
    local_count = 0
    enabled_count = 0
    disabled_count = 0

    for skill in all_skills:
        name = skill["name"]
        category = skill.get("category", "") or "—"
        hub_entry = hub_installed.get(name)

        if hub_entry:
            source_type = "hub"
        else:
            source_type = "local"

        if source_filter != "all" and source_filter != source_type:
            continue

        is_enabled = name not in disabled_names
        if enabled_only and not is_enabled:
            continue

        if source_type == "hub":
            hub_count += 1
        else:
            local_count += 1

        if is_enabled:
            enabled_count += 1
            status_cell = "[bold green]● Ativa[/]"
        else:
            disabled_count += 1
            status_cell = "[dim red]○ Desativada[/]"

        origem_cell = (
            "[bold #2DD8FC]Ector Hub[/]"
            if source_type == "hub"
            else "[dim]Local[/]"
        )

        rows.append(
            (
                _origin_order(source_type),
                source_type,
                (category or "").lower(),
                name.lower(),
                name,
                category,
                origem_cell,
                status_cell,
            )
        )

    rows.sort(key=lambda r: (r[0], r[2], r[3]))

    title = "Habilidades instaladas"
    if enabled_only:
        title += " (só ativas)"

    if not rows:
        c.print()
        c.print(
            Panel(
                "[dim]Nenhuma encontrada.[/]",
                border_style=primary,
                padding=(0, 1),
                title=f"[bold {primary}]Habilidades instaladas[/]",
            )
        )
        c.print()
        return

    table = Table(
        title=f"[bold {primary}]{title}[/]",
        box=box.ROUNDED,
        show_header=True,
        header_style=f"bold {primary}",
        expand=True,
        padding=(0, 1),
        title_justify="left",
        border_style="#A8A29E",
        row_styles=["none", "dim"],
    )
    table.add_column("Skill", style=f"bold {primary}", no_wrap=True, ratio=2)
    table.add_column("Categoria", style="dim", overflow="fold", ratio=3)
    table.add_column("Origem", style="dim", no_wrap=True, ratio=1)
    table.add_column("Estado", no_wrap=True, ratio=1)

    prev_source: Optional[str] = None
    for _o, src, _c, _n, name, category, origem, status_cell in rows:
        end_section = prev_source is not None and src != prev_source
        table.add_row(name, category, origem, status_cell, end_section=end_section)
        prev_source = src

    c.print(table)
    summary = f"[dim]{hub_count} hub · {local_count} locais"
    if enabled_only:
        summary += f" — {enabled_count} listadas (ativas)"
    else:
        summary += f" — {enabled_count} ativas, {disabled_count} desativadas"
    c.print(
        Panel(
            summary,
            border_style="#A8A29E",
            padding=(0, 1),
            title=f"[bold {primary}]Resumo[/]",
        )
    )
    c.print()


def do_check(name: Optional[str] = None, console: Optional[Console] = None) -> None:
    """Check hub-installed skills for upstream updates."""
    from tools.skills_hub import check_for_skill_updates

    c = console or _console
    results = check_for_skill_updates(name=name)
    if not results:
        c.print("[dim]Nenhuma habilidade instalada via hub para verificar.[/]\n")
        return

    table = Table(title="Atualizações de Habilidades")
    table.add_column("Nome", style="bold cyan")
    table.add_column("Fonte", style="dim")
    table.add_column("Status", style="dim")

    for entry in results:
        table.add_row(entry.get("name", ""), entry.get("source", ""), entry.get("status", ""))

    c.print(table)
    update_count = sum(1 for entry in results if entry.get("status") == "update_available")
    c.print(f"[dim]{update_count} atualização(ões) disponível(is) em {len(results)} habilidade(s) verificada(s)[/]\n")


def do_update(
    name: Optional[str] = None,
    console: Optional[Console] = None,
    *,
    check_only: bool = False,
) -> None:
    """Check for and apply upstream updates to hub-installed skills."""
    from tools.skills_hub import HubLockFile, check_for_skill_updates

    c = console or _console
    lock = HubLockFile()
    results = check_for_skill_updates(name=name)
    updates = [entry for entry in results if entry.get("status") == "update_available"]

    if check_only or not updates:
        do_check(name=name, console=c)
        return

    for entry in updates:
        installed = lock.get_installed(entry["name"])
        category = _derive_category_from_install_path(installed.get("install_path", "")) if installed else ""
        c.print(f"[bold]Atualizando:[/] {entry['name']}")
        do_install(entry["identifier"], category=category, force=True, console=c)

    c.print(f"[bold green]Atualizada(s) {len(updates)} habilidade(s).[/]\n")


def do_audit(name: Optional[str] = None, console: Optional[Console] = None) -> None:
    """Re-run security scan on installed hub skills."""
    from tools.skills_hub import HubLockFile, SKILLS_DIR
    from tools.skills_guard import scan_skill, format_scan_report

    c = console or _console
    lock = HubLockFile()
    installed = lock.list_installed()

    if not installed:
        c.print("[dim]Nenhuma habilidade instalada via hub para auditar.[/]\n")
        return

    targets = installed
    if name:
        targets = [e for e in installed if e["name"] == name]
        if not targets:
            c.print(f"[bold red]Erro:[/] '{name}' não é uma habilidade instalada via hub.\n")
            return

    c.print(f"\n[bold]Auditando {len(targets)} habilidade(s)...[/]\n")

    for entry in targets:
        skill_path = SKILLS_DIR / entry["install_path"]
        if not skill_path.exists():
            c.print(f"[yellow]Aviso:[/] {entry['name']} — caminho ausente: {entry['install_path']}")
            continue

        result = scan_skill(skill_path, source=entry.get("identifier", entry["source"]))
        c.print(format_scan_report(result))
        c.print()


def do_uninstall(name: str, console: Optional[Console] = None,
                 skip_confirm: bool = False,
                 invalidate_cache: bool = True) -> None:
    """Remove a hub-installed skill with confirmation."""
    from tools.skills_hub import uninstall_skill

    c = console or _console

    # skip_confirm bypasses the prompt (needed in TUI mode where input() hangs)
    if not skip_confirm:
        c.print(f"\n[bold]Desinstalar '{name}'?[/]")
        try:
            answer = input("Confirmar (s/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("s", "sim", "y", "yes"):
            c.print("[dim]Cancelado.[/]\n")
            return

    success, msg = uninstall_skill(name)
    if success:
        c.print(f"[bold green]{msg}[/]\n")
        try:
            from agent.skill_commands import notify_skill_commands_changed

            notify_skill_commands_changed()
        except Exception:
            pass
        if invalidate_cache:
            try:
                from agent.prompt_builder import clear_skills_system_prompt_cache
                clear_skills_system_prompt_cache(clear_snapshot=True)
            except Exception:
                pass
        else:
            c.print("[dim]A alteração terá efeito em sua próxima sessão.[/]")
            c.print("[dim]Use /reset para iniciar uma nova sessão agora, ou --now para aplicar imediatamente (invalida o cache de prompts).[/]\n")
    else:
        c.print(f"[bold red]Erro:[/] {msg}\n")


def do_tap(action: str, repo: str = "", console: Optional[Console] = None) -> None:
    """Manage taps (custom GitHub repo sources)."""
    from tools.skills_hub import TapsManager

    c = console or _console
    mgr = TapsManager()

    if action == "list":
        taps = mgr.list_taps()
        if not taps:
            c.print("[dim]Nenhum tap personalizado configurado. Usando apenas fontes padrão.[/]\n")
            return
        table = Table(title="Taps Configurados")
        table.add_column("Repositório", style="bold cyan")
        table.add_column("Caminho", style="dim")
        for t in taps:
            label = t.get("repo") or t.get("name") or t.get("path", "unknown")
            table.add_row(label, t.get("path", "skills/"))
        c.print(table)
        c.print()

    elif action == "add":
        if not repo:
            c.print("[bold red]Erro:[/] Repositório necessário. Uso: ector skills tap add dono/repositorio\n")
            return
        if mgr.add(repo):
            c.print(f"[bold green]Tap adicionado:[/] {repo}\n")
        else:
            c.print(f"[yellow]Tap já existe:[/] {repo}\n")

    elif action == "remove":
        if not repo:
            c.print("[bold red]Erro:[/] Repositório necessário. Uso: ector skills tap remove dono/repositorio\n")
            return
        if mgr.remove(repo):
            c.print(f"[bold green]Tap removido:[/] {repo}\n")
        else:
            c.print(f"[bold red]Erro:[/] Tap não encontrado: {repo}\n")

    else:
        c.print(f"[bold red]Ação de tap desconhecida:[/] {action}. Use: list, add, remove\n")


def do_publish(skill_path: str, target: str = "github", repo: str = "",
               console: Optional[Console] = None) -> None:
    """Publish a local skill to a registry (GitHub PR or ClawHub submission)."""
    from tools.skills_hub import GitHubAuth, SKILLS_DIR
    from tools.skills_guard import scan_skill, format_scan_report

    c = console or _console
    path = Path(skill_path)

    # Resolve relative to skills dir if not absolute
    if not path.is_absolute():
        path = SKILLS_DIR / path
    if not path.exists() or not (path / "SKILL.md").exists():
        c.print(f"[bold red]Erro:[/] Nenhum SKILL.md encontrado em {path}\n")
        return

    # Validate the skill
    import yaml
    skill_md = (path / "SKILL.md").read_text(encoding="utf-8")
    fm = {}
    if skill_md.startswith("---"):
        import re
        match = re.search(r'\n---\s*\n', skill_md[3:])
        if match:
            try:
                fm = yaml.safe_load(skill_md[3:match.start() + 3]) or {}
            except yaml.YAMLError:
                pass

    name = fm.get("name", path.name)
    description = fm.get("description", "")
    if not description:
        c.print("[bold red]Erro:[/] SKILL.md deve ter uma 'description' no frontmatter.\n")
        return

    # Self-scan before publishing
    c.print(f"[bold]Escaneando '{name}' antes de publicar...[/]")
    result = scan_skill(path, source="self")
    c.print(format_scan_report(result))
    if result.verdict == "dangerous":
        c.print("[bold red]Não é possível publicar uma habilidade com veredito PERIGOSO (DANGEROUS).[/]\n")
        return

    if target == "github":
        if not repo:
            c.print("[bold red]Erro:[/] --repo necessário para publicação no GitHub.\n"
                    "Uso: ector skills publish <caminho> --to github --repo dono/repositorio\n")
            return

        auth = GitHubAuth()
        if not auth.is_authenticated():
            c.print("[bold red]Erro:[/] Autenticação do GitHub necessária.\n"
                    f"Defina GITHUB_TOKEN em {display_ector_home()}/.env ou execute 'gh auth login'.\n")
            return

        c.print(f"[bold]Publicando '{name}' em {repo}...[/]")
        success, msg = _github_publish(path, name, repo, auth)
        if success:
            c.print(f"[bold green]{msg}[/]\n")
        else:
            c.print(f"[bold red]Error:[/] {msg}\n")

    elif target == "clawhub":
        c.print("[yellow]A publicação no ClawHub ainda não é suportada. "
                "Submeta manualmente em https://clawhub.ai/submit[/]\n")
    else:
        c.print(f"[bold red]Alvo desconhecido:[/] {target}. Use 'github' ou 'clawhub'.\n")


def _github_publish(skill_path: Path, skill_name: str, target_repo: str,
                    auth) -> tuple:
    """Create a PR to a GitHub repo with the skill. Returns (success, message)."""
    import httpx

    headers = auth.get_headers()

    # 1. Fork the repo
    try:
        resp = httpx.post(
            f"https://api.github.com/repos/{target_repo}/forks",
            headers=headers, timeout=30,
        )
        if resp.status_code in (200, 202):
            fork = resp.json()
            fork_repo = fork["full_name"]
        elif resp.status_code == 403:
            return False, "GitHub token lacks permission to fork repos"
        else:
            return False, f"Failed to fork {target_repo}: {resp.status_code}"
    except httpx.HTTPError as e:
        return False, f"Network error forking repo: {e}"

    # 2. Get default branch
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{target_repo}",
            headers=headers, timeout=15,
        )
        default_branch = resp.json().get("default_branch", "main")
    except Exception:
        default_branch = "main"

    # 3. Get the base tree SHA
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{fork_repo}/git/refs/heads/{default_branch}",
            headers=headers, timeout=15,
        )
        base_sha = resp.json()["object"]["sha"]
    except Exception as e:
        return False, f"Failed to get base branch: {e}"

    # 4. Create a new branch
    branch_name = f"add-skill-{skill_name}"
    try:
        httpx.post(
            f"https://api.github.com/repos/{fork_repo}/git/refs",
            headers=headers, timeout=15,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
    except Exception as e:
        return False, f"Failed to create branch: {e}"

    # 5. Upload skill files
    for f in skill_path.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(skill_path))
        upload_path = f"skills/{skill_name}/{rel}"
        try:
            import base64
            content_b64 = base64.b64encode(f.read_bytes()).decode()
            httpx.put(
                f"https://api.github.com/repos/{fork_repo}/contents/{upload_path}",
                headers=headers, timeout=15,
                json={
                    "message": f"Add {skill_name} skill: {rel}",
                    "content": content_b64,
                    "branch": branch_name,
                },
            )
        except Exception as e:
            return False, f"Failed to upload {rel}: {e}"

    # 6. Create PR
    try:
        resp = httpx.post(
            f"https://api.github.com/repos/{target_repo}/pulls",
            headers=headers, timeout=15,
            json={
                "title": f"Add skill: {skill_name}",
                "body": f"Submitting the `{skill_name}` skill via Ector Skills Hub.\n\n"
                        f"This skill was scanned by the Ector Skills Guard before submission.",
                "head": f"{fork_repo.split('/')[0]}:{branch_name}",
                "base": default_branch,
            },
        )
        if resp.status_code == 201:
            pr_url = resp.json().get("html_url", "")
            return True, f"PR created: {pr_url}"
        else:
            return False, f"Failed to create PR: {resp.status_code} {resp.text[:200]}"
    except httpx.HTTPError as e:
        return False, f"Network error creating PR: {e}"


def do_snapshot_export(output_path: str, console: Optional[Console] = None) -> None:
    """Export current hub skill configuration to a portable JSON file."""
    from tools.skills_hub import HubLockFile, TapsManager

    c = console or _console
    lock = HubLockFile()
    taps = TapsManager()

    installed = lock.list_installed()
    tap_list = taps.list_taps()

    snapshot = {
        "ector_version": "0.1.0",
        "exported_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "skills": [
            {
                "name": entry["name"],
                "source": entry.get("source", ""),
                "identifier": entry.get("identifier", ""),
                "category": str(Path(entry.get("install_path", "")).parent)
                            if "/" in entry.get("install_path", "") else "",
            }
            for entry in installed
        ],
        "taps": tap_list,
    }

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    if output_path == "-":
        import sys
        sys.stdout.write(payload)
    else:
        out = Path(output_path)
        out.write_text(payload)
        c.print(f"[bold green]Snapshot exportado:[/] {out}")
        c.print(f"[dim]{len(installed)} habilidade(s), {len(tap_list)} tap(s)[/]\n")


def do_snapshot_import(input_path: str, force: bool = False,
                       console: Optional[Console] = None) -> None:
    """Re-install skills from a snapshot file."""
    from tools.skills_hub import TapsManager

    c = console or _console
    inp = Path(input_path)
    if not inp.exists():
        c.print(f"[bold red]Erro:[/] Arquivo não encontrado: {inp}\n")
        return

    try:
        snapshot = json.loads(inp.read_text())
    except json.JSONDecodeError:
        c.print(f"[bold red]Erro:[/] JSON inválido em {inp}\n")
        return

    # Restore taps first
    taps = snapshot.get("taps", [])
    if taps:
        mgr = TapsManager()
        for tap in taps:
            repo = tap.get("repo", "")
            if repo:
                mgr.add(repo, tap.get("path", "skills/"))
        c.print(f"[dim]Restaurados {len(taps)} tap(s)[/]")

    # Install skills
    skills = snapshot.get("skills", [])
    if not skills:
        c.print("[dim]Nenhuma habilidade no snapshot para instalar.[/]\n")
        return

    c.print(f"[bold]Importando {len(skills)} habilidade(s) do snapshot...[/]\n")
    for entry in skills:
        identifier = entry.get("identifier", "")
        category = entry.get("category", "")
        if not identifier:
            c.print(f"[yellow]Pulando entrada sem identificador: {entry.get('name', '?')}[/]")
            continue

        c.print(f"[bold]--- {entry.get('name', identifier)} ---[/]")
        do_install(identifier, category=category, force=force, console=c)

    c.print("[bold green]Importação do snapshot concluída.[/]\n")


# ---------------------------------------------------------------------------
# CLI argparse entry point
# ---------------------------------------------------------------------------

def skills_command(args) -> None:
    """Router for `ector skills <subcommand>` — called from ector_cli/main.py."""
    action = getattr(args, "skills_action", None)

    if not action:
        _print_skills_help(_console, for_cli=True)
        return

    if action == "browse":
        do_browse(
            page=int(getattr(args, "page", 1) or 1),
            page_size=int(getattr(args, "size", 20) or 20),
            source=str(getattr(args, "source", None) or "all"),
        )
    elif action == "search":
        query = (getattr(args, "query", None) or "").strip()
        if not query:
            _console.print(
                '[yellow]Falta o termo de busca.[/yellow] Ex.: [bold]ector skills search "web scraping"[/bold]\n'
            )
            return
        do_search(
            query,
            source=str(getattr(args, "source", None) or "all"),
            limit=int(getattr(args, "limit", 10) or 10),
        )
    elif action in ("library-sync", "sync-cloud", "sync"):
        from tools.cloud_skills_sync import sync_cloud_skills_library

        sync_cloud_skills_library(quiet=False, respect_rate_limit=False)
    elif action in ("library-remove", "library-rm", "remove"):
        slug = (getattr(args, "identifier", None) or getattr(args, "slug", None) or "").strip()
        if not slug:
            _console.print(
                "[yellow]Falta o slug.[/yellow] Ex.: [bold]ector skills remove ector-hub-onboarding[/bold]\n"
            )
            return
        from tools.cloud_skills_sync import remove_skill_from_cloud_library

        remove_skill_from_cloud_library(slug, quiet=False)
    elif action == "install":
        identifier = (getattr(args, "identifier", None) or getattr(args, "source", None) or "").strip()
        if not identifier:
            _console.print(
                "[yellow]Falta o que instalar.[/yellow] Ex.: [bold]ector skills install official/github[/bold] "
                "ou caminho local / URL\n"
            )
            return
        do_install(
            identifier,
            category=str(getattr(args, "category", None) or ""),
            force=bool(getattr(args, "force", False)),
            skip_confirm=bool(getattr(args, "yes", False)),
            name_override=str(getattr(args, "name", "") or ""),
        )
    elif action == "create":
        do_create(
            name=str(getattr(args, "name", "") or ""),
            category=str(getattr(args, "category", "") or ""),
            description=str(getattr(args, "description", "") or ""),
            skip_edit=bool(getattr(args, "no_edit", False)),
            skip_confirm=bool(getattr(args, "yes", False)),
        )
    elif action == "inspect":
        ident = (getattr(args, "identifier", None) or "").strip()
        if not ident:
            _console.print(
                "[yellow]Falta o identificador.[/yellow] Ex.: [bold]ector skills inspect official/github[/bold]\n"
            )
            return
        do_inspect(ident)
    elif action == "list":
        raw_src = getattr(args, "source", None)
        source_filter = str(raw_src).strip() if raw_src not in (None, "") else "all"
        if source_filter not in ("all", "hub", "local"):
            _console.print(
                f"[yellow]Valor inválido para --source:[/yellow] {source_filter!r}. "
                "Use: all, hub, local.\n"
            )
            return
        do_list(
            source_filter=source_filter,
            enabled_only=bool(getattr(args, "enabled_only", False)),
        )
    elif action in ("update", "check"):
        do_update(
            name=getattr(args, "name", None),
            check_only=(action == "check"),
        )
    elif action == "audit":
        do_audit(name=getattr(args, "name", None))
    elif action == "uninstall":
        name = (getattr(args, "name", None) or "").strip()
        if not name:
            _console.print("[yellow]Falta o nome da skill.[/yellow] Ex.: [bold]ector skills uninstall minha-skill[/bold]\n")
            return
        do_uninstall(name)
    elif action == "publish":
        path = (getattr(args, "skill_path", None) or "").strip()
        if not path:
            _console.print("[yellow]Falta o caminho da skill.[/yellow] Ex.: [bold]ector skills publish ./minha-skill[/bold]\n")
            return
        do_publish(
            path,
            target=str(getattr(args, "to", None) or "github"),
            repo=str(getattr(args, "repo", "") or ""),
        )
    elif action == "snapshot":
        snap_action = getattr(args, "snapshot_action", None)
        if snap_action == "export":
            out = getattr(args, "output", None)
            if out is None or (isinstance(out, str) and not str(out).strip()):
                _console.print(
                    "[yellow]Falta o ficheiro de saída.[/yellow] Ex.: [bold]ector skills snapshot export skills.json[/bold]\n"
                )
                return
            do_snapshot_export(out)
        elif snap_action == "import":
            inp = getattr(args, "input", None)
            if inp is None or (isinstance(inp, str) and not str(inp).strip()):
                _console.print(
                    "[yellow]Falta o ficheiro de entrada.[/yellow] Ex.: [bold]ector skills snapshot import skills.json[/bold]\n"
                )
                return
            do_snapshot_import(inp, force=bool(getattr(args, "force", False)))
        else:
            _console.print("Uso: ector skills snapshot [export|import]\n")
    elif action == "tap":
        tap_action = getattr(args, "tap_action", None)
        repo = str(getattr(args, "repo", "") or getattr(args, "name", "") or "")
        if not tap_action:
            _console.print("Uso: ector skills tap [list|add|remove]\n")
            return
        do_tap(tap_action, repo=repo)
    else:
        _console.print(f"[yellow]Subcomando desconhecido:[/yellow] {action!r}\n")
        _print_skills_help(_console, for_cli=True)


# ---------------------------------------------------------------------------
# Slash command entry point (/skills in chat)
# ---------------------------------------------------------------------------

def handle_skills_slash(cmd: str, console: Optional[Console] = None) -> None:
    """
    Parse and dispatch `/skills <subcommand> [args]` from the chat interface.

    Examples:
        /skills search kubernetes
        /skills install openai/skills/skill-creator
        /skills install openai/skills/skill-creator --force
        /skills install https://example.com/path/SKILL.md
        /skills inspect openai/skills/skill-creator
        /skills list
        /skills list --source hub
        /skills check
        /skills update
        /skills audit
        /skills audit my-skill
        /skills uninstall my-skill
        /skills tap list
        /skills tap add owner/repo
        /skills tap remove owner/repo
    """
    c = console or _console
    parts = cmd.strip().split()

    # Strip the leading "/skills" if present
    if parts and parts[0].lower() == "/skills":
        parts = parts[1:]

    if not parts:
        _print_skills_help(c)
        return

    action = parts[0].lower()
    args = parts[1:]

    if action == "browse":
        page = 1
        page_size = 20
        source = "all"
        i = 0
        while i < len(args):
            if args[i] == "--page" and i + 1 < len(args):
                try:
                    page = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif args[i] == "--size" and i + 1 < len(args):
                try:
                    page_size = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif args[i] == "--source" and i + 1 < len(args):
                source = args[i + 1]
                i += 2
            else:
                i += 1
        do_browse(page=page, page_size=page_size, source=source, console=c)

    elif action == "search":
        if not args:
            c.print("[bold red]Uso:[/] /skills search <termo> [--source skills-sh|well-known|github|official] [--limit N]\n")
            return
        source = "all"
        limit = 10
        query_parts = []
        i = 0
        while i < len(args):
            if args[i] == "--source" and i + 1 < len(args):
                source = args[i + 1]
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                query_parts.append(args[i])
                i += 1
        do_search(" ".join(query_parts), source=source, limit=limit, console=c)

    elif action == "install":
        if not args:
            c.print("[bold red]Uso:[/] /skills install <identificador-ou-url> [--name <nome>] [--category <categoria>] [--force] [--now]\n")
            return
        identifier = args[0]
        category = ""
        name_override = ""
        # Slash commands run inside prompt_toolkit where input() hangs.
        # Always skip confirmation — the user typing the command is implicit consent.
        skip_confirm = True
        force = "--force" in args
        # --now invalidates prompt cache immediately (costs more money).
        # Default: defer to next session to preserve cache.
        invalidate_cache = "--now" in args
        for i, a in enumerate(args):
            if a == "--category" and i + 1 < len(args):
                category = args[i + 1]
            elif a == "--name" and i + 1 < len(args):
                name_override = args[i + 1]
        do_install(identifier, category=category, force=force,
                   skip_confirm=skip_confirm, invalidate_cache=invalidate_cache,
                   name_override=name_override, console=c)

    elif action == "inspect":
        if not args:
            c.print("[bold red]Uso:[/] /skills inspect <identificador>\n")
            return
        do_inspect(args[0], console=c)

    elif action == "list":
        source_filter = "all"
        enabled_only = "--enabled-only" in args or "--enabled" in args
        if "--source" in args:
            idx = args.index("--source")
            if idx + 1 < len(args):
                source_filter = args[idx + 1]
        do_list(source_filter=source_filter, enabled_only=enabled_only, console=c)

    elif action in ("check", "update"):
        name = args[0] if args else None
        do_update(name=name, console=c, check_only=(action == "check"))

    elif action == "audit":
        name = args[0] if args else None
        do_audit(name=name, console=c)

    elif action == "uninstall":
        if not args:
            c.print("[bold red]Uso:[/] /skills uninstall <nome> [--now]\n")
            return
        # Slash commands run inside prompt_toolkit where input() hangs.
        skip_confirm = True
        invalidate_cache = "--now" in args
        do_uninstall(args[0], console=c, skip_confirm=skip_confirm,
                     invalidate_cache=invalidate_cache)

    elif action == "publish":
        if not args:
            c.print("[bold red]Uso:[/] /skills publish <caminho-da-habilidade> [--to github] [--repo dono/repositorio]\n")
            return
        skill_path = args[0]
        target = "github"
        repo = ""
        for i, a in enumerate(args):
            if a == "--to" and i + 1 < len(args):
                target = args[i + 1]
            if a == "--repo" and i + 1 < len(args):
                repo = args[i + 1]
        do_publish(skill_path, target=target, repo=repo, console=c)

    elif action == "snapshot":
        if not args:
            c.print("[bold red]Uso:[/] /skills snapshot export <arquivo> | /skills snapshot import <arquivo>\n")
            return
        snap_action = args[0]
        if snap_action == "export" and len(args) > 1:
            do_snapshot_export(args[1], console=c)
        elif snap_action == "import" and len(args) > 1:
            force = "--force" in args
            do_snapshot_import(args[1], force=force, console=c)
        else:
            c.print("[bold red]Uso:[/] /skills snapshot export <arquivo> | /skills snapshot import <arquivo>\n")

    elif action == "tap":
        if not args:
            do_tap("list", console=c)
            return
        tap_action = args[0]
        repo = args[1] if len(args) > 1 else ""
        do_tap(tap_action, repo=repo, console=c)

    elif action in ("help", "--help", "-h"):
        _print_skills_help(c)

    else:
        c.print(f"[bold red]Ação desconhecida:[/] {action}")
        _print_skills_help(c)


def _skills_help_table(*, for_cli: bool) -> Table:
    """Two-column command list for skills help (CLI and /skills)."""
    primary = "#2DD8FC"
    table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
    table.add_column(no_wrap=True, min_width=30)
    table.add_column()

    _first_section = True

    def section(label: str) -> None:
        nonlocal _first_section
        if not _first_section:
            table.add_row("", "")
        _first_section = False
        table.add_row(Text(label, style="bold"), "")

    def row(cmd: str, desc: str, *, optional: str = "") -> None:
        label = Text(cmd, style=primary)
        if optional:
            label.append(optional, style="dim")
        table.add_row(label, Text(desc, style="dim"))

    section("Uso rápido")
    row("sync", "Sincronizar biblioteca do Hub para este dispositivo")
    row("list", "Ver skills instaladas", optional=" [--source hub|local]")
    row("create [nome]", "Criar skill local com template SKILL.md")
    row("install <slug|url|caminho>", "Instalar uma skill")
    row("remove <slug>", "Remover da biblioteca cloud e desinstalar local")
    row("uninstall <nome>", "Desinstalar uma skill local")

    section("Descobrir skills")
    row("search <termo>", "Pesquisar no catálogo")
    row("browse", "Navegar catálogo paginado", optional=" [--source …]")
    row("inspect <id>", "Pré-visualizar antes de instalar")

    section("Manutenção")
    row("update", "Verificar e aplicar atualizações", optional=" [nome]")

    section("Avançado")
    row("audit", "Revalidar segurança", optional=" [nome]")
    row("tap list|add|remove", "Gerenciar fontes extras (taps)")
    row("snapshot export|import", "Exportar/importar estado de skills")
    row("publish <caminho>", "Publicar skill em um registro")
    if for_cli:
        row("config", "Habilitar/desabilitar skills (interativo)")
    else:
        row("reset <nome>", "Resetar rastreamento (flag «modificada pelo usuário»)", optional=" [--restore]")

    return table


def _print_skills_help(console: Console, *, for_cli: bool = False) -> None:
    """Ajuda estruturada para ``ector skills`` (CLI) ou ``/skills`` (chat)."""
    primary = "#2DD8FC"
    title = f"[bold {primary}]ector skills[/]" if for_cli else f"[bold {primary}]/skills[/]"
    subtitle = (
        "[dim]ector skills <comando> --help — detalhes por comando[/]"
        if for_cli
        else None
    )
    console.print()
    console.print(
        Panel(
            _skills_help_table(for_cli=for_cli),
            title=title,
            subtitle=subtitle,
            border_style=primary,
            padding=(1, 2),
        ),
    )
    if for_cli:
        console.print("[dim]Exemplos:[/]")
        console.print(f"  [{primary}]ector skills sync[/]")
        console.print(f"  [{primary}]ector skills list[/]")
        console.print(f"  [{primary}]ector skills create minha-skill[/]")
        console.print(f"  [{primary}]ector skills search onboarding[/]")
        console.print(f"  [{primary}]ector skills install ector-hub-onboarding[/]")
    console.print()
