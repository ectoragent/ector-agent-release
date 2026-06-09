"""TUI bootstrap, build, and launch for ``ector chat``."""

from __future__ import annotations

import contextlib
import itertools
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from ector_constants import safe_getcwd


def print_tui_exit_summary(session_id: Optional[str]) -> None:
    """Print a shell-visible epilogue after TUI exits.

    Only summarizes *session_id* when provided — typically the session the
    user actually touched this run (see ``tui_run_session``). We intentionally
    do not fall back to "last TUI session in the DB", which would show stale
    data after opening ``ector`` and exiting immediately with Ctrl+C.
    """
    target = (session_id or "").strip()
    if not target:
        return

    db = None
    try:
        from ector_state import SessionDB

        db = SessionDB()
        session = db.get_session(target)
        if not session:
            return

        title = db.get_session_title(target)
        message_count = int(session.get("message_count") or 0)
        if message_count <= 0:
            return
        input_tokens = int(session.get("input_tokens") or 0)
        output_tokens = int(session.get("output_tokens") or 0)
        cache_read_tokens = int(session.get("cache_read_tokens") or 0)
        cache_write_tokens = int(session.get("cache_write_tokens") or 0)
        reasoning_tokens = int(session.get("reasoning_tokens") or 0)
        total_tokens = (
            input_tokens
            + output_tokens
            + cache_read_tokens
            + cache_write_tokens
            + reasoning_tokens
        )
    except Exception:
        return
    finally:
        if db is not None:
            db.close()

    print()
    print("Retome esta sessão com:")
    print(f"  ector --resume {target}")
    if title:
        print(f'  ector -c "{title}"')
    print()
    if title:
        print(f"Título:         {title}")
    print(f"Mensagens:      {message_count}")
    from agent.usage_pricing import format_token_count_compact

    _tok = format_token_count_compact
    cache_tokens = cache_read_tokens + cache_write_tokens
    token_parts = (
        f"↓ {_tok(input_tokens)}, ↑ {_tok(output_tokens)}, cache {_tok(cache_tokens)}"
    )
    if reasoning_tokens > 0:
        token_parts += f", raciocínio {_tok(reasoning_tokens)}"
    print(f"Tokens:         {_tok(total_tokens)} ({token_parts})")




def sync_ector_ink_dist_to_pnpm_store(tui_dir: Path) -> None:
    """Mirror ``packages/ector-tui/dist/`` to every pnpm-store copy.

    ``@ector/ink`` is declared as ``file:./packages/ector-tui``.  pnpm
    hardlinks the package contents into
    ``node_modules/.pnpm/<hash>/node_modules/@ector/ink/`` at install
    time — **before** the bundle is built.  The bundle script writes
    ``dist/tui-bundle.js`` only into the source tree, so every store
    copy is left with no ``dist/`` directory and ``index.js`` (which
    re-exports ``./dist/tui-bundle.js``) crashes the TUI at boot with
    ``ERR_MODULE_NOT_FOUND``.

    This propagates the freshly built bundle into every store copy.
    Idempotent and silent on failure: a missing pnpm-store layout
    isn't fatal (npm-flat installs, custom layouts, etc.).
    """
    src_dist = tui_dir / "packages" / "ector-tui" / "dist"
    src_bundle = src_dist / "tui-bundle.js"
    if not src_bundle.is_file():
        return
    pnpm_root = tui_dir / "node_modules" / ".pnpm"
    if not pnpm_root.is_dir():
        return
    for entry in pnpm_root.iterdir():
        if not entry.name.startswith("@ector+ink@"):
            continue
        target_dir = entry / "node_modules" / "@ector" / "ink" / "dist"
        try:
            target_dir.mkdir(exist_ok=True)
        except OSError:
            continue
        target_bundle = target_dir / "tui-bundle.js"
        try:
            if target_bundle.exists() or target_bundle.is_symlink():
                target_bundle.unlink()
        except OSError:
            pass
        try:
            os.link(src_bundle, target_bundle)
        except OSError:
            # Cross-FS hardlink failure → fall back to byte copy.
            try:
                shutil.copy2(src_bundle, target_bundle)
            except OSError:
                pass


