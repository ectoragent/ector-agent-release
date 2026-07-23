"""``ector logs`` — view and filter Ector log files.

Supports tailing, following, session filtering, level filtering,
component filtering, and relative time ranges.  All log files live
under ``~/.ector/logs/``.

Usage examples::

    ector logs                    # last 50 lines of agent.log
    ector logs -f                 # follow agent.log in real time
    ector logs errors             # last 50 lines of errors.log
    ector logs gateway -n 100    # last 100 lines of gateway.log
    ector logs --level WARNING    # only WARNING+ lines
    ector logs --session abc123   # filter by session ID substring
    ector logs --component tools  # only tool-related lines
    ector logs --since 1h         # lines from the last hour
    ector logs --since 30m -f     # follow, starting 30 min ago
    ector logs list               # list log files with sizes
    ector logs clear              # truncate all .log files
    ector logs clear agent        # truncate agent.log only
"""

import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

from ector_constants import get_ector_home, display_ector_home

# Brand accent — matches config status / profile panels
_ECTOR_ACCENT = "#00D1FF"

# Known log files (name → filename)
LOG_FILES = {
    "agent": "agent.log",
    "errors": "errors.log",
    "gateway": "gateway.log",
}

_LOG_META = {
    "agent.log": "Loop do agente, ferramentas e sessões",
    "errors.log": "WARNING, ERROR e CRITICAL",
    "gateway.log": "Canais de mensagem (Telegram, Discord, WhatsApp…)",
}

# Log line timestamp regex — matches "2026-04-05 22:35:00,123" or
# "2026-04-05 22:35:00" at the start of a line.
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")

# Level extraction — matches " INFO ", " WARNING ", " ERROR ", " DEBUG ", " CRITICAL "
_LEVEL_RE = re.compile(r"\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s")

# Logger name extraction — after level and optional session tag, the next
# non-space token before ":" is the logger name.
# Matches: "INFO gateway.run:" or "INFO [sess_abc] tools.terminal_tool:"
_LOGGER_NAME_RE = re.compile(
    r"\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)"  # level
    r"(?:\s+\[.*?\])?"                           # optional session tag
    r"\s+(\S+):"                                 # logger name
)

# Level ordering for >= filtering
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


def _parse_since(since_str: str) -> Optional[datetime]:
    """Parse a relative time string like '1h', '30m', '2d' into a datetime cutoff.

    Returns None if the string can't be parsed.
    """
    since_str = since_str.strip().lower()
    match = re.match(r"^(\d+)\s*([smhd])$", since_str)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    delta = {
        "s": timedelta(seconds=value),
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value),
    }[unit]
    return datetime.now() - delta


def _parse_line_timestamp(line: str) -> Optional[datetime]:
    """Extract timestamp from a log line. Returns None if not parseable."""
    m = _TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _extract_level(line: str) -> Optional[str]:
    """Extract the log level from a line."""
    m = _LEVEL_RE.search(line)
    return m.group(1) if m else None


def _extract_logger_name(line: str) -> Optional[str]:
    """Extract the logger name from a log line."""
    m = _LOGGER_NAME_RE.search(line)
    return m.group(1) if m else None


def _line_matches_component(line: str, prefixes: Sequence[str]) -> bool:
    """Check if a log line's logger name starts with any of *prefixes*."""
    name = _extract_logger_name(line)
    if name is None:
        return False
    return name.startswith(tuple(prefixes))


def _matches_filters(
    line: str,
    *,
    min_level: Optional[str] = None,
    session_filter: Optional[str] = None,
    since: Optional[datetime] = None,
    component_prefixes: Optional[Sequence[str]] = None,
) -> bool:
    """Check if a log line passes all active filters."""
    if since is not None:
        ts = _parse_line_timestamp(line)
        if ts is not None and ts < since:
            return False

    if min_level is not None:
        level = _extract_level(line)
        if level is not None:
            if _LEVEL_ORDER.get(level, 0) < _LEVEL_ORDER.get(min_level, 0):
                return False

    if session_filter is not None:
        if session_filter not in line:
            return False

    if component_prefixes is not None:
        if not _line_matches_component(line, component_prefixes):
            return False

    return True


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _format_age(mtime: datetime) -> str:
    age = datetime.now() - mtime
    seconds = age.total_seconds()
    if seconds < 60:
        return "agora mesmo"
    if seconds < 3600:
        return f"{int(seconds / 60)} min atrás"
    if seconds < 86400:
        return f"{int(seconds / 3600)} h atrás"
    return mtime.strftime("%Y-%m-%d %H:%M")


