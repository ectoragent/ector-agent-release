"""Directory browsing helpers for the web dashboard folder picker."""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

_MAX_LIST_ENTRIES = 200
_MAX_SEARCH_RESULTS = 50
_MAX_SEARCH_DEPTH = 5
_MIN_GLOBAL_SEARCH_LEN = 2
_MAX_VISITED_DIRS = 800

# Heavy or irrelevant trees — skip descent to keep search responsive.
_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        "Library",
        "Caches",
        "Cache",
        ".npm",
        ".pnpm-store",
        "venv",
        ".venv",
        "__pycache__",
        "target",
        "build",
        "dist",
        ".next",
        ".nuxt",
        "vendor",
        "Pods",
        "DerivedData",
        ".android",
        ".gradle",
        ".m2",
        ".cargo",
        ".rustup",
        ".cache",
        "Trash",
        ".Trash",
        "Applications",
        ".docker",
        "containers",
        ".local",
        "go",
        ".pyenv",
        ".nvm",
        ".volta",
        "Music",
        "Movies",
        "Pictures",
    }
)

# Dev-oriented roots searched before a wider home walk.
_PRIORITY_ROOT_NAMES = (
    "Documents",
    "Desktop",
    "Projects",
    "dev",
    "code",
    "workspace",
    "src",
    "develop",
    "develop-personal",
    "repos",
    "git",
)


def short_display_path(cwd: str, max_len: int = 40) -> str:
    """Home-relative path for UI labels (parity with web_server._short_display_cwd)."""
    del max_len
    try:
        home = os.path.expanduser("~")
    except Exception:
        home = ""
    p = cwd
    if home and p.startswith(home):
        p = "~" + p[len(home) :]
    return p


def resolve_browse_path(raw: str) -> str:
    """Resolve *raw* to an absolute existing directory path."""
    text = (raw or "").strip()
    if not text:
        resolved = Path.home().resolve()
    else:
        resolved = Path(os.path.expanduser(text)).resolve()
    if not resolved.is_dir():
        raise ValueError("caminho não é um diretório")
    if not os.access(resolved, os.R_OK):
        raise ValueError("sem permissão de leitura")
    return str(resolved)


def _parent_path(path: str) -> Optional[str]:
    parent = Path(path).parent
    if str(parent) == path:
        return None
    if not parent.is_dir():
        return None
    return str(parent)


def _entry_payload(full: Path, *, label_fn: Callable[[str], str]) -> dict[str, Any]:
    text = str(full)
    return {
        "name": full.name,
        "path": text,
        "path_label": label_fn(text),
        "is_dir": True,
    }


def _dir_rank(name: str, needle: str) -> Optional[int]:
    lowered = name.lower()
    if lowered.startswith(needle):
        return 0
    if needle in lowered:
        return 1
    return None


def _is_hidden_dir_name(name: str) -> bool:
    return bool(name) and name.startswith(".")


def _iter_subdirs(directory: Path, *, hide_hidden: bool = False) -> list[Path]:
    rows: list[Path] = []
    try:
        with os.scandir(directory) as scan:
            for entry in scan:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if hide_hidden and _is_hidden_dir_name(entry.name):
                    continue
                if entry.name in _SKIP_DIR_NAMES:
                    continue
                if not os.access(entry.path, os.R_OK):
                    continue
                rows.append(Path(entry.path))
    except OSError:
        return rows
    return rows


def _list_subdirs(
    directory: str,
    *,
    query: str = "",
    hide_hidden: bool = False,
    label_fn: Callable[[str], str] = short_display_path,
) -> list[dict[str, Any]]:
    root = Path(directory)
    match = query.strip().lower()
    entries: list[dict[str, Any]] = []
    for full in _iter_subdirs(root, hide_hidden=hide_hidden):
        if match and not full.name.lower().startswith(match):
            continue
        entries.append(_entry_payload(full, label_fn=label_fn))
        if len(entries) >= _MAX_LIST_ENTRIES:
            break
    entries.sort(key=lambda row: row["name"].lower())
    return entries


def _recent_project_matches(
    query: str,
    *,
    label_fn: Callable[[str], str],
) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return []
    try:
        from ector_cli.recent_projects import list_recent_projects

        rows = list_recent_projects(limit=20)
    except Exception:
        return []
    results: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        path = row.get("path")
        if not isinstance(path, str) or not path:
            continue
        name = Path(path).name
        rank = _dir_rank(name, needle)
        if rank is None and needle not in path.lower():
            continue
        if rank is None:
            rank = 2
        results.append((rank, path, _entry_payload(Path(path), label_fn=label_fn)))
    results.sort(key=lambda item: (item[0], len(item[1]), item[1]))
    return [item[2] for item in results]