def refresh_install_marker(root: Path) -> None:
    """Bump ``node_modules/.modules.yaml`` (or ``.package-lock.json``) so
    it is no older than the lockfile we just installed from.

    ``pnpm`` writes the marker *before* rewriting ``pnpm-lock.yaml`` when
    the install isn't fully frozen, leaving the lockfile microseconds
    newer than the marker. ``tui_need_pkg_install`` then keeps reporting
    "needs install" forever. Mirroring the lockfile's mtime onto the
    marker resolves the race without falsifying staleness — a real
    future lockfile change still bumps the lockfile past the marker.
    """
    pnpm_lock = root / "pnpm-lock.yaml"
    npm_lock = root / "package-lock.json"
    marker_paths = []
    if pnpm_lock.is_file():
        marker_paths.append((pnpm_lock, root / "node_modules" / ".modules.yaml"))
    if npm_lock.is_file():
        marker_paths.append((npm_lock, root / "node_modules" / ".package-lock.json"))
    for lock, marker in marker_paths:
        if not marker.exists():
            continue
        try:
            ts = lock.stat().st_mtime
            os.utime(marker, (ts, ts))
        except OSError:
            pass


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


def ensure_pnpm_esbuild_allowlist(tui_dir: Path, pm_bin: str | None = None) -> None:
    """Allow esbuild lifecycle scripts: .npmrc (pnpm 10) + pnpm-workspace.yaml (pnpm 11+)."""
    npmrc = tui_dir / ".npmrc"
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

    ink_npmrc = tui_dir / "packages" / "ector-tui" / ".npmrc"
    try:
        ink_npmrc.parent.mkdir(parents=True, exist_ok=True)
        if not ink_npmrc.is_file():
            ink_npmrc.write_text(
                "# allow esbuild postinstall (pnpm 10+)\nonly-built-dependencies[]=esbuild\n",
                encoding="utf-8",
            )
    except OSError:
        pass

    ws = tui_dir / "pnpm-workspace.yaml"
    ws_body = (
        "packages:\n"
        "  - .\n"
        "\n"
        "# Ector: allow esbuild lifecycle scripts (pnpm 11+ strictDepBuilds)\n"
        "allowBuilds:\n"
        "  esbuild: true\n"
    )
    try:
        if not ws.is_file():
            ws.write_text(ws_body, encoding="utf-8")
        else:
            text = ws.read_text(encoding="utf-8")
            if "packages:" not in text or "allowBuilds" not in text or "esbuild" not in text:
                ws.write_text(ws_body, encoding="utf-8")
    except OSError:
        pass

    if not pm_bin:
        pm_bin = shutil.which("pnpm") or ""
    if pm_bin and _pnpm_major_version(pm_bin) >= 10:
        try:
            subprocess.run(
                [pm_bin, "approve-builds", "esbuild"],
                cwd=str(tui_dir),
                capture_output=True,
                text=True,
                check=False,
                env=pnpm_tui_env(),
            )
        except (OSError, subprocess.SubprocessError):
            pass


_PNPM_ESBUILD_CONFIG = ("--config.only-built-dependencies[]=esbuild",)


def pnpm_tui_env(base: dict | None = None) -> dict[str, str]:
    """Env for non-interactive pnpm in frontend/tui (esbuild allowlist + CI)."""
    env = dict(base if base is not None else os.environ)
    env.setdefault("CI", "true")
    env.setdefault("PNPM_CONFIG_CONFIRM_MODULES_PURGE", "false")
    env.setdefault("npm_config_only_built_dependencies", "esbuild")
    return env


def pnpm_install_argv(pm_bin: str, *, frozen: bool) -> list[str]:
    cmd = [pm_bin, "install"]
    if frozen:
        cmd.append("--frozen-lockfile")
    cmd.extend(_PNPM_ESBUILD_CONFIG)
    return cmd


