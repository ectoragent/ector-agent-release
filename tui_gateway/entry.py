import json
import os
import signal
import sys
import time
import traceback

from tui_gateway import server
from tui_gateway.server import _CRASH_LOG, dispatch, write_json
from tui_gateway.transport import TeeTransport


def _install_sidecar_publisher() -> None:
    """Mirror every dispatcher emit to the dashboard sidebar via WS.

    Activated by `ECTOR_TUI_SIDECAR_URL`, set by the dashboard's
    ``/api/pty`` endpoint when a chat tab passes a ``channel`` query param.
    Best-effort: connect failure or runtime drop falls back to stdio-only.
    """
    url = os.environ.get("ECTOR_TUI_SIDECAR_URL")

    if not url:
        return

    from tui_gateway.event_publisher import WsPublisherTransport

    server._stdio_transport = TeeTransport(
        server._stdio_transport, WsPublisherTransport(url)
    )


def _log_signal(signum: int, frame) -> None:
    """Capture WHICH thread and WHERE a termination signal hit us.

    SIG_DFL for SIGPIPE kills the process silently the instant any
    background thread (TTS playback, beep, voice status emitter, etc.)
    writes to a stdout the TUI has stopped reading.  Without this
    handler the gateway-exited banner in the TUI has no trace — the
    crash log never sees a Python exception because the kernel reaps
    the process before the interpreter runs anything.
    """
    name = {
        signal.SIGPIPE: "SIGPIPE",
        signal.SIGTERM: "SIGTERM",
        signal.SIGHUP: "SIGHUP",
    }.get(signum, f"signal {signum}")
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== {name} received · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            if frame is not None:
                f.write("main-thread stack at signal delivery:\n")
                traceback.print_stack(frame, file=f)
            # All live threads — signal may have been triggered by a
            # background thread (write to broken stdout from TTS, etc.).
            import threading as _threading
            for tid, th in _threading._active.items():
                f.write(f"\n--- thread {th.name} (id={tid}) ---\n")
                f.write("".join(traceback.format_stack(sys._current_frames().get(tid))))
    except Exception:
        pass
    print(f"[gateway-signal] {name}", file=sys.stderr, flush=True)
    sys.exit(0)


# SIGPIPE: ignore, don't exit. The old SIG_DFL killed the process
# silently whenever a *background* thread (TTS playback chain, voice
# debug stderr emitter, beep thread) wrote to a pipe the TUI had gone
# quiet on — even though the main thread was perfectly fine waiting on
# stdin.  Ignoring the signal lets Python raise BrokenPipeError on the
# offending write (write_json already handles that with a clean
# sys.exit(0) + _log_exit), which keeps the gateway alive as long as
# the main command pipe is still readable.  Terminal signals still
# route through _log_signal so kills and hangups are diagnosable.
signal.signal(signal.SIGPIPE, signal.SIG_IGN)
# SIGHUP: ignore while stdin is the command pipe.  Cursor/iTerm/tmux
# often deliver a spurious hangup to the process group mid-turn while
# the TUI↔gateway pipe is still open — the old handler called
# sys.exit(0) and killed in-flight agent work (see tui_gateway_crash.log).
# Real shutdown still arrives via stdin EOF when the TUI closes the pipe
# (gw.kill() → stdin.end()) or via SIGTERM.
signal.signal(signal.SIGHUP, signal.SIG_IGN)
signal.signal(signal.SIGTERM, _log_signal)
signal.signal(signal.SIGINT, signal.SIG_IGN)


def _gateway_ready_payload() -> dict:
    """Build the payload for the initial ``gateway.ready`` event.

    Includes the authenticated Ector identity (when present) so the TUI
    chrome can show which account is active.  Best-effort: any failure
    falls back to an empty payload — the gateway must boot even when
    identity_auth import or read fails.
    """
    payload: dict = {}
    try:
        from ector_cli.identity_auth import get_active_session

        session = get_active_session()
    except Exception:
        return payload
    if session is None:
        return payload
    payload["user"] = {
        "id": session.user_id,
        "email": session.email,
    }
    return payload


def _log_exit(reason: str, *, abnormal: bool = True) -> None:
    """Record why the gateway subprocess is shutting down.

    ``abnormal=False`` is used for a **normal** TUI teardown (stdin EOF when
    the Ink client closes the JSON-RPC pipe). That is not a crash; it used
    to land in ``tui_gateway_crash.log`` and looked like repeated failures.

    ``abnormal=True`` keeps the trail for broken-pipe / startup failures so
    voice-mode and similar issues remain debuggable from ``tui_gateway_crash.log``.
    """
    log_path = (
        _CRASH_LOG
        if abnormal
        else os.path.join(os.path.dirname(_CRASH_LOG), "tui_gateway_shutdown.log")
    )
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== gateway exit · {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"· reason={reason} ===\n"
            )
    except Exception:
        pass
    print(f"[gateway-exit] {reason}", file=sys.stderr, flush=True)


def main():
    try:
        from ector_process import set_process_title

        set_process_title("Ector")
    except Exception:
        pass

    _install_sidecar_publisher()

    ready_payload = _gateway_ready_payload()
    boot_user = (ready_payload.get("user") or {}) if isinstance(ready_payload, dict) else {}
    if not write_json({
        "jsonrpc": "2.0",
        "method": "event",
        "params": {"type": "gateway.ready", "payload": ready_payload},
    }):
        _log_exit("startup write failed (broken stdout pipe before first event)")
        sys.exit(0)

    try:
        from tui_gateway.identity_watch import start_identity_watch

        start_identity_watch(
            boot_user_id=boot_user.get("id"),
            boot_email=boot_user.get("email"),
        )
    except Exception:
        pass

    try:
        from tools.cloud_skills_sync import ensure_cloud_skills_for_agent_startup

        ensure_cloud_skills_for_agent_startup()
    except Exception:
        pass

    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue

            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                if not write_json({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None}):
                    _log_exit("parse-error-response write failed (broken stdout pipe)")
                    sys.exit(0)
                continue

            method = req.get("method") if isinstance(req, dict) else None
            resp = dispatch(req)
            if resp is not None:
                if not write_json(resp):
                    _log_exit(f"response write failed for method={method!r} (broken stdout pipe)")
                    sys.exit(0)
    finally:
        try:
            from tui_gateway.identity_watch import stop_identity_watch

            stop_identity_watch()
        except Exception:
            pass

    server.shutdown_sessions_for_exit()
    _log_exit("stdin EOF (TUI closed the command pipe)", abnormal=False)


if __name__ == "__main__":
    main()
