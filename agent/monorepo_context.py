"""Detect monorepo / multi-package workspaces and build a compact prompt hint.

Injected into the session working-directory guidance so the agent knows the
repo layout before the first tool call — without breaking prompt caching mid-
conversation (topology is computed once at system-prompt build time).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_MAX_PACKAGES_LISTED = 24
_MAX_HINT_CHARS = 2_500

_WORKSPACE_MARKERS = (
    "pnpm-workspace.yaml",
    "pnpm-workspace.yml",
    "turbo.json",
    "turbo.jsonc",
    "nx.json",
    "lerna.json",
    "rush.json",
    "go.work",
    "Cargo.toml",  # may or may not be a workspace — checked below
    "package.json",  # workspaces field checked below
    "pyproject.toml",  # uv/poetry workspace members checked below
)


@dataclass
class MonorepoTopology:
    """Compact description of a detected multi-package workspace."""

    root: Path
    tools: List[str] = field(default_factory=list)
    packages: List[Tuple[str, str]] = field(default_factory=list)  # (rel_path, name)
    session_package: Optional[str] = None  # rel path of package containing cwd


def discover_monorepo_topology(cwd: Path) -> Optional[MonorepoTopology]:
    """Walk to git root (or filesystem) and detect a multi-package workspace."""
    try:
        start = cwd.expanduser().resolve()
    except OSError:
        return None

    root = _find_workspace_root(start)
    if root is None:
        return None

    tools: List[str] = []
    package_dirs: List[Path] = []

    if (root / "pnpm-workspace.yaml").is_file() or (root / "pnpm-workspace.yml").is_file():
        tools.append("pnpm workspaces")
        package_dirs.extend(_packages_from_pnpm_workspace(root))

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        ws_globs = _read_npm_workspaces(pkg_json)
        if ws_globs:
            if "npm/yarn/bun workspaces" not in tools and "pnpm workspaces" not in tools:
                tools.append("npm/yarn/bun workspaces")
            if not package_dirs:
                package_dirs.extend(_expand_workspace_globs(root, ws_globs))

    if (root / "turbo.json").is_file() or (root / "turbo.jsonc").is_file():
        tools.append("turbo")
    if (root / "nx.json").is_file():
        tools.append("nx")
    if (root / "lerna.json").is_file():
        tools.append("lerna")
    if (root / "rush.json").is_file():
        tools.append("rush")

    if (root / "go.work").is_file():
        tools.append("go work")
        if not package_dirs:
            package_dirs.extend(_packages_from_go_work(root))

    cargo = root / "Cargo.toml"
    if cargo.is_file() and _cargo_is_workspace(cargo):
        tools.append("cargo workspace")
        if not package_dirs:
            package_dirs.extend(_packages_from_cargo_workspace(root, cargo))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        members = _python_workspace_members(pyproject)
        if members:
            tools.append("python workspace")
            if not package_dirs:
                package_dirs.extend(_expand_workspace_globs(root, members))

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_dirs: List[Path] = []
    for d in package_dirs:
        try:
            resolved = d.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        if not resolved.is_dir():
            continue
        if resolved == root:
            continue
        seen.add(resolved)
        unique_dirs.append(resolved)

    # Need either an explicit workspace tool OR multiple packages
    if not tools and len(unique_dirs) < 2:
        return None
    # package.json without workspaces + turbo alone at a single package repo —
    # only accept if we have packages or a clear multi-tool workspace marker.
    if not unique_dirs and not any(
        t in {"pnpm workspaces", "npm/yarn/bun workspaces", "go work",
              "cargo workspace", "python workspace", "nx", "lerna", "rush"}
        for t in tools
    ):
        # turbo.json alone is common in monorepos — still hint if apps/packages exist
        heuristic = _heuristic_package_dirs(root)
        if len(heuristic) >= 2:
            unique_dirs = heuristic
            if "turbo" not in tools and "nx" not in tools:
                tools.append("apps/packages layout")
        else:
            return None

    if not unique_dirs and ("turbo" in tools or "nx" in tools):
        unique_dirs = _heuristic_package_dirs(root)
        if len(unique_dirs) < 2:
            return None

    packages: List[Tuple[str, str]] = []
    for d in unique_dirs:
        try:
            rel = str(d.relative_to(root))
        except ValueError:
            rel = str(d)
        packages.append((rel, _package_display_name(d)))

    packages.sort(key=lambda item: item[0])

    session_package = _session_package_rel(start, root, unique_dirs)

    return MonorepoTopology(
        root=root,
        tools=tools or ["multi-package"],
        packages=packages,
        session_package=session_package,
    )


def build_monorepo_topology_hint(cwd: Optional[str] = None) -> str:
    """Return a compact system-prompt block, or empty string if not a monorepo."""
    if cwd is None:
        import os

        cwd = os.getcwd()
    try:
        topology = discover_monorepo_topology(Path(cwd))
    except Exception as exc:
        logger.debug("monorepo topology discovery failed: %s", exc)
        return ""
    if topology is None:
        return ""
    return _format_topology_hint(topology)


def _format_topology_hint(topology: MonorepoTopology) -> str:
    tools = ", ".join(topology.tools)
    lines = [
        "# Topologia do monorepo",
        f"Raiz do workspace: `{topology.root}`.",
        f"Ferramentas: {tools}.",
    ]
    if topology.session_package:
        lines.append(
            f"Pacote da sessão (cwd): `{topology.session_package}` "
            f"— rode installs/builds/tests aqui ou com filter do gerenciador; "
            "não assuma que dependências do root valem neste package."
        )
    else:
        lines.append(
            "A sessão está na raiz do workspace — ao editar código, identifique o "
            "package alvo antes de instalar dependências ou rodar scripts."
        )

    listed = topology.packages[:_MAX_PACKAGES_LISTED]
    if listed:
        lines.append("Packages:")
        for rel, name in listed:
            if name and name != rel:
                lines.append(f"- `{rel}` ({name})")
            else:
                lines.append(f"- `{rel}`")
        remaining = len(topology.packages) - len(listed)
        if remaining > 0:
            lines.append(f"- … +{remaining} outros")

    lines.extend(
        [
            "Regras:",
            "- Preferir filter (`pnpm --filter`, `npx turbo run <task> --filter=…`, "
            "`nx run <proj>:<target>`) em vez de scripts globais cegos.",
            "- Confira o `package.json` / manifesto do package alvo antes de importar deps.",
            "- Respeite AGENTS.md / CLAUDE.md do package quando existirem (além da raiz).",
        ]
    )
    text = "\n".join(lines)
    if len(text) > _MAX_HINT_CHARS:
        text = text[:_MAX_HINT_CHARS] + "\n… [truncado]"
    return text


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _find_workspace_root(start: Path) -> Optional[Path]:
    """Nearest ancestor that looks like a workspace root, capped at git root."""
    git_root = None
    for parent in [start, *start.parents]:
        if (parent / ".git").exists():
            git_root = parent
            break

    best: Optional[Path] = None
    for directory in [start, *start.parents]:
        if _looks_like_workspace_root(directory):
            best = directory
            # Prefer the outermost workspace within the git tree (root package.json
            # with workspaces often sits at git root). Keep walking to git root.
        if git_root and directory == git_root:
            break
        if directory.parent == directory:
            break
    return best


def _looks_like_workspace_root(directory: Path) -> bool:
    if (directory / "pnpm-workspace.yaml").is_file() or (
        directory / "pnpm-workspace.yml"
    ).is_file():
        return True
    for name in ("turbo.json", "turbo.jsonc", "nx.json", "lerna.json", "rush.json", "go.work"):
        if (directory / name).is_file():
            return True
    pkg = directory / "package.json"
    if pkg.is_file() and _read_npm_workspaces(pkg):
        return True
    cargo = directory / "Cargo.toml"
    if cargo.is_file() and _cargo_is_workspace(cargo):
        return True
    pyproject = directory / "pyproject.toml"
    if pyproject.is_file() and _python_workspace_members(pyproject):
        return True
    return False


def _read_npm_workspaces(package_json: Path) -> List[str]:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    workspaces = data.get("workspaces")
    if isinstance(workspaces, list):
        return [str(item) for item in workspaces if isinstance(item, str)]
    if isinstance(workspaces, dict):
        packages = workspaces.get("packages")
        if isinstance(packages, list):
            return [str(item) for item in packages if isinstance(item, str)]
    return []


def _packages_from_pnpm_workspace(root: Path) -> List[Path]:
    for name in ("pnpm-workspace.yaml", "pnpm-workspace.yml"):
        path = root / name
        if path.is_file():
            globs = _parse_pnpm_workspace_packages(path)
            return _expand_workspace_globs(root, globs)
    return []


def _parse_pnpm_workspace_packages(path: Path) -> List[str]:
    """Parse `packages:` globs from pnpm-workspace.yaml without requiring full YAML.

    Falls back to PyYAML when available for complex files.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        import yaml

        data = yaml.safe_load(text) or {}
        packages = data.get("packages") if isinstance(data, dict) else None
        if isinstance(packages, list):
            return [str(item) for item in packages if isinstance(item, (str, int, float))]
    except Exception:
        pass

    # Minimal fallback: lines under `packages:` that look like `- pattern`
    globs: List[str] = []
    in_packages = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^packages:\s*$", stripped):
            in_packages = True
            continue
        if in_packages:
            if re.match(r"^[A-Za-z0-9_-]+:", stripped):
                break
            match = re.match(r"^-\s+['\"]?([^'\"]+)['\"]?\s*$", stripped)
            if match:
                globs.append(match.group(1).strip())
    return globs


