"""Layout compartilhado para comandos ``list`` do CLI Ector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

LIST_PRIMARY = "#2DD8FC"
LIST_BORDER = "#A8A29E"


@dataclass(frozen=True)
class ListColumn:
    header: str
    style: str = ""
    ratio: int = 1
    min_width: int | None = None
    width: int | None = None
    no_wrap: bool = False
    overflow: str | None = None
    justify: str = "left"


def print_list_heading(
    console: Console,
    title: str,
    *,
    subtitle: str = "",
    primary: str = LIST_PRIMARY,
) -> None:
    console.print()
    if subtitle:
        console.print(f"[bold {primary}]{title}[/] [dim]{subtitle}[/]")
    else:
        console.print(f"[bold {primary}]{title}[/]")


def print_list_empty(
    console: Console,
    title: str,
    message: str = "Nenhuma encontrada.",
    *,
    primary: str = LIST_PRIMARY,
    hint: str = "",
) -> None:
    body = f"[dim]{message}[/]"
    if hint:
        body = f"{body}\n{hint}"
    console.print()
    console.print(
        Panel(
            body,
            border_style=primary,
            padding=(0, 1),
            title=f"[bold {primary}]{title}[/]",
        )
    )
    console.print()


def build_list_table(
    columns: Sequence[ListColumn],
    *,
    primary: str = LIST_PRIMARY,
) -> Table:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {primary}",
        expand=True,
        padding=(0, 1),
        border_style=LIST_BORDER,
    )
    for col in columns:
        kwargs: dict[str, Any] = {
            "no_wrap": col.no_wrap,
            "ratio": col.ratio,
            "justify": col.justify,
        }
        if col.style:
            kwargs["style"] = col.style
        if col.min_width is not None:
            kwargs["min_width"] = col.min_width
        if col.width is not None:
            kwargs["width"] = col.width
        if col.overflow:
            kwargs["overflow"] = col.overflow
        table.add_column(col.header, **kwargs)
    return table


def print_list_section(
    console: Console,
    *,
    title: str,
    columns: Sequence[ListColumn],
    rows: Sequence[Sequence[str]],
    primary: str = LIST_PRIMARY,
    show_count: bool = True,
) -> None:
    if not rows:
        return

    table = build_list_table(columns, primary=primary)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])

    console.print()
    if show_count:
        console.print(f"[bold {primary}]{title}[/] [dim]({len(rows)})[/]")
    else:
        console.print(f"[bold {primary}]{title}[/]")
    console.print(table)


def print_list_summary(
    console: Console,
    body: str,
    *,
    title: str = "Resumo",
    primary: str = LIST_PRIMARY,
) -> None:
    console.print(
        Panel(
            body,
            border_style=LIST_BORDER,
            padding=(0, 1),
            title=f"[bold {primary}]{title}[/]",
        )
    )
    console.print()


def print_list_footer(console: Console, body: str) -> None:
    if body.strip():
        console.print(body)


def render_list_page(
    console: Console,
    *,
    title: str,
    subtitle: str = "",
    sections: Iterable[tuple[str, Sequence[ListColumn], Sequence[Sequence[str]]]],
    summary: str = "",
    footer: str = "",
    empty_message: str = "",
    empty_hint: str = "",
    primary: str = LIST_PRIMARY,
) -> bool:
    """Renderiza página de lista com seções. Retorna False se vazia."""
    section_list = [(t, cols, rows) for t, cols, rows in sections if rows]
    total = sum(len(rows) for _, _, rows in section_list)

    if total == 0:
        print_list_empty(
            console,
            title,
            empty_message or "Nenhuma encontrada.",
            primary=primary,
            hint=empty_hint,
        )
        return False

    print_list_heading(console, title, subtitle=subtitle, primary=primary)
    for section_title, columns, rows in section_list:
        print_list_section(
            console,
            title=section_title,
            columns=columns,
            rows=rows,
            primary=primary,
        )
    if summary:
        print_list_summary(console, summary, primary=primary)
    print_list_footer(console, footer)
    return True
