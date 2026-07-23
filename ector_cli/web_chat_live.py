"""In-memory live turn snapshot for web chat — server-side source of truth during SSE."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any

from agent.tool_result_status import infer_tool_failed

_LOCK = threading.Lock()
_LIVE: dict[str, dict[str, Any]] = {}

PREPARING_STATUS = "Analisando seu pedido…"


def _new_turn(request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "revision": 0,
        "status_text": PREPARING_STATUS,
        "streaming_buffer": "",
        "tool_calls": [],
        "segments": [],
        "_tool_index": {},
    }


def _bump(state: dict[str, Any]) -> None:
    state["revision"] = int(state.get("revision", 0)) + 1


def begin_turn(session_id: str, request_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        _LIVE[sid] = _new_turn(request_id)


def clear_turn(session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        _LIVE.pop(sid, None)


def _get_state(session_id: str) -> dict[str, Any] | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        state = _LIVE.get(sid)
        return state


def _mutate(session_id: str, fn) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        state = _LIVE.get(sid)
        if state is None:
            return
        fn(state)
        _bump(state)


def _append_text_segment(state: dict[str, Any], text: str) -> None:
    trimmed = str(text or "").strip()
    if not trimmed:
        return
    segments: list[dict[str, Any]] = state.setdefault("segments", [])
    if segments and segments[-1].get("kind") == "text":
        prev = str(segments[-1].get("content") or "").strip()
        if prev == trimmed:
            return
        if trimmed.startswith(prev):
            segments[-1] = {"kind": "text", "content": text}
            return
        if prev.endswith(trimmed):
            return
    segments.append({"kind": "text", "content": text})


def _flush_buffer(state: dict[str, Any]) -> None:
    buf = str(state.get("streaming_buffer") or "")
    if not buf.strip():
        state["streaming_buffer"] = ""
        return
    _append_text_segment(state, buf)
    state["streaming_buffer"] = ""


def append_text(session_id: str, chunk: str) -> None:
    piece = str(chunk or "")
    if not piece:
        return

    def _apply(state: dict[str, Any]) -> None:
        state["streaming_buffer"] = str(state.get("streaming_buffer") or "") + piece
        if piece.strip():
            state["status_text"] = "Gerando resposta…"

    _mutate(session_id, _apply)


def set_status(session_id: str, text: str) -> None:
    status = str(text or "").strip()
    if not status:
        return

    def _apply(state: dict[str, Any]) -> None:
        state["status_text"] = status[:240]

    _mutate(session_id, _apply)


def set_thinking(session_id: str) -> None:
    def _apply(state: dict[str, Any]) -> None:
        current = str(state.get("status_text") or "").strip()
        if current in ("", PREPARING_STATUS, "Gerando resposta…", "Em andamento…"):
            state["status_text"] = "Raciocínio prolongado…"

    _mutate(session_id, _apply)


def tool_start(
    session_id: str,
    *,
    tool_id: str,
    name: str,
    args: str = "",
    live_label: str = "",
    live_technical: str = "",
) -> None:
    tc_id = str(tool_id or "").strip() or f"tool-{name}"
    tool_name = str(name or "tool").strip() or "tool"

    def _apply(state: dict[str, Any]) -> None:
        _flush_buffer(state)
        index: dict[str, int] = state.setdefault("_tool_index", {})
        tools: list[dict[str, Any]] = state.setdefault("tool_calls", [])
        row = {
            "id": tc_id,
            "server_id": tc_id,
            "name": tool_name,
            "args": str(args or ""),
            "live_label": str(live_label or "")[:240],
            "live_technical": str(live_technical or "")[:240],
            "result": None,
            "status": "running",
            "cwd": None,
        }
        if tc_id in index:
            pos = index[tc_id]
            prev = tools[pos]
            tools[pos] = {
                **prev,
                **row,
                "args": row["args"] or prev.get("args") or "",
                "live_label": row["live_label"] or prev.get("live_label") or "",
                "live_technical": row["live_technical"] or prev.get("live_technical") or "",
                "status": "running",
            }
        else:
            index[tc_id] = len(tools)
            tools.append(row)
            segments: list[dict[str, Any]] = state.setdefault("segments", [])
            segments.append({"kind": "tools", "tool_calls": [deepcopy(row)]})
        state["status_text"] = str(live_label or "Em andamento…")[:240]

    _mutate(session_id, _apply)


def _patch_tool_in_segments(
    state: dict[str, Any],
    row: dict[str, Any],
    *,
    status: str | None = None,
) -> None:
    segments: list[dict[str, Any]] = state.setdefault("segments", [])
    for segment in segments:
        if segment.get("kind") != "tools":
            continue
        for seg_tool in segment.get("tool_calls") or []:
            if (
                seg_tool.get("id") == row.get("id")
                or seg_tool.get("server_id") == row.get("server_id")
            ):
                if status is not None:
                    seg_tool["status"] = status
                if row.get("result") is not None:
                    seg_tool["result"] = row.get("result")
                if row.get("cwd"):
                    seg_tool["cwd"] = row.get("cwd")
                if row.get("live_label"):
                    seg_tool["live_label"] = row.get("live_label")
                if row.get("live_technical"):
                    seg_tool["live_technical"] = row.get("live_technical")


def tool_progress(
    session_id: str,
    *,
    tool_id: str = "",
    tool_name: str,
    preview: str = "",
    technical: str = "",
) -> None:
    name = str(tool_name or "").strip()
    label = str(preview or technical or "").strip()
    if not label:
        return
    tc_id = str(tool_id or "").strip()

    def _apply(state: dict[str, Any]) -> None:
        index: dict[str, int] = state.setdefault("_tool_index", {})
        tools: list[dict[str, Any]] = state.setdefault("tool_calls", [])
        pos: int | None = None
        if tc_id and tc_id in index:
            pos = index[tc_id]
        if pos is None:
            for idx in range(len(tools) - 1, -1, -1):
                row = tools[idx]
                if row.get("status") == "running" and (
                    not name or str(row.get("name") or "") == name
                ):
                    pos = idx
                    break
        if pos is None:
            return
        row = tools[pos]
        if preview:
            row["live_label"] = str(preview)[:240]
        if technical:
            row["live_technical"] = str(technical)[:240]
        _patch_tool_in_segments(state, row)
        state["status_text"] = label[:240]

    _mutate(session_id, _apply)


def _detect_background_spawn(
    tool_name: str,
    result_str: str | None,
    args_str: str | None = None,
) -> dict[str, str] | None:
    name = str(tool_name or "").strip().lower()
    if name not in ("terminal", "shell"):
        return None
    if not result_str:
        return None
    try:
        data = json.loads(result_str)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    proc_id = str(data.get("session_id") or "").strip()
    output = str(data.get("output") or "")
    if not proc_id.startswith("proc_"):
        return None
    if "Background process started" not in output:
        return None
    description = ""
    if args_str:
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
            if isinstance(args, dict):
                description = str(args.get("description") or "").strip()
        except Exception:
            pass
    live_label = (
        f"{description} — executando em segundo plano…"
        if description
        else "Executando em segundo plano…"
    )
    return {"proc_session_id": proc_id, "live_label": live_label}


def tool_complete(
    session_id: str,
    *,
    tool_id: str,
    name: str,
    result: str | None = None,
    cwd: str | None = None,
    args: str | None = None,
) -> None:
    tc_id = str(tool_id or "").strip()
    tool_name = str(name or "tool").strip() or "tool"
    result_str = str(result) if result is not None else None
    failed = infer_tool_failed(tool_name, result_str)
    bg = _detect_background_spawn(tool_name, result_str, args)
    status = "error" if failed else ("running" if bg else "complete")

    def _apply(state: dict[str, Any]) -> None:
        index: dict[str, int] = state.setdefault("_tool_index", {})
        tools: list[dict[str, Any]] = state.setdefault("tool_calls", [])
        pos = index.get(tc_id) if tc_id else None
        if pos is None:
            for idx, row in enumerate(tools):
                if row.get("status") == "running" and str(row.get("name") or "") == tool_name:
                    pos = idx
                    break
        if pos is None:
            return
        row = tools[pos]
        row["status"] = status
        if result_str is not None:
            row["result"] = result_str
        if cwd:
            row["cwd"] = cwd
        if bg:
            row["background_proc_id"] = bg["proc_session_id"]
            row["live_label"] = bg["live_label"]
        _patch_tool_in_segments(state, row, status=status)
        state["status_text"] = (
            bg["live_label"] if bg else "Preparando próximo passo…"
        )

    _mutate(session_id, _apply)


def mark_background_killed(session_id: str, proc_id: str) -> None:
    """Resolve a background tool call in the live view after an out-of-band kill.

    The REST kill endpoint (POST /api/chat/background-processes/kill) stops the
    OS process via process_registry, but that's independent of this in-memory
    live-turn state. Without this, tool_complete()'s earlier ``status =
    "running"`` for that background spawn stays "running" for as long as the
    turn is still busy — every subsequent /api/chat/turn poll would keep
    reporting it as running, undoing the frontend's optimistic "stopped" mark
    and making the card look like it revives/restarts on its own.
    """
    pid = str(proc_id or "").strip()
    if not pid:
        return
    killed_result = json.dumps(
        {
            "status": "killed",
            "exit_code": -15,
            "output": "Processo interrompido pelo utilizador.",
        }
    )

    def _apply(state: dict[str, Any]) -> None:
        tools: list[dict[str, Any]] = state.setdefault("tool_calls", [])
        for row in tools:
            if row.get("background_proc_id") != pid:
                continue
            row["status"] = "error"
            row["result"] = killed_result
            row["background_proc_id"] = None
            _patch_tool_in_segments(state, row, status="error")

    _mutate(session_id, _apply)


def snapshot(session_id: str) -> dict[str, Any] | None:
    state = _get_state(session_id)
    if state is None:
        return None
    with _LOCK:
        raw = deepcopy(state)
    raw.pop("_tool_index", None)
    return raw


def live_for_api(session_id: str) -> dict[str, Any] | None:
    raw = snapshot(session_id)
    if raw is None:
        return None
    tool_calls = []
    for row in raw.get("tool_calls") or []:
        tool_calls.append(
            {
                "id": row.get("id"),
                "server_id": row.get("server_id"),
                "name": row.get("name"),
                "args": row.get("args") or "",
                "live_label": row.get("live_label") or "",
                "live_technical": row.get("live_technical") or "",
                "result": row.get("result"),
                "status": row.get("status") or "running",
                "cwd": row.get("cwd"),
                "background_proc_id": row.get("background_proc_id"),
            }
        )
    return {
        "revision": int(raw.get("revision") or 0),
        "request_id": raw.get("request_id"),
        "status_text": raw.get("status_text") or "",
        "streaming_buffer": raw.get("streaming_buffer") or "",
        "tool_calls": tool_calls,
        "segments": raw.get("segments") or [],
    }