def _expand_workspace_globs(root: Path, patterns: Sequence[str]) -> List[Path]:
    include: List[str] = []
    exclude: List[str] = []
    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            continue
        if pattern.startswith("!"):
            exclude.append(pattern[1:])
        else:
            include.append(pattern)

    found: List[Path] = []
    for pattern in include:
        found.extend(_glob_dirs(root, pattern))

    if exclude:
        excluded: set[Path] = set()
        for pattern in exclude:
            excluded.update(_glob_dirs(root, pattern))
        found = [p for p in found if p not in excluded]

    return found


def _glob_dirs(root: Path, pattern: str) -> List[Path]:
    # pnpm allows patterns like `packages/*` or `apps/**`
    try:
        matches = sorted(root.glob(pattern))
    except OSError:
        return []
    return [m for m in matches if m.is_dir()]


def _packages_from_go_work(root: Path) -> List[Path]:
    path = root / "go.work"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    dirs: List[Path] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("go "):
            continue
        if stripped == "use (" or stripped == ")" or stripped == "use":
            continue
        if stripped.startswith("use "):
            stripped = stripped[4:].strip()
        token = stripped.strip().strip("()")
        if not token or token.startswith(("replace", "exclude")):
            continue
        candidate = (root / token).resolve() if not Path(token).is_absolute() else Path(token)
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs


