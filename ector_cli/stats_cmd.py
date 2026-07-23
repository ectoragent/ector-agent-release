"""``ector stats`` — Rich usage analytics output."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ector_constants import display_ector_home

from agent.stats import _bar_chart, _format_duration

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

_DAY_LABELS = {
    "Mon": "Seg",
    "Tue": "Ter",
    "Wed": "Qua",
    "Thu": "Qui",
    "Fri": "Sex",
    "Sat": "Sáb",
    "Sun": "Dom",
}

_NOTABLE_LABELS = {
    "Longest session": "Sessão mais longa",
    "Most messages": "Mais mensagens",
    "Most tokens": "Mais tokens",
    "Most tool calls": "Mais ferramentas",
}


def _source_label(source: str) -> str:
    key = (source or "").strip().lower()
    return _SOURCE_LABELS.get(key, key or "—")


def _format_period_title(days: int, source: Optional[str] = None) -> str:
    title = f"[bold {_ECTOR_ACCENT}]Stats[/bold {_ECTOR_ACCENT}]"
    meta = [f"últimos {days} dias"]
    if source:
        meta.append(f"origem={source}")
    return f"{title} [dim]({', '.join(meta)})[/dim]"


def _format_date(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


def _make_table(title: str):
    from rich.table import Table

    return Table(
        title=f"[bold {_ECTOR_ACCENT}]{title}[/bold {_ECTOR_ACCENT}]",
        box=None,
        show_header=True,
        show_lines=False,
        header_style="bold",
        expand=False,
        padding=(0, 1),
        title_justify="left",
    )


def _name_column(width: int = 32) -> dict:
    return {"overflow": "ellipsis", "max_width": width, "no_wrap": True}


def _num_column(width: int = 10) -> dict:
    return {"justify": "right", "no_wrap": True, "width": width}


def _print_section_spacer(console) -> None:
    console.print()


def _localize_notable_value(value: str) -> str:
    return (
        value.replace(" calls", " chamadas")
        .replace(" msgs", " msgs")
    )


def _print_key_value_section(console, title: str, rows: Sequence[Tuple[str, str]]) -> None:
    if not rows:
        return
    from rich.table import Table

    _print_section_spacer(console)
    console.print(f"[bold {_ECTOR_ACCENT}]{title}[/bold {_ECTOR_ACCENT}]")
    kv = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    kv.add_column(style="dim", no_wrap=True, width=28)
    kv.add_column(justify="right", no_wrap=False, min_width=12)
    for label, value in rows:
        kv.add_row(label, value)
    console.print(kv)


def _print_data_table(
    console,
    title: str,
    columns: Sequence[Tuple[str, dict]],
    rows: Iterable[Sequence[Any]],
) -> None:
    _print_section_spacer(console)
    table = _make_table(title)
    for name, opts in columns:
        table.add_column(name, **opts)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    console.print(table)


def _overview_rows(overview: Dict[str, Any]) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = [
        ("Sessões", f"{overview['total_sessions']:,}"),
        ("Mensagens", f"{overview['total_messages']:,}"),
        ("Chamadas de ferramentas", f"{overview['total_tool_calls']:,}"),
        ("Mensagens do utilizador", f"{overview['user_messages']:,}"),
        ("Tokens de entrada", f"{overview['total_input_tokens']:,}"),
        ("Tokens de saída", f"{overview['total_output_tokens']:,}"),
        ("Total de tokens", f"{overview['total_tokens']:,}"),
    ]

    cache_read = overview.get("total_cache_read_tokens") or 0
    cache_write = overview.get("total_cache_write_tokens") or 0
    if cache_read or cache_write:
        rows.append(("Cache (leitura / escrita)", f"{cache_read:,} / {cache_write:,}"))

    if overview.get("total_hours", 0) > 0:
        rows.append(
            (
                "Tempo ativo",
                f"~{_format_duration(overview['total_hours'] * 3600)} "
                f"[dim](média por sessão: ~{_format_duration(overview['avg_session_duration'])})[/dim]",
            )
        )

    rows.append(("Média msgs/sessão", f"{overview['avg_messages_per_session']:.1f}"))

    estimated = overview.get("estimated_cost") or 0.0
    actual = overview.get("actual_cost") or 0.0
    if estimated > 0 or actual > 0:
        if actual > 0:
            cost = f"US$ {actual:.2f} (real)"
        else:
            cost = f"~US$ {estimated:.2f} (estimado)"
        unknown = overview.get("unknown_cost_sessions") or 0
        if unknown:
            cost += f" [dim]· {unknown} sessão(ões) sem preço conhecido[/dim]"
        rows.append(("Custo", cost))

    return rows


def print_stats_report(report: Dict[str, Any]) -> None:
    """Render ``ector stats`` with Rich tables."""
    from rich.console import Console

    console = Console()
    days = report.get("days", 30)
    source = report.get("source_filter")
    store_hint = f"{display_ector_home()}/state.db"

    console.print()
    console.print(_format_period_title(days, source))

    if report.get("empty"):
        if source:
            console.print(
                f"[dim]Nenhuma sessão com origem[/dim] [bold]{source}[/bold] "
                f"[dim]nos últimos {days} dias.[/dim]"
            )
        else:
            console.print(f"[dim]Nenhuma sessão nos últimos {days} dias.[/dim]")
        console.print(f"[dim]{store_hint}[/dim]")
        console.print(
            "[dim]Use [bold]ector[/bold] "
            "para gerar histórico analisável.[/dim]"
        )
        console.print(
            "[dim]Período: [bold]ector stats --days 7[/bold]  ·  "
            "Origem: [bold]ector stats --source web[/bold][/dim]"
        )
        console.print()
        return

    overview = report["overview"]
    if overview.get("date_range_start") and overview.get("date_range_end"):
        start = _format_date(overview["date_range_start"])
        end = _format_date(overview["date_range_end"])
        console.print(f"[dim]Período analisado: {start} — {end}[/dim]")
        console.print(f"[dim]{store_hint}[/dim]")
        console.print()

    _print_key_value_section(console, "Resumo", _overview_rows(overview))

    models = report.get("models") or []
    if models:
        _print_data_table(
            console,
            "Modelos",
            [
                ("Modelo", _name_column(36)),
                ("Sessões", _num_column(8)),
                ("Tokens", _num_column(12)),
            ],
            (
                (m["model"][:40], f"{m['sessions']:,}", f"{m['total_tokens']:,}")
                for m in models
            ),
        )

    platforms = report.get("platforms") or []
    if len(platforms) > 1 or (platforms and platforms[0].get("platform") != "cli"):
        _print_data_table(
            console,
            "Plataformas",
            [
                ("Plataforma", {"no_wrap": True, "width": 12}),
                ("Sessões", _num_column(8)),
                ("Mensagens", _num_column(10)),
                ("Tokens", _num_column(12)),
            ],
            (
                (
                    _source_label(p["platform"]),
                    f"{p['sessions']:,}",
                    f"{p['messages']:,}",
                    f"{p['total_tokens']:,}",
                )
                for p in platforms
            ),
        )

    tools = report.get("tools") or []
    if tools:
        rows = [
            (t["tool"][:32], f"{t['count']:,}", f"{t['percentage']:.1f}%")
            for t in tools[:15]
        ]
        _print_data_table(
            console,
            "Ferramentas mais usadas",
            [
                ("Ferramenta", _name_column(28)),
                ("Chamadas", _num_column(8)),
                ("%", _num_column(7)),
            ],
            rows,
        )
        if len(tools) > 15:
            console.print(f"[dim]  … e mais {len(tools) - 15} ferramenta(s)[/dim]")

    skills = report.get("skills") or {}
    top_skills = skills.get("top_skills") or []
    if top_skills:
        skill_rows = []
        for skill in top_skills[:10]:
            last_used = "—"
            if skill.get("last_used_at"):
                last_used = datetime.fromtimestamp(skill["last_used_at"]).strftime("%d/%m")
            skill_rows.append(
                (
                    skill["skill"][:32],
                    f"{skill['view_count']:,}",
                    f"{skill['manage_count']:,}",
                    last_used,
                )
            )
        _print_data_table(
            console,
            "Skills",
            [
                ("Skill", _name_column(28)),
                ("Leituras", _num_column(8)),
                ("Edições", _num_column(8)),
                ("Último uso", {"justify": "right", "no_wrap": True, "width": 10}),
            ],
            skill_rows,
        )
        summary = skills.get("summary") or {}
        console.print(
            "[dim]  "
            f"{summary.get('distinct_skills_used', 0)} skill(s) distintas · "
            f"{summary.get('total_skill_loads', 0):,} leituras · "
            f"{summary.get('total_skill_edits', 0):,} edições[/dim]"
        )

    activity = report.get("activity") or {}
    if activity.get("by_day"):
        day_values = [d["count"] for d in activity["by_day"]]
        bars = _bar_chart(day_values, max_width=18)
        _print_section_spacer(console)
        act_table = _make_table("Atividade")
        act_table.add_column("Dia", no_wrap=True, width=4)
        act_table.add_column("Distribuição", no_wrap=True, width=20, style=_ECTOR_ACCENT)
        act_table.add_column("Sessões", justify="right", no_wrap=True, width=8)
        for idx, day in enumerate(activity["by_day"]):
            act_table.add_row(
                _DAY_LABELS.get(day["day"], day["day"]),
                bars[idx] or "[dim]·[/dim]",
                str(day["count"]),
            )
        console.print(act_table)

        busy_hours = sorted(activity.get("by_hour") or [], key=lambda x: x["count"], reverse=True)
        busy_hours = [h for h in busy_hours if h["count"] > 0][:5]
        if busy_hours:
            hour_bits = [f"{h['hour']:02d}h ({h['count']})" for h in busy_hours]
            console.print(f"[dim]  Horários de pico: {', '.join(hour_bits)}[/dim]")
        if activity.get("active_days"):
            console.print(f"[dim]  Dias ativos: {activity['active_days']}[/dim]")
        if activity.get("max_streak", 0) > 1:
            console.print(
                f"[dim]  Maior sequência: {activity['max_streak']} dias seguidos[/dim]"
            )

    notable = report.get("top_sessions") or []
    if notable:
        _print_data_table(
            console,
            "Destaques",
            [
                ("Tipo", {"no_wrap": True, "width": 20}),
                ("Valor", {"no_wrap": True, "width": 18}),
                ("Data", {"no_wrap": True, "width": 8}),
                ("ID", {"style": "dim cyan", "overflow": "ellipsis", "max_width": 20}),
            ],
            (
                (
                    _NOTABLE_LABELS.get(item["label"], item["label"]),
                    _localize_notable_value(item["value"]),
                    item["date"],
                    item["session_id"],
                )
                for item in notable
            ),
        )

    console.print(
        "[dim]Filtrar: [bold]ector stats --days 7[/bold]  ·  "
        "[bold]ector stats --source web[/bold]  ·  "
        "[bold]ector sessions list[/bold][/dim]"
    )
    console.print()
