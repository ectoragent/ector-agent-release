"""Central slash-command resolution (registry, quick commands, plugins, skills, prefixes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedSlash:
    raw: str
    base: str  # first token without leading /
    arg: str
    canonical: str


def parse_slash(command: str) -> ParsedSlash:
    """Parse ``/foo bar`` into base token, argument tail, and registry canonical name."""
    raw = (command or "").strip()
    lower = raw.lower()
    base = lower.split()[0].lstrip("/") if lower else ""
    arg = raw.split(None, 1)[1].strip() if raw.split(None, 1)[1:] else ""

    from ector_cli.commands import resolve_command

    cmd_def = resolve_command(base) if base else None
    canonical = cmd_def.name if cmd_def else base
    return ParsedSlash(raw=raw, base=base, arg=arg, canonical=canonical)


def expand_command_prefix(typed_base: str, *, include_skills: bool = True) -> str | list[str] | None:
    """Expand ambiguous slash prefixes the same way ``EctorCLI.process_command`` does.

    Returns:
        - full command string to redispatch when uniquely expanded
        - list of matches when ambiguous
        - None when unknown / already exact with no handler
    """
    typed = typed_base.lower().lstrip("/")
    if not typed:
        return None

    from ector_cli.commands import COMMANDS

    skill_cmds: set[str] = set()
    if include_skills:
        try:
            from agent.skill_commands import scan_skill_commands

            skill_cmds = {k.lstrip("/") for k in scan_skill_commands()}
        except Exception:
            skill_cmds = set()

    all_known = {k.lstrip("/") for k in COMMANDS} | skill_cmds
    matches = [c for c in all_known if c.startswith(typed)]
    if len(matches) > 1:
        exact = [c for c in matches if c == typed]
        if len(exact) == 1:
            matches = exact
        else:
            min_len = min(len(c) for c in matches)
            shortest = [c for c in matches if len(c) == min_len]
            if len(shortest) == 1:
                matches = shortest
    if len(matches) == 1 and matches[0] != typed:
        return f"/{matches[0]}"
    if len(matches) > 1:
        return sorted(matches)
    return None


def resolve_quick_command(name: str, config: dict[str, Any]) -> dict | None:
    qcmds = config.get("quick_commands", {}) or {}
    if not isinstance(qcmds, dict):
        return None
    return qcmds.get(name)


def resolve_plugin_handler(name: str):
    try:
        from ector_cli.plugins import get_plugin_command_handler

        return get_plugin_command_handler(name)
    except Exception:
        return None


def resolve_skill_message(name: str, arg: str, *, task_id: str = "") -> dict | None:
    try:
        from agent.skill_commands import (
            build_skill_invocation_message,
            scan_skill_commands,
        )

        key = f"/{name.lstrip('/')}"
        cmds = scan_skill_commands()
        if key not in cmds:
            return None
        msg = build_skill_invocation_message(key, arg, task_id=task_id)
        if not msg:
            return None
        return {"message": msg, "name": cmds[key].get("name", name)}
    except Exception:
        return None
