"""Git summary for web/TUI composer footers."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

_GIT_TIMEOUT_S = 0.5
_CACHE_TTL_S = 5.0
_cache: Dict[str, Tuple[float, "GitFooterInfo"]] = {}

_AHEAD_RE = re.compile(r"ahead (\d+)")
_BEHIND_RE = re.compile(r"behind (\d+)")


@dataclass(frozen=True)
class GitFooterInfo:
    dir_name: str
    branch: Optional[str]
    modified: int
    untracked: int
    ahead: int = 0
    behind: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "cwd_dir_name": self.dir_name,
            "git_branch": self.branch,
            "git_modified": self.modified,
            "git_untracked": self.untracked,
            "git_ahead": self.ahead,
            "git_behind": self.behind,
        }


def cwd_dir_name(cwd: str) -> str:
    text = (cwd or "").strip()
    if not text:
        return ""
    try:
        resolved = Path(text).expanduser().resolve()
    except OSError:
        resolved = Path(text).expanduser()
    name = resolved.name
    if name:
        return name
    return "~" if str(resolved) in {"/", str(Path.home())} else text


def _run_git(cwd: str, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_porcelain(stdout: str) -> Tuple[int, int]:
    modified = 0
    untracked = 0
    for raw in stdout.splitlines():
        line = raw.rstrip("\n")
        if not line:
            continue
        if line.startswith("??"):
            untracked += 1
            continue
        if len(line) > 1 and line[1] != " ":
            modified += 1
    return modified, untracked


def _parse_branch_header(line: str) -> Tuple[int, int]:
    """Parse ahead/behind counts from a `git status --branch` `## ...` header.

    Examples: "## main...origin/main [ahead 2]",
    "## main...origin/main [ahead 2, behind 3]", "## main" (no upstream).
    """
    ahead_match = _AHEAD_RE.search(line)
    behind_match = _BEHIND_RE.search(line)
    ahead = int(ahead_match.group(1)) if ahead_match else 0
    behind = int(behind_match.group(1)) if behind_match else 0
    return ahead, behind


def _resolve_git_footer_uncached(cwd: str) -> GitFooterInfo:
    directory = cwd_dir_name(cwd)

    inside = _run_git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.strip().lower() != "true":
        return GitFooterInfo(
            dir_name=directory,
            branch=None,
            modified=0,
            untracked=0,
        )

    branch_out = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    branch = None
    if branch_out is not None:
        candidate = branch_out.strip()
        if candidate and candidate != "HEAD":
            branch = candidate

    # Sem branch válida → não há status útil para o rodapé.
    if not branch:
        return GitFooterInfo(
            dir_name=directory,
            branch=None,
            modified=0,
            untracked=0,
        )

    status_out = _run_git(cwd, "status", "--porcelain", "--branch")
    modified = 0
    untracked = 0
    ahead = 0
    behind = 0
    if status_out is not None:
        lines = status_out.splitlines()
        if lines and lines[0].startswith("##"):
            ahead, behind = _parse_branch_header(lines[0])
            lines = lines[1:]
        modified, untracked = _parse_porcelain("\n".join(lines))

    return GitFooterInfo(
        dir_name=directory,
        branch=branch,
        modified=modified,
        untracked=untracked,
        ahead=ahead,
        behind=behind,
    )


def resolve_git_footer(cwd: Optional[str], *, force: bool = False) -> GitFooterInfo:
    text = (cwd or "").strip()
    if not text:
        return GitFooterInfo(dir_name="", branch=None, modified=0, untracked=0)

    try:
        key = str(Path(text).expanduser().resolve())
    except OSError:
        key = text

    now = time.monotonic()
    if not force:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_S:
            return cached[1]

    info = _resolve_git_footer_uncached(key)
    _cache[key] = (now, info)
    return info


def clear_git_footer_cache(cwd: Optional[str] = None) -> None:
    """Clear all cached footers, or only the entry for ``cwd`` when given."""
    if cwd is None:
        _cache.clear()
        return
    text = (cwd or "").strip()
    if not text:
        return
    try:
        key = str(Path(text).expanduser().resolve())
    except OSError:
        key = text
    _cache.pop(key, None)
