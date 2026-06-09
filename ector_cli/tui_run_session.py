"""Track which TUI session had user activity in the current ``ector`` run."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from ector_constants import get_ector_home

_MARKER_NAME = ".tui-run-session"


def _marker_path() -> Path:
    return get_ector_home() / _MARKER_NAME


def clear_tui_run_session() -> None:
    """Drop any session marker from a prior TUI launch."""
    try:
        _marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def record_tui_run_session(session_key: str) -> None:
    """Remember the persistent session key touched during this TUI run."""
    key = (session_key or "").strip()
    if not key:
        return
    payload = {
        "session_key": key,
        "recorded_at": time.time(),
        "parent_pid": os.getppid(),
    }
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def read_tui_run_session() -> Optional[str]:
    """Return the session key for this run, or None if the user never interacted."""
    path = _marker_path()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    key = (data.get("session_key") or "").strip()
    return key or None
