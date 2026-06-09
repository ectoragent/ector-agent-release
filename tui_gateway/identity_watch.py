"""Poll ``identity.json`` while the TUI gateway runs.

Detects logout or account switches performed in another terminal (e.g.
``ector logout`` / ``ector login``) and emits JSON-RPC events so the Ink
client can block the composer and reset state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

_log = logging.getLogger(__name__)

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_boot_user_id: str = ""
_boot_email: str = ""
_last_user_id: Optional[str] = None
_state_lock = threading.Lock()


def _poll_interval_seconds() -> float:
    try:
        from ector_cli.config import load_config

        cfg = load_config() or {}
        auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else {}
        raw = auth.get("tui_identity_poll_seconds", 5)
        interval = float(raw)
        return max(1.0, interval)
    except Exception:
        return 5.0


def _current_user_id() -> Optional[str]:
    try:
        from ector_cli.identity_auth import get_persisted_session

        session = get_persisted_session()
    except Exception:
        return None
    if session is None:
        return None
    uid = str(session.user_id or "").strip()
    return uid or None


def _current_user_payload() -> Optional[dict]:
    try:
        from ector_cli.identity_auth import get_persisted_session

        session = get_persisted_session()
    except Exception:
        return None
    if session is None:
        return None
    return {
        "id": session.user_id,
        "email": session.email,
    }


def interrupt_all_sessions() -> None:
    """Interrupt in-flight turns on every live gateway session."""
    from tui_gateway import server

    for sid, session in list(server._sessions.items()):
        try:
            if session.get("running") and session.get("agent") is not None:
                agent = session["agent"]
                if hasattr(agent, "interrupt"):
                    agent.interrupt()
            server._clear_pending(sid)
            try:
                from tools.approval import resolve_gateway_approval

                key = session.get("session_key")
                if key:
                    resolve_gateway_approval(key, "deny", resolve_all=True)
            except Exception:
                pass
        except Exception:
            _log.debug("interrupt session %s failed", sid, exc_info=True)


def _emit_identity_event(event: str, payload: dict | None = None) -> None:
    from tui_gateway.server import _emit

    _emit(event, "", payload)


def _purge_previous_user_data(previous_user_id: str) -> None:
    if not previous_user_id:
        return
    try:
        from ector_constants import get_ector_home
        from ector_state import SessionDB

        db = SessionDB()
        sessions_dir = get_ector_home() / "sessions"
        db.delete_sessions_for_user(previous_user_id, sessions_dir=sessions_dir)
        db.delete_untagged_sessions(sessions_dir=sessions_dir)
    except Exception:
        _log.warning("failed to purge sessions for user %s", previous_user_id, exc_info=True)


def _sync_profile_best_effort() -> None:
    try:
        from ector_cli.identity_auth import sync_user_profile_from_cloud

        sync_user_profile_from_cloud()
    except Exception:
        _log.debug("sync_user_profile_from_cloud failed", exc_info=True)


def _sync_cloud_skills_best_effort() -> None:
    try:
        from tools.cloud_skills_sync import maybe_schedule_cloud_skills_sync

        maybe_schedule_cloud_skills_sync(quiet=True, force=False)
    except Exception:
        _log.debug("cloud skills sync after identity change failed", exc_info=True)


def _handle_user_changed(previous_user_id: str, *, reason: str) -> None:
    interrupt_all_sessions()
    _purge_previous_user_data(previous_user_id)
    _sync_profile_best_effort()
    _sync_cloud_skills_best_effort()
    user = _current_user_payload()
    _emit_identity_event(
        "identity.user_changed",
        {
            "previous_user_id": previous_user_id,
            "reason": reason,
            "user": user,
        },
    )


def _handle_revoked() -> None:
    interrupt_all_sessions()
    _emit_identity_event(
        "identity.revoked",
        {"message": "Sessão encerrada. Execute `ector login` para continuar."},
    )


def _handle_restored() -> None:
    _sync_cloud_skills_best_effort()
    user = _current_user_payload()
    _emit_identity_event("identity.restored", {"user": user})


def _tick() -> None:
    global _last_user_id

    current_id = _current_user_id()

    with _state_lock:
        previous_id = _last_user_id
        boot_id = _boot_user_id

    if previous_id and not current_id:
        _handle_revoked()
    elif not previous_id and current_id:
        if boot_id and current_id != boot_id:
            _handle_user_changed(boot_id, reason="login_different_user")
        elif boot_id and current_id == boot_id:
            _handle_restored()
        elif boot_id:
            pass
        else:
            _handle_restored()
    elif (
        previous_id
        and current_id
        and previous_id != current_id
    ):
        _handle_user_changed(previous_id, reason="account_switch")

    with _state_lock:
        _last_user_id = current_id


def _watch_loop() -> None:
    while not _stop.wait(_poll_interval_seconds()):
        try:
            _tick()
        except Exception:
            _log.debug("identity watch tick failed", exc_info=True)


def start_identity_watch(
    boot_user_id: str | None = None,
    boot_email: str | None = None,
) -> None:
    """Start the background identity poller (idempotent)."""
    global _thread, _boot_user_id, _boot_email, _last_user_id

    stop_identity_watch()

    with _state_lock:
        _boot_user_id = (boot_user_id or "").strip()
        _boot_email = (boot_email or "").strip()
        _last_user_id = _current_user_id()
        _stop.clear()

    _thread = threading.Thread(
        target=_watch_loop,
        name="tui-identity-watch",
        daemon=True,
    )
    _thread.start()


def stop_identity_watch() -> None:
    """Stop the background identity poller."""
    global _thread

    _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=2.0)
    _thread = None


__all__ = [
    "interrupt_all_sessions",
    "start_identity_watch",
    "stop_identity_watch",
]
