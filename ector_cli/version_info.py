"""Read and format Ector release metadata (versionName + versionCode)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_INIT_REL = "ector_cli/__init__.py"
_VERSION_FIELD_RE = re.compile(
    r"^__(?:version_name__|version_code__|version__|release_name__|release_date__)\s*=.*$",
    re.MULTILINE,
)


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