def _cargo_is_workspace(cargo_toml: Path) -> bool:
    try:
        text = cargo_toml.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"(?m)^\[workspace\]\s*$", text))


def _packages_from_cargo_workspace(root: Path, cargo_toml: Path) -> List[Path]:
    try:
        text = cargo_toml.read_text(encoding="utf-8")
    except OSError:
        return []
    # members = ["a", "b"] or members = ["crates/*"]
    match = re.search(
        r"(?ms)^\[workspace\].*?^members\s*=\s*\[(.*?)\]",
        text,
    )
    if not match:
        return _heuristic_package_dirs(root)
    body = match.group(1)
    members = re.findall(r'"([^"]+)"', body)
    return _expand_workspace_globs(root, members)


def _python_workspace_members(pyproject: Path) -> List[str]:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return []
    # uv: [tool.uv.workspace] members = [...]
    # poetry: [tool.poetry] packages / rarely true workspaces via [tool.poetry.group]
    match = re.search(
        r"(?ms)^\[tool\.uv\.workspace\].*?^members\s*=\s*\[(.*?)\]",
        text,
    )
    if match:
        return re.findall(r'"([^"]+)"', match.group(1))
    # Hatch / pantheon-style rarely — skip
    return []


def _heuristic_package_dirs(root: Path) -> List[Path]:
    """Fallback: top-level apps/*, packages/*, services/*, libs/*."""
    dirs: List[Path] = []
    for base_name in ("apps", "packages", "services", "libs", "crates", "modules"):
        base = root / base_name
        if not base.is_dir():
            continue
        try:
            children = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            continue
        dirs.extend(children)
    return dirs


def _package_display_name(directory: Path) -> str:
    pkg = directory / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            name = data.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        except (OSError, json.JSONDecodeError):
            pass
    cargo = directory / "Cargo.toml"
    if cargo.is_file():
        try:
            text = cargo.read_text(encoding="utf-8")
            match = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
            if match:
                return match.group(1)
        except OSError:
            pass
    pyproject = directory / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
            match = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
            if match:
                return match.group(1)
        except OSError:
            pass
    return directory.name


def _session_package_rel(
    session_cwd: Path,
    root: Path,
    package_dirs: Sequence[Path],
) -> Optional[str]:
    """Longest package path that contains session_cwd (or is equal)."""
    best: Optional[Path] = None
    for package in package_dirs:
        try:
            session_cwd.relative_to(package)
        except ValueError:
            continue
        if best is None or len(package.parts) > len(best.parts):
            best = package
    if best is None:
        return None
    try:
        return str(best.relative_to(root))
    except ValueError:
        return str(best)
