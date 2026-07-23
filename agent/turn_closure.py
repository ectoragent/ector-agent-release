"""Deterministic turn-closure markdown when the agent stops without a final response."""

from __future__ import annotations

import json
import re
from typing import Any

from agent.tool_result_status import infer_tool_failed, tool_failure_message

_CANCELLED_PREFIX = re.compile(
    r"^\[Tool execution cancelled",
    re.IGNORECASE,
)

_TOOL_DESCRIPTION_KEYS = ("description", "command", "path", "query", "url")


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
    return {}


def _tool_label(tool_name: str, args_raw: Any) -> str:
    args = _parse_args(args_raw)
    for key in _TOOL_DESCRIPTION_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    name = (tool_name or "ferramenta").strip()
    return name or "ferramenta"


_OPTIONAL_FAILURE_TOOLS = frozenset({"browser_snapshot", "browser_vision"})


def _is_optional_failure_tool(name: str) -> bool:
    return (name or "").strip().lower() in _OPTIONAL_FAILURE_TOOLS


def _is_only_optional_failures(
    failed_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
) -> bool:
    if not failed_rows:
        return False
    if not all(
        _is_optional_failure_tool(str(row.get("name") or "")) for row in failed_rows
    ):
        return False
    return any(
        _classify_row(row) == "completed"
        and not _is_optional_failure_tool(str(row.get("name") or ""))
        and str(row.get("result") or "").strip()
        for row in all_rows
    )


def _optional_failure_display_label(row: dict[str, Any]) -> str:
    name = (row.get("name") or "").strip().lower()
    if name == "browser_snapshot":
        return "Screenshot do browser"
    if name == "browser_vision":
        return "Visão do browser"
    return str(row.get("label") or row.get("name") or "ação")


def _build_partial_optional_failure_message(
    failed_optional: list[dict[str, Any]],
    completed: list[str],
) -> str | None:
    if not failed_optional:
        return None
    optional_labels = [_optional_failure_display_label(row) for row in failed_optional]
    meaningful_completed = [label for label in completed if _is_meaningful_label(label)]
    success_part = (
        ", ".join(meaningful_completed) if meaningful_completed else "outra verificação"
    )

    reasons: list[str] = []
    for row in failed_optional:
        reason = tool_failure_message(str(row.get("name") or ""), row.get("result"))
        if reason:
            reasons.append(reason)

    headline = f"**{optional_labels[0]} indisponível; {success_part} concluída.**"
    if reasons:
        headline = (
            f"**{optional_labels[0]} indisponível** ({reasons[0]}); "
            f"**{success_part} concluída.**"
        )
    return headline


