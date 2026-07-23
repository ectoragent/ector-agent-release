"""Node.js bootstrap and pnpm helpers for web build and WhatsApp bridge."""

from __future__ import annotations

import contextlib
import itertools
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@contextlib.contextmanager
def build_startup_spinner(message: str):
    """TTY spinner for slow install/build steps."""
    if os.environ.get("ECTOR_QUIET"):
        yield
        return
    if not sys.stderr.isatty():
        print(message, file=sys.stderr, flush=True)
        yield
        return

    stop = threading.Event()
    frames = itertools.cycle(_SPINNER_FRAMES)

    def _spin() -> None:
        while not stop.wait(0.08):
            frame = next(frames)
            sys.stderr.write(f"\r  {frame} {message}")
            sys.stderr.flush()

    thread = threading.Thread(target=_spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=0.5)
        pad = len(message) + 4
        sys.stderr.write(f"\r{' ' * pad}\r")
        sys.stderr.flush()


def maybe_bootstrap_yarn() -> None:
    """Baileys (git tarball) runs ``yarn install`` in ``prepare`` — need yarn even without npm."""
    if not shutil.which("node"):
        return
    try:
        from ector_cli.yarn_bootstrap import ensure_yarn_on_path
    except ImportError:
        return
    ensure_yarn_on_path()


def ensure_node_runtime(project_root: Path) -> None:
    """Make sure ``node`` + ``npm`` are on PATH for web build / WhatsApp bridge."""
    if os.environ.get("ECTOR_SKIP_NODE_BOOTSTRAP"):
        return

    npm_bin = shutil.which("npm")

    def _npm_install_global(pkg: str) -> None:
        if not npm_bin:
            return
        try:
            subprocess.run(
                [npm_bin, "install", "-g", pkg],
                capture_output=True,
                text=True,
                timeout=300,
                env={**os.environ},
                check=False,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass

    if shutil.which("node") and npm_bin:
        if not shutil.which("yarn"):
            _npm_install_global("yarn")
        if not shutil.which("pnpm"):
            _npm_install_global("pnpm")

    maybe_bootstrap_yarn()

    if shutil.which("node") and (shutil.which("pnpm") or shutil.which("npm")):
        return

    helper = project_root / "scripts" / "lib" / "node-bootstrap.sh"
    if not helper.is_file():
        return

    ector_home = os.environ.get("ECTOR_HOME") or str(Path.home() / ".ector")
    try:
        with build_startup_spinner("Preparando Node.js…"):
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{helper}" >&2 && ensure_node >&2 && command -v node',
                ],
                env={**os.environ, "ECTOR_HOME": ector_home},
                capture_output=True,
                text=True,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return

    parts = os.environ.get("PATH", "").split(os.pathsep)
    extras: list[Path] = []

    resolved = (result.stdout or "").strip()
    if resolved:
        extras.append(Path(resolved).resolve().parent)

    extras.extend([Path(ector_home) / "node" / "bin", Path.home() / ".local" / "bin"])

    for extra in extras:
        s = str(extra)
        if extra.is_dir() and s not in parts:
            parts.insert(0, s)
    os.environ["PATH"] = os.pathsep.join(parts)
    maybe_bootstrap_yarn()


def _pnpm_major_version(pm_bin: str) -> int:
    try:
        proc = subprocess.run(
            [pm_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return 0
        return int((proc.stdout or "0").strip().split(".", 1)[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _pnpm_ci_env(base: dict | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    env.setdefault("CI", "true")
    env.setdefault("PNPM_CONFIG_CONFIRM_MODULES_PURGE", "false")
    env.setdefault("npm_config_only_built_dependencies", "esbuild")
    return env


def ensure_pnpm_esbuild_allowlist(project_dir: Path, pm_bin: str | None = None) -> None:
    """Allow esbuild lifecycle scripts: .npmrc (pnpm 10) + pnpm-workspace.yaml (pnpm 11+)."""
    npmrc = project_dir / ".npmrc"
    try:
        existing = npmrc.read_text(encoding="utf-8") if npmrc.is_file() else ""
    except OSError:
        existing = ""
    if "only-built-dependencies" not in existing and "onlyBuiltDependencies" not in existing:
        line = "only-built-dependencies[]=esbuild\n"
        try:
            with npmrc.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                if not existing:
                    fh.write("# allow esbuild postinstall (pnpm 10)\n")
                fh.write(line)
        except OSError:
            pass

    ws = project_dir / "pnpm-workspace.yaml"
    if ws.is_file():
        try:
            text = ws.read_text(encoding="utf-8")
            if "allowBuilds" not in text or "esbuild" not in text:
                ws.write_text(
                    text.rstrip()
                    + "\n\n# Ector: allow esbuild lifecycle scripts (pnpm 11+)\n"
                    + "allowBuilds:\n  esbuild: true\n",
                    encoding="utf-8",
                )
        except OSError:
            pass

    if not pm_bin:
        pm_bin = shutil.which("pnpm") or ""
    if pm_bin and _pnpm_major_version(pm_bin) >= 10:
        try:
            subprocess.run(
                [pm_bin, "approve-builds", "esbuild"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                check=False,
                env=_pnpm_ci_env(),
            )
        except (OSError, subprocess.SubprocessError):
            pass
