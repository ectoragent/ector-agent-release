"""Garante que o binário ``yarn`` exista no PATH (hooks ``prepare`` de deps git, ex.: Baileys)."""

from __future__ import annotations

import os
import shutil
import subprocess


def ensure_yarn_on_path(
    *,
    timeout_corepack: int = 120,
    timeout_install: int = 300,
) -> bool:
    """Tenta expor ``yarn`` via corepack, ``npm install -g`` ou ``pnpm add -g``.

    Imagens ou ambientes com apenas ``node`` + ``pnpm`` (sem ``npm`` no PATH)
    não passam pelo fluxo legado que instalava yarn só com npm — daí este helper.
    """
    if shutil.which("yarn"):
        return True

    env = {**os.environ}
    corepack = shutil.which("corepack")
    if corepack:
        try:
            subprocess.run(
                [corepack, "enable"],
                capture_output=True,
                text=True,
                timeout=timeout_corepack,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
    if shutil.which("yarn"):
        return True
    # ``corepack enable`` sozinho às vezes não expõe o shim até ``prepare`` (ex.: Node do apt).
    if corepack:
        try:
            subprocess.run(
                [corepack, "prepare", "yarn@4.6.0", "--activate"],
                capture_output=True,
                text=True,
                timeout=timeout_corepack,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
    if shutil.which("yarn"):
        return True

    npm_bin = shutil.which("npm")
    if npm_bin:
        try:
            subprocess.run(
                [npm_bin, "install", "-g", "yarn"],
                capture_output=True,
                text=True,
                timeout=timeout_install,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
    if shutil.which("yarn"):
        return True

    pnpm_bin = shutil.which("pnpm")
    if pnpm_bin:
        try:
            subprocess.run(
                [pnpm_bin, "add", "-g", "yarn"],
                capture_output=True,
                text=True,
                timeout=timeout_install,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
    return bool(shutil.which("yarn"))