def _collect_turn_tool_rows(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect tool calls from the trailing assistant+tool block of the turn."""
    if not messages:
        return []

    results_by_id: dict[str, str] = {}
    for msg in reversed(messages):
        if msg.get("role") == "tool":
            tc_id = str(msg.get("tool_call_id") or "")
            if tc_id:
                results_by_id[tc_id] = str(msg.get("content") or "")
            continue
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            rows: list[dict[str, Any]] = []
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                tc_id = str(tc.get("id") or "")
                name = str(fn.get("name") or msg.get("tool_name") or "tool")
                args = fn.get("arguments") or ""
                content = results_by_id.get(tc_id, "")
                rows.append(
                    {
                        "id": tc_id,
                        "name": name,
                        "args": args,
                        "result": content,
                        "label": _tool_label(name, args),
                    }
                )
            return rows
        break
    return []


def _classify_row(row: dict[str, Any]) -> str:
    result = str(row.get("result") or "")
    if not result.strip():
        return "pending"
    if _CANCELLED_PREFIX.search(result.strip()):
        return "cancelled"
    if infer_tool_failed(str(row.get("name") or ""), result):
        return "failed"
    return "completed"


def _parse_result_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
    return {}


def _find_successful_process_wait(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for row in reversed(rows):
        if (row.get("name") or "").strip().lower() != "process":
            continue
        args = _parse_args(row.get("args"))
        if str(args.get("action") or "").strip().lower() != "wait":
            continue
        result = _parse_result_json(row.get("result"))
        if result.get("status") == "exited" and result.get("exit_code") == 0:
            return row
    return None


def _is_meaningful_label(label: str) -> bool:
    lowered = label.strip().lower()
    return lowered not in ("terminal", "shell", "process", "tool", "ferramenta", "")


def _build_all_success_message(completed: list[str]) -> str | None:
    meaningful = [label for label in completed if _is_meaningful_label(label)]
    if not meaningful:
        return None
    if len(meaningful) == 1:
        return f"**{meaningful[0]} concluído.**"
    items = "\n".join(f"- {label}" for label in meaningful)
    return f"**Concluí as seguintes ações:**\n\n{items}"


def _build_process_wait_success_message(
    rows: list[dict[str, Any]],
    wait_row: dict[str, Any],
) -> str:
    for row in rows:
        name = (row.get("name") or "").strip().lower()
        if name not in ("terminal", "shell"):
            continue
        label = str(row.get("label") or "").strip()
        if label and label.lower() not in ("terminal", "shell", "process"):
            return f"**{label} concluído com sucesso.**"

    output = str(_parse_result_json(wait_row.get("result")).get("output") or "")
    if "BUILD SUCCESSFUL" in output.upper():
        match = re.search(r"BUILD SUCCESSFUL[^\n]*", output, re.IGNORECASE)
        detail = match.group(0).strip() if match else ""
        if detail:
            return f"**Build concluído com sucesso.**\n\n`{detail}`"
        return "**Build concluído com sucesso.**"

    return "**Processo em segundo plano concluído com sucesso.**"


def _interrupt_resume_hint(rows: list[dict[str, Any]]) -> str:
    shell_stuck = any(
        _classify_row(row) in ("failed", "cancelled")
        and (str(row.get("name") or "").strip().lower() in ("terminal", "shell"))
        for row in rows
    )
    if shell_stuck:
        return (
            "Para retomar: posso continuar com **comandos menores e escopados** "
            "(um diretório por vez), usar **background=true** com notify_on_complete "
            "para varreduras longas, ou trocar a abordagem (ex. `du -sh ~/Library` "
            "em vez de `du ~/.*`). Como prefere seguir?"
        )
    return (
        "Posso retomar de onde parou, tentar outra abordagem ou verificar o que restou — "
        "como prefere seguir?"
    )


def build_turn_closure_markdown(
    messages: list[dict[str, Any]],
    *,
    interrupted: bool = False,
) -> str | None:
    """Build a user-facing summary when the turn ends without assistant text."""
    rows = _collect_turn_tool_rows(messages)
    if not rows:
        return None

    completed: list[str] = []
    failed: list[str] = []
    cancelled: list[str] = []
    pending: list[str] = []

    for row in rows:
        label = str(row.get("label") or row.get("name") or "ação")
        bucket = _classify_row(row)
        if bucket == "completed":
            completed.append(label)
        elif bucket == "failed":
            reason = tool_failure_message(str(row.get("name") or ""), row.get("result"))
            failed.append(f"{label} ({reason})" if reason else label)
        elif bucket == "cancelled":
            cancelled.append(label)
        else:
            pending.append(label)

    if not failed and not cancelled and not pending and not interrupted:
        wait_row = _find_successful_process_wait(rows)
        if wait_row:
            return _build_process_wait_success_message(rows, wait_row)
        return _build_all_success_message(completed)

    failed_rows = [row for row in rows if _classify_row(row) == "failed"]
    if (
        not interrupted
        and not cancelled
        and not pending
        and _is_only_optional_failures(failed_rows, rows)
    ):
        partial = _build_partial_optional_failure_message(failed_rows, completed)
        if partial:
            return partial

    parts: list[str] = []
    if interrupted:
        parts.append("**Turno interrompido.**")
    elif failed or cancelled:
        parts.append("**Algumas ações não foram concluídas.**")

    if completed:
        parts.append(f"- Concluído: {', '.join(completed)}")
    if failed:
        parts.append(f"- Falhou: {', '.join(failed)}")
    if cancelled:
        parts.append(f"- Cancelado: {', '.join(cancelled)}")
    if pending:
        parts.append(f"- Pendente: {', '.join(pending)}")

    if interrupted or failed or cancelled:
        parts.append(_interrupt_resume_hint(rows))

    body = "\n".join(parts).strip()
    return body or None