def _print_log_line(line: str) -> None:
    """Print one log line, highlighting severity when color is enabled."""
    from ector_cli.colors import Colors, color, should_use_color

    text = line.rstrip("\n")
    if not text:
        return
    if not should_use_color():
        print(text)
        return

    level = _extract_level(line)
    style_map = {
        "DEBUG": (Colors.DIM,),
        "WARNING": (Colors.YELLOW,),
        "ERROR": (Colors.RED,),
        "CRITICAL": (Colors.RED, Colors.BOLD),
    }
    styles = style_map.get(level or "")
    if styles:
        print(color(text, *styles))
    else:
        print(text)


def _print_log_header(
    *,
    log_name: str,
    filename: str,
    num_lines: int,
    follow: bool,
    filter_parts: Sequence[str],
) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right", no_wrap=True)
    grid.add_column()

    grid.add_row("Arquivo", f"{display_ector_home()}/logs/{filename}")
    grid.add_row("Origem", log_name)
    if follow:
        grid.add_row(
            "Modo",
            f"[{_ECTOR_ACCENT}]acompanhando[/{_ECTOR_ACCENT}] "
            "[dim](Ctrl+C para parar)[/dim]",
        )
    else:
        grid.add_row("Linhas", str(num_lines))
    if filter_parts:
        grid.add_row("Filtros", ", ".join(filter_parts))

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold {_ECTOR_ACCENT}]Logs[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(1, 2),
        ),
    )
    console.print()


def tail_log(
    log_name: str = "agent",
    *,
    num_lines: int = 50,
    follow: bool = False,
    level: Optional[str] = None,
    session: Optional[str] = None,
    since: Optional[str] = None,
    component: Optional[str] = None,
) -> None:
    """Read and display log lines, optionally following in real time.

    Parameters
    ----------
    log_name
        Which log to read: ``"agent"``, ``"errors"``, ``"gateway"``.
    num_lines
        Number of recent lines to show (before follow starts).
    follow
        If True, keep watching for new lines (Ctrl+C to stop).
    level
        Minimum log level to show (e.g. ``"WARNING"``).
    session
        Session ID substring to filter on.
    since
        Relative time string (e.g. ``"1h"``, ``"30m"``).
    component
        Component name to filter by (e.g. ``"gateway"``, ``"tools"``).
    """
    filename = LOG_FILES.get(log_name)
    if filename is None:
        print(f"Log desconhecido: {log_name!r}. Disponíveis: {', '.join(sorted(LOG_FILES))}")
        sys.exit(1)

    log_path = get_ector_home() / "logs" / filename
    if not log_path.exists():
        print(f"Arquivo de log não encontrado: {log_path}")
        print(f"(Logs são criados quando o Ector é executado — tente 'ector' primeiro)")
        sys.exit(1)

    # Parse --since into a datetime cutoff
    since_dt = None
    if since:
        since_dt = _parse_since(since)
        if since_dt is None:
            print(f"Valor inválido para --since: {since!r}. Use formatos como '1h', '30m', '2d'.")
            sys.exit(1)

    min_level = level.upper() if level else None
    if min_level and min_level not in _LEVEL_ORDER:
        print(f"Nível inválido para --level: {level!r}. Use DEBUG, INFO, WARNING, ERROR ou CRITICAL.")
        sys.exit(1)

    # Resolve component to logger name prefixes
    component_prefixes = None
    if component:
        from ector_logging import COMPONENT_PREFIXES
        component_lower = component.lower()
        if component_lower not in COMPONENT_PREFIXES:
            available = ", ".join(sorted(COMPONENT_PREFIXES))
            print(f"Componente desconhecido: {component!r}. Disponíveis: {available}")
            sys.exit(1)
        component_prefixes = COMPONENT_PREFIXES[component_lower]

    has_filters = (
        min_level is not None
        or session is not None
        or since_dt is not None
        or component_prefixes is not None
    )

    # Read and display the tail
    try:
        lines = _read_tail(log_path, num_lines, has_filters=has_filters,
                           min_level=min_level, session_filter=session,
                           since=since_dt, component_prefixes=component_prefixes)
    except PermissionError:
        print(f"Permissão negada: {log_path}")
        sys.exit(1)

    # Print header
    filter_parts = []
    if min_level:
        filter_parts.append(f"nível>={min_level}")
    if session:
        filter_parts.append(f"sessão={session}")
    if component:
        filter_parts.append(f"componente={component}")
    if since:
        filter_parts.append(f"desde={since}")

    _print_log_header(
        log_name=log_name,
        filename=filename,
        num_lines=num_lines,
        follow=follow,
        filter_parts=filter_parts,
    )

    for line in lines:
        _print_log_line(line)

    if not follow:
        return

    # Follow mode — poll for new content
    try:
        _follow_log(log_path, min_level=min_level, session_filter=session,
                     since=since_dt, component_prefixes=component_prefixes)
    except KeyboardInterrupt:
        from ector_cli.colors import Colors, color

        print(color("\nMonitoramento encerrado.", Colors.DIM))


