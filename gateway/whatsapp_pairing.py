"""
WhatsApp QR pairing subprocess for the dashboard (pair-http bridge mode).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ector_cli.config import get_ector_home, save_env_value

_lock = threading.RLock()
_state: dict[str, Any] = {
    "proc": None,
    "port": None,
    "session_dir": None,
    "mode": None,
    "error": None,
    "active": False,
    "stderr_tail": "",
    "installing": False,
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = PROJECT_ROOT / "scripts" / "whatsapp-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _ensure_bridge_deps() -> tuple[bool, str]:
    from gateway.whatsapp_bridge_install import ensure_bridge_deps

    with _lock:
        _state["installing"] = True
    try:
        return ensure_bridge_deps()
    finally:
        with _lock:
            _state["installing"] = False


def _poll_bridge_status(port: int, timeout: float = 2.0) -> dict | None:
    url = f"http://127.0.0.1:{port}/pair/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _wait_for_bridge_http(port: int, proc: subprocess.Popen, timeout: float = 25.0) -> tuple[bool, str]:
    """Wait until /pair/status responds or the subprocess exits."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = _read_stderr_tail(proc)
            return False, tail or "A ponte do WhatsApp encerrou antes de ficar pronta."
        remote = _poll_bridge_status(port, timeout=1.0)
        if remote is not None:
            return True, ""
        time.sleep(0.4)
    return False, "A ponte WhatsApp não respondeu a tempo. Verifique Node.js e npm install."


def _read_stderr_tail(proc: subprocess.Popen | None) -> str:
    if proc is None or proc.stderr is None:
        with _lock:
            return str(_state.get("stderr_tail") or "")
    try:
        raw = proc.stderr.read() or b""
        text = raw.decode("utf-8", errors="replace").strip()
        tail = text[-800:] if text else ""
        with _lock:
            if tail:
                _state["stderr_tail"] = tail
        return tail
    except Exception:
        return ""


def _terminate_proc(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def _reset_state_unlocked() -> None:
    _terminate_proc(_state.get("proc"))
    _state["proc"] = None
    _state["port"] = None
    _state["error"] = None
    _state["active"] = False
    _state["stderr_tail"] = ""


def cancel_pairing() -> dict:
    with _lock:
        _reset_state_unlocked()
    return {"ok": True}


def start_pairing(
    *,
    mode: str = "self-chat",
    reset_session: bool = False,
    allowed_users: str = "",
) -> dict:
    """Start bridge in --pair-http mode on loopback."""
    from gateway.platform_catalog import check_managed

    check_managed()

    ok, msg = _ensure_bridge_deps()
    if not ok:
        return {"ok": False, "error": msg, "installing": False}

    if mode not in ("bot", "self-chat"):
        mode = "self-chat"

    session_dir = get_ector_home() / "whatsapp" / "session"
    session_dir.mkdir(parents=True, exist_ok=True)

    if reset_session and session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
        session_dir.mkdir(parents=True, exist_ok=True)

    save_env_value("WHATSAPP_MODE", mode)
    if allowed_users:
        save_env_value("WHATSAPP_ALLOWED_USERS", allowed_users.replace(" ", ""))

    port = _free_port()
    cmd = [
        "node",
        str(BRIDGE_SCRIPT),
        "--pair-http",
        "--pair-port",
        str(port),
        "--session",
        str(session_dir),
        "--mode",
        mode,
    ]

    env = os.environ.copy()
    env["ECTOR_HOME"] = str(get_ector_home())
    env["WHATSAPP_MODE"] = mode
    if allowed_users:
        env["WHATSAPP_ALLOWED_USERS"] = allowed_users.replace(" ", "")

    with _lock:
        _reset_state_unlocked()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(BRIDGE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        _state["proc"] = proc
        _state["port"] = port
        _state["session_dir"] = str(session_dir)
        _state["mode"] = mode
        _state["error"] = None
        _state["active"] = True
        _state["stderr_tail"] = ""

    ready, err = _wait_for_bridge_http(port, proc)
    if not ready:
        tail = _read_stderr_tail(proc)
        detail = tail or err
        with _lock:
            _reset_state_unlocked()
            _state["error"] = detail
        return {"ok": False, "error": detail}

    return {"ok": True, "port": port, "mode": mode}


def pairing_status() -> dict:
    session_file = get_ector_home() / "whatsapp" / "session" / "creds.json"

    with _lock:
        proc = _state.get("proc")
        port = _state.get("port")
        err = _state.get("error")
        active = bool(_state.get("active"))
        stderr_tail = str(_state.get("stderr_tail") or "")
        installing = bool(_state.get("installing"))

    if installing:
        return {
            "state": "installing",
            "message": "Instalando dependências da ponte WhatsApp (só na primeira vez)…",
            "qrDataUrl": None,
        }

    # Already paired from a previous session (no active pairing flow).
    if session_file.exists() and not active and port is None:
        return {
            "state": "paired",
            "message": "Sessão WhatsApp já emparelhada.",
            "qrDataUrl": None,
        }

    if port is None:
        return {
            "state": "idle",
            "message": "Nenhum emparelhamento em andamento.",
            "qrDataUrl": None,
            "error": err,
        }

    if proc is not None and proc.poll() is not None:
        stderr = _read_stderr_tail(proc)
        with _lock:
            _reset_state_unlocked()
        if session_file.exists():
            save_env_value("WHATSAPP_ENABLED", "true")
            return {"state": "paired", "message": "Emparelhamento concluído.", "qrDataUrl": None}
        return {
            "state": "error",
            "message": "Processo de emparelhamento terminou inesperadamente.",
            "qrDataUrl": None,
            "error": stderr or err or stderr_tail,
        }

    remote = _poll_bridge_status(int(port))
    if remote:
        st = str(remote.get("state", "waiting"))
        if st == "connected":
            save_env_value("WHATSAPP_ENABLED", "true")
            with _lock:
                _reset_state_unlocked()
            return {
                "state": "paired",
                "message": remote.get("message") or "WhatsApp emparelhado.",
                "qrDataUrl": None,
            }
        if st in ("logged_out", "error"):
            msg = remote.get("message") or "Emparelhamento falhou."
            with _lock:
                _reset_state_unlocked()
                _state["error"] = msg
            return {
                "state": "error",
                "message": msg,
                "qrDataUrl": None,
                "error": remote.get("error") or msg,
            }
        return {
            "state": st,
            "message": remote.get("message"),
            "qrDataUrl": remote.get("qrDataUrl"),
            "error": remote.get("error"),
        }

    return {
        "state": "starting",
        "message": "Iniciando ponte WhatsApp…",
        "qrDataUrl": None,
        "error": err,
    }
