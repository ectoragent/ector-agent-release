"""Session working-directory helpers shared by prompts and terminal execution."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Tuple

_CD_PREFIX_RE = re.compile(
    r'^\s*cd\s+("(?:[^"\\]|\\.)*"|\'(?:[^\']|\\.)*\'|[^\s;&|]+)\s*&&\s*(.+)$',
    re.DOTALL,
)


def _resolved_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def resolve_session_cwd(task_id: Optional[str] = None) -> str:
    """Best-effort session cwd for tools and system-prompt hints."""
    try:
        from tools.terminal_tool import get_active_env

        if task_id:
            env = get_active_env(task_id)
            if env is not None:
                cwd = getattr(env, "cwd", None)
                if isinstance(cwd, str) and cwd.strip():
                    return _resolved_path(cwd)
    except Exception:
        pass

    terminal_cwd = os.getenv("TERMINAL_CWD", "").strip()
    if terminal_cwd:
        return _resolved_path(terminal_cwd)

    try:
        from tools.terminal_tool import get_active_env

        env = get_active_env("default")
        if env is not None:
            cwd = getattr(env, "cwd", None)
            if isinstance(cwd, str) and cwd.strip():
                return _resolved_path(cwd)
    except Exception:
        pass

    from ector_constants import safe_getcwd

    return _resolved_path(safe_getcwd())


def git_worktree_root(path: str) -> Optional[str]:
    """Return the git worktree root containing *path*, if any."""
    try:
        current = Path(path).expanduser().resolve()
    except OSError:
        return None

    for directory in [current, *current.parents]:
        if (directory / ".git").exists():
            return str(directory)
    return None


def rewrite_phantom_cd_command(command: str, session_cwd: str) -> Tuple[str, Optional[str]]:
    """Drop misleading ``cd PATH && …`` prefixes that leave the session repo.

    Returns ``(command, note)`` where *note* is a short explanation when rewritten.
    """
    match = _CD_PREFIX_RE.match(command or "")
    if not match:
        return command, None

    raw_path = match.group(1).strip().strip('"').strip("'")
    rest = match.group(2).strip()
    if not rest:
        return command, None

    try:
        session_path = Path(session_cwd).expanduser().resolve()
        cd_path = Path(os.path.expanduser(raw_path)).resolve()
    except OSError:
        return command, None

    session_git = git_worktree_root(str(session_path))
    looks_like_git = bool(re.match(r"^git\b", rest, re.I))

    if not cd_path.is_dir():
        return rest, (
            f"Dropped `cd {raw_path}` (path does not exist); "
            f"running in session cwd `{session_path}`."
        )

    if cd_path == session_path:
        return rest, None

    try:
        cd_path.relative_to(session_path)
        return command, None
    except ValueError:
        pass

    if looks_like_git:
        if session_git is None or git_worktree_root(str(cd_path)) != session_git:
            return rest, (
                f"Dropped `cd {raw_path}` (outside session cwd `{session_path}`); "
                f"running git in the active repository."
            )

    return command, None
