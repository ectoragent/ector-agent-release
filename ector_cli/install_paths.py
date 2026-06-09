"""Resolve the git checkout directory for installed Ector Agent copies."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from ector_constants import get_ector_home

_INIT_REL = "ector_cli/__init__.py"
_VERSION_FIELD_RE = re.compile(
    r"^__(?:version_name__|version_code__|version__|release_name__|release_date__)\s*=.*$",
    re.MULTILINE,
)

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


def parse_version_metadata(content: str) -> tuple[str, int]:
    name_m = re.search(r'__version_name__\s*=\s*"([^"]+)"', content)
    if not name_m:
        name_m = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    if not name_m:
        raise ValueError("missing __version_name__")
    code_m = re.search(r"__version_code__\s*=\s*(\d+)", content)
    code = int(code_m.group(1)) if code_m else 0
    return name_m.group(1), code


def format_version_label(version_name: str, version_code: int | None = None) -> str:
    name = (version_name or "").strip().lstrip("vV")
    if not name:
        return ""
    label = f"v{name}"
    if version_code is not None and version_code > 0:
        return f"{label} ({version_code})"
    return label


def read_install_version(install_dir: Path) -> tuple[str, int] | None:
    init_py = install_dir / _INIT_REL
    if not init_py.is_file():
        return None
    try:
        return parse_version_metadata(init_py.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_git_ref_version(repo_dir: Path, git_ref: str) -> tuple[str, int] | None:
    try:
        proc = subprocess.run(
            ["git", "show", f"{git_ref}:{_INIT_REL}"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        return parse_version_metadata(proc.stdout)
    except ValueError:
        return None


def write_install_version(
    version_file: Path,
    version_name: str,
    version_code: int,
) -> None:
    """Persist versionName/versionCode in ``ector_cli/__init__.py``."""
    content = version_file.read_text(encoding="utf-8")
    content = _VERSION_FIELD_RE.sub("", content).rstrip() + "\n\n"
    content += f'__version_name__ = "{version_name}"\n'
    content += f"__version_code__ = {version_code}\n"
    content += "__version__ = __version_name__\n"
    version_file.write_text(content, encoding="utf-8")


def bump_install_version(version_file: Path) -> tuple[str, int]:
    name, code = parse_version_metadata(version_file.read_text(encoding="utf-8"))
    new_code = code + 1
    write_install_version(version_file, name, new_code)
    return name, new_code


def format_release_version(version_name: str, version_code: int) -> str:
    """Release tag label without ``v`` prefix — e.g. ``1.0 (42)``."""
    return f"{version_name} ({version_code})"


def package_version_meta() -> tuple[str, int]:
    """versionName/versionCode from the loaded ``ector_cli`` package."""
    try:
        import ector_cli as pkg

        name = (
            getattr(pkg, "__version_name__", None)
            or getattr(pkg, "__version__", None)
            or ""
        )
        return str(name).strip(), int(getattr(pkg, "__version_code__", 0) or 0)
    except Exception:
        return "", 0


def running_version_label() -> str:
    """User-facing label for the running install — e.g. ``v1.0 (42)``."""
    name, code = package_version_meta()
    return format_version_label(name, code)
