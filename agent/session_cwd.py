"""Per-session working directory persistence and terminal env binding."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CWD_PLACEHOLDERS = frozenset({".", "auto", "cwd"})


def _load_config():
    from ector_cli.config import load_config

    return load_config()


def _launch_terminal_cwd() -> Optional[str]:
    """Best-effort cwd from env or process (CLI/TUI launch directory)."""
    for key in ("TERMINAL_CWD", "ECTOR_CWD"):
        raw = os.environ.get(key, "").strip()
        if not raw or raw in CWD_PLACEHOLDERS:
            continue
        expanded = os.path.expanduser(raw)
        if os.path.isabs(expanded):
            return os.path.abspath(expanded)
    try:
        from ector_constants import safe_getcwd

        return os.path.abspath(safe_getcwd())
    except Exception:
        return None


def default_terminal_cwd(*, cwd_placeholder: str = "launch") -> str:
    """Fallback cwd when ``terminal.cwd`` is ``.`` / ``auto``."""
    if cwd_placeholder == "home":
        return str(Path.home().resolve())
    return _launch_terminal_cwd() or str(Path.home().resolve())


def configured_terminal_cwd(*, cwd_placeholder: str = "launch") -> str:
    """Canonical cwd from config (footer, ``TERMINAL_CWD``, agent prompt).

    *cwd_placeholder* controls ``terminal.cwd`` values like ``.`` / ``auto``:

    - ``launch`` (CLI/TUI): ``TERMINAL_CWD``, ``ECTOR_CWD``, then process cwd
    - ``home`` (web dashboard): user home — never inherit server process cwd
    """
    try:
        cfg = _load_config() or {}
        term = cfg.get("terminal") or {}
        if isinstance(term, dict):
            raw = str(term.get("cwd") or "").strip()
            if raw and raw not in CWD_PLACEHOLDERS:
                return os.path.abspath(os.path.expanduser(raw))
            if cwd_placeholder == "home":
                return str(Path.home().resolve())
            launch = _launch_terminal_cwd()
            if launch:
                return launch
    except Exception:
        pass
    return default_terminal_cwd(cwd_placeholder=cwd_placeholder)


def bootstrap_interactive_terminal_cwd() -> str:
    """Seed ``TERMINAL_CWD`` for CLI/TUI from launch env + config bridge.

    Mirrors ``load_cli_config()`` terminal bridging so the gateway picks up
    the directory where the user ran ``ector chat``, not the subprocess cwd.
    """
    ector_cwd = os.environ.get("ECTOR_CWD", "").strip()
    if ector_cwd and ector_cwd not in CWD_PLACEHOLDERS:
        launch = os.path.abspath(os.path.expanduser(ector_cwd))
        existing = os.environ.get("TERMINAL_CWD", "").strip()
        existing_abs = (
            os.path.abspath(os.path.expanduser(existing))
            if existing and existing not in CWD_PLACEHOLDERS
            else ""
        )
        if not existing_abs or existing_abs != launch:
            os.environ["TERMINAL_CWD"] = launch
    try:
        from ector_cli.cli_config import load_cli_config

        load_cli_config()
    except Exception:
        pass
    resolved = configured_terminal_cwd(cwd_placeholder="launch")
    os.environ["TERMINAL_CWD"] = resolved
    return resolved


def config_has_explicit_terminal_cwd() -> bool:
    """True when ``terminal.cwd`` in config is a concrete path (not . / auto / cwd)."""
    try:
        cfg = _load_config() or {}
        term = cfg.get("terminal") or {}
        if isinstance(term, dict):
            raw = str(term.get("cwd") or "").strip()
            return bool(raw and raw not in CWD_PLACEHOLDERS)
    except Exception:
        pass
    return False


def web_workspace_defined(session_id: Optional[str] = None) -> bool:
    """Whether the web dashboard should show an opened project (vs. prompt to open folder)."""
    if config_has_explicit_terminal_cwd():
        return True

    default_home = os.path.abspath(configured_terminal_cwd(cwd_placeholder="home"))

    if session_id:
        persisted = load_persisted_session_cwd(session_id)
        if not persisted:
            return False
        return os.path.abspath(persisted) != default_home

    raw = os.environ.get("TERMINAL_CWD", "").strip()
    if raw and raw not in CWD_PLACEHOLDERS:
        resolved = os.path.abspath(os.path.expanduser(raw))
        return resolved != default_home
    return False


def path_is_web_workspace(path: str) -> bool:
    """True when *path* is a concrete project folder (not the default home cwd)."""
    if config_has_explicit_terminal_cwd():
        return True
    text = (path or "").strip()
    if not text or text in CWD_PLACEHOLDERS:
        return False
    try:
        resolved = os.path.abspath(os.path.expanduser(text))
    except Exception:
        return False
    default_home = os.path.abspath(configured_terminal_cwd(cwd_placeholder="home"))
    return resolved != default_home


def cwd_from_model_config(raw: Any) -> Optional[str]:
    if not raw:
        return None
    try:
        meta = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    cwd = meta.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return os.path.abspath(os.path.expanduser(cwd.strip()))
    return None


def load_persisted_session_cwd(session_id: str) -> Optional[str]:
    if not session_id:
        return None
    try:
        from ector_state import SessionDB

        db = SessionDB()
        try:
            sid = db.resolve_session_id(session_id) or session_id
            row = db.get_session(sid)
            return cwd_from_model_config((row or {}).get("model_config"))
        finally:
            db.close()
    except Exception:
        return None


def persist_session_cwd(
    session_id: str, cwd: str, *, source: str = "web"
) -> None:
    if not session_id or not cwd:
        return
    try:
        from ector_state import SessionDB

        db = SessionDB()
        try:
            sid = db.resolve_session_id(session_id) or session_id
            exists = db.get_session(sid) is not None
            # Web: never create a ghost session row just to store cwd — that
            # shows up as empty "Novo chat" entries in the sidebar. In-memory
            # apply_session_cwd + landing cwd cover the gap until the first
            # real chat turn calls ensure_session.
            if not exists:
                if source == "web":
                    return
                db.ensure_session(sid, source=source)
            db.merge_model_config(sid, {"cwd": cwd})
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to persist session cwd", exc_info=True)


def cwd_from_terminal_env(task_id: str) -> Optional[str]:
    """Read cwd from an active terminal env for *task_id*, if any."""
    try:
        from tools.terminal_tool import get_active_env

        env = get_active_env(task_id)
        if env is None:
            return None
        cwd = getattr(env, "cwd", None)
        if isinstance(cwd, str) and cwd.strip():
            return os.path.abspath(os.path.expanduser(cwd.strip()))
    except Exception:
        return None
    return None


def apply_session_cwd(
    session_id: str, cwd: str, *, cwd_placeholder: str = "launch"
) -> str:
    """Bind *cwd* to a chat session (per-session terminal env override).

    Does **not** write ``TERMINAL_CWD`` when *session_id* is set — that env var
    is process-global and would leak folders across concurrent web chats.
    """
    resolved = os.path.abspath(os.path.expanduser((cwd or "").strip()))
    if not resolved:
        resolved = configured_terminal_cwd(cwd_placeholder=cwd_placeholder)
    if session_id:
        try:
            from tools.terminal_tool import (
                get_active_env,
                register_task_env_overrides,
            )

            register_task_env_overrides(session_id, {"cwd": resolved})
            env = get_active_env(session_id)
            if env is not None:
                env.cwd = resolved
        except Exception:
            pass
    else:
        os.environ["TERMINAL_CWD"] = resolved
    return resolved


def prime_session_cwd(
    session_id: Optional[str], *, cwd_placeholder: str = "launch"
) -> None:
    """Bootstrap cwd for *session_id* without clobbering a live terminal env."""
    if not session_id:
        return
    # openProject / landing bind may have registered a real project before the
    # session row exists — never replace that with the home placeholder.
    existing_override = cwd_from_task_override(session_id)
    if existing_override and path_is_web_workspace(existing_override):
        return

    persisted = load_persisted_session_cwd(session_id)
    configured = configured_terminal_cwd(cwd_placeholder=cwd_placeholder)
    try:
        from tools.terminal_tool import get_active_env, register_task_env_overrides

        env = get_active_env(session_id)
        if env is not None:
            active = getattr(env, "cwd", None)
            if isinstance(active, str) and active.strip():
                resolved = os.path.abspath(os.path.expanduser(active.strip()))
                # After server restart the in-memory shell may be at configured home
                # while SQLite still has the chat's last directory.
                if (
                    persisted
                    and resolved == configured
                    and os.path.abspath(persisted) != configured
                ):
                    apply_session_cwd(
                        session_id, persisted, cwd_placeholder=cwd_placeholder
                    )
                    return
                register_task_env_overrides(session_id, {"cwd": resolved})
            return
    except Exception:
        pass
    initial = persisted or configured
    apply_session_cwd(session_id, initial, cwd_placeholder=cwd_placeholder)


def live_terminal_cwd(session_id: Optional[str] = None) -> Optional[str]:
    """Best-effort live cwd (per-session sandbox only — never shared ``default``)."""
    if session_id:
        return cwd_from_terminal_env(session_id)
    return cwd_from_terminal_env("default")


def sync_session_cwd_from_env(
    session_id: str, *, allow_default_env: bool = False, source: str = "web"
) -> None:
    """Persist cwd from the live terminal env into the session row.

    Read-only footer loads must not call this with ``allow_default_env`` — a
    shared ``default`` shell at home would overwrite per-chat directories
    after a server restart or dashboard rebuild.

    Never falls back to process-global ``TERMINAL_CWD``: that value is often
    the last *other* chat that was primed and must not be written into this
    session's SQLite row.
    """
    if not session_id:
        return
    active = cwd_from_terminal_env(session_id)
    if not active and allow_default_env:
        active = cwd_from_terminal_env("default")
    if active:
        try:
            from tools.terminal_tool import register_task_env_overrides

            register_task_env_overrides(session_id, {"cwd": active})
        except Exception:
            pass
        persist_session_cwd(session_id, active, source=source)


def cwd_from_task_override(task_id: Optional[str]) -> Optional[str]:
    """Cwd registered via ``register_task_env_overrides`` (before shell exists)."""
    if not task_id:
        return None
    try:
        from tools.terminal_tool import _task_env_overrides

        raw = _task_env_overrides.get(task_id) or {}
        cwd = raw.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            return os.path.abspath(os.path.expanduser(cwd.strip()))
    except Exception:
        return None
    return None


def resolve_chat_cwd(
    session_id: Optional[str] = None,
    *,
    cwd_placeholder: str = "launch",
    allow_default_env: bool = False,
) -> str:
    """Working directory for chat footer (per-session when possible)."""
    configured = configured_terminal_cwd(cwd_placeholder=cwd_placeholder)
    if session_id:
        session_live = cwd_from_terminal_env(session_id)
        if session_live:
            return session_live
        override = cwd_from_task_override(session_id)
        if override:
            return override
        if allow_default_env:
            default_live = cwd_from_terminal_env("default")
            if default_live:
                return default_live
            raw = os.environ.get("TERMINAL_CWD", "").strip()
            if raw and raw not in CWD_PLACEHOLDERS:
                return os.path.abspath(os.path.expanduser(raw))
        persisted = load_persisted_session_cwd(session_id)
        if persisted:
            return persisted
        return configured
    active = cwd_from_terminal_env("default")
    if active:
        return active
    return configured
