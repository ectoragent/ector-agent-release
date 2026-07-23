"""
Cron subcommand for ector CLI.

Handles standalone cron management commands like list, create, edit,
pause/resume/run/remove, status, and tick.
"""

import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from ector_cli.colors import Colors, color


def _normalize_skills(single_skill=None, skills: Optional[Iterable[str]] = None) -> Optional[List[str]]:
    if skills is None:
        if single_skill is None:
            return None
        raw_items = [single_skill]
    else:
        raw_items = list(skills)

    normalized: List[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _cron_api(**kwargs):
    from tools.cronjob_tools import cronjob as cronjob_tool

    return json.loads(cronjob_tool(**kwargs))


def cron_list(show_all: bool = False):
    """List all scheduled jobs."""
    from cron.jobs import list_jobs
    from rich.console import Console

    from ector_cli.list_format import LIST_PRIMARY, ListColumn, render_list_page

    jobs = list_jobs(include_disabled=show_all)
    console = Console()

    if not jobs:
        render_list_page(
            console,
            title="Tarefas agendadas",
            sections=[],
            empty_message="Nenhuma tarefa agendada.",
            empty_hint="[dim]Crie com[/] [bold]ector cron create[/] [dim]ou[/] [bold]/cron[/] [dim]no chat.[/]",
            primary=LIST_PRIMARY,
        )
        return

    rows = []
    active_n = 0
    paused_n = 0
    for job in jobs:
        job_id = job.get("id", "?")
        name = job.get("name", "(sem nome)")
        schedule = job.get("schedule_display", job.get("schedule", {}).get("value", "?"))
        state = job.get("state", "agendada" if job.get("enabled", True) else "pausada")
        next_run = job.get("next_run_at", "?")

        if state == "pausada":
            status = "[yellow]Pausada[/]"
            paused_n += 1
        elif state == "concluída":
            status = "[blue]Concluída[/]"
        elif job.get("enabled", True):
            status = "[green]Ativa[/]"
            active_n += 1
        else:
            status = "[red]Desabilitada[/]"
            paused_n += 1

        rows.append((str(job_id), name, str(schedule), status, str(next_run)))

    render_list_page(
        console,
        title="Tarefas agendadas",
        sections=[
            (
                "Jobs",
                (
                    ListColumn("ID", style="dim", no_wrap=True, min_width=8, ratio=1),
                    ListColumn("Nome", style=f"bold {LIST_PRIMARY}", ratio=2),
                    ListColumn("Agenda", style="dim", overflow="fold", ratio=2),
                    ListColumn("Estado", no_wrap=True, min_width=12, ratio=1),
                    ListColumn("Próxima exec.", style="dim", no_wrap=True, min_width=14, ratio=1),
                ),
                rows,
            )
        ],
        summary=f"[dim]{active_n} ativa(s) · {paused_n} pausada(s)/desabilitada(s)[/]",
        footer="[dim]Gerir:[/] [bold]ector cron edit|pause|resume|run|remove <id>[/]",
        primary=LIST_PRIMARY,
    )

    from ector_cli.gateway import find_gateway_pids
    if not find_gateway_pids():
        print(color("  ▲  O Gateway não está em execução — as tarefas não iniciarão automaticamente.", Colors.YELLOW))
        print(color("     Instale-o com: ector gateway install", Colors.DIM))
        print(color("                    sudo ector gateway install --system  # Servidores Linux", Colors.DIM))
        print()


def cron_tick():
    """Run due jobs once and exit."""
    from cron.scheduler import tick
    tick(verbose=True)


def cron_status():
    """Show cron execution status."""
    from cron.jobs import list_jobs
    from ector_cli.gateway import find_gateway_pids

    print()

    pids = find_gateway_pids()
    if pids:
        print(color("✔ Gateway em execução — as tarefas agendadas iniciarão automaticamente", Colors.GREEN))
        print(f"  PID: {', '.join(map(str, pids))}")
    else:
        print(color("✖ Gateway não está em execução — as tarefas NÃO iniciarão", Colors.RED))
        print()
        print("  Para habilitar a execução automática:")
        print("    ector gateway install    # Instalar como serviço de usuário")
        print("    sudo ector gateway install --system  # Servidores Linux: serviço de sistema no boot")
        print("    ector gateway            # Ou execute em primeiro plano")

    print()

    jobs = list_jobs(include_disabled=False)
    if jobs:
        next_runs = [j.get("next_run_at") for j in jobs if j.get("next_run_at")]
        print(f"  {len(jobs)} tarefa(s) ativa(s)")
        if next_runs:
            print(f"  Próxima execução: {min(next_runs)}")
    else:
        print("  Nenhuma tarefa ativa")

    print()


def cron_create(args):
    result = _cron_api(
        action="create",
        schedule=args.schedule,
        prompt=args.prompt,
        name=getattr(args, "name", None),
        deliver=getattr(args, "deliver", None),
        repeat=getattr(args, "repeat", None),
        skill=getattr(args, "skill", None),
        skills=_normalize_skills(getattr(args, "skill", None), getattr(args, "skills", None)),
        script=getattr(args, "script", None),
        workdir=getattr(args, "workdir", None),
    )
    if not result.get("success"):
        print(color(f"Falha ao criar tarefa: {result.get('error', 'erro desconhecido')}", Colors.RED))
        return 1
    print(color(f"Tarefa criada: {result['job_id']}", Colors.GREEN))
    print(f"  Nome: {result['name']}")
    print(f"  Agenda: {result['schedule']}")
    if result.get("skills"):
        print(f"  Habilidades: {', '.join(result['skills'])}")
    job_data = result.get("job", {})
    if job_data.get("script"):
        print(f"  Script: {job_data['script']}")
    if job_data.get("workdir"):
        print(f"  Workdir: {job_data['workdir']}")
    print(f"  Próxima execução: {result['next_run_at']}")
    return 0


def cron_edit(args):
    from cron.jobs import get_job

    job = get_job(args.job_id)
    if not job:
        print(color(f"Tarefa não encontrada: {args.job_id}", Colors.RED))
        return 1

    existing_skills = list(job.get("skills") or ([] if not job.get("skill") else [job.get("skill")]))
    replacement_skills = _normalize_skills(getattr(args, "skill", None), getattr(args, "skills", None))
    add_skills = _normalize_skills(None, getattr(args, "add_skills", None)) or []
    remove_skills = set(_normalize_skills(None, getattr(args, "remove_skills", None)) or [])

    final_skills = None
    if getattr(args, "clear_skills", False):
        final_skills = []
    elif replacement_skills is not None:
        final_skills = replacement_skills
    elif add_skills or remove_skills:
        final_skills = [skill for skill in existing_skills if skill not in remove_skills]
        for skill in add_skills:
            if skill not in final_skills:
                final_skills.append(skill)

    result = _cron_api(
        action="update",
        job_id=args.job_id,
        schedule=getattr(args, "schedule", None),
        prompt=getattr(args, "prompt", None),
        name=getattr(args, "name", None),
        deliver=getattr(args, "deliver", None),
        repeat=getattr(args, "repeat", None),
        skills=final_skills,
        script=getattr(args, "script", None),
        workdir=getattr(args, "workdir", None),
    )
    if not result.get("success"):
        print(color(f"Falha ao atualizar tarefa: {result.get('error', 'erro desconhecido')}", Colors.RED))
        return 1

    updated = result["job"]
    print(color(f"Tarefa atualizada: {updated['job_id']}", Colors.GREEN))
    print(f"  Nome: {updated['name']}")
    print(f"  Agenda: {updated['schedule']}")
    if updated.get("skills"):
        print(f"  Habilidades: {', '.join(updated['skills'])}")
    else:
        print("  Habilidades: nenhuma")
    if updated.get("script"):
        print(f"  Script: {updated['script']}")
    if updated.get("workdir"):
        print(f"  Workdir: {updated['workdir']}")
    return 0


def _job_action(action: str, job_id: str, success_verb: str) -> int:
    result = _cron_api(action=action, job_id=job_id)
    if not result.get("success"):
        print(color(f"Falha ao {action} tarefa: {result.get('error', 'erro desconhecido')}", Colors.RED))
        return 1
    job = result.get("job") or result.get("removed_job") or {}
    print(color(f"{success_verb} tarefa: {job.get('name', job_id)} ({job_id})", Colors.GREEN))
    if action in {"resume", "run"} and result.get("job", {}).get("next_run_at"):
        print(f"  Próxima execução: {result['job']['next_run_at']}")
    if action == "run":
        print("  Ela será executada no próximo ciclo do agendador.")
    return 0


def cron_command(args):
    """Handle cron subcommands."""
    subcmd = getattr(args, 'cron_command', None)

    if subcmd is None or subcmd == "list":
        show_all = getattr(args, 'all', False)
        cron_list(show_all)
        return 0

    if subcmd == "status":
        cron_status()
        return 0

    if subcmd == "tick":
        cron_tick()
        return 0

    if subcmd in {"create", "add"}:
        return cron_create(args)

    if subcmd == "edit":
        return cron_edit(args)

    if subcmd == "pause":
        return _job_action("pause", args.job_id, "Pausada")

    if subcmd == "resume":
        return _job_action("resume", args.job_id, "Retomada")

    if subcmd == "run":
        return _job_action("run", args.job_id, "Disparada")

    if subcmd in {"remove", "rm", "delete"}:
        return _job_action("remove", args.job_id, "Removida")

    print(f"Comando cron desconhecido: {subcmd}")
    print("Uso: ector cron [list|create|edit|pause|resume|run|remove|status|tick]")
    sys.exit(1)
