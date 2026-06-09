"""Resolve the git checkout directory for installed Ector Agent copies."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from ector_constants import get_ector_home

# Legacy and current install directory names under ECTOR_HOME.
_INSTALL_DIR_NAMES = ("agent", "ector-agent")

# FHS layout on Linux root installs (see scripts/install.sh).
_FHS_INSTALL_DIR = Path("/usr/local/lib/ector-agent")

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _shared_code_install_root(ector_home: Path) -> Path:
    """When ``ECTOR_HOME`` is a named profile, return the shared install root.

    Example: ``~/.ector/profiles/coder`` → ``~/.ector``.
    """
    try:
        resolved = ector_home.expanduser().resolve()
    except OSError:
        resolved = ector_home.expanduser()
    if resolved.parent.name == "profiles":
        return resolved.parent.parent
    return resolved


def _iter_install_search_bases() -> list[Path]:
    """Directories that may contain ``agent/`` or ``ector-agent/`` checkouts."""
    seen: set[str] = set()
    bases: list[Path] = []

    def add(base: Path) -> None:
        try:
            key = str(base.expanduser().resolve())
        except OSError:
            key = str(base.expanduser())
        if key not in seen:
            seen.add(key)
            bases.append(base.expanduser())

    ector_home = get_ector_home()
    add(ector_home)
    shared = _shared_code_install_root(ector_home)
    if shared != ector_home:
        add(shared)

    return bases


def _first_git_checkout_under(bases: list[Path]) -> Optional[Path]:
    for base in bases:
        for name in _INSTALL_DIR_NAMES:
            candidate = base / name
            if (candidate / ".git").is_dir():
                return candidate
    return None


def is_package_tree_install_dir(path: Path) -> bool:
    """True when ``path`` is the Python package tree this process loaded from."""
    try:
        return path.resolve() == _PACKAGE_ROOT.resolve()
    except OSError:
        return False


def looks_like_release_install_remote(install_dir: Path) -> bool:
    """True when ``origin`` points at the public release repository."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=str(install_dir),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    url = (result.stdout or "").strip().lower()
    return "ector-agent-release" in url


def resolve_install_dir() -> Optional[Path]:
    """Return the active Ector code checkout, or None if this is not a git install.

    Search order:
    1. ``$ECTOR_INSTALL_DIR`` when set and contains ``.git``
    2. ``$ECTOR_HOME/{agent,ector-agent}`` then the same under the shared
       install root when ``ECTOR_HOME`` is a named profile
    3. ``/usr/local/lib/ector-agent`` (FHS root layout)
    4. The running package tree (editable / dev checkout)
    """
    explicit = os.environ.get("ECTOR_INSTALL_DIR", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if (candidate / ".git").is_dir():
            return candidate

    found = _first_git_checkout_under(_iter_install_search_bases())
    if found is not None:
        return found

    if (_FHS_INSTALL_DIR / ".git").is_dir():
        return _FHS_INSTALL_DIR

    if (_PACKAGE_ROOT / ".git").is_dir():
        return _PACKAGE_ROOT

    return None


def resolve_install_script(install_dir: Path) -> Optional[Path]:
    """Return the installer script path for ``install_dir``, if present."""
    import sys

    candidates = ("scripts/install.sh", "install.sh")
    if sys.platform == "win32":
        candidates = ("scripts/install.ps1",) + candidates
    for rel in candidates:
        candidate = install_dir / rel
        if candidate.is_file():
            return candidate
    return None
