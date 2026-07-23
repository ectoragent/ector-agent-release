"""Repo/branch PR-readiness summary for the dashboard's top git status bar.

Separate from git_footer.py (which the composer footer polls frequently and
must stay cheap) — this does a couple of extra `git` calls (base-branch
detection, diff --shortstat against it) that are fine at a slower poll
interval but shouldn't run on every footer refresh.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from agent.git_footer import _run_git, cwd_dir_name, resolve_git_footer

# Short enough that idle polls (~8s) see branch switches; force=True bypasses.
_CACHE_TTL_S = 5.0
_cache: Dict[str, Tuple[float, "GitPrStatus"]] = {}

_REMOTE_GITHUB_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
_INSERTIONS_RE = re.compile(r"(\d+) insertion")
_DELETIONS_RE = re.compile(r"(\d+) deletion")

_COMMON_BASE_BRANCHES = ("main", "master", "develop")


@dataclass(frozen=True)
class GitPrStatus:
    repo_name: str
    branch: Optional[str]
    base_branch: Optional[str]
    insertions: int
    deletions: int
    needs_attention: bool
    owner: Optional[str]
    repo: Optional[str]
    ahead: int = 0
    behind: int = 0
    modified: int = 0
    untracked: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "repo_name": self.repo_name,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "diff_insertions": self.insertions,
            "diff_deletions": self.deletions,
            "needs_attention": self.needs_attention,
            "github_owner": self.owner,
            "github_repo": self.repo,
            "ahead": self.ahead,
            "behind": self.behind,
            "modified": self.modified,
            "untracked": self.untracked,
        }


def _parse_github_remote(remote_url: str) -> Optional[Tuple[str, str]]:
    match = _REMOTE_GITHUB_RE.search(remote_url.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _detect_base_branch(cwd: str, current_branch: str) -> Optional[str]:
    symbolic = _run_git(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if symbolic:
        candidate = symbolic.strip()
        if candidate.startswith("origin/"):
            candidate = candidate[len("origin/") :]
        if candidate and candidate != current_branch:
            return candidate
    for name in _COMMON_BASE_BRANCHES:
        if name == current_branch:
            continue
        if _run_git(cwd, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}") is not None:
            return name
        if _run_git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return None


def _diff_shortstat(cwd: str, base_branch: str) -> Tuple[int, int]:
    out = _run_git(cwd, "diff", f"{base_branch}...HEAD", "--shortstat")
    if not out:
        return 0, 0
    ins_match = _INSERTIONS_RE.search(out)
    del_match = _DELETIONS_RE.search(out)
    insertions = int(ins_match.group(1)) if ins_match else 0
    deletions = int(del_match.group(1)) if del_match else 0
    return insertions, deletions


def _resolve_git_pr_status_uncached(cwd: str, *, force: bool = False) -> GitPrStatus:
    footer = resolve_git_footer(cwd, force=force)
    directory = footer.dir_name or cwd_dir_name(cwd)

    if not footer.branch:
        return GitPrStatus(
            repo_name=directory,
            branch=None,
            base_branch=None,
            insertions=0,
            deletions=0,
            needs_attention=False,
            owner=None,
            repo=None,
        )
    ahead = footer.ahead
    behind = footer.behind
    modified = footer.modified
    untracked = footer.untracked

    toplevel = _run_git(cwd, "rev-parse", "--show-toplevel")
    repo_name = Path(toplevel.strip()).name if toplevel else directory

    owner: Optional[str] = None
    repo: Optional[str] = None
    remote_url = _run_git(cwd, "remote", "get-url", "origin")
    if remote_url:
        parsed = _parse_github_remote(remote_url)
        if parsed:
            owner, repo = parsed

    base_branch = _detect_base_branch(cwd, footer.branch)
    insertions, deletions = (
        _diff_shortstat(cwd, base_branch) if base_branch else (0, 0)
    )

    needs_attention = bool(footer.modified or footer.untracked)

    return GitPrStatus(
        repo_name=repo_name,
        branch=footer.branch,
        base_branch=base_branch,
        insertions=insertions,
        deletions=deletions,
        needs_attention=needs_attention,
        owner=owner,
        repo=repo,
        ahead=ahead,
        behind=behind,
        modified=modified,
        untracked=untracked,
    )


def resolve_git_pr_status(cwd: Optional[str], *, force: bool = False) -> GitPrStatus:
    text = (cwd or "").strip()
    if not text:
        return GitPrStatus(
            repo_name="",
            branch=None,
            base_branch=None,
            insertions=0,
            deletions=0,
            needs_attention=False,
            owner=None,
            repo=None,
        )

    try:
        key = str(Path(text).expanduser().resolve())
    except OSError:
        key = text

    now = time.monotonic()
    if not force:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_S:
            return cached[1]

    info = _resolve_git_pr_status_uncached(key, force=force)
    _cache[key] = (now, info)
    return info


def clear_git_pr_status_cache(cwd: Optional[str] = None) -> None:
    """Clear all cached PR statuses, or only the entry for ``cwd`` when given."""
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
