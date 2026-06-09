"""Build do dashboard web (Vite → ector_cli/web_dist)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ector_cli.tui_launch import tui_startup_spinner


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

    def _run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        # Capture so `ector localhost` doesn't spam pnpm/vite logs.
        # stderr is merged into stdout so CalledProcessError carries both.
        return subprocess.run(
            cmd,
            cwd=str(dashboard_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    try:
        with tui_startup_spinner("Preparando web…"):
            lock = dashboard_dir / "pnpm-lock.yaml"
            if pm_name == "pnpm" and lock.is_file():
                # Avoid pnpm lifecycle-script warnings for esbuild (and keep output quiet
                # for `ector localhost`). For pnpm v10, this maps to `only-built-dependencies`.
                install_argv = [
                    pm_bin,
                    "install",
                    "--frozen-lockfile",
                    "--config.only-built-dependencies[]=esbuild",
                ]
            else:
                install_argv = [pm_bin, "install", "--config.only-built-dependencies[]=esbuild"]
        with tui_startup_spinner("Instalando dependências…"):
            _run_checked(install_argv)
        with tui_startup_spinner("Aguarde um instante…"):
            _run_checked([pm_bin, "run", "build"])
    except subprocess.CalledProcessError as exc:
        last_output = (exc.output or "").strip()
        # pnpm v10+ can block dependency postinstall/build scripts until approved.
        # Fall back to npm so `ector localhost` remains usable in non-interactive
        # environments where `pnpm approve-builds` is not practical.
        if pm_name == "pnpm":
            npm_bin = shutil.which("npm")
            if npm_bin:
                print(
                    "Falha no build via pnpm. Tentando fallback com npm…"
                )
                try:
                    with tui_startup_spinner("Instalando dependências…"):
                        subprocess.run(
                            [npm_bin, "install"],
                            cwd=dashboard_dir,
                            check=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                    with tui_startup_spinner("Aguarde um instante…"):
                        subprocess.run(
                            [npm_bin, "run", "build"],
                            cwd=dashboard_dir,
                            check=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
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
