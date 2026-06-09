"""``ector update`` — upgrade an installed Ector Agent from ector-agent-release."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

from ector_cli.colors import Colors, color
from ector_cli.install_paths import resolve_install_dir, resolve_install_script

logger = logging.getLogger(__name__)

_MAX_INSTALL_ATTEMPTS = 2

_UPDATE_EVENT_OK = "ECTOR_UPDATE:ok:"
_UPDATE_EVENT_START = "ECTOR_UPDATE:start:"
_UPDATE_EVENT_FAIL = "ECTOR_UPDATE:fail:"

# Weight budget (must sum to 100)
_PROGRESS_BACKUP = 8
_PROGRESS_PREPARE = 7
_PROGRESS_INSTALL = 75
_PROGRESS_GATEWAY = 7
_PROGRESS_DONE = 3
_PROGRESS_INSTALL_EXPECTED_STEPS = 10


def _friendly_install_step(label: str) -> str:
    shortcuts = (
        ("Código do Ector", "Código"),
        ("Pacote Python", "Dependências"),
        ("Ambiente virtual Python", "Ambiente Python"),
        ("Verificação do release", "Verificação"),
        ("Ferramentas de navegador", "Navegador"),
        ("Comando ector", "Comando CLI"),
        ("Gerenciador Python (uv)", "uv"),
        ("Chat no terminal", "Terminal UI"),
    )
    for needle, short in shortcuts:
        if needle in label:
            return short
    if label.startswith("Sistema:"):
        return "Sistema"
    if label.startswith("Python "):
        return "Python"
    if label.startswith("Git"):
        return "Git"
    if "Node.js" in label:
        return "Node.js"
    return label.strip()[:36]


class UpdateProgressUI:
    """Compact Rich progress bar for ``ector update`` (stderr, transient)."""

    def __init__(self) -> None:
        self.enabled = self._should_enable()
        self._progress = None
        self._task_id: int | None = None
        self._completed = 0.0
        self._install_steps_done = 0
        self._install_base = _PROGRESS_BACKUP + _PROGRESS_PREPARE

    @staticmethod
    def _should_enable() -> bool:
        if os.environ.get("NO_COLOR") is not None:
            return False
        if os.environ.get("TERM") == "dumb":
            return False
        return sys.stderr.isatty()

    def __enter__(self) -> UpdateProgressUI:
        if not self.enabled:
            return self
        from rich.console import Console
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
        from rich.style import Style
        from rich.theme import Theme

        # Rich default bar.complete is pink/red — use Ector accent (#00D1FF).
        _accent = "rgb(0,209,255)"
        console = Console(
            stderr=True,
            theme=Theme(
                {
                    "bar.back": "grey30",
                    "bar.complete": _accent,
                    "bar.finished": "green",
                }
            ),
        )
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(
                bar_width=28,
                style=Style(color="grey30"),
                complete_style=Style(color=_accent),
                finished_style=Style(color="green"),
            ),
            TextColumn(f"[{_accent}]{{task.percentage:>3.0f}}%"),
            console=console,
            transient=True,
        )
        self._progress.__enter__()
        self._task_id = self._progress.add_task("Atualizando...", total=100)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc, tb)

    def _set(self, completed: float, description: str) -> None:
        self._completed = min(100.0, completed)
        if self._progress is not None and self._task_id is not None:
            self._progress.update(
                self._task_id,
                completed=self._completed,
                description=description,
            )

    def set_phase(self, description: str, completed: float) -> None:
        self._set(completed, description)

    def phase_backup(self) -> None:
        self.set_phase("Backup", _PROGRESS_BACKUP)

    def phase_prepare(self) -> None:
        self.set_phase("Preparando", _PROGRESS_BACKUP + _PROGRESS_PREPARE)

    def phase_gateway_restart(self) -> None:
        self.set_phase(
            "Reiniciando gateway",
            _PROGRESS_BACKUP + _PROGRESS_PREPARE + _PROGRESS_INSTALL + _PROGRESS_GATEWAY,
        )

    def phase_done(self) -> None:
        self.set_phase("Concluído", 100)

    def handle_install_line(self, line: str) -> None:
        if line.startswith(_UPDATE_EVENT_START):
            label = _friendly_install_step(line[len(_UPDATE_EVENT_START) :])
            if self._progress is not None and self._task_id is not None:
                self._progress.update(self._task_id, description=label)
            return

        if line.startswith(_UPDATE_EVENT_OK):
            self._install_steps_done += 1
            label = _friendly_install_step(line[len(_UPDATE_EVENT_OK) :])
            fraction = min(1.0, self._install_steps_done / _PROGRESS_INSTALL_EXPECTED_STEPS)
            completed = self._install_base + (_PROGRESS_INSTALL * fraction)
            self._set(completed, label)
            return

        if line.startswith("✔ "):
            self.handle_install_line(_UPDATE_EVENT_OK + line[2:])

    def phase_install_complete(self) -> None:
        self.set_phase(
            "Finalizando",
            _PROGRESS_BACKUP + _PROGRESS_PREPARE + _PROGRESS_INSTALL,
        )

    def note_retry(self) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, description="Tentando novamente...")


def _emit_update_install_line(line: str, progress: UpdateProgressUI | None) -> None:
    """Map install protocol lines to UI; drop tool noise (uv, npm, …)."""
    if progress is not None and progress.enabled:
        progress.handle_install_line(line)
        return

    stripped = line.strip()
    if not stripped:
        return

    if stripped.startswith(_UPDATE_EVENT_OK):
        _ok(_friendly_install_step(stripped[len(_UPDATE_EVENT_OK) :]))
        return
    if stripped.startswith(_UPDATE_EVENT_FAIL):
        body = stripped[len(_UPDATE_EVENT_FAIL) :].strip() or stripped
        _fail(body)
        return
    if stripped.startswith(_UPDATE_EVENT_START):
        _info(_friendly_install_step(stripped[len(_UPDATE_EVENT_START) :]))
        return
    if stripped.startswith("✔ "):
        _ok(stripped[2:])
        return
    if stripped.startswith("✗ "):
        _fail(stripped[2:])
        return
    if stripped.startswith("▲ "):
        _warn(stripped[2:])


def _status_line(icon: str, icon_color: str, msg: str) -> None:
    print(f"{color(icon, icon_color)} {msg}")


def _ok(msg: str) -> None:
    _status_line("✔", Colors.GREEN, msg)


def _warn(msg: str) -> None:
    _status_line("▲", Colors.YELLOW, msg)


def _info(msg: str) -> None:
    print(f"→ {msg}")


def _fail(msg: str) -> None:
    _status_line("✗", Colors.RED, msg)


def _title(text: str) -> None:
    print(text)
    print()


def _invalidate_update_cache() -> None:
    try:
        from ector_constants import get_ector_home

        cache = get_ector_home() / ".update_check"
        if cache.exists():
            cache.unlink()
    except Exception:
        pass


def _install_env(install_dir: Path) -> dict[str, str]:
    try:
        from ector_constants import get_ector_home

        ector_home = str(get_ector_home())
    except Exception:
        ector_home = os.environ.get("ECTOR_HOME", "")

    home = Path.home()
    path_parts: list[str] = [
        str(home / ".local" / "bin"),
        str(home / ".cargo" / "bin"),
    ]
    if ector_home:
        eh = Path(ector_home)
        path_parts.extend(
            [
                str(eh / "bun" / "bin"),
                str(eh / "node" / "bin"),
            ]
        )
    path_parts.extend(p for p in os.environ.get("PATH", "").split(os.pathsep) if p)

    env = {
        **os.environ,
        "ECTOR_INSTALL_DIR": str(install_dir),
        "ECTOR_NONINTERACTIVE": "1",
        "ECTOR_INSTALL_COMPACT": "1",
        "ECTOR_UPDATE_PROGRESS": "1",
        "UV_NO_PROGRESS": "1",
        "UV_COLOR": "never",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GCM_INTERACTIVE": "Never",
        "PATH": os.pathsep.join(path_parts),
    }
    if ector_home:
        env["ECTOR_HOME"] = ector_home
    return env


def _run_pre_update_backup(args, *, progress: UpdateProgressUI | None = None) -> None:
    quiet = progress is not None and progress.enabled

    if getattr(args, "no_backup", False):
        if not quiet:
            _ok("Backup antes da atualização: ignorado (--no-backup)")
            print()
        if progress is not None:
            progress.phase_backup()
        return

    try:
        from ector_cli.config import load_config

        cfg = load_config()
    except Exception as exc:
        logger.debug("Could not load config for pre-update backup: %s", exc)
        cfg = {}

    updates_cfg = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    if not updates_cfg.get("pre_update_backup", True):
        if not quiet:
            _warn(
                "Backup antes da atualização: desativado "
                "(updates.pre_update_backup=false no config.yaml)"
            )
            print()
        if progress is not None:
            progress.phase_backup()
        return

    keep = int(updates_cfg.get("backup_keep", 5) or 5)

    try:
        from ector_cli.backup import create_pre_update_backup
    except Exception as exc:
        if not quiet:
            _warn(f"Backup antes da atualização: indisponível ({exc}) — continuando")
            print()
        if progress is not None:
            progress.phase_backup()
        return

    if not quiet:
        _info("Backup antes da atualização...")
    try:
        from ector_constants import get_ector_home

        out_path = create_pre_update_backup(
            ector_home=get_ector_home(),
            keep=keep,
        )
    except Exception as exc:
        if not quiet:
            _warn(f"Backup antes da atualização: falhou ({exc}) — continuando")
            print()
        if progress is not None:
            progress.phase_backup()
        return

    if out_path is None:
        if not quiet:
            _warn("Backup antes da atualização: ignorado — continuando")
            print()
        if progress is not None:
            progress.phase_backup()
        return

    if progress is not None:
        progress.phase_backup()
        return

    try:
        from ector_constants import display_ector_home, get_ector_home

        home = get_ector_home()
        try:
            display_path = f"{display_ector_home()}/{out_path.relative_to(home)}"
        except ValueError:
            display_path = str(out_path)
    except Exception:
        display_path = str(out_path)

    _ok("Backup antes da atualização")
    print(color(f"  Guardado em: {display_path}", Colors.DIM))
    print(color(f"  Restaurar: ector import {out_path}", Colors.DIM))
    print()


_GATEWAY_STOP_TIMEOUT_SEC = 15.0


def _stop_gateway_processes() -> int:
    """Return number of gateway PIDs signalled, or 0 if none / unavailable."""
    from ector_cli.gateway import find_gateway_pids

    pids = find_gateway_pids(all_profiles=True)
    if not pids:
        return 0

    import signal

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            logger.debug("Could not SIGTERM gateway pid %s: %s", pid, exc)
    return len(pids)


def _stop_gateways_quietly(*, progress: UpdateProgressUI | None = None) -> None:
    """Best-effort stop of gateway processes before mutating the install tree."""
    quiet = progress is not None and progress.enabled
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_stop_gateway_processes)
            n = future.result(timeout=_GATEWAY_STOP_TIMEOUT_SEC)
    except FuturesTimeoutError:
        if not quiet:
            _warn("Paragem do gateway demorou — continuando")
        return
    except Exception as exc:
        logger.debug("Gateway stop skipped: %s", exc)
        return

    if n <= 0 or quiet:
        return

    word = "processo" if n == 1 else "processos"
    _ok(f"Gateway: {n} {word} parado(s)")


def _restart_gateway_if_needed(
    was_active: bool,
    *,
    progress: UpdateProgressUI | None = None,
) -> None:
    if not was_active:
        return

    quiet = progress is not None and progress.enabled
    if progress is not None:
        progress.phase_gateway_restart()
    elif not quiet:
        print()
        _info("Reiniciando gateway...")
        sys.stdout.flush()

    try:
        from ector_cli.gateway import restart_gateway_after_update

        if restart_gateway_after_update():
            if not quiet:
                _ok("Gateway reiniciado")
            return
    except Exception as exc:
        logger.debug("Gateway restart after update failed: %s", exc)

    if not quiet:
        _warn("Não foi possível reiniciar o gateway automaticamente")


def _print_version_screen() -> None:
    from ector_cli.presentation import print_version_screen

    print_version_screen()


def _resolve_update_install_dir() -> Path:
    install_dir = resolve_install_dir()
    if install_dir is None:
        _fail("Instalação git não encontrada.")
        print(color("  curl -fsSL https://ector.cc/install.sh | bash", Colors.DIM))
        sys.exit(1)
    return install_dir


def _installed_version_label(install_dir: Path) -> str | None:
    from ector_cli.install_paths import format_version_label, read_install_version

    meta = read_install_version(install_dir)
    if meta is None:
        return None
    return format_version_label(*meta)


def _remote_version_label(install_dir: Path, upstream_label: str) -> str | None:
    from ector_cli.install_paths import format_version_label, read_git_ref_version

    meta = read_git_ref_version(install_dir, upstream_label)
    if meta is None:
        return None
    return format_version_label(*meta)


def _commits_behind(install_dir: Path, *, force_refresh: bool = False) -> int | None:
    """Commits behind upstream, or ``None`` on failure.

    When git reports ``0`` but ``versionCode`` on the remote is higher, treat
    as at least one pending update (same release branch, newer build).
    """
    from ector_cli.install_paths import read_git_ref_version, read_install_version
    from ector_cli.presentation import check_for_updates, get_cached_update_upstream_label

    behind = check_for_updates(force_refresh=force_refresh)
    if behind is None:
        return None
    if behind > 0:
        return behind

    upstream = get_cached_update_upstream_label()
    local_meta = read_install_version(install_dir)
    remote_meta = read_git_ref_version(install_dir, upstream) if upstream else None
    if local_meta and remote_meta and remote_meta[1] > local_meta[1]:
        return remote_meta[1] - local_meta[1]
    return 0


def _check_updates_available(install_dir: Path) -> int:
    """Return commits behind upstream, or exit on failure / already up to date."""
    from ector_cli.presentation import get_cached_update_upstream_label

    _info("Verificando atualizações...")
    behind = _commits_behind(install_dir, force_refresh=True)
    if behind is None:
        _fail("Não foi possível verificar atualizações (rede ou git).")
        sys.exit(1)

    current = _installed_version_label(install_dir)
    if behind == 0:
        if current:
            _ok(f"Ector está na versão mais recente — {current}")
        else:
            _ok("Ector está na versão mais recente")
        sys.exit(0)

    upstream = get_cached_update_upstream_label()
    remote = _remote_version_label(install_dir, upstream)
    if remote:
        _ok(f"Atualização disponível: {remote}")
    else:
        _ok("Atualização disponível")
    print()
    return behind


class UpdateCancelled(Exception):
    """User interrupted ``ector update`` (Ctrl+C)."""


def _run_shell(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    stream: bool = False,
    log_file: Path | None = None,
    silent: bool = False,
) -> tuple[int, str]:
    """Run a shell command.

    ``stream=True`` attaches stdout/stderr to the terminal. When ``log_file`` is
    set, output is also tee'd there for post-mortem analysis on failure.
    """
    run_cwd = str(cwd) if cwd else None
    if stream:
        try:
            if log_file is not None:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_q = shlex.quote(str(log_file))
                inner = " ".join(shlex.quote(part) for part in cmd)
                script = (
                    f"set -o pipefail; {inner} 2>&1 | tee {log_q}; "
                    "exit ${PIPESTATUS[0]}"
                )
                proc = subprocess.run(
                    ["bash", "-c", script],
                    cwd=run_cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
                log = (
                    log_file.read_text(encoding="utf-8", errors="replace")
                    if log_file.is_file()
                    else ""
                )
                return proc.returncode, log
            proc = subprocess.run(
                cmd,
                cwd=run_cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except KeyboardInterrupt:
            raise UpdateCancelled from None
        return proc.returncode, ""

    proc = subprocess.run(
        cmd,
        cwd=run_cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    combined = f"{proc.stdout or ''}{proc.stderr or ''}"
    if not silent:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode, combined


def _run_installer_streaming(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Run the installer capturing output for logs; feed lines to ``on_line``."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    chunks: list[str] = []
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                chunks.append(line)
                if on_line is not None:
                    on_line(line.rstrip("\n"))
        rc = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise UpdateCancelled from None
    return rc, "".join(chunks)


def _ensure_uv(env: dict[str, str]) -> bool:
    for candidate in ("uv", str(Path.home() / ".local" / "bin" / "uv")):
        if subprocess.run(
            [candidate, "--version"],
            env=env,
            capture_output=True,
            check=False,
        ).returncode == 0:
            return True

    _info("Instalando gerenciador Python (uv)...")
    rc, _ = _run_shell(
        ["bash", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
        env=env,
    )
    if rc != 0:
        return False

    env["PATH"] = os.pathsep.join(
        [
            str(Path.home() / ".local" / "bin"),
            str(Path.home() / ".cargo" / "bin"),
            env.get("PATH", ""),
        ]
    )
    return subprocess.run(
        ["uv", "--version"],
        env=env,
        capture_output=True,
        check=False,
    ).returncode == 0


def _ensure_git(env: dict[str, str]) -> bool:
    if subprocess.run(["git", "--version"], env=env, capture_output=True).returncode == 0:
        return True
    if os.geteuid() != 0:
        return False
    _info("Instalando git...")
    rc, _ = _run_shell(
        ["bash", "-c", "DEBIAN_FRONTEND=noninteractive apt-get update -qq && apt-get install -y git"],
        env=env,
    )
    return rc == 0


def _sync_git(install_dir: Path, env: dict[str, str]) -> bool:
    _info("Sincronizando repositório git...")
    branch = "main"
    rc, _ = _run_shell(["git", "fetch", "origin"], cwd=install_dir, env=env)
    if rc != 0:
        return False
    rc, _ = _run_shell(["git", "checkout", branch], cwd=install_dir, env=env)
    if rc != 0:
        return False
    rc, _ = _run_shell(["git", "pull", "--ff-only", "origin", branch], cwd=install_dir, env=env)
    return rc == 0


def _install_git_pull_ok(log: str) -> bool:
    return (
        "✔ Código do Ector (git pull)" in log
        or f"{_UPDATE_EVENT_OK}Código do Ector (git pull)" in log
    )


def _resolve_uv_cmd(env: dict[str, str]) -> str:
    for candidate in ("uv", str(Path.home() / ".local" / "bin" / "uv")):
        if subprocess.run(
            [candidate, "--version"],
            env=env,
            capture_output=True,
            check=False,
        ).returncode == 0:
            return candidate
    return "uv"


def _retry_pip_install(install_dir: Path, env: dict[str, str]) -> tuple[bool, str]:
    """Re-run ``uv pip install`` into the install venv after a partial update."""
    venv_python = install_dir / "venv" / "bin" / "python"
    if not venv_python.is_file():
        return False, "venv/bin/python não encontrado"

    uv = _resolve_uv_cmd(env)
    root = shlex.quote(str(install_dir))
    py = shlex.quote(str(venv_python))
    venv = shlex.quote(str(install_dir / "venv"))
    shell = (
        f"cd {root} && export VIRTUAL_ENV={venv} UV_NO_PROGRESS=1 UV_COLOR=never && "
        f"{uv} pip install -q --no-progress --python {py} --upgrade '.[all]' || "
        f"{uv} pip install -q --no-progress --python {py} --upgrade '.'"
    )
    rc, log = _run_shell(["bash", "-c", shell], cwd=install_dir, env=env, silent=True)
    return rc == 0, log


def _try_recover_partial_update(
    install_dir: Path,
    env: dict[str, str],
    log: str,
    *,
    progress: UpdateProgressUI | None = None,
) -> bool:
    """When git already moved forward, finish deps instead of leaving a false failure."""
    quiet = progress is not None and progress.enabled
    behind = _commits_behind(install_dir, force_refresh=True)
    git_ok = _install_git_pull_ok(log)
    if not git_ok and (behind is None or behind > 0):
        return False

    if not quiet:
        print()
        _warn("Código já atualizado; concluindo dependências Python...")
        current = _installed_version_label(install_dir)
        if current:
            print(color(f"  Versão no disco: {current}", Colors.DIM))
    else:
        current = _installed_version_label(install_dir)
        if progress is not None:
            progress.set_phase("Dependências", progress._install_base)

    ok, pip_log = _retry_pip_install(install_dir, env)
    if ok:
        if not quiet:
            label = _installed_version_label(install_dir) or current
            if label:
                _ok(f"Atualizado para {label}")
            else:
                _ok("Atualização concluída")
        elif progress is not None:
            progress.phase_install_complete()
        return True

    if not quiet and pip_log.strip():
        print()
        print(color("  Erro ao instalar dependências:", Colors.DIM))
        for line in _tail_log_lines(pip_log, limit=12):
            print(color(f"    {line}", Colors.DIM))
    return False


def _attempt_recovery(install_dir: Path, log: str, env: dict[str, str]) -> bool:
    text = log.lower()
    recovered = False

    if "uv" in text and ("docs.astral.sh/uv" in text or "gerenciador python (uv)" in text):
        recovered = _ensure_uv(env) or recovered

    if "git not found" in text or "git —" in text:
        recovered = _ensure_git(env) or recovered

    if any(
        needle in text
        for needle in (
            "git pull",
            "ff-only",
            "fetch origin",
            "failed to clone",
            "could not read from remote",
        )
    ):
        recovered = _sync_git(install_dir, env) or recovered

    if _install_git_pull_ok(log):
        recovered = _retry_pip_install(install_dir, env)[0] or recovered

    return recovered


_INSTALL_CHECK_MARKERS = (
    "Sistema:",
    "Gerenciador Python (uv)",
    "Python ",
    "Git",
    "Node.js",
)


def _is_install_check_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("✔"):
        return False
    body = stripped[1:].strip()
    return any(marker in body for marker in _INSTALL_CHECK_MARKERS)


def _extract_install_failure_lines(log: str, *, limit: int = 20) -> list[str]:
    """Prefer actionable errors over repeated prerequisite check lines."""
    lines = [ln.rstrip() for ln in log.splitlines() if ln.strip()]
    if not lines:
        return []

    error_markers = (
        "✗",
        "instalação incompleta",
        "pacote clonado",
        "failed",
        "error:",
        "fatal:",
        "ff-only",
        "not possible to fast-forward",
        "could not read from remote",
        "gerenciador python (uv) —",
        "git not found",
    )
    hits: list[str] = []
    for idx, line in enumerate(lines):
        lower = line.lower()
        stripped = line.strip()
        if stripped.startswith(_UPDATE_EVENT_FAIL):
            hits.append(stripped[len(_UPDATE_EVENT_FAIL) :].strip() or stripped)
            for follow in lines[idx + 1 : idx + 6]:
                if follow.startswith("  ") or follow.lstrip().startswith("- "):
                    hits.append(follow)
                else:
                    break
            continue
        if stripped.startswith("✗") or any(marker in lower for marker in error_markers):
            hits.append(line)
            for follow in lines[idx + 1 : idx + 6]:
                if follow.startswith("  ") or follow.lstrip().startswith("- "):
                    hits.append(follow)
                else:
                    break
    if hits:
        return hits[-limit:]

    non_check = [ln for ln in lines if not _is_install_check_line(ln)]
    if non_check:
        return non_check[-limit:]
    return lines[-limit:]


def _tail_log_lines(log: str, limit: int = 20) -> list[str]:
    return _extract_install_failure_lines(log, limit=limit)


def _diagnose_failure(log: str) -> str | None:
    text = log.lower()
    if "pacote python" in text and "✗" in log:
        return (
            "Falha ao instalar dependências Python. "
            "O código git já pode estar atualizado — tente `ector update` de novo."
        )
    if "instalação incompleta" in text or "pacote clonado" in text:
        return (
            "O release público está incompleto (faltam artefactos de UI ou runtime). "
            "Aguarde um sync corrigido ou reinstale com curl | bash."
        )
    if "ff-only" in text or "not possible to fast-forward" in text:
        return (
            "O repositório local divergiu do release. "
            "Use o backup criado antes da atualização se precisar restaurar dados."
        )
    if "uv" in text and "docs.astral.sh" in text:
        return "Não foi possível instalar o gerenciador Python (uv) automaticamente."
    if "git not found" in text:
        return "Git não está instalado neste servidor."
    return None


def _report_install_failure(returncode: int, log: str) -> None:
    print()
    _fail(f"Atualização falhou (código {returncode}).")
    hint = _diagnose_failure(log)
    if hint:
        print(color(f"  {hint}", Colors.DIM))

    tail = _tail_log_lines(log)
    if tail:
        print()
        print(color("  Últimas linhas do instalador:", Colors.DIM))
        for line in tail:
            print(color(f"    {line}", Colors.DIM))

    print()
    print(color("  Diagnóstico: ector doctor", Colors.DIM))
    print(color("  Logs: ector logs --level warning", Colors.DIM))


def _report_update_cancelled() -> None:
    print()
    _warn("Atualização cancelada.")


def _run_installer_update(
    installer: Path,
    install_dir: Path,
    env: dict[str, str],
    *,
    progress: UpdateProgressUI | None = None,
) -> tuple[int, bool]:
    """Return ``(exit_code, success_already_reported)``."""
    use_bar = progress is not None and progress.enabled
    if installer.suffix.lower() == ".ps1":
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "ByPass",
            "-NoProfile",
            "-File",
            str(installer),
            "-SkipSetup",
        ]
    else:
        cmd = ["bash", str(installer), "--skip-setup"]
    last_rc = 1
    last_log = ""

    if not use_bar:
        _info("Aplicando atualização...")

    log_fd, log_path_str = tempfile.mkstemp(prefix="ector-update-", suffix=".log")
    os.close(log_fd)
    log_path = Path(log_path_str)

    def _on_install_line(line: str) -> None:
        _emit_update_install_line(line, progress)

    def _run_attempt() -> tuple[int, str]:
        return _run_installer_streaming(
            cmd,
            cwd=install_dir,
            env=env,
            on_line=_on_install_line,
        )

    try:
        for attempt in range(1, _MAX_INSTALL_ATTEMPTS + 1):
            if attempt > 1:
                if use_bar:
                    progress.note_retry()
                else:
                    print()
                    _info("Tentando atualização novamente...")
            try:
                last_rc, last_log = _run_attempt()
            except UpdateCancelled:
                _report_update_cancelled()
                return 130, False
            if last_rc == 0:
                if progress is not None:
                    progress.phase_install_complete()
                return 0, False
            if _try_recover_partial_update(
                install_dir, env, last_log, progress=progress
            ):
                return 0, True
            if attempt < _MAX_INSTALL_ATTEMPTS and _attempt_recovery(
                install_dir, last_log, env
            ):
                continue
            break

        _report_install_failure(last_rc, last_log)
        return last_rc, False
    finally:
        log_path.unlink(missing_ok=True)


def cmd_update_check() -> None:
    install_dir = _resolve_update_install_dir()

    from ector_cli.presentation import get_cached_update_upstream_label

    behind = _commits_behind(install_dir, force_refresh=True)
    if behind is None:
        _fail("Não foi possível verificar atualizações (rede ou git).")
        sys.exit(1)

    current = _installed_version_label(install_dir)
    if behind == 0:
        if current:
            _ok(f"Ector está na versão mais recente — {current}")
        else:
            _ok("Ector está na versão mais recente")
        return

    upstream = get_cached_update_upstream_label()
    remote = _remote_version_label(install_dir, upstream)
    if remote:
        print(f"Atualização disponível: {remote}.")
    else:
        print("Atualização disponível.")
    print(color("  Execute: ector update", Colors.DIM))


def cmd_update(args) -> None:
    """Update Ector Agent via scripts/install.sh (ector-agent-release)."""
    from ector_cli.config import is_managed, managed_error

    if is_managed():
        managed_error("update Ector Agent")
        sys.exit(1)

    if getattr(args, "check", False):
        cmd_update_check()
        return

    install_dir = _resolve_update_install_dir()

    installer = resolve_install_script(install_dir)
    if installer is None:
        _fail(f"Instalador não encontrado em {install_dir}")
        sys.exit(1)

    from ector_cli.install_paths import (
        is_package_tree_install_dir,
        looks_like_release_install_remote,
    )

    if is_package_tree_install_dir(install_dir) and not looks_like_release_install_remote(
        install_dir
    ):
        print()
        _warn(
            "Este checkout parece ser um repositório de desenvolvimento "
            "(não ector-agent-release)."
        )
        print(
            color(
                "  `ector update` fará git pull aqui — use apenas em instalações "
                "de release (~/.ector/ector-agent).",
                Colors.DIM,
            )
        )
        print()

    _check_updates_available(install_dir)

    was_gateway_active = False
    try:
        from ector_cli.gateway import gateway_is_active

        was_gateway_active = gateway_is_active(all_profiles=True)
    except Exception as exc:
        logger.debug("Could not detect gateway state before update: %s", exc)

    with UpdateProgressUI() as progress:
        _run_pre_update_backup(args, progress=progress)

        if not progress.enabled:
            _info("Preparando atualização...")
        else:
            progress.phase_prepare()
        sys.stdout.flush()
        _stop_gateways_quietly(progress=progress)

        env = _install_env(install_dir)
        try:
            result, success_reported = _run_installer_update(
                installer,
                install_dir,
                env,
                progress=progress,
            )
        except KeyboardInterrupt:
            _report_update_cancelled()
            sys.exit(130)

        _invalidate_update_cache()

        if result == 130:
            sys.exit(130)
        if result != 0:
            sys.exit(result)

        if not success_reported and not progress.enabled:
            updated = _installed_version_label(install_dir)
            if updated:
                _ok(f"Atualizado para {updated}")

        _restart_gateway_if_needed(was_gateway_active, progress=progress)
        if progress.enabled:
            progress.phase_done()

    _print_version_screen()
