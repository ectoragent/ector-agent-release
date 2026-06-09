"""``ector sessions list`` — Rich session history listing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ector_constants import display_ector_home

from ector_cli.session_resolve import relative_time

_ECTOR_ACCENT = "#00D1FF"

_SOURCE_LABELS = {
    "cli": "CLI",
    "tui": "Terminal",
    "web": "Web",
    "telegram": "Telegram",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "slack": "Slack",
    "matrix": "Matrix",
    "signal": "Signal",
    "email": "E-mail",
    "acp": "ACP",
    "api": "API",
}


def _source_label(source: str) -> str:
    key = (source or "").strip().lower()
    return _SOURCE_LABELS.get(key, key or "—")


def _session_title(session: Dict[str, Any]) -> str:
    return (session.get("title") or "").strip()


def _session_preview_text(session: Dict[str, Any]) -> str:
    return (session.get("preview") or "").strip()


def _session_conversation_label(session: Dict[str, Any]) -> str:
    title = _session_title(session)
    if title:
        return title
    preview = _session_preview_text(session)
    if preview:
        return preview
    return session.get("id", "—")


def _truncate(text: str, max_len: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def _is_pinned(session: Dict[str, Any]) -> bool:
    return bool(session.get("pinned"))


def _sort_sessions(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key(session: Dict[str, Any]) -> tuple:
        pinned = _is_pinned(session)
        pinned_at = float(session.get("pinned_at") or 0)
        last_active = float(session.get("last_active") or session.get("started_at") or 0)
        return (0 if pinned else 1, -pinned_at if pinned else 0, -last_active)

    return sorted(sessions, key=_key)


def _session_summary(session: Dict[str, Any]) -> str:
    """One-line label for the main column (title, or preview, or id)."""
    title = _session_title(session)
    preview = _session_preview_text(session)
    if title and preview and preview != title:
        return _truncate(f"{title} — {preview}", 64)
    return _truncate(_session_conversation_label(session), 64)


def _format_title(
    count: int,
    *,
    pinned_count: int = 0,
    source: Optional[str] = None,
    limit: int = 20,
    at_limit: bool = False,
) -> str:
    parts = [f"[bold {_ECTOR_ACCENT}]Histórico de sessões[/bold {_ECTOR_ACCENT}]"]
    meta: List[str] = [str(count)]
    if pinned_count:
        meta.append(f"{pinned_count} fixada(s)")
    if source:
        meta.append(f"origem={source}")
    if at_limit and limit:
        meta.append(f"limite={limit}")
    parts.append(f"[dim]({', '.join(meta)})[/dim]")
    return " ".join(parts)


def print_sessions_list(
    sessions: List[Dict[str, Any]],
    *,
    source: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> None:
    """Render ``ector sessions list`` with a Rich table."""
    from rich import box
    from rich.console import Console
    from rich.table import Table

    console = Console()
    dhh = display_ector_home()
    store_hint = f"{dhh}/state.db"
    if db_path is not None:
        store_hint = str(db_path).replace(str(Path.home()), "~", 1)

    if not sessions:
        console.print()
        console.print(f"[bold {_ECTOR_ACCENT}]Histórico de sessões[/bold {_ECTOR_ACCENT}]")
        if source:
            console.print(f"[dim]Nenhuma sessão com origem[/dim] [bold]{source}[/bold][dim].[/dim]")
        else:
            console.print("[dim]Nenhuma sessão encontrada.[/dim]")
        console.print(f"[dim]{store_hint}[/dim]")
        console.print()
        console.print(
            "[dim]Inicie uma conversa com [bold]ector chat[/bold] ou "
            "[bold]ector localhost[/bold] para criar a primeira sessão.[/dim]"
        )
        console.print(
            "[dim]Retomar: [bold]ector --resume <id>[/bold]  ·  "
            "Explorar: [bold]ector sessions browse[/bold][/dim]"
        )
        console.print()
        return

    ordered = _sort_sessions(sessions)
    pinned_count = sum(1 for s in ordered if _is_pinned(s))
    at_limit = bool(limit and len(ordered) >= limit)

    table = Table(
        title=_format_title(
            len(ordered),
            pinned_count=pinned_count,
            source=source,
            limit=limit,
            at_limit=at_limit,
        ),
        caption=f"[dim]{store_hint}[/dim]",
        box=box.HORIZONTALS,
        show_header=True,
        show_lines=True,
        header_style="bold",
        border_style="dim",
        expand=True,
        padding=(0, 1),
        title_justify="left",
        caption_justify="left",
    )
    table.add_column("Sessão", no_wrap=True, overflow="ellipsis", ratio=4)
    table.add_column("Origem", no_wrap=True, min_width=9, style="dim")
    table.add_column("Atividade", no_wrap=True, min_width=11)
    table.add_column("Msgs", justify="right", no_wrap=True, width=5, style="dim")
    table.add_column("ID", style="dim cyan", no_wrap=True, ratio=2)

    for session in ordered:
        label = _session_summary(session)
        if _is_pinned(session):
            label = f"[{_ECTOR_ACCENT}]◆[/] {label}"
        table.add_row(
            label,
            _source_label(session.get("source", "")),
            relative_time(session.get("last_active")),
            str(session.get("message_count") or "—"),
            session.get("id", ""),
        )

    console.print()
    console.print(table)
    console.print(
        "[dim]Retomar: [bold]ector --resume <id>[/bold]  ·  "
        "[bold]ector sessions browse[/bold]  ·  "
        "[bold]ector sessions rename <id> <título>[/bold]  ·  "
        "[bold]ector sessions export -[/bold][/dim]"
    )
    console.print()