def _read_tail(
    path: Path,
    num_lines: int,
    *,
    has_filters: bool = False,
    min_level: Optional[str] = None,
    session_filter: Optional[str] = None,
    since: Optional[datetime] = None,
    component_prefixes: Optional[Sequence[str]] = None,
) -> list:
    """Read the last *num_lines* matching lines from a log file.

    When filters are active, we read more raw lines to find enough matches.
    """
    if has_filters:
        # Read more lines to ensure we get enough after filtering.
        # For large files, read last 10K lines and filter down.
        raw_lines = _read_last_n_lines(path, max(num_lines * 20, 2000))
        filtered = [
            l for l in raw_lines
            if _matches_filters(l, min_level=min_level,
                                session_filter=session_filter, since=since,
                                component_prefixes=component_prefixes)
        ]
        return filtered[-num_lines:]
    else:
        return _read_last_n_lines(path, num_lines)


def _read_last_n_lines(path: Path, n: int) -> list:
    """Efficiently read the last N lines from a file.

    For files under 1MB, reads the whole file (fast, simple).
    For larger files, reads chunks from the end.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return []

        # For files up to 1MB, just read the whole thing — simple and correct.
        if size <= 1_048_576:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return all_lines[-n:]

        # For large files, read chunks from the end.
        with open(path, "rb") as f:
            chunk_size = 8192
            lines = []
            pos = size

            while pos > 0 and len(lines) <= n + 1:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                chunk_lines = chunk.split(b"\n")
                if lines:
                    # Merge the last partial line of the new chunk with the
                    # first partial line of what we already have.
                    lines[0] = chunk_lines[-1] + lines[0]
                    lines = chunk_lines[:-1] + lines
                else:
                    lines = chunk_lines
                chunk_size = min(chunk_size * 2, 65536)

            # Decode and return last N non-empty lines.
            decoded = []
            for raw in lines:
                if not raw.strip():
                    continue
                try:
                    decoded.append(raw.decode("utf-8", errors="replace") + "\n")
                except Exception:
                    decoded.append(raw.decode("latin-1") + "\n")
            return decoded[-n:]

    except Exception:
        # Fallback: read entire file
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return all_lines[-n:]


def _follow_log(
    path: Path,
    *,
    min_level: Optional[str] = None,
    session_filter: Optional[str] = None,
    since: Optional[datetime] = None,
    component_prefixes: Optional[Sequence[str]] = None,
) -> None:
    """Poll a log file for new content and print matching lines."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        # Seek to end
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                if _matches_filters(line, min_level=min_level,
                                    session_filter=session_filter, since=since,
                                    component_prefixes=component_prefixes):
                    _print_log_line(line)
                    sys.stdout.flush()
            else:
                time.sleep(0.3)