def tui_can_build_from_source(tui_dir: Path) -> bool:
    """True when a dev checkout has both the ink bundle driver and app sources."""
    ink_driver = tui_dir / "packages" / "ector-tui" / "scripts" / "bundle.mjs"
    app_src = tui_dir / "src"
    return ink_driver.is_file() and app_src.is_dir()


def tui_is_prebuilt_release(tui_dir: Path) -> bool:
    """Release tree ships pre-built dist without TypeScript sources."""
    entry = tui_dir / "dist" / "entry.js"
    bundle = tui_dir / "packages" / "ector-tui" / "dist" / "tui-bundle.js"
    if not entry.is_file() or not bundle.is_file():
        return False
    return not tui_can_build_from_source(tui_dir)


def tui_need_pkg_install(root: Path) -> bool:
    """True when @ector/ink is missing or node_modules is behind the lockfile."""
    ink = root / "node_modules" / "@ector" / "ink" / "package.json"
    if not ink.is_file():
        return True

    # Check for pnpm lockfile
    pnpm_lock = root / "pnpm-lock.yaml"
    if pnpm_lock.is_file():
        marker = root / "node_modules" / ".modules.yaml"
        if not marker.is_file():
            return True
        return pnpm_lock.stat().st_mtime > marker.stat().st_mtime

    # Legacy npm logic
    lock = root / "package-lock.json"
    if not lock.is_file():
        return False
    marker = root / "node_modules" / ".package-lock.json"
    if not marker.is_file():
        return True
    return lock.stat().st_mtime > marker.stat().st_mtime


def find_bundled_tui(tui_dir: Path) -> Optional[Path]:
    """Directory whose dist/entry.js we should run: ECTOR_TUI_DIR first, else repo frontend/tui."""
    env = os.environ.get("ECTOR_TUI_DIR")
    if env:
        p = Path(env)
        if (p / "dist" / "entry.js").exists() and not tui_need_pkg_install(p):
            return p
    if (tui_dir / "dist" / "entry.js").exists() and not tui_need_pkg_install(tui_dir):
        return tui_dir
    return None


