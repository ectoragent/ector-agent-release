"""Persist web chat plans as markdown under ECTOR_HOME/plans/."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ector_constants import display_ector_home, get_ector_home

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

_PLAN_HEADING_RE = re.compile(
    r"(?:^|\n)(#{1,3}\s*(?:Plano|Plan)\b[^\n]*\n[\s\S]*)",
    re.IGNORECASE,
)
_STRUCTURE_HEADING_RE = re.compile(
    r"(?:^|\n)(##\s*(?:Objetivo|Passos|Steps)\b[^\n]*\n[\s\S]*)",
    re.IGNORECASE,
)
_NUMBERED_STEP_RE = re.compile(r"^\d+\.\s", re.MULTILINE)
_PLAN_SUBSECTION_RE = re.compile(
    r"^##\s*(?:Objetivo|Passos|Steps|Arquivos|Riscos|Crit[eé]rios)\b",
    re.IGNORECASE | re.MULTILINE,
)
_CHECKLIST_RE = re.compile(r"^-\s+\[[ xX]\]\s", re.MULTILINE)

_PLAN_NOISE_RE = re.compile(
    r"modo\s+plano|ferramenta.*bloquead|dropdown|executar\s+plano|"
    r"continuar\s+planejando|toggle|procurar\s+um\s+bot",
    re.IGNORECASE,
)

_MIN_PLAN_CHARS = 80


def plans_root() -> Path:
    root = get_ector_home() / "plans"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _plan_path(session_id: str) -> Path:
    sid = (session_id or "").strip()
    if not sid or not _SESSION_ID_RE.match(sid):
        raise ValueError("invalid session_id for plan path")
    return plans_root() / f"{sid}.md"


def save_session_plan(
    session_id: str,
    markdown: str,
    *,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the latest plan for a session. Overwrites prior plan file."""
    body = (markdown or "").strip()
    if not body:
        return {}
    path = _plan_path(session_id)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heading = (title or "Plano").strip() or "Plano"
    if not body.lstrip().startswith("#"):
        body = f"# {heading}\n\n{body}"
    text = (
        f"---\n"
        f"session_id: {session_id.strip()}\n"
        f"created_at: {created}\n"
        f"---\n\n"
        f"{body.strip()}\n"
    )
    path.write_text(text, encoding="utf-8")
    rel = f"plans/{path.name}"
    return {
        "ok": True,
        "session_id": session_id.strip(),
        "path": str(path),
        "relative_path": rel,
        "display_path": f"{display_ector_home()}/{rel}",
    }


def read_session_plan(session_id: str) -> Optional[Dict[str, Any]]:
    """Return plan metadata + markdown body for a session, if present."""
    try:
        path = _plan_path(session_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not content.strip():
        return None
    rel = f"plans/{path.name}"
    return {
        "ok": True,
        "session_id": session_id.strip(),
        "path": str(path),
        "relative_path": rel,
        "display_path": f"{display_ector_home()}/{rel}",
        "content": content,
    }


def clear_session_plan(session_id: str) -> bool:
    try:
        path = _plan_path(session_id)
    except ValueError:
        return False
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def extract_plan_section(text: str) -> str:
    """Return the structured plan section, excluding conversational preamble."""
    raw = (text or "").strip()
    if not raw:
        return ""

    match = _PLAN_HEADING_RE.search(raw)
    if match:
        return match.group(1).strip()

    struct = _STRUCTURE_HEADING_RE.search(raw)
    if struct:
        section = struct.group(1).strip()
        if _NUMBERED_STEP_RE.search(section):
            return section

    return ""


def is_actionable_plan(text: str) -> bool:
    """True when markdown looks like a real plan, not UI/meta chatter."""
    section = (text or "").strip()
    if len(section) < _MIN_PLAN_CHARS:
        return False

    numbered_steps = len(_NUMBERED_STEP_RE.findall(section))
    has_subsections = bool(_PLAN_SUBSECTION_RE.search(section))
    has_checklist = bool(_CHECKLIST_RE.search(section))
    has_plan_signal = numbered_steps >= 2 or has_subsections or has_checklist
    if not has_plan_signal:
        return False

    noise_hits = len(_PLAN_NOISE_RE.findall(section))
    if noise_hits >= 3 and numbered_steps < 2 and not has_subsections:
        return False

    return True


def _raw_assistant_text_from_turn(result: Optional[Dict[str, Any]]) -> str:
    if not result:
        return ""
    final = str(result.get("final_response") or "").strip()
    if final:
        return final
    messages = result.get("messages") or []
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    part_text = str(part.get("text") or "").strip()
                    if part_text:
                        parts.append(part_text)
            joined = "\n\n".join(parts).strip()
            if joined:
                return joined
    return ""


def _todo_step_texts_from_payload(payload: Dict[str, Any]) -> list[str]:
    todos = payload.get("todos")
    if not isinstance(todos, list):
        return []
    steps: list[str] = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "pending").strip().lower()
        if status == "cancelled":
            continue
        content = str(item.get("content") or item.get("text") or "").strip()
        if content:
            steps.append(content)
    return steps


def _latest_todo_steps_from_messages(messages: list) -> list[str]:
    if not isinstance(messages, list):
        return []
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or "todos" not in payload:
            continue
        steps = _todo_step_texts_from_payload(payload)
        if len(steps) >= 2:
            return steps
    return []


def synthesize_plan_markdown_from_todo_steps(steps: list[str]) -> str:
    cleaned = [str(step).strip() for step in steps if str(step).strip()]
    if len(cleaned) < 2:
        return ""
    body = "## Plano\n\n### Passos\n" + "\n".join(
        f"{index}. {step}" for index, step in enumerate(cleaned, start=1)
    )
    if not is_actionable_plan(body):
        return ""
    return body


def extract_plan_from_todos_in_turn(result: Optional[Dict[str, Any]]) -> str:
    """Synthesize ## Plano from the latest todo tool result in a turn."""
    if not result:
        return ""
    messages = result.get("messages") or []
    steps = _latest_todo_steps_from_messages(messages)
    return synthesize_plan_markdown_from_todo_steps(steps)


def extract_plan_markdown_from_turn(result: Optional[Dict[str, Any]]) -> str:
    """Extract validated plan markdown from a completed agent turn."""
    raw = _raw_assistant_text_from_turn(result)
    if raw:
        section = extract_plan_section(raw)
        if section and is_actionable_plan(section):
            return section
    return extract_plan_from_todos_in_turn(result)
