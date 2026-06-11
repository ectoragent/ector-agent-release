"""Infer tool failure from raw result strings (mirrors dashboard formatToolResult)."""

from __future__ import annotations

import json
import re
from typing import Any

_DELEGATE_FAILURE_STATUSES = frozenset(
    {"failed", "error", "interrupted", "timeout"}
)

_LEGACY_PROCESS_NOT_FOUND = re.compile(
    r"^No process with ID (proc_[\w]+)$",
    re.IGNORECASE,
)


def _humanize_tool_error(message: str) -> str:
    """Normaliza mensagens legadas em inglês para pt-BR."""
    trimmed = (message or "").strip()
    if not trimmed:
        return trimmed

    match = _LEGACY_PROCESS_NOT_FOUND.match(trimmed)
    if match:
        sid = match.group(1)
        return (
            f"Processo em segundo plano não encontrado ({sid}). "
            "Pode já ter encerrado ou o registro expirou."
        )
    if trimmed == "Process has already finished":
        return "O processo já foi encerrado"
    if trimmed.startswith("Process stdin not available"):
        return "Entrada do processo indisponível (backend remoto ou stdin fechado)"
    if trimmed.startswith("Recovered process cannot be killed"):
        return (
            "Não foi possível encerrar: o processo foi recuperado após reinício "
            "e o handle original não está mais disponível"
        )
    return trimmed


_TOOL_ERROR_HINT = re.compile(
    r"\b("
    r"traceback \(most recent|"
    r"navigation failed|"
    r"net::err_|"
    r"could not navigate|"
    r"operation failed|"
    r"permission denied|"
    r"access denied"
    r")\b",
    re.IGNORECASE,
)


def _parse_json_record(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _delegate_row_failed(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    status = str(row.get("status") or "").lower()
    return status in _DELEGATE_FAILURE_STATUSES


def infer_tool_failed(tool_name: str, result: str | None) -> bool:
    """Return True when the tool result indicates failure."""
    raw = (result or "").strip()
    if not raw:
        return False

    data = _parse_json_record(raw)
    if data is not None:
        if data.get("success") is False:
            return True
        if data.get("error"):
            return True

        status = str(data.get("status") or "").lower()
        if status in ("not_found", "error"):
            return True

        key = (tool_name or "").strip().lower()
        rows = data.get("results")
        if key == "delegate_task" and isinstance(rows, list):
            failed = any(_delegate_row_failed(row) for row in rows)
            completed = any(
                isinstance(row, dict)
                and str(row.get("status") or "").lower() == "completed"
                for row in rows
            )
            if failed and not completed:
                return True

    return bool(_TOOL_ERROR_HINT.search(raw))


def tool_failure_message(tool_name: str, result: str | None) -> str | None:
    """Short user-facing error line when infer_tool_failed is True."""
    raw = (result or "").strip()
    if not raw:
        return None

    data = _parse_json_record(raw)
    if data is not None:
        err = data.get("error")
        if isinstance(err, str) and err.strip():
            return _humanize_tool_error(err.strip())[:200]

        status = str(data.get("status") or "").lower()
        if status == "not_found":
            return "Processo em segundo plano não encontrado"

        key = (tool_name or "").strip().lower()
        rows = data.get("results")
        if key == "delegate_task" and isinstance(rows, list) and rows:
            failed = sum(1 for row in rows if _delegate_row_failed(row))
            completed = sum(
                1
                for row in rows
                if isinstance(row, dict)
                and str(row.get("status") or "").lower() == "completed"
            )
            if failed and not completed:
                return f"Delegação falhou (0/{len(rows)})"
            if failed:
                return f"{completed}/{len(rows)} subagentes concluídos"

    first = raw.split("\n", 1)[0].strip()
    if first.lower().startswith("traceback"):
        for line in reversed(raw.splitlines()):
            if "error:" in line.lower() or "exception:" in line.lower():
                return line.strip()[:200]
        return "Erro ao executar"
    if _TOOL_ERROR_HINT.search(raw):
        return first[:200]
    return first[:200] if first else None
