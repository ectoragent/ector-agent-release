"""Workspace scoping for agent-created skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.skill_utils import parse_frontmatter


def resolve_workspace_root(task_id: Optional[str] = None) -> Optional[str]:
    """Git worktree root for the session, or resolved cwd when not in a repo."""
    from agent.session_paths import git_worktree_root, resolve_session_cwd

    cwd = resolve_session_cwd(task_id)
    if not cwd:
        return None
    try:
        resolved_cwd = Path(cwd).expanduser().resolve()
    except OSError:
        return cwd.strip() or None
    root = git_worktree_root(str(resolved_cwd)) or str(resolved_cwd)
    try:
        return str(Path(root).expanduser().resolve())
    except OSError:
        return root.strip() or None


def normalize_session_workspace(session_cwd: Optional[str]) -> Optional[str]:
    """Normalize a session cwd to a comparable workspace root."""
    if not session_cwd or not str(session_cwd).strip():
        return None
    return resolve_workspace_root_from_path(str(session_cwd).strip())


def resolve_workspace_root_from_path(path: str) -> Optional[str]:
    from agent.session_paths import git_worktree_root

    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return path.strip() or None
    root = git_worktree_root(str(resolved)) or str(resolved)
    try:
        return str(Path(root).expanduser().resolve())
    except OSError:
        return root.strip() or None


def parse_skill_workspace_roots(frontmatter: Dict[str, Any]) -> Optional[List[str]]:
    """Return declared workspace roots, or None when the skill is global."""
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return None
    ector = metadata.get("ector")
    if not isinstance(ector, dict):
        return None
    roots = ector.get("workspace_roots")
    if not roots:
        return None
    if isinstance(roots, str):
        roots = [roots]
    if not isinstance(roots, list):
        return None
    normalized: List[str] = []
    for raw in roots:
        if not isinstance(raw, str) or not raw.strip():
            continue
        normalized.append(_normalize_path(raw))
    return normalized or None


def workspace_paths_match(current: str, declared: str) -> bool:
    """True when *current* and *declared* refer to the same project tree."""
    try:
        cur = Path(current).expanduser().resolve()
        dec = Path(declared).expanduser().resolve()
    except OSError:
        return current == declared
    if cur == dec:
        return True
    try:
        cur.relative_to(dec)
        return True
    except ValueError:
        pass
    try:
        dec.relative_to(cur)
        return True
    except ValueError:
        pass
    return False


def skill_applies_to_workspace(
    frontmatter: Dict[str, Any],
    body: str = "",
    task_id: Optional[str] = None,
    *,
    session_workspace: Optional[str] = None,
) -> bool:
    """True when the skill is global or matches the active session workspace."""
    declared = parse_skill_workspace_roots(frontmatter)
    if not declared:
        return True

    current = session_workspace or resolve_workspace_root(task_id)
    if not current:
        return False

    return any(workspace_paths_match(current, root) for root in declared)


def inject_workspace_metadata(content: str, workspace_root: str) -> str:
    """Merge metadata.ector.workspace_roots into SKILL.md frontmatter."""
    root = _normalize_path(workspace_root)
    if not root:
        return content

    frontmatter, body = parse_frontmatter(content)
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    ector = metadata.get("ector")
    if not isinstance(ector, dict):
        ector = {}

    roots = ector.get("workspace_roots")
    if not isinstance(roots, list):
        roots = []
    normalized_roots = [_normalize_path(str(item)) for item in roots if str(item).strip()]
    if root not in normalized_roots:
        normalized_roots.append(root)

    ector["workspace_roots"] = normalized_roots
    metadata["ector"] = ector
    frontmatter["metadata"] = metadata

    return _format_skill_md(frontmatter, body)


def workspace_roots_from_frontmatter(frontmatter: Dict[str, Any]) -> List[str]:
    """Serializable roots list for snapshots and API responses."""
    return list(parse_skill_workspace_roots(frontmatter) or [])


def skill_snapshot_applies_to_workspace(
    entry: Dict[str, Any],
    session_workspace: Optional[str],
) -> bool:
    roots = entry.get("workspace_roots") or []
    if not roots:
        return True
    if not session_workspace:
        return False
    return any(workspace_paths_match(session_workspace, str(root)) for root in roots)


def _normalize_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return path.strip()


def _format_skill_md(frontmatter: Dict[str, Any], body: str) -> str:
    import yaml

    dumped = yaml.dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    trimmed_body = body.lstrip("\n")
    if trimmed_body:
        return f"---\n{dumped}\n---\n\n{trimmed_body}"
    return f"---\n{dumped}\n---\n"
