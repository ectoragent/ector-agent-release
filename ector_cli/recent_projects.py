"""Persist recently opened project directories for the web dashboard."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ector_constants import get_ector_home

_MAX_STORED = 20
_DEFAULT_LIMIT = 10


def _store_path() -> Path:
    return get_ector_home() / "recent_projects.json"


def _normalize_project_path(path: str) -> str:
    resolved = Path(os.path.expanduser((path or "").strip())).resolve()
    return str(resolved)


def validate_project_directory(path: str) -> str:
    """Return absolute path when *path* is an existing readable directory."""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("path é obrigatório")
    resolved = Path(os.path.expanduser(raw)).resolve()
    if not resolved.is_dir():
        raise ValueError("caminho não é um diretório")
    if not os.access(resolved, os.R_OK):
        raise ValueError("sem permissão de leitura")
    return str(resolved)


def _load_store() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"projects": []}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"projects": []}
    if not isinstance(data, dict):
        return {"projects": []}
    projects = data.get("projects")
    if not isinstance(projects, list):
        return {"projects": []}
    return {"projects": projects}


def _save_store(data: dict[str, Any]) -> None:
    from utils import atomic_json_write

    atomic_json_write(_store_path(), data, indent=2)


def list_recent_projects(limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Return recent projects sorted by ``opened_at`` descending."""
    cap = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_STORED))
    projects = _load_store().get("projects") or []
    cleaned: list[dict[str, Any]] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        opened_at = item.get("opened_at")
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(opened_at, (int, float)):
            continue
        if not Path(path).is_dir():
            continue
        cleaned.append(
            {
                "path": path,
                "opened_at": int(opened_at),
            }
        )
    cleaned.sort(key=lambda row: row["opened_at"], reverse=True)
    return cleaned[:cap]


def record_project_open(path: str) -> dict[str, Any]:
    """Record *path* as the most recently opened project."""
    resolved = validate_project_directory(path)
    now = int(time.time() * 1000)
    store = _load_store()
    projects = store.get("projects") or []
    if not isinstance(projects, list):
        projects = []

    kept: list[dict[str, Any]] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        existing = item.get("path")
        if not isinstance(existing, str):
            continue
        try:
            if _normalize_project_path(existing) == resolved:
                continue
        except (OSError, ValueError):
            continue
        opened_at = item.get("opened_at")
        if isinstance(opened_at, (int, float)):
            kept.append({"path": existing, "opened_at": int(opened_at)})

    kept.insert(0, {"path": resolved, "opened_at": now})
    kept = kept[:_MAX_STORED]
    _save_store({"projects": kept})
    return {"path": resolved, "opened_at": now}
