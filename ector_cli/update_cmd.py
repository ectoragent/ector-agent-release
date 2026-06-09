"""``ector update`` — upgrade an installed Ector Agent from ector-agent-release."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

from ector_cli.colors import Colors, color
from ector_cli.install_paths import resolve_install_dir, resolve_install_script

logger = logging.getLogger(__name__)

_MAX_INSTALL_ATTEMPTS = 2


def _ok(msg: str) -> None:
    print(color(f"✔ {msg}", Colors.GREEN))


def _warn(msg: str) -> None:
    print(color(f"▲ {msg}", Colors.YELLOW))


def _info(msg: str) -> None:
    print(color(f"→ {msg}", Colors.CYAN))


def _fail(msg: str) -> None:
    print(color(f"✗ {msg}", Colors.RED))


def _title(text: str) -> None:
    print(color(text, Colors.CYAN, Colors.BOLD))
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
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GCM_INTERACTIVE": "Never",
        "PATH": os.pathsep.join(path_parts),
    }
    if ector_home:
        env["ECTOR_HOME"] = ector_home
    return env


def _run_pre_update_backup(args) -> None:
    if getattr(args, "no_backup", False):
        _ok("Backup antes da atualização: ignorado (--no-backup)")
        print()
        return

    try:
        from ector_cli.config import load_config

        cfg = load_config()
    except Exception as exc:
        logger.debug("Could not load config for pre-update backup: %s", exc)
        cfg = {}

    updates_cfg = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    if not updates_cfg.get("pre_update_backup", True):
        _warn(
            "Backup antes da atualização: desativado "
            "(updates.pre_update_backup=false no config.yaml)"
        )
        print()
        return

    keep = int(updates_cfg.get("backup_keep", 5) or 5)

    try:
        from ector_cli.backup import create_pre_update_backup
    except Exception as exc:
        _warn(f"Backup antes da atualização: indisponível ({exc}) — continuando")
        print()
        return

    _info("Backup antes da atualização...")
    try:
        from ector_constants import get_ector_home

        out_path = create_pre_update_backup(
            ector_home=get_ector_home(),
            keep=keep,
        )
    except Exception as exc:
        _warn(f"Backup antes da atualização: falhou ({exc}) — continuando")
        print()
        return

    if out_path is None:
        _warn("Backup antes da atualização: ignorado — continuando")
        print()
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


def _stop_gateways_quietly() -> None:
    """Best-effort stop of gateway processes before mutating the install tree."""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_stop_gateway_processes)
            n = future.result(timeout=_GATEWAY_STOP_TIMEOUT_SEC)
    except FuturesTimeoutError:
        _warn("Paragem do gateway demorou — continuando")
        return
    except Exception as exc:
        logger.debug("Gateway stop skipped: %s", exc)
        return

    if n <= 0:
        return

    word = "processo" if n == 1 else "processos"
    _ok(f"Gateway: {n} {word} parado(s)")


def _restart_gateways_hint() -> None:
    print()
    _info("Reinicie o gateway quando quiser:")
    print(color("    ector gateway restart", Colors.DIM))
    print(color("    ector gateway start   # se não usa serviço", Colors.DIM))


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
    commits_word = "commit" if behind == 1 else "commits"
    if remote and current and remote != current:
        _ok(
            f"Atualização disponível: {remote} "
            f"(instalado: {current}; {behind} {commits_word} atrás de {upstream})"
        )
    elif remote:
        _ok(
            f"Atualização disponível: {remote} "
            f"({behind} {commits_word} atrás de {upstream})"
        )
    else:
        _ok(f"Atualização disponível: {behind} {commits_word} atrás de {upstream}")
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
) -> tuple[int, str]:
    """Run a shell command.

    ``stream=True`` attaches stdout/stderr to the terminal (no pipe capture).
    Piping install.sh stdout causes block-buffering stalls that make ``ector
    update`` look hung unless ``ECTOR_INSTALL_VERBOSE=1`` adds enough traffic
    to flush the buffer.
    """
    run_cwd = str(cwd) if cwd else None
    if stream:
        try:
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
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode, combined


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
        if line.strip().startswith("✗") or any(marker in lower for marker in error_markers):
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


def _run_installer_update(installer: Path, install_dir: Path, env: dict[str, str]) -> int:
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

    _info("Aplicando atualização...")
    print()

    for attempt in range(1, _MAX_INSTALL_ATTEMPTS + 1):
        if attempt > 1:
            print()
            _info("Tentando atualização novamente...")
        try:
            last_rc, last_log = _run_shell(cmd, cwd=install_dir, env=env, stream=True)
        except UpdateCancelled:
            _report_update_cancelled()
            return 130
        if last_rc == 0:
            return 0
        if attempt < _MAX_INSTALL_ATTEMPTS and _attempt_recovery(install_dir, last_log, env):
            continue
        break

    _report_install_failure(last_rc, last_log)
    return last_rc


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
    commits_word = "commit" if behind == 1 else "commits"
    if remote and current and remote != current:
        print(
            f"Atualização disponível: {remote} "
            f"(instalado: {current}; {behind} {commits_word} atrás de {upstream})."
        )
    elif remote:
        print(
            f"Atualização disponível: {remote} "
            f"({behind} {commits_word} atrás de {upstream})."
        )
    else:
        print(
            f"Atualização disponível: {behind} {commits_word} atrás de {upstream}."
        )
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

    _title("Atualização do Ector Agent")
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

    _run_pre_update_backup(args)

    _info("Preparando atualização...")
    sys.stdout.flush()
    _stop_gateways_quietly()

    env = _install_env(install_dir)
    try:
        result = _run_installer_update(installer, install_dir, env)
    except KeyboardInterrupt:
        _report_update_cancelled()
        sys.exit(130)

    _invalidate_update_cache()

    if result == 130:
        sys.exit(130)
    if result != 0:
        sys.exit(result)

    updated = _installed_version_label(install_dir)
    if updated:
        _ok(f"Atualizado para {updated}")

    _restart_gateways_hint()
