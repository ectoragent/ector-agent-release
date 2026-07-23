"""Detect the dev-server framework (Vite/Next.js/etc.) at a project directory.

Used by the dashboard's Browser panel so the user can start their own dev
server with one click, without asking the agent to do it.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

_LOCKFILE_MANAGERS: list[tuple[str, str]] = [
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
    ("npm-shrinkwrap.json", "npm"),
]

_RUN_PREFIX = {"npm": "npm run", "yarn": "yarn", "pnpm": "pnpm", "bun": "bun run"}

_PACKAGE_MANAGER_FIELD_RE = re.compile(r"^(npm|yarn|pnpm|bun)\b")

_YARNRC_FILES = (".yarnrc.yml", ".yarnrc")
_PNPM_WORKSPACE_FILE = "pnpm-workspace.yaml"

# When lockfiles are gitignored (fresh clone / local-only), node_modules layout
# is still a reliable signal of which manager last installed deps.
_NODE_MODULES_MARKERS: list[tuple[str, str]] = [
    (os.path.join("node_modules", ".pnpm"), "pnpm"),
    (os.path.join("node_modules", ".yarn-state.yml"), "yarn"),
    (os.path.join("node_modules", ".yarn-integrity"), "yarn"),
    (os.path.join("node_modules", ".package-lock.json"), "npm"),
]

_MAX_ANCESTOR_LEVELS = 6

_FRAMEWORK_BY_DEP: list[tuple[str, str, int]] = [
    ("next", "next", 3000),
    ("nuxt3", "nuxt", 3000),
    ("nuxt", "nuxt", 3000),
    ("vite", "vite", 5173),
    ("astro", "astro", 4321),
    ("react-scripts", "cra", 3000),
]

_FALLBACK_COMMAND_BY_FRAMEWORK = {
    "next": "npx next dev",
    "vite": "npx vite",
}


def _package_manager_from_field(data: dict[str, Any]) -> str | None:
    """Corepack's `packageManager` field (e.g. "pnpm@8.15.0") — an explicit,
    authoritative signal that beats guessing from whichever lockfile happens
    to be present (or committed) in the working tree."""
    raw = data.get("packageManager")
    if not isinstance(raw, str):
        return None
    match = _PACKAGE_MANAGER_FIELD_RE.match(raw.strip())
    return match.group(1) if match else None


def _walk_up_dirs(start: str, max_levels: int = _MAX_ANCESTOR_LEVELS):
    """Yield *start* then its ancestors, stopping at the repo root (a `.git`
    directory) or the filesystem root — whichever comes first."""
    current = os.path.abspath(start)
    for _ in range(max_levels):
        yield current
        if os.path.isdir(os.path.join(current, ".git")):
            return
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def _package_manager_from_volta(data: dict[str, Any]) -> str | None:
    """Volta pins (e.g. ``"volta": {"yarn": "1.22.19"}``) — weaker than
    Corepack's ``packageManager`` but stronger than guessing from leftovers."""
    volta = data.get("volta")
    if not isinstance(volta, dict):
        return None
    for manager in ("pnpm", "yarn", "bun", "npm"):
        if manager in volta:
            return manager
    return None


def _package_manager_signal(directory: str) -> str | None:
    """packageManager field, lockfile, or yarn/pnpm workspace config at *directory*."""
    pkg_path = os.path.join(directory, "package.json")
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = None
        if isinstance(data, dict):
            from_field = _package_manager_from_field(data)
            if from_field:
                return from_field
            from_volta = _package_manager_from_volta(data)
            if from_volta:
                return from_volta
    for fname, manager in _LOCKFILE_MANAGERS:
        if os.path.isfile(os.path.join(directory, fname)):
            return manager
    # Yarn/pnpm workspace config can exist before any lockfile is committed
    # (fresh clone, gitignored lockfile) — still a solid signal.
    if any(os.path.isfile(os.path.join(directory, f)) for f in _YARNRC_FILES):
        return "yarn"
    if os.path.isfile(os.path.join(directory, _PNPM_WORKSPACE_FILE)):
        return "pnpm"
    for relpath, manager in _NODE_MODULES_MARKERS:
        marker = os.path.join(directory, relpath)
        if os.path.isdir(marker) or os.path.isfile(marker):
            return manager
    return None


def _detect_package_manager(cwd: str) -> str:
    """Walk up from *cwd* to the repo root — monorepos/workspaces usually keep
    a single lockfile (or `packageManager` field) at the root, not inside
    each package's own directory."""
    for directory in _walk_up_dirs(cwd):
        signal = _package_manager_signal(directory)
        if signal:
            return signal
    return "npm"


def detect_dev_project(cwd: str) -> dict[str, Any]:
    """Best-effort framework/dev-command detection from package.json at cwd."""
    result: dict[str, Any] = {
        "cwd": cwd,
        "framework": "unknown",
        "package_manager": "npm",
        "command": None,
        "port": None,
    }

    pkg_path = os.path.join(cwd, "package.json")
    if not os.path.isfile(pkg_path):
        return result

    try:
        with open(pkg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return result
    if not isinstance(data, dict):
        return result

    deps: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section)

    scripts = data.get("scripts")
    scripts = scripts if isinstance(scripts, dict) else {}

    framework = "unknown"
    port = None
    for dep_name, label, default_port in _FRAMEWORK_BY_DEP:
        if dep_name in deps:
            framework = label
            port = default_port
            break

    manager = _detect_package_manager(cwd)
    script_name = "dev" if "dev" in scripts else ("start" if "start" in scripts else None)

    command = None
    if script_name:
        command = f"{_RUN_PREFIX[manager]} {script_name}"
    elif framework in _FALLBACK_COMMAND_BY_FRAMEWORK:
        command = _FALLBACK_COMMAND_BY_FRAMEWORK[framework]

    result.update(
        {
            "framework": framework,
            "package_manager": manager,
            "command": command,
            "port": port,
        }
    )
    return result