def _bfs_search_roots(
    roots: list[Path],
    needle: str,
    *,
    label_fn: Callable[[str], str],
    seen_paths: set[str],
    hide_hidden: bool = False,
) -> list[dict[str, Any]]:
    results: list[tuple[int, str, dict[str, Any]]] = []
    visited = 0
    queue: deque[tuple[Path, int]] = deque((root, 0) for root in roots if root.is_dir())

    while queue and len(results) < _MAX_SEARCH_RESULTS and visited < _MAX_VISITED_DIRS:
        current, depth = queue.popleft()
        visited += 1
        if depth > _MAX_SEARCH_DEPTH:
            continue

        try:
            with os.scandir(current) as scan:
                children: list[Path] = []
                for entry in scan:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if hide_hidden and _is_hidden_dir_name(entry.name):
                        continue
                    if entry.name in _SKIP_DIR_NAMES:
                        continue
                    if not os.access(entry.path, os.R_OK):
                        continue
                    children.append(Path(entry.path))
        except OSError:
            continue

        for full in children:
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
            rank = _dir_rank(full.name, needle)
            resolved = str(full)
            if rank is not None and resolved not in seen_paths:
                seen_paths.add(resolved)
                results.append(
                    (rank, resolved, _entry_payload(full, label_fn=label_fn))
                )
            if depth < _MAX_SEARCH_DEPTH and full.name not in _SKIP_DIR_NAMES:
                queue.append((full, depth + 1))

    results.sort(key=lambda row: (row[0], len(row[1]), row[1]))
    return [row[2] for row in results]


def _search_dirs_under_home(
    query: str,
    *,
    hide_hidden: bool = False,
    label_fn: Callable[[str], str] = short_display_path,
) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if len(needle) < _MIN_GLOBAL_SEARCH_LEN:
        return []

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []

    for entry in _recent_project_matches(needle, label_fn=label_fn):
        path = entry["path"]
        if path not in seen:
            seen.add(path)
            merged.append(entry)
        if len(merged) >= _MAX_SEARCH_RESULTS:
            return merged

    home = Path.home().resolve()
    priority_roots: list[Path] = []
    for name in _PRIORITY_ROOT_NAMES:
        candidate = home / name
        if candidate.is_dir():
            priority_roots.append(candidate)

    for entry in _bfs_search_roots(
        priority_roots,
        needle,
        label_fn=label_fn,
        seen_paths=seen,
        hide_hidden=hide_hidden,
    ):
        merged.append(entry)
        if len(merged) >= _MAX_SEARCH_RESULTS:
            return merged

    if len(merged) < _MAX_SEARCH_RESULTS:
        for entry in _bfs_search_roots(
            [home],
            needle,
            label_fn=label_fn,
            seen_paths=seen,
            hide_hidden=hide_hidden,
        ):
            merged.append(entry)
            if len(merged) >= _MAX_SEARCH_RESULTS:
                break

    return merged[:_MAX_SEARCH_RESULTS]


def _search_path_like_query(
    query: str,
    *,
    hide_hidden: bool = False,
    label_fn: Callable[[str], str],
) -> Optional[list[dict[str, Any]]]:
    raw = query.strip()
    if not raw or ("/" not in raw and not raw.startswith("~")):
        return None
    try:
        resolved = resolve_browse_path(raw)
    except ValueError:
        return None
    path = Path(resolved)
    if path.is_dir():
        return [_entry_payload(path, label_fn=label_fn)]
    parent = path.parent
    if not parent.is_dir():
        return None
    needle = path.name.lower()
    return _list_subdirs(
        str(parent), query=needle, hide_hidden=hide_hidden, label_fn=label_fn
    )


def browse_directory(
    path: str = "",
    *,
    query: str = "",
    hide_hidden: bool = False,
    label_fn: Callable[[str], str] = short_display_path,
) -> dict[str, Any]:
    """List directories under *path*, optionally filtered by *query*."""
    q = (query or "").strip()
    if q and not (path or "").strip():
        home = str(Path.home().resolve())
        path_like = _search_path_like_query(
            q, hide_hidden=hide_hidden, label_fn=label_fn
        )
        entries = (
            path_like
            if path_like is not None
            else _search_dirs_under_home(
                q, hide_hidden=hide_hidden, label_fn=label_fn
            )
        )
        return {
            "path": home,
            "path_label": label_fn(home),
            "parent": _parent_path(home),
            "entries": entries,
        }

    resolved = resolve_browse_path(path or "~")
    entries = _list_subdirs(resolved, query=q, hide_hidden=hide_hidden, label_fn=label_fn)
    return {
        "path": resolved,
        "path_label": label_fn(resolved),
        "parent": _parent_path(resolved),
        "entries": entries,
    }


def create_directory(
    parent: str,
    name: str,
    *,
    label_fn: Callable[[str], str] = short_display_path,
) -> dict[str, Any]:
    """Create a subdirectory under *parent* and return its browse entry."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("nome de pasta obrigatório")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("nome de pasta inválido")
    if cleaned != Path(cleaned).name:
        raise ValueError("nome de pasta inválido")

    parent_resolved = resolve_browse_path(parent or "~")
    if not os.access(parent_resolved, os.W_OK):
        raise ValueError("sem permissão de escrita")

    target = Path(parent_resolved) / cleaned
    if target.exists():
        raise ValueError("já existe uma pasta com esse nome")

    try:
        target.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        raise ValueError(f"não foi possível criar a pasta: {exc}") from exc

    if not target.is_dir():
        raise ValueError("não foi possível criar a pasta")

    return _entry_payload(target.resolve(), label_fn=label_fn)
