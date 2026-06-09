"""
Auto-install Node dependencies for scripts/whatsapp-bridge (dashboard + pairing).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = PROJECT_ROOT / "scripts" / "whatsapp-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"
_NODE_MODULES = BRIDGE_DIR / "node_modules"
_BAILEYS_INDEX = _NODE_MODULES / "@whiskeysockets" / "baileys" / "lib" / "index.js"
_BAILEYS_BARE = _NODE_MODULES / "baileys" / "lib" / "index.js"
_QRCODE_PKG = _NODE_MODULES / "qrcode" / "package.json"

_install_lock = threading.Lock()


def _baileys_present() -> bool:
    return _BAILEYS_INDEX.exists() or _BAILEYS_BARE.exists()


def bridge_deps_satisfied() -> bool:
    if not BRIDGE_SCRIPT.exists():
        return False
    if not _NODE_MODULES.exists() or not _baileys_present():
        return False
    return _QRCODE_PKG.exists()


def _needs_lockfile_migration() -> bool:
    bridge_pkg = BRIDGE_DIR / "package.json"
    bridge_lock = BRIDGE_DIR / "pnpm-lock.yaml"
    if not bridge_pkg.exists() or not bridge_lock.exists():
        return False
    try:
        pkg_text = bridge_pkg.read_text(encoding="utf-8")
        lock_text = bridge_lock.read_text(encoding="utf-8")
    except OSError:
        return False
    return '"@whiskeysockets/baileys": "7.0.0-rc.9"' in pkg_text and (
        "WhiskeySockets/Baileys#" in lock_text or "/Baileys/tar.gz" in lock_text
    )


def _refresh_pnpm_lockfile(pnpm_bin: str) -> bool:
    result = subprocess.run(
        [pnpm_bin, "install", "--lockfile-only"],
        cwd=str(BRIDGE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
    )
    return result.returncode == 0


def _run_pm_install(pm_bin: str) -> subprocess.CompletedProcess[str]:
    pm = os.path.basename(pm_bin)
    if pm == "pnpm":
        cmd = [pm_bin, "install", "--no-frozen-lockfile"]
    else:
        cmd = [pm_bin, "install", "--no-fund", "--no-audit"]
    return subprocess.run(
        cmd,
        cwd=str(BRIDGE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=600,
    )


def _install_output_tail(result: subprocess.CompletedProcess[str], lines: int = 24) -> str:
    out = (result.stdout or "").strip()
    if not out:
        return "(sem saída)"
    parts = out.splitlines()
    return "\n".join(parts[-lines:])


def ensure_bridge_deps(*, force: bool = False) -> tuple[bool, str]:
    """
    Ensure whatsapp-bridge node_modules exist. Installs via pnpm/npm when missing.

    Returns (ok, error_message).
    """
    if not BRIDGE_SCRIPT.exists():
        return False, f"Script da ponte não encontrado: {BRIDGE_SCRIPT}"

    if bridge_deps_satisfied() and not force:
        return True, ""

    with _install_lock:
        if bridge_deps_satisfied() and not force:
            return True, ""

        try:
            from ector_cli.tui_launch import ensure_tui_node

            ensure_tui_node(PROJECT_ROOT)
        except Exception as exc:
            return False, f"Node.js não disponível: {exc}"

        if not shutil.which("node"):
            return (
                False,
                "Node.js não encontrado no PATH. Instale em https://nodejs.org "
                "(ou use nvm/fnm e reinicie o dashboard no mesmo terminal).",
            )

        pnpm_bin = shutil.which("pnpm")
        npm_bin = shutil.which("npm")
        pm_bin = pnpm_bin or npm_bin
        if not pm_bin:
            return (
                False,
                "npm/pnpm não encontrado. Instale Node.js (inclui npm) em https://nodejs.org",
            )

        if _NODE_MODULES.exists() and not _baileys_present():
            shutil.rmtree(_NODE_MODULES, ignore_errors=True)

        if _needs_lockfile_migration() and pnpm_bin:
            _refresh_pnpm_lockfile(pnpm_bin)

        try:
            result = _run_pm_install(pm_bin)
        except subprocess.TimeoutExpired:
            return False, "Instalação das dependências WhatsApp expirou (timeout 10 min)."
        except OSError as exc:
            return False, str(exc)

        pnpm_err = (result.stdout or "") if result.returncode != 0 else ""
        if (
            result.returncode != 0
            and pnpm_bin
            and os.path.basename(pm_bin) == "pnpm"
            and ("ERR_PNPM_PREPARE_PACKAGE" in pnpm_err or "yarn-install" in pnpm_err)
        ):
            try:
                from ector_cli.yarn_bootstrap import ensure_yarn_on_path

                if ensure_yarn_on_path():
                    result = _run_pm_install(pnpm_bin)
            except ImportError:
                pass
            if result.returncode != 0 and _refresh_pnpm_lockfile(pnpm_bin):
                result = _run_pm_install(pnpm_bin)

        if result.returncode != 0 and pnpm_bin and npm_bin and pm_bin != npm_bin:
            try:
                result = _run_pm_install(npm_bin)
                pm_bin = npm_bin
            except subprocess.TimeoutExpired:
                return False, "Instalação das dependências WhatsApp expirou (timeout 10 min)."

        if result.returncode != 0:
            pm_name = os.path.basename(pm_bin or "npm")
            return (
                False,
                f"Falha ao instalar dependências da ponte ({pm_name}):\n"
                f"{_install_output_tail(result)}",
            )

        if not bridge_deps_satisfied():
            return (
                False,
                "Instalação concluída mas dependências ainda em falta. "
                "Tente novamente ou execute `ector whatsapp` no terminal.",
            )

        return True, ""
