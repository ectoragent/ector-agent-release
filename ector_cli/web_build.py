"""Build do dashboard web (Vite → ector_cli/web_dist)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ector_cli.node_build import build_startup_spinner, ensure_pnpm_esbuild_allowlist


def web_dist_dir(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parent.parent
    return root / "ector_cli" / "web_dist"


def web_can_build_from_source(dashboard_dir: Path) -> bool:
    """True when a dev checkout has dashboard TypeScript sources."""
    return (dashboard_dir / "src").is_dir()


def web_is_prebuilt_release(project_root: Path, dashboard_dir: Path | None = None) -> bool:
    """Release tree ships ``ector_cli/web_dist`` without ``frontend/dashboard/src``."""
    dash = dashboard_dir or (project_root / "frontend" / "dashboard")
    index = web_dist_dir(project_root) / "index.html"
    if not index.is_file():
        return False
    return not web_can_build_from_source(dash)


def web_prebuilt_missing_message(project_root: Path) -> str:
    """User-facing error when release export lacks pre-built web assets."""
    return (
        "Dashboard não pré-compilado — ector_cli/web_dist/index.html ausente e "
        "não há fontes em frontend/dashboard/src para compilar. "
        "Reinstale a partir de um release completo "
        "(sync_public_release com pré-build, sem --no-prebuild)."
    )


def web_dist_is_stale(dashboard_dir: Path, dist: Path) -> bool:
    """True when dashboard sources are newer than the last web build."""
    index = dist / "index.html"
    if not index.is_file():
        return True
    dist_mtime = index.stat().st_mtime
    src = dashboard_dir / "src"
    if not src.is_dir():
        return False
    for path in src.rglob("*"):
        if path.is_file() and path.stat().st_mtime > dist_mtime:
            return True
    return False


def _dashboard_subprocess_env() -> dict[str, str]:
    """Non-interactive env for pnpm/npm under bare ``ector`` (no TTY)."""
    env = os.environ.copy()
    env.setdefault("CI", "true")
    env.setdefault("npm_config_yes", "true")
    return env


def _dashboard_deps_need_install(dashboard_dir: Path, pm_name: str) -> bool:
    """Skip install when node_modules already matches the lockfile/package.json."""
    node_modules = dashboard_dir / "node_modules"
    if not node_modules.is_dir():
        return True

    marker = node_modules / ".modules.yaml"
    if not marker.is_file():
        return True

    marker_mtime = marker.stat().st_mtime
    package_json = dashboard_dir / "package.json"
    if package_json.is_file() and package_json.stat().st_mtime > marker_mtime:
        return True

    if pm_name == "pnpm":
        lock = dashboard_dir / "pnpm-lock.yaml"
        if lock.is_file() and lock.stat().st_mtime > marker_mtime:
            return True
    else:
        lock = dashboard_dir / "package-lock.json"
        if lock.is_file() and lock.stat().st_mtime > marker_mtime:
            return True

    return False


def build_web_ui(dashboard_dir: Path, *, fatal: bool = True) -> bool:
    """Garante ``ector_cli/web_dist/index.html`` existe, compilando se necessário."""
    project_root = dashboard_dir.parent.parent
    dist = web_dist_dir(project_root)
    index = dist / "index.html"
    if index.is_file() and not web_dist_is_stale(dashboard_dir, dist):
        return True

    if not web_can_build_from_source(dashboard_dir):
        msg = web_prebuilt_missing_message(project_root)
        if fatal:
            print(msg, file=sys.stderr)
        else:
            print(msg)
        return False

    pm_bin = shutil.which("pnpm") or shutil.which("npm")
    if not pm_bin:
        msg = (
            "Dashboard não compilado e nenhum gerenciador npm/pnpm no PATH.\n"
            "Execute: cd frontend/dashboard && npm run build"
        )
        if fatal:
            print(msg, file=sys.stderr)
            return False
        print(msg)
        return False

    pm_name = os.path.basename(pm_bin)
    if pm_name == "pnpm":
        ensure_pnpm_esbuild_allowlist(dashboard_dir, pm_bin)
    env = _dashboard_subprocess_env()

    def _run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        # Capture so bare `ector` doesn't spam pnpm/vite logs.
        # stderr is merged into stdout so CalledProcessError carries both.
        return subprocess.run(
            cmd,
            cwd=str(dashboard_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

    def _run_install(cmd: list[str]) -> None:
        result = subprocess.run(
            cmd,
            cwd=str(dashboard_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        if result.returncode == 0:
            return
        output = (result.stdout or "").strip()
        if result.returncode != 0 and (dashboard_dir / "node_modules").is_dir():
            # pnpm may warn about ignored builds yet leave node_modules usable.
            if "Already up to date" in output or "Packages:" in output:
                return
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=output,
        )

    try:
        with build_startup_spinner("Preparando web…"):
            lock = dashboard_dir / "pnpm-lock.yaml"
            if pm_name == "pnpm" and lock.is_file():
                install_argv = [pm_bin, "install", "--frozen-lockfile"]
            else:
                install_argv = [pm_bin, "install"]

        if _dashboard_deps_need_install(dashboard_dir, pm_name):
            with build_startup_spinner("Instalando dependências…"):
                _run_install(install_argv)
        with build_startup_spinner("Aguarde um instante…"):
            _run_checked([pm_bin, "run", "build"])
    except subprocess.CalledProcessError as exc:
        last_output = (exc.output or "").strip()
        # pnpm v10+ can block dependency postinstall/build scripts until approved.
        # Fall back to npm so bare `ector` remains usable in non-interactive
        # environments where `pnpm approve-builds` is not practical.
        if pm_name == "pnpm":
            npm_bin = shutil.which("npm")
            if npm_bin:
                print(
                    "Falha no build via pnpm. Tentando fallback com npm…"
                )
                try:
                    if _dashboard_deps_need_install(dashboard_dir, "npm"):
                        with build_startup_spinner("Instalando dependências…"):
                            _run_install([npm_bin, "install"])
                    with build_startup_spinner("Aguarde um instante…"):
                        _run_checked([npm_bin, "run", "build"])
                    return index.is_file()
                except subprocess.CalledProcessError as npm_exc:
                    last_output = (npm_exc.output or "").strip() or last_output
        if fatal:
            if last_output:
                preview = "\n".join(last_output.splitlines()[-40:])
                print("Detalhe (últimas linhas):", file=sys.stderr)
                print(preview, file=sys.stderr)
            print(
                "Falha ao compilar o dashboard. Tente manualmente:\n"
                f"  cd {dashboard_dir} && npm run build",
                file=sys.stderr,
            )
        return False

    if not index.is_file():
        if fatal:
            print(f"Build não produziu {index}", file=sys.stderr)
        return False
    return True