def list_logs() -> None:
    """Print available log files with sizes."""
    from rich import box
    from rich.console import Console
    from rich.table import Table

    log_dir = get_ector_home() / "logs"
    dhh = display_ector_home()
    console = Console()

    if not log_dir.exists():
        console.print()
        console.print(
            f"[dim]Nenhum diretório de logs em {dhh}/logs/[/dim]"
        )
        console.print(
            "[dim]Execute [bold]ector[/bold] para gerar logs.[/dim]"
        )
        console.print()
        return

    entries: list[tuple[str, int, datetime]] = []
    for entry in log_dir.iterdir():
        if entry.is_file() and entry.suffix == ".log":
            stat = entry.stat()
            entries.append((entry.name, stat.st_size, datetime.fromtimestamp(stat.st_mtime)))

    if not entries:
        console.print()
        console.print(
            f"[dim]Nenhum arquivo .log em {dhh}/logs/ ainda.[/dim]"
        )
        console.print(
            "[dim]Execute [bold]ector[/bold] para gerar logs.[/dim]"
        )
        console.print()
        return

    known_order = {name: idx for idx, name in enumerate(_LOG_META)}
    entries.sort(
        key=lambda row: (known_order.get(row[0], len(known_order)), row[0])
    )

    table = Table(
        title=f"[bold {_ECTOR_ACCENT}]Arquivos de log[/bold {_ECTOR_ACCENT}]",
        caption=f"[dim]{dhh}/logs/[/dim]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
        title_justify="left",
        caption_justify="left",
        border_style=_ECTOR_ACCENT,
    )
    table.add_column("Arquivo", style="bold", no_wrap=True, ratio=1, max_width=20)
    table.add_column("Tamanho", justify="right", no_wrap=True, min_width=10)
    table.add_column("Atualizado", no_wrap=True, min_width=16)
    table.add_column("Conteúdo", overflow="fold", ratio=3, style="dim")

    for name, size, mtime in entries:
        short = name.replace(".log", "")
        cmd_hint = short if short in LOG_FILES else name
        file_cell = f"[{_ECTOR_ACCENT}]{name}[/{_ECTOR_ACCENT}]"
        table.add_row(
            file_cell,
            _format_size(size),
            _format_age(mtime),
            _LOG_META.get(name, f"ector logs {cmd_hint}"),
        )

    console.print()
    console.print(table)
    console.print()
    console.print(
        "[dim]Ver: [bold]ector logs[/bold]  ·  "
        "[bold]ector logs -f[/bold]  ·  "
        "[bold]ector logs clear[/bold]  ·  "
        "[bold]ector logs --level WARNING[/bold][/dim]"
    )
    console.print()


def _resolve_log_paths(target: Optional[str] = None) -> list[Path]:
    """Return log file paths to truncate for *target* (None = all ``*.log``)."""
    log_dir = get_ector_home() / "logs"
    if target:
        name = target.strip().lower()
        if name not in LOG_FILES:
            available = ", ".join(sorted(LOG_FILES))
            raise ValueError(
                f"Log desconhecido: {target!r}. Disponíveis: {available}"
            )
        return [log_dir / LOG_FILES[name]]
    if not log_dir.is_dir():
        return []
    return sorted(p for p in log_dir.glob("*.log") if p.is_file())


def clear_logs(target: Optional[str] = None) -> None:
    """Truncate log file(s) under ``~/.ector/logs/``.

    Uses truncate (not delete) so processes with open handles keep writing.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    dhh = display_ector_home()
    console = Console()

    try:
        paths = _resolve_log_paths(target)
    except ValueError as exc:
        print(f"Erro: {exc}")
        sys.exit(1)

    if not paths:
        console.print()
        console.print(
            f"[dim]Nenhum arquivo .log para limpar em {dhh}/logs/[/dim]"
        )
        console.print()
        return

    cleared: list[tuple[str, int]] = []
    failed: list[tuple[str, str]] = []
    for path in paths:
        if not path.exists():
            continue
        size = path.stat().st_size
        try:
            path.open("w", encoding="utf-8").close()
            cleared.append((path.name, size))
        except OSError as exc:
            failed.append((path.name, str(exc)))

    if not cleared and not failed:
        console.print()
        console.print(
            f"[dim]Nenhum arquivo .log para limpar em {dhh}/logs/[/dim]"
        )
        console.print()
        return

    scope = target or "todos"
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right", no_wrap=True)
    grid.add_column()
    grid.add_row("Escopo", scope)
    grid.add_row("Pasta", f"{dhh}/logs/")
    if cleared:
        grid.add_row(
            "Limpos",
            f"[green]{len(cleared)}[/green] "
            f"([dim]{_format_size(sum(size for _, size in cleared))} liberados[/dim])",
        )
        names = ", ".join(name for name, _ in cleared)
        grid.add_row("Arquivos", names)
    if failed:
        grid.add_row("Falhas", f"[red]{len(failed)}[/red]")

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold {_ECTOR_ACCENT}]Logs limpos[/bold {_ECTOR_ACCENT}]",
            border_style=_ECTOR_ACCENT,
            padding=(1, 2),
        ),
    )

    if failed:
        console.print()
        for name, err in failed:
            console.print(f"[red]✖[/red] {name}: {err}")

    console.print()
    console.print(
        "[dim]Listar: [bold]ector logs list[/bold]  ·  "
        "Ver: [bold]ector logs[/bold][/dim]"
    )
    console.print()