def tui_build_needed(tui_dir: Path) -> bool:
    if tui_is_prebuilt_release(tui_dir):
        return False
    if ector_ink_bundle_stale(tui_dir):
        return True
    entry = tui_dir / "dist" / "entry.js"
    if not entry.exists():
        return True
    dist_m = entry.stat().st_mtime
    skip = frozenset({"node_modules", "dist"})
    for dirpath, dirnames, filenames in os.walk(tui_dir, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith((".ts", ".tsx")):
                if os.path.getmtime(os.path.join(dirpath, fn)) > dist_m:
                    return True
    for meta in (
        "package.json",
        "pnpm-lock.yaml",
        "package-lock.json",
        "tsconfig.json",
        "tsconfig.build.json",
    ):
        mp = tui_dir / meta
        if mp.exists() and mp.stat().st_mtime > dist_m:
            return True
    return False


def ector_ink_bundle_stale(tui_dir: Path) -> bool:
    if tui_is_prebuilt_release(tui_dir):
        return False
    ink_root = tui_dir / "packages" / "ector-tui"
    bundle = ink_root / "dist" / "tui-bundle.js"
    if not bundle.exists():
        return True
    bm = bundle.stat().st_mtime
    skip = frozenset({"node_modules", "dist"})
    for dirpath, dirnames, filenames in os.walk(ink_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith((".ts", ".tsx")):
                if os.path.getmtime(os.path.join(dirpath, fn)) > bm:
                    return True
    mp = ink_root / "package.json"
    if mp.exists() and mp.stat().st_mtime > bm:
        return True
    return False


_TUI_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@contextlib.contextmanager
def tui_startup_spinner(message: str):
    """TTY spinner for slow TUI bootstrap steps (install/build/node)."""
    if os.environ.get("ECTOR_QUIET"):
        yield
        return
    if not sys.stderr.isatty():
        print(message, file=sys.stderr, flush=True)
        yield
        return

    stop = threading.Event()
    frames = itertools.cycle(_TUI_SPINNER_FRAMES)

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


def ensure_tui_node(project_root: Path) -> None:
    """Make sure `node` + `npm` are on PATH for the TUI.

    If either is missing and scripts/lib/node-bootstrap.sh is available, source
    it and call `ensure_node` (fnm/nvm/proto/brew/bundled cascade). After
    install, capture the resolved node binary path from the bash subprocess
    and prepend its directory to os.environ["PATH"] so shutil.which finds the
    new binaries in this Python process — regardless of which version manager
    was used (nvm, fnm, proto, brew, or the bundled fallback).

    When Node is already on PATH with ``npm``, best-effort ``npm install -g``
    for **yarn** (Baileys git prepare) then **pnpm** (repo tooling / bridge).

    Idempotent no-op when node+npm are already discoverable. Set
    ``ECTOR_SKIP_NODE_BOOTSTRAP=1`` to disable auto-install.
    """
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

    if shutil.which("node") and (
        shutil.which("pnpm") or shutil.which("npm")
    ):
        return

    helper = project_root / "scripts" / "lib" / "node-bootstrap.sh"
    if not helper.is_file():
        return

    ector_home = os.environ.get("ECTOR_HOME") or str(Path.home() / ".ector")
    try:
        # Helper writes logs to stderr; we ask bash to print `command -v node`
        # on stdout once ensure_node succeeds. Subshell PATH edits don't leak
        # back into Python, so the stdout capture is the bridge.
        with tui_startup_spinner("Preparando Node.js…"):
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


def ensure_tui_bun(project_root: Path) -> None:
    """Install Bun into ``$ECTOR_HOME/bun`` when missing (OpenTUI FFI).

    Set ``ECTOR_SKIP_BUN_BOOTSTRAP=1`` to disable auto-install.
    """
    if os.environ.get("ECTOR_SKIP_BUN_BOOTSTRAP") or shutil.which("bun"):
        return

    from ector_constants import get_ector_home

    ector_home = get_ector_home()
    managed_bin = ector_home / "bun" / "bin"
    if (managed_bin / "bun").is_file():
        parts = os.environ.get("PATH", "").split(os.pathsep)
        s = str(managed_bin)
        if s not in parts:
            os.environ["PATH"] = s + os.pathsep + os.environ.get("PATH", "")
        if shutil.which("bun"):
            return

    helper = project_root / "scripts" / "lib" / "bun-bootstrap.sh"
    if not helper.is_file():
        return

    ector_home_str = str(ector_home)
    try:
        with tui_startup_spinner("Preparando Bun…"):
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{helper}" >&2 && ensure_bun >&2 && command -v bun',
                ],
                env={**os.environ, "ECTOR_HOME": ector_home_str},
                capture_output=True,
                text=True,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return

    parts = os.environ.get("PATH", "").split(os.pathsep)
    resolved = (result.stdout or "").strip()
    extras: list[Path] = []
    if resolved:
        extras.append(Path(resolved).resolve().parent)
    extras.extend(
        [
            ector_home / "bun" / "bin",
            Path.home() / ".bun" / "bin",
            Path.home() / ".local" / "bin",
        ]
    )
    for extra in extras:
        s = str(extra)
        if extra.is_dir() and s not in parts:
            parts.insert(0, s)
    os.environ["PATH"] = os.pathsep.join(parts)


def bun_bin() -> str:
    path = shutil.which("bun")
    if not path:
        print(
            "Bun não encontrado — o TUI (OpenTUI) requer Bun "
            "(FFI nativa; Node sem node:ffi não suporta). "
            "Instale em https://bun.sh ou execute o install.sh novamente."
        )
        sys.exit(1)
    return path


def build_ector_tui_bundle(tui_dir: Path, pm_bin: str, pm_name: str) -> None:
    """Build ``packages/ector-tui`` when sources are newer than ``tui-bundle.js``."""
    if tui_is_prebuilt_release(tui_dir):
        sync_ector_ink_dist_to_pnpm_store(tui_dir)
        return
    if not tui_can_build_from_source(tui_dir):
        bundle = tui_dir / "packages" / "ector-tui" / "dist" / "tui-bundle.js"
        if not bundle.is_file():
            print(
                "Pacote TUI incompleto — dist/tui-bundle.js ausente e não há "
                "fontes para recompilar. Reinstale a partir de um release "
                "completo (sync_public_release com pré-build)."
            )
            sys.exit(1)
        return
    if not ector_ink_bundle_stale(tui_dir):
        return
    ensure_pnpm_esbuild_allowlist(tui_dir, pm_bin)
    env = pnpm_tui_env()
    if pm_name == "pnpm":
        ink_argv = [pm_bin, *_PNPM_ESBUILD_CONFIG, "-C", "packages/ector-tui", "run", "build"]
    else:
        ink_argv = [pm_bin, "run", "build", "--prefix", "packages/ector-tui"]
    with tui_startup_spinner("Compilando @ector/ink…"):
        result = subprocess.run(
            ink_argv,
            cwd=str(tui_dir),
            capture_output=True,
            text=True,
            env=env,
        )
    if result.returncode != 0:
        combined = f"{result.stdout or ''}{result.stderr or ''}"
        if pm_name == "pnpm" and (
            "ERR_PNPM_IGNORED_BUILDS" in combined
            or "Ignored build scripts" in combined
        ):
            subprocess.run(
                pnpm_install_argv(pm_bin, frozen=False),
                cwd=str(tui_dir),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            subprocess.run(
                [pm_bin, *_PNPM_ESBUILD_CONFIG, "rebuild", "esbuild"],
                cwd=str(tui_dir),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            result = subprocess.run(
                ink_argv,
                cwd=str(tui_dir),
                capture_output=True,
                text=True,
                env=env,
            )
    if result.returncode != 0:
        preview = "\n".join(
            f"{result.stdout or ''}{result.stderr or ''}".strip().splitlines()[-30:]
        )
        print(f"build do @ector/ink falhou ({pm_name}).")
        if preview:
            print(preview)
        sys.exit(1)
    sync_ector_ink_dist_to_pnpm_store(tui_dir)


def _resolve_project_root(tui_dir: Path) -> Path:
    """Repo root for node-bootstrap.sh (not necessarily the TUI package dir)."""
    env_root = os.environ.get("ECTOR_PYTHON_SRC_ROOT")
    if env_root:
        return Path(env_root)
    return tui_dir.parent.parent


def make_tui_argv(tui_dir: Path) -> tuple[list[str], Path]:
    """TUI: OpenTUI via Bun usando o bundle dist/entry.js."""
    project_root = _resolve_project_root(tui_dir)
    ensure_tui_node(project_root)
    ensure_tui_bun(project_root)
    bun = bun_bin()

    # pre-built dist + node_modules (nix / full ECTOR_TUI_DIR) skips pnpm install.
    ext_dir = os.environ.get("ECTOR_TUI_DIR")
    if ext_dir:
        p = Path(ext_dir)
        if (p / "dist" / "entry.js").exists() and not tui_need_pkg_install(p):
            return [bun, str(p / "dist" / "entry.js")], p

    entry = tui_dir / "dist" / "entry.js"
    if (
        tui_is_prebuilt_release(tui_dir)
        and entry.is_file()
        and not tui_need_pkg_install(tui_dir)
    ):
        sync_ector_ink_dist_to_pnpm_store(tui_dir)
        return [bun, str(entry)], tui_dir

    pm_bin = shutil.which("pnpm") or shutil.which("npm")
    if not pm_bin:
        print("Nenhum gerenciador de pacotes (pnpm/npm) encontrado — instale o Node.js.")
        sys.exit(1)
        
    pm_name = os.path.basename(pm_bin)
    
    if tui_need_pkg_install(tui_dir):
        ensure_pnpm_esbuild_allowlist(tui_dir, pm_bin)
        install_env = pnpm_tui_env()

        def _install_output_preview(proc: subprocess.CompletedProcess) -> str:
            merged = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
            return "\n".join(merged.splitlines()[-40:])

        with tui_startup_spinner(f"Preparando para começar…"):
            if pm_name == "pnpm":
                result = subprocess.run(
                    pnpm_install_argv(pm_bin, frozen=True),
                    cwd=str(tui_dir),
                    capture_output=True,
                    text=True,
                    env=install_env,
                )
                if result.returncode != 0:
                    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
                    lockfile_mismatch = any(
                        needle in combined
                        for needle in (
                            "err_pnpm_outdated_lockfile",
                            "frozenlockfile",
                            "frozen-lockfile",
                            "lockfile is not up to date",
                            "specifiers in the lockfile",
                        )
                    )
                    ignored_builds = "err_pnpm_ignored_builds" in combined
                    if ignored_builds and not lockfile_mismatch:
                        subprocess.run(
                            pnpm_install_argv(pm_bin, frozen=False),
                            cwd=str(tui_dir),
                            capture_output=True,
                            text=True,
                            env=install_env,
                            check=False,
                        )
                        subprocess.run(
                            [pm_bin, *_PNPM_ESBUILD_CONFIG, "rebuild", "esbuild"],
                            cwd=str(tui_dir),
                            capture_output=True,
                            text=True,
                            env=install_env,
                            check=False,
                        )
                        ink = tui_dir / "node_modules" / "@ector" / "ink" / "package.json"
                        if ink.is_file():
                            result = subprocess.CompletedProcess(
                                args=result.args,
                                returncode=0,
                                stdout=result.stdout,
                                stderr=result.stderr,
                            )
                    if result.returncode != 0 and lockfile_mismatch:
                        if not os.environ.get("ECTOR_QUIET"):
                            print(
                                "Lockfile desatualizado em relação ao package.json — "
                                "tentando pnpm install (sem --frozen-lockfile)…"
                            )
                        result = subprocess.run(
                            pnpm_install_argv(pm_bin, frozen=False),
                            cwd=str(tui_dir),
                            capture_output=True,
                            text=True,
                            env=install_env,
                        )
            else:
                result = subprocess.run(
                    [pm_bin, "install", "--no-fund", "--no-audit", "--progress=false"],
                    cwd=str(tui_dir),
                    capture_output=True,
                    text=True,
                    env=install_env,
                )

        if result.returncode != 0:
            print(f"{pm_name} install falhou.")
            preview = _install_output_preview(result)
            if preview:
                print(preview)
            sys.exit(1)

        # pnpm writes `.modules.yaml` BEFORE rewriting `pnpm-lock.yaml`, which
        # leaves the lockfile ~1ms newer than the install marker. The next
        # invocation then thinks dependencies are stale, reinstalls, and the
        # cycle repeats forever — surfacing as "O build do TUI não produziu
        # dist/entry.js" because `find_bundled_tui` gates on
        # `tui_need_pkg_install(...) == False`. Touch the marker so it is
        # at least as new as the lockfile we just synced against.
        refresh_install_marker(tui_dir)

        # Re-install reset the pnpm-store copy of @ector/ink, blowing
        # away the propagated dist/ from a previous run.  Re-sync now;
        # safe noop if `dist/tui-bundle.js` doesn't exist yet (the
        # subsequent build step will sync again).
        sync_ector_ink_dist_to_pnpm_store(tui_dir)

    build_ector_tui_bundle(tui_dir, pm_bin, pm_name)

    if tui_build_needed(tui_dir):
        build_argv = (
            [pm_bin, *_PNPM_ESBUILD_CONFIG, "run", "build"]
            if pm_name == "pnpm"
            else [pm_bin, "run", "build"]
        )
        with tui_startup_spinner("Carregando interface…"):
            result = subprocess.run(
                build_argv,
                cwd=str(tui_dir),
                capture_output=True,
                text=True,
                env=pnpm_tui_env() if pm_name == "pnpm" else None,
            )
        if result.returncode != 0:
            combined = f"{result.stdout or ''}{result.stderr or ''}".strip()
            preview = "\n".join(combined.splitlines()[-30:])
            print(f"build do TUI falhou ({pm_name}).")
            if preview:
                print(preview)
            sys.exit(1)
        sync_ector_ink_dist_to_pnpm_store(tui_dir)
    else:
        # Build was skipped (everything fresh).  Still verify the
        # pnpm-store copy carries the bundle — a previous incomplete
        # run, or a manual `rm -rf node_modules` followed by install,
        # may have left the store half-empty.  Cheap and idempotent.
        sync_ector_ink_dist_to_pnpm_store(tui_dir)

    root = find_bundled_tui(tui_dir)
    if not root:
        print("O build do TUI não produziu dist/entry.js")
        sys.exit(1)

    return [bun, str(root / "dist" / "entry.js")], root


def launch_tui(
    project_root: Path,
    resume_session_id: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    initial_image: Optional[str] = None,
    worktree: bool = False,
):
    """Replace current process with the TUI."""
    tui_dir = project_root / "frontend" / "tui"

    env = os.environ.copy()
    env["ECTOR_PYTHON_SRC_ROOT"] = os.environ.get(
        "ECTOR_PYTHON_SRC_ROOT", str(project_root)
    )
    try:
        from ector_cli.macos_bundle import (
            python_home_for_gateway_executable,
            resolve_gateway_python,
        )

        gateway_python = resolve_gateway_python(
            fallback=sys.executable,
            project_root=project_root,
        )
        env.setdefault("ECTOR_PYTHON", gateway_python)
        python_home = python_home_for_gateway_executable(gateway_python)
        if python_home is not None:
            env.setdefault("PYTHONHOME", str(python_home))
    except Exception:
        env.setdefault("ECTOR_PYTHON", sys.executable)
    env.setdefault("ECTOR_CWD", safe_getcwd())
    env.setdefault("NODE_ENV", "production")

    from ector_cli.tui_run_session import clear_tui_run_session

    clear_tui_run_session()
    if model:
        env["ECTOR_MODEL"] = model
        env["ECTOR_INFERENCE_MODEL"] = model
    if provider:
        env["ECTOR_TUI_PROVIDER"] = provider
        env["ECTOR_INFERENCE_PROVIDER"] = provider
    # Guarantee an 8GB V8 heap + exposed GC for the TUI. Default node cap is
    # ~1.5–4GB depending on version and can fatal-OOM on long sessions with
    # large transcripts / reasoning blobs. Token-level merge: respect any
    # user-supplied --max-old-space-size (they may have set it higher) and
    # avoid duplicating --expose-gc.
    _tokens = env.get("NODE_OPTIONS", "").split()
    if not any(t.startswith("--max-old-space-size=") for t in _tokens):
        _tokens.append("--max-old-space-size=8192")
    if "--expose-gc" not in _tokens:
        _tokens.append("--expose-gc")
    env["NODE_OPTIONS"] = " ".join(_tokens)
    if resume_session_id:
        env["ECTOR_TUI_RESUME"] = resume_session_id
    if initial_prompt:
        env["ECTOR_TUI_INITIAL_PROMPT"] = initial_prompt
    if initial_image:
        env["ECTOR_TUI_INITIAL_IMAGE"] = initial_image
    if worktree:
        env["ECTOR_TUI_WORKTREE"] = "1"

    # Propagate the Ector identity token to the TUI child.  We only
    # forward the *access* token (never the refresh token, which must
    # stay scoped to the parent so the file-locked rotation logic in
    # ector_cli.identity_auth remains single-writer).
    try:
        from ector_cli.identity_auth import session_for_subprocess

        identity_env = session_for_subprocess()
    except Exception:
        identity_env = None
    if identity_env:
        for key, value in identity_env.items():
            env.setdefault(key, value)

    argv, cwd = make_tui_argv(tui_dir)
    try:
        code = subprocess.call(argv, cwd=str(cwd), env=env)
    except KeyboardInterrupt:
        code = 130

    if code in (0, 130):
        from ector_cli.tui_run_session import read_tui_run_session

        active = read_tui_run_session()
        if active:
            print_tui_exit_summary(active)

    sys.exit(code)


