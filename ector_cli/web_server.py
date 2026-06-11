"""
Ector Agent — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m ector_cli.main web          # Start on http://ector.localhost:9000
    python -m ector_cli.main web --port 8080
"""

import asyncio
import base64
import contextlib
import hmac
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
import signal

import uuid

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ector_cli import __version__, __version_code__, __version_name__
from ector_cli.config import (
    DEFAULT_CONFIG,
    OPTIONAL_ENV_VARS,
    format_managed_message,
    get_config_path,
    get_env_path,
    get_ector_home,
    get_managed_system,
    is_managed,
    load_config,
    load_env,
    save_config,
    save_env_value,
    remove_env_value,
    check_config_version,
    redact_key,
)
from gateway.status import get_running_pid, read_runtime_status
from ector_cli.dashboard_auth import create_dashboard_access_token, verify_dashboard_access_token

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    raise SystemExit(
        "Web UI requires fastapi and uvicorn.\n"
        f"Install with: {sys.executable} -m pip install 'fastapi' 'uvicorn[standard]'"
    )

WEB_DIST = Path(os.environ["ECTOR_WEB_DIST"]) if "ECTOR_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"
_log = logging.getLogger(__name__)

app = FastAPI(title="ECTOR", version=__version__)

# ---------------------------------------------------------------------------
# Session token for protecting sensitive endpoints (reveal).
# Generated fresh on every server start — dies when the process exits.
# Injected into the SPA HTML so only the legitimate web UI can use it.
# ---------------------------------------------------------------------------
_SESSION_TOKEN = secrets.token_urlsafe(32)
_SESSION_HEADER_NAME = "X-Ector-Session-Token"

# ---------------------------------------------------------------------------
# "Real" dashboard authentication (optional): signed access tokens exchanged
# for an HttpOnly cookie. Enables token URL on `ector localhost` startup.
# ---------------------------------------------------------------------------
_DASH_AUTH_COOKIE_NAME = "ector_dash_auth"
_DASH_AUTH_QUERY_PARAM = "token"
_DASH_AUTH_DEFAULT_COOKIE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# Dashboard PID file (profile-aware via get_ector_home()).
_DASHBOARD_PID_DIR_NAME = "dashboard"
_DASHBOARD_PID_FILE_NAME = "dashboard.pid"


def _dashboard_pid_path() -> Path:
    return get_ector_home() / _DASHBOARD_PID_DIR_NAME / _DASHBOARD_PID_FILE_NAME


def write_dashboard_pid_file() -> None:
    path = _dashboard_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def read_dashboard_pid_file() -> Optional[int]:
    path = _dashboard_pid_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text().strip()
        pid = int(raw)
        return pid if pid > 1 else None
    except Exception:
        return None


def clear_dashboard_pid_file() -> None:
    try:
        _dashboard_pid_path().unlink(missing_ok=True)
    except Exception:
        pass


_DASHBOARD_CMD_PATTERNS = (
    "ector_cli.dashboard_daemon",
    "ector_cli.web_server",
    "ector_cli.main localhost",
    "ector_cli/main.py localhost",
    "ector localhost",
    "ector_cli.main web",
    "ector_cli/main.py web",
)


def _append_unique_dashboard_pid(pids: list[int], pid: int | None, exclude: set[int]) -> None:
    if pid is None or pid <= 1 or pid in exclude or pid in pids:
        return
    pids.append(pid)


def _dashboard_command_matches(command: str) -> bool:
    if not command:
        return False
    if any(pattern in command for pattern in _DASHBOARD_CMD_PATTERNS):
        return True
    lower = command.lower()
    if "uvicorn" in lower and ("ector_cli" in lower or "web_server" in lower):
        return True
    return False


def _dashboard_matches_current_profile(command: str) -> bool:
    current_home = str(get_ector_home().resolve())
    if f"ECTOR_HOME={current_home}" in command:
        return True
    if "--profile " in command or " -p " in command:
        profiles_root = Path.home() / ".ector" / "profiles"
        try:
            rel = get_ector_home().resolve().relative_to(profiles_root.resolve())
            if len(rel.parts) == 1:
                profile_name = rel.parts[0]
                return (
                    f"--profile {profile_name}" in command
                    or f"-p {profile_name}" in command
                )
        except ValueError:
            pass
        return False
    if "ECTOR_HOME=" in command and f"ECTOR_HOME={current_home}" not in command:
        return False
    return True


def _process_command_line(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _scan_dashboard_pids(exclude: set[int] | None = None) -> list[int]:
    """Find dashboard-related PIDs via process command line (current profile)."""
    exclude_set = set(exclude or ())
    pids: list[int] = []
    try:
        result = subprocess.run(
            ["ps", "-A", "eww", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        for line in result.stdout.split("\n"):
            stripped = line.strip()
            if not stripped or "grep" in stripped:
                continue
            pid = None
            command = ""
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                try:
                    pid = int(parts[0])
                    command = parts[1]
                except ValueError:
                    pid = None
            if pid is None:
                aux_parts = stripped.split()
                if len(aux_parts) > 10 and aux_parts[1].isdigit():
                    pid = int(aux_parts[1])
                    command = " ".join(aux_parts[10:])
            if pid is None:
                continue
            if _dashboard_command_matches(command) and _dashboard_matches_current_profile(command):
                _append_unique_dashboard_pid(pids, pid, exclude_set)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return pids


def _pids_listening_on_tcp_port(port: int) -> list[int]:
    if sys.platform == "win32":
        return []
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        pids: list[int] = []
        for line in (result.stdout or "").split():
            line = line.strip()
            if not line:
                continue
            try:
                pids.append(int(line))
            except ValueError:
                continue
        return pids
    except (OSError, subprocess.TimeoutExpired):
        return []


def _probe_ector_dashboard_http(port: int, *, host: str = "127.0.0.1") -> bool:
    """True when something on *port* responds like our /api/status endpoint."""
    url = f"http://{host}:{int(port)}/api/status"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return False
    return isinstance(body, dict) and "version" in body and "ector_home" in body


def wait_for_dashboard_ready(
    port: int,
    *,
    host: str = "127.0.0.1",
    timeout_seconds: float = 60.0,
    poll_interval: float = 0.05,
) -> bool:
    """Poll until the dashboard HTTP endpoint responds."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _probe_ector_dashboard_http(port, host=host):
            return True
        time.sleep(poll_interval)
    return False


def open_dashboard_browser(
    open_url: Optional[str] = None,
    *,
    host: str = "127.0.0.1",
    port: int = 9000,
    timeout_seconds: float = 60.0,
) -> None:
    """Open the dashboard in the system browser after the server is reachable."""
    import webbrowser

    probe_host = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    if not wait_for_dashboard_ready(
        port,
        host=probe_host,
        timeout_seconds=timeout_seconds,
    ):
        _log.warning(
            "Painel não respondeu em %ss; abrindo o navegador mesmo assim.",
            timeout_seconds,
        )

    if open_url:
        url = open_url
    else:
        friendly = get_dashboard_local_hostname()
        display_host = friendly if friendly and host in _LOOPBACK_HOST_VALUES else host
        url = f"http://{display_host}:{port}"

    try:
        webbrowser.open(url)
    except Exception:
        pass


def find_dashboard_pids(*, port: int | None = None, exclude: set[int] | None = None) -> list[int]:
    """Collect PIDs for the dashboard in the active profile (PID file, ps, port)."""
    exclude_set = set(exclude or ())
    pids: list[int] = []

    pid_file = read_dashboard_pid_file()
    if pid_file:
        try:
            os.kill(pid_file, 0)
            _append_unique_dashboard_pid(pids, pid_file, exclude_set)
        except OSError:
            clear_dashboard_pid_file()

    for pid in _scan_dashboard_pids(exclude_set):
        _append_unique_dashboard_pid(pids, pid, exclude_set)

    if port is not None and int(port) > 0:
        port_int = int(port)
        if _probe_ector_dashboard_http(port_int):
            for pid in _pids_listening_on_tcp_port(port_int):
                cmd = _process_command_line(pid)
                if cmd and not _dashboard_command_matches(cmd):
                    # Port serves Ector /api/status but cmdline is opaque — still stop it.
                    pass
                _append_unique_dashboard_pid(pids, pid, exclude_set)

    return pids


def _terminate_dashboard_pid(pid: int, *, timeout_seconds: float) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            return False

    deadline = time.time() + float(timeout_seconds)
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


def stop_running_dashboard(*, timeout_seconds: float = 5.0, port: int | None = 9000) -> bool:
    """Best-effort stop for a dashboard process (PID file, ps scan, or TCP port).

    Returns True if at least one running process was found and stopped.
    """
    pids = find_dashboard_pids(port=port)
    if not pids:
        clear_dashboard_pid_file()
        return False

    stopped_any = False
    per_pid_timeout = max(0.5, float(timeout_seconds) / max(len(pids), 1))
    for pid in pids:
        if _terminate_dashboard_pid(pid, timeout_seconds=per_pid_timeout):
            stopped_any = True

    clear_dashboard_pid_file()
    return stopped_any

_WEB_CHAT_DEBUG = (
    str(os.environ.get("ECTOR_WEB_CHAT_DEBUG", "")).strip().lower()
    in {"1", "true", "yes", "on"}
)

# Simple rate limiter for the reveal endpoint
_reveal_timestamps: List[float] = []
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30

# Accepted Host header values for loopback binds. DNS rebinding attacks
# point a victim browser at an attacker-controlled hostname (evil.test)
# which resolves to 127.0.0.1 after a TTL flip — bypassing same-origin
# checks because the browser now considers evil.test and our dashboard
# "same origin". Validating the Host header at the app layer rejects any
# request whose Host isn't one we bound for. See GHSA-ppp5-vxwm-4cf7.
_LOOPBACK_HOST_VALUES: frozenset = frozenset({
    "localhost", "127.0.0.1", "::1",
})

# Friendly loopback hostname (RFC 6761 *.localhost → 127.0.0.1 in modern browsers).
DEFAULT_DASHBOARD_LOCAL_HOSTNAME = "ector.localhost"


def _normalize_dashboard_local_hostname(raw: str) -> str:
    """Return a safe hostname fragment, or empty string if invalid/disabled."""
    h = (raw or "").strip().lower().rstrip(".")
    if not h or "/" in h or " " in h or ":" in h:
        return ""
    return h


def get_dashboard_local_hostname() -> str:
    """Hostname for friendly local dashboard URLs (e.g. ector.localhost).

    Precedence: ``ECTOR_DASHBOARD_LOCAL_HOSTNAME`` env → ``dashboard.local_hostname``
    in config → :data:`DEFAULT_DASHBOARD_LOCAL_HOSTNAME`. An explicit empty value
    disables the friendly name (CLI falls back to ``127.0.0.1``).
    """
    env = os.environ.get("ECTOR_DASHBOARD_LOCAL_HOSTNAME", "").strip()
    if env:
        return _normalize_dashboard_local_hostname(env)
    try:
        cfg = load_config()
        dashboard = cfg.get("dashboard") if isinstance(cfg.get("dashboard"), dict) else {}
        if "local_hostname" in dashboard:
            return _normalize_dashboard_local_hostname(str(dashboard.get("local_hostname") or ""))
    except Exception:
        pass
    return DEFAULT_DASHBOARD_LOCAL_HOSTNAME


def dashboard_local_hostnames() -> frozenset[str]:
    """Loopback names plus the configured friendly hostname (when set)."""
    names = set(_LOOPBACK_HOST_VALUES)
    friendly = get_dashboard_local_hostname()
    if friendly:
        names.add(friendly)
    return frozenset(names)


def _dashboard_cors_origin_regex() -> str:
    parts = ["localhost", r"127\.0\.0\.1"]
    friendly = get_dashboard_local_hostname()
    if friendly:
        parts.append(re.escape(friendly))
    return rf"^https?://({'|'.join(parts)})(:\d+)?$"


# CORS: restrict to localhost origins only.  The web UI is intended to run
# locally; binding to 0.0.0.0 with allow_origins=["*"] would let any website
# read/modify config and secrets.

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_dashboard_cors_origin_regex(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Endpoints that do NOT require the session token.  Everything else under
# /api/ is gated by the auth middleware below.  Keep this list minimal —
# only truly non-sensitive, read-only endpoints belong here.
# ---------------------------------------------------------------------------
_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/status",
    "/api/cwd",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/auth/logout",
    # Metadados do assistente de primeiros passos (sem segredos) — útil se o
    # token da sessão ainda não estiver disponível no primeiro paint.
    "/api/setup/catalog",
    # Alias neutro — alguns bloqueadores de anúncios filtram ``/setup/`` nas URLs.
    "/api/firstrun/providers",
    # Lista de toolsets configuráveis (sem segredos). Necessário para parear o
    # wizard web com o `ector setup` antes de haver sessão completa.
    "/api/tools/toolsets",
})


def _has_valid_session_token(request: Request) -> bool:
    """True if the request carries a valid dashboard session token.

    The dedicated session header avoids collisions with reverse proxies that
    already use ``Authorization`` (for example Caddy ``basic_auth``). We still
    accept the legacy Bearer path for backward compatibility with older
    dashboard bundles.
    """
    session_header = request.headers.get(_SESSION_HEADER_NAME, "")
    if session_header and hmac.compare_digest(
        session_header.encode(),
        _SESSION_TOKEN.encode(),
    ):
        return True

    auth = request.headers.get("authorization", "")
    expected = f"Bearer {_SESSION_TOKEN}"
    return hmac.compare_digest(auth.encode(), expected.encode())


def _require_token(request: Request) -> None:
    """Validate the ephemeral session token.  Raises 401 on mismatch."""
    if not _has_valid_session_token(request):
        raise HTTPException(status_code=401, detail="Não autorizado")


def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface we bound to.

    Accepts:
    - Exact bound host (with or without port suffix)
    - Loopback aliases when bound to loopback
    - Any host when bound to 0.0.0.0 (explicit opt-in to non-loopback,
      no protection possible at this layer)
    """
    if not host_header:
        return False
    # Strip port suffix. IPv6 addresses use bracket notation:
    #   [::1]         — no port
    #   [::1]:9000    — with port
    # Plain hosts/v4:
    #   localhost:9000
    #   127.0.0.1:9000
    h = host_header.strip()
    if h.startswith("["):
        # IPv6 bracketed — port (if any) follows "]:"
        close = h.find("]")
        if close != -1:
            host_only = h[1:close]  # strip brackets
        else:
            host_only = h.strip("[]")
    else:
        host_only = h.rsplit(":", 1)[0] if ":" in h else h
    host_only = host_only.lower()

    # 0.0.0.0 bind means operator explicitly opted into all-interfaces
    # (requires --insecure per web_server.start_server). No Host-layer
    # defence can protect that mode; rely on operator network controls.
    if bound_host in ("0.0.0.0", "::"):
        return True

    # Loopback bind: accept the loopback names and the configured friendly hostname
    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        if host_only in _LOOPBACK_HOST_VALUES:
            return True
        friendly = get_dashboard_local_hostname()
        return bool(friendly) and host_only == friendly

    # Explicit non-loopback bind: require exact host match
    return host_only == bound_lc


@app.middleware("http")
async def host_header_middleware(request: Request, call_next):
    """Reject requests whose Host header doesn't match the bound interface.

    Defends against DNS rebinding: a victim browser on a localhost
    dashboard is tricked into fetching from an attacker hostname that
    TTL-flips to 127.0.0.1. CORS and same-origin checks don't help —
    the browser now treats the attacker origin as same-origin with the
    dashboard. Host-header validation at the app layer catches it.

    See GHSA-ppp5-vxwm-4cf7.
    """
    # Store the bound host on app.state so this middleware can read it —
    # set by start_server() at listen time.
    bound_host = getattr(app.state, "bound_host", None)
    if bound_host:
        # Allow reverse-proxy access from loopback even when Host differs.
        # This preserves DNS-rebinding protection for direct browser access,
        # but avoids blocking nginx/caddy proxies that forward the public Host
        # while connecting locally to 127.0.0.1.
        client_host = getattr(getattr(request, "client", None), "host", "") or ""
        xf_host = request.headers.get("x-forwarded-host", "")
        if client_host in _LOOPBACK_HOST_VALUES and xf_host:
            return await call_next(request)

        host_header = request.headers.get("host", "")
        if not _is_accepted_host(host_header, bound_host):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "Cabeçalho Host inválido. As requisições do dashboard devem usar "
                        "o nome de host ao qual o servidor foi vinculado."
                    ),
                },
            )
    return await call_next(request)


def _extract_cookie_token(cookie_header: str, name: str) -> str:
    """Parse a single cookie value from the Cookie header (best-effort)."""
    if not cookie_header:
        return ""
    parts = cookie_header.split(";")
    needle = f"{name}="
    for part in parts:
        p = part.strip()
        if p.startswith(needle):
            return p[len(needle):].strip()
    return ""


def _has_valid_dashboard_auth_cookie(request: Request) -> bool:
    cookie_header = request.headers.get("cookie", "")
    raw = _extract_cookie_token(cookie_header, _DASH_AUTH_COOKIE_NAME)
    ok, _ = verify_dashboard_access_token(raw)
    return bool(ok)


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _unauthorized_logo_data_uri() -> str:
    """Return embedded logo for auth error page (no public static dependency)."""
    logo_candidates = (
        WEB_DIST / "logo_for_dark.png",
        Path(__file__).parent / "web_dist" / "logo_for_dark.png",
        PROJECT_ROOT / "frontend" / "dashboard" / "public" / "logo_for_dark.png",
    )
    for path in logo_candidates:
        try:
            if path.is_file():
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                return f"data:image/png;base64,{encoded}"
        except OSError:
            continue
    return ""


def _unauthorized_dashboard_page() -> str:
    logo_src = _unauthorized_logo_data_uri()
    return """<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ector • Acesso não autorizado</title>
    <style>
      :root {
        --bg: #060b13;
        --surface: #121620;
        --surface-2: #1a2332;
        --text: #ffffff;
        --muted: #94a3b8;
        --border: #1e293b;
        --accent: #2eb1e5;
      }
      * { box-sizing: border-box; }
      html, body { height: 100%; }
      body {
        margin: 0;
        color: var(--text);
        background:
          radial-gradient(1200px 700px at 20% 10%, rgba(46,177,229,0.20), transparent 60%),
          radial-gradient(900px 500px at 80% 20%, rgba(46,177,229,0.10), transparent 55%),
          radial-gradient(900px 600px at 50% 100%, rgba(26,35,50,0.45), transparent 55%),
          var(--bg);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
        display: grid;
        place-items: center;
        padding: 24px;
      }
      .wrap { width: min(760px, 100%); }
      .brand {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 14px;
      }
      .logo {
        height: 28px;
        width: auto;
        display: block;
      }
      .card {
        border: 1px solid var(--border);
        background: linear-gradient(180deg, rgba(18,22,32,0.94), rgba(18,22,32,0.88));
        border-radius: 16px;
        padding: 18px 18px 16px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.35);
        backdrop-filter: blur(10px);
      }
      .title {
        font-size: 18px;
        margin: 0 0 6px 0;
        font-weight: 750;
      }
      .desc {
        margin: 0 0 14px 0;
        color: var(--muted);
        line-height: 1.45;
        font-size: 14px;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="brand">
        <img class="logo" src="{{LOGO_SRC}}" alt="Ector" />
      </div>
      <div class="card text-center" role="main">
        <h2 class="title">Acesso não autorizado</h2>
        <p class="desc">
          Você não tem permissão ou sessão ativa para acessar este local.
        </p>
      </div>
    </div>
  </body>
</html>""".replace("{{LOGO_SRC}}", logo_src)


@app.middleware("http")
async def dashboard_access_middleware(request: Request, call_next):
    """Gate the entire dashboard behind a signed access token/cookie.

    Flow:
    - User hits any URL with `?token=...` (generated when starting `ector localhost`)
    - If valid, we set an HttpOnly cookie and redirect to the same URL without the token.
    - Subsequent requests are authorized by the cookie.
    """
    # Require auth by default (safer when users bind beyond loopback).
    # Set ECTOR_DASHBOARD_AUTH=0 to disable.
    require_auth = _parse_bool_env("ECTOR_DASHBOARD_AUTH", True)
    if not require_auth:
        return await call_next(request)

    # Same paths as ``_PUBLIC_API_PATHS`` (read-only / diagnóstico). Não exigem
    # cookie de dashboard — necessário para ``pnpm dev``: o browser fica em
    # localhost:5173 e não envia o cookie HttpOnly definido em 127.0.0.1:9000.
    if request.url.path in _PUBLIC_API_PATHS:
        return await call_next(request)

    if _has_valid_dashboard_auth_cookie(request):
        return await call_next(request)

    token = request.query_params.get(_DASH_AUTH_QUERY_PARAM, "")
    ok, _payload = verify_dashboard_access_token(token)
    if not ok:
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Não autorizado (dashboard auth)"})
        return HTMLResponse(status_code=401, content=_unauthorized_dashboard_page())

    # Exchange URL token → cookie, then redirect without leaking token to logs/history.
    clean_url = str(request.url).split("?", 1)[0]
    # Preserve other query params except token.
    qs = [(k, v) for (k, v) in request.query_params.multi_items() if k != _DASH_AUTH_QUERY_PARAM]
    if qs:
        clean_url = f"{clean_url}?{urllib.parse.urlencode(qs)}"

    response = RedirectResponse(url=clean_url, status_code=307)
    # Issue a longer-lived cookie token.
    cookie_token = create_dashboard_access_token(ttl_seconds=_DASH_AUTH_DEFAULT_COOKIE_TTL_SECONDS)
    response.set_cookie(
        key=_DASH_AUTH_COOKIE_NAME,
        value=cookie_token,
        httponly=True,
        samesite="lax",
        max_age=_DASH_AUTH_DEFAULT_COOKIE_TTL_SECONDS,
        path="/",
    )
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require the session token on all /api/ routes except the public list."""
    path = request.url.path
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        if not _has_valid_session_token(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Não autorizado"},
            )
    return await call_next(request)


@app.post("/api/auth/logout")
async def dashboard_logout(request: Request) -> JSONResponse:
    """Clear the HttpOnly dashboard auth cookie (if auth is enabled)."""
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(key=_DASH_AUTH_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "model": {
        "type": "string",
        "description": "Modelo padrão (ex: anthropic/claude-sonnet-4.6)",
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Sobrescrita da janela de contexto (0 = auto-detectar a partir dos metadados do modelo)",
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Backend de execução do terminal",
        "options": ["local", "docker", "ssh", "modal", "daytona", "singularity"],
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modo sandbox do Modal",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Provedor de conversão de texto em fala (TTS)",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Provedor de conversão de fala em texto (STT)",
        "options": ["local", "openai", "mistral"],
    },
    "dashboard.theme": {
        "type": "select",
        "description": "Tema visual do dashboard web",
        "options": ["default", "midnight", "ember", "mono", "cyberpunk", "rose"],
    },
    "display.resume_display": {
        "type": "select",
        "description": "Como as sessões retomadas exibem o histórico",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Comportamento de entrada enquanto o agente está rodando",
        "options": ["interrupt", "queue", "steer"],
    },
    "memory.provider": {
        "type": "string",
        "description": "Identificador do plugin (vazio = só memória interna). Use `ector memory setup` para listar opções.",
    },
    "approvals.mode": {
        "type": "select",
        "description": "Modo de aprovação de comandos perigosos",
        "options": ["ask", "yolo", "deny"],
    },
    "context.engine": {
        "type": "select",
        "description": "Motor de gerenciamento de contexto",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Modo de atraso de digitação simulada",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Nível de log para agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "Nível de serviço da API (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Esforço de raciocínio para subagentes delegados",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "approvals": "security",
    "human_delay": "display",
    "dashboard": "display",
    "code_execution": "agent",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general", "agent", "terminal", "display", "delegation",
    "memory", "compression", "security", "browser", "voice",
    "tts", "stt", "logging", "discord", "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in ("_config_version",):
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(entry["category"], entry["category"])
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle.  Insert model_context_length right after
# the "model" key so it renders adjacent in the frontend.
_mcl_entry = _SCHEMA_OVERRIDES["model_context_length"]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        _ordered_schema["model_context_length"] = _mcl_entry
CONFIG_SCHEMA = _ordered_schema


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


class SetupInferenceBlock(BaseModel):
    """Provedor + modelo + segredos opcionais (mesma semântica do ``ector setup`` rápido)."""

    provider_id: str
    model: str
    secrets: Dict[str, str] = {}
    base_url_override: str = ""


class SetupApplyBody(BaseModel):
    """Aplicação atômica de trechos do assistente de configuração na web."""

    inference: Optional[SetupInferenceBlock] = None
    terminal_backend: Optional[str] = None
    terminal_cwd: Optional[str] = None
    apply_recommended_agent_defaults: bool = False
    agent_max_turns: Optional[int] = None
    agent_tool_progress: Optional[str] = None
    toolsets_cli: Optional[List[str]] = None
    # Extra steps (paridade com o wizard CLI)
    compression_threshold: Optional[float] = None
    session_reset_mode: Optional[str] = None  # daily | idle | both | none
    session_reset_at_hour: Optional[int] = None
    session_reset_idle_minutes: Optional[int] = None
    tts_provider: Optional[str] = None


from ector_cli.provider_model_catalog import build_setup_catalog_rows


def _setup_resolve_provider(provider_id: str):
    """Return (canonical_id, default_base_url, allowed_secret_keys)."""
    from ector_constants import OPENROUTER_BASE_URL

    pid = (provider_id or "").strip().lower()
    if pid == "openrouter":
        return "openrouter", OPENROUTER_BASE_URL, ("OPENROUTER_API_KEY",)

    from ector_cli.auth import PROVIDER_REGISTRY

    p = PROVIDER_REGISTRY.get(pid)
    if not p:
        raise HTTPException(status_code=400, detail=f"Provedor desconhecido: {provider_id}")
    if p.auth_type == "oauth_external":
        base = (p.inference_base_url or "").strip()
        return pid, base, ()
    if p.auth_type != "api_key":
        raise HTTPException(
            status_code=400,
            detail="Este provedor usa OAuth ou outro fluxo — use a seção de logins abaixo ou o CLI.",
        )
    if not p.api_key_env_vars:
        raise HTTPException(
            status_code=400,
            detail="Este provedor não usa chave de API neste assistente — configure via CLI ou YAML.",
        )
    base = (p.inference_base_url or "").strip()
    return pid, base, tuple(p.api_key_env_vars)


def _setup_merge_model_dict(
    cfg: Dict[str, Any],
    provider_id: str,
    model_default: str,
    base_url_override: str,
) -> None:
    """Atualiza ``cfg['model']`` como dict com default, provider e base_url."""
    from ector_constants import OPENROUTER_BASE_URL

    md: Dict[str, Any] = {}
    existing = cfg.get("model")
    if isinstance(existing, dict):
        md = dict(existing)
    name = (model_default or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome do modelo.")
    md["default"] = name
    md["provider"] = provider_id
    override = (base_url_override or "").strip()
    if override:
        md["base_url"] = override
    elif provider_id == "openrouter":
        md["base_url"] = OPENROUTER_BASE_URL
    else:
        _, default_base, _ = _setup_resolve_provider(provider_id)
        if default_base:
            md["base_url"] = default_base
        else:
            md.pop("base_url", None)
    cfg["model"] = md


def _setup_apply_recommended_agent_defaults(cfg: Dict[str, Any]) -> None:
    """Espelha ``_apply_default_agent_settings`` sem prompts interativos."""
    cfg.setdefault("agent", {})["max_turns"] = 90
    save_env_value("ECTOR_MAX_ITERATIONS", "90")
    cfg.setdefault("display", {})["tool_progress"] = "all"
    cfg.setdefault("compression", {})["enabled"] = True
    cfg["compression"]["threshold"] = 0.50
    cfg.setdefault("session_reset", {}).update(
        {
            "mode": "both",
            "idle_minutes": 1440,
            "at_hour": 4,
        }
    )


_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    _log.warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r — using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint (cross-container).

    Uses ``/health/detailed`` first (returns full state), falling back to
    the simpler ``/health`` endpoint.  Returns ``(is_alive, body_dict)``.

    Accepts any of these as ``GATEWAY_HEALTH_URL``:
    - ``http://gateway:8642``                (base URL — recommended)
    - ``http://gateway:8642/health``         (explicit health path)
    - ``http://gateway:8642/health/detailed`` (explicit detailed path)

    This is a **blocking** call — run via ``run_in_executor`` from async code.
    """
    if not _GATEWAY_HEALTH_URL:
        return False, None

    # Normalise to base URL so we always probe the right paths regardless of
    # whether the user included /health or /health/detailed in the env var.
    base = _GATEWAY_HEALTH_URL.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=_GATEWAY_HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


@app.get("/api/status")
async def get_status(session_id: Optional[str] = None):
    current_ver, latest_ver = check_config_version()

    # --- Gateway liveness detection ---
    # Try local PID check first (same-host).  If that fails and a remote
    # GATEWAY_HEALTH_URL is configured, probe the gateway over HTTP so the
    # dashboard works when the gateway runs in a separate container.
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    remote_health_body: dict | None = None

    if not gateway_running and _GATEWAY_HEALTH_URL:
        loop = asyncio.get_event_loop()
        alive, remote_health_body = await loop.run_in_executor(
            None, _probe_gateway_health
        )
        if alive:
            gateway_running = True
            # PID from the remote container (display only — not locally valid)
            if remote_health_body:
                gateway_pid = remote_health_body.get("pid")

    gateway_state = None
    gateway_platforms: dict = {}
    gateway_exit_reason = None
    gateway_updated_at = None
    configured_gateway_platforms: set[str] | None = None
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        configured_gateway_platforms = {
            platform.value for platform in gateway_config.get_connected_platforms()
        }
    except Exception:
        configured_gateway_platforms = None

    # Prefer the detailed health endpoint response (has full state) when the
    # local runtime status file is absent or stale (cross-container).
    runtime = read_runtime_status()
    if runtime is None and remote_health_body and remote_health_body.get("gateway_state"):
        runtime = remote_health_body

    if runtime:
        gateway_state = runtime.get("gateway_state")
        gateway_platforms = runtime.get("platforms") or {}
        if configured_gateway_platforms is not None:
            gateway_platforms = {
                key: value
                for key, value in gateway_platforms.items()
                if key in configured_gateway_platforms
            }
        gateway_exit_reason = runtime.get("exit_reason")
        gateway_updated_at = runtime.get("updated_at")
        if not gateway_running:
            gateway_state = gateway_state if gateway_state in ("stopped", "startup_failed") else "stopped"
            gateway_platforms = {}
        elif gateway_running and remote_health_body is not None:
            # The health probe confirmed the gateway is alive, but the local
            # runtime status file may be stale (cross-container).  Override
            # stopped/None state so the dashboard shows the correct badge.
            if gateway_state in (None, "stopped"):
                gateway_state = "running"

    # If there was no runtime info at all but the health probe confirmed alive,
    # ensure we still report the gateway as running (no shared volume scenario).
    if gateway_running and gateway_state is None and remote_health_body is not None:
        gateway_state = "running"

    active_sessions = 0
    try:
        from ector_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=50)
            now = time.time()
            active_sessions = sum(
                1 for s in sessions
                if s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0))) < 300
            )
        finally:
            db.close()
    except Exception:
        pass

    provider_configured = False
    managed = False
    managed_system: Optional[str] = None
    try:
        managed = bool(is_managed())
        managed_system = get_managed_system()
    except Exception:
        pass
    if not managed:
        try:
            from ector_cli.main import _has_any_provider_configured

            provider_configured = bool(_has_any_provider_configured())
        except Exception:
            provider_configured = False

    try:
        _footer = _chat_footer_payload(session_id)
    except Exception:
        _footer = {"cwd": "", "cwd_label": ""}

    return {
        "version": __version__,
        "version_name": __version_name__,
        "version_code": __version_code__,
        "ector_home": str(get_ector_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": current_ver,
        "latest_config_version": latest_ver,
        "gateway_running": gateway_running,
        "gateway_pid": gateway_pid,
        "gateway_health_url": _GATEWAY_HEALTH_URL,
        "gateway_state": gateway_state,
        "gateway_platforms": gateway_platforms,
        "gateway_exit_reason": gateway_exit_reason,
        "gateway_updated_at": gateway_updated_at,
        "active_sessions": active_sessions,
        "provider_configured": provider_configured,
        "managed": managed,
        "managed_system": managed_system,
        "cwd": _footer.get("cwd", ""),
        "cwd_label": _footer.get("cwd_label", ""),
        "model": _footer.get("model", ""),
        "model_label": _footer.get("model_label", ""),
        "provider": _footer.get("provider", ""),
    }


@app.get("/api/ws/token")
async def get_ws_token(request: Request):
    """Return the ephemeral WS/REST session token (requires prior dashboard auth)."""
    if not _has_valid_session_token(request) and not _has_valid_dashboard_auth_cookie(request):
        return JSONResponse(status_code=401, content={"detail": "Não autorizado"})
    return {"token": _SESSION_TOKEN}


# ---------------------------------------------------------------------------
# Gateway + update actions (invoked from the Status page).
# (invoked from the Status page).
#
# Both commands are spawned as detached subprocesses so the HTTP request
# returns immediately.  stdin is closed (``DEVNULL``) so any stray ``input()``
# calls fail fast with EOF rather than hanging forever.  stdout/stderr are
# streamed to a per-action log file under ``~/.ector/logs/<action>.log`` so
# the dashboard can tail them back to the user.
# ---------------------------------------------------------------------------

_ACTION_LOG_DIR: Path = get_ector_home() / "logs"

# Short ``name`` (from the URL) → absolute log file path.
_ACTION_LOG_FILES: Dict[str, str] = {
    "gateway-restart": "gateway-restart.log",
    "gateway-start": "gateway-start.log",
    "gateway-stop": "gateway-stop.log",
}

# ``name`` → most recently spawned Popen handle.  Used so ``status`` can
# report liveness and exit code without shelling out to ``ps``.
_ACTION_PROCS: Dict[str, subprocess.Popen] = {}


def _spawn_ector_action(subcommand: List[str], name: str) -> subprocess.Popen:
    """Spawn ``ector <subcommand>`` detached and record the Popen handle.

    Uses the running interpreter's ``ector_cli.main`` module so the action
    inherits the same venv/PYTHONPATH the web server is using.
    """
    log_file_name = _ACTION_LOG_FILES[name]
    _ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _ACTION_LOG_DIR / log_file_name
    log_file = open(log_path, "ab", buffering=0)
    log_file.write(
        f"\n=== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    cmd = [sys.executable, "-m", "ector_cli.main", *subcommand]

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "ECTOR_NONINTERACTIVE": "1"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    _ACTION_PROCS[name] = proc
    return proc


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path``.  Reads the whole file — fine
    for our small per-action logs.  Binary-decoded with ``errors='replace'``
    so log corruption doesn't 500 the endpoint."""
    if not path.exists():
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else lines


def _spawn_gateway_cli_action(subcommand: str, action_name: str) -> dict:
    try:
        proc = _spawn_ector_action(["gateway", subcommand], action_name)
    except Exception as exc:
        _log.exception("Failed to spawn gateway %s", subcommand)
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao executar gateway {subcommand}: {exc}",
        ) from exc
    return {"ok": True, "pid": proc.pid, "name": action_name}


@app.post("/api/gateway/restart")
async def restart_gateway():
    """Kick off a ``ector gateway restart`` in the background."""
    return _spawn_gateway_cli_action("restart", "gateway-restart")


@app.post("/api/gateway/start")
async def start_gateway_service():
    """Kick off a ``ector gateway start`` in the background."""
    return _spawn_gateway_cli_action("start", "gateway-start")


@app.post("/api/gateway/stop")
async def stop_gateway_service():
    """Kick off a ``ector gateway stop`` in the background."""
    return _spawn_gateway_cli_action("stop", "gateway-stop")


@app.get("/api/gateway/platforms")
async def get_gateway_platforms():
    """Messaging platform catalog with configuration status."""
    from gateway.platform_catalog import snapshot

    try:
        snap = snapshot()
        return {"ok": True, **snap}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/gateway/platforms/{platform_key}")
async def get_gateway_platform_detail(platform_key: str):
    from gateway.platform_catalog import get_platform_detail

    try:
        return {"ok": True, "platform": get_platform_detail(platform_key)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plataforma desconhecida: {platform_key}")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.delete("/api/gateway/platforms/{platform_key}")
async def delete_gateway_platform(platform_key: str):
    """Disconnect a messaging platform (clear credentials and local sessions)."""
    from gateway.platform_catalog import disconnect_platform

    try:
        return disconnect_platform(platform_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plataforma desconhecida: {platform_key}")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/gateway/platforms/{platform_key}")
async def put_gateway_platform(platform_key: str, request: Request):
    from gateway.platform_catalog import apply_platform_env

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Corpo JSON inválido")
    values = body.get("vars")
    if values is not None and not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="vars deve ser um objeto")
    allowlist_access = body.get("allowlist_access")
    if values is None:
        values = {
            k: v
            for k, v in body.items()
            if k not in ("allowlist_access", "TELEGRAM_AUTO_HOME")
        }
    try:
        result = apply_platform_env(
            platform_key,
            values,
            allowlist_access=str(allowlist_access) if allowlist_access is not None else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plataforma desconhecida: {platform_key}")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result["gateway_restart"] = _spawn_gateway_cli_action("restart", "gateway-restart")
    except Exception as exc:
        _log.warning(
            "Platform %s saved but gateway restart failed: %s",
            platform_key,
            exc,
        )
        result["gateway_restart"] = {"ok": False, "error": str(exc)}
    return result


@app.post("/api/gateway/whatsapp/deps/ensure")
async def whatsapp_deps_ensure():
    """Install whatsapp-bridge node_modules if missing (idempotent)."""
    from gateway.whatsapp_bridge_install import ensure_bridge_deps

    ok, err = ensure_bridge_deps()
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@app.post("/api/gateway/whatsapp/pair/start")
async def whatsapp_pair_start(request: Request):
    from gateway.whatsapp_pairing import start_pairing

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mode = str(body.get("mode") or "self-chat")
    reset_session = bool(body.get("reset_session", False))
    allowed_users = str(body.get("allowed_users") or "")
    result = start_pairing(
        mode=mode,
        reset_session=reset_session,
        allowed_users=allowed_users,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Falha ao iniciar emparelhamento")
    return result


@app.get("/api/gateway/whatsapp/pair/status")
async def whatsapp_pair_status():
    from gateway.whatsapp_pairing import pairing_status

    return pairing_status()


@app.post("/api/gateway/whatsapp/pair/cancel")
async def whatsapp_pair_cancel():
    from gateway.whatsapp_pairing import cancel_pairing

    return cancel_pairing()


@app.get("/api/actions/{name}/status")
async def get_action_status(name: str, lines: int = 200):
    """Tail an action log and report whether the process is still running."""
    log_file_name = _ACTION_LOG_FILES.get(name)
    if log_file_name is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

    log_path = _ACTION_LOG_DIR / log_file_name
    tail = _tail_lines(log_path, min(max(lines, 1), 2000))

    proc = _ACTION_PROCS.get(name)
    if proc is None:
        running = False
        exit_code: Optional[int] = None
        pid: Optional[int] = None
    else:
        exit_code = proc.poll()
        running = exit_code is None
        pid = proc.pid

    return {
        "name": name,
        "running": running,
        "exit_code": exit_code,
        "pid": pid,
        "lines": tail,
    }


@app.get("/api/sessions")
async def get_sessions(limit: int = 20, offset: int = 0):
    try:
        from ector_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=limit, offset=offset)
            total = db.session_count()
            now = time.time()
            for s in sessions:
                s["is_active"] = (
                    s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0))) < 300
                )
            return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
        finally:
            db.close()
    except Exception as e:
        _log.exception("GET /api/sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/search")
async def search_sessions(q: str = "", limit: int = 20):
    """Full-text search across session message content using FTS5."""
    if not q or not q.strip():
        return {"results": []}
    try:
        from ector_state import SessionDB
        db = SessionDB()
        try:
            # Auto-add prefix wildcards so partial words match
            # e.g. "nimb" → "nimb*" matches "nimby"
            # Preserve quoted phrases and existing wildcards as-is
            import re
            terms = []
            for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                if token.startswith('"') or token.endswith("*"):
                    terms.append(token)
                else:
                    terms.append(token + "*")
            prefix_query = " ".join(terms)
            matches = db.search_messages(query=prefix_query, limit=limit)
            # Group by session_id — return unique sessions with their best snippet
            seen: dict = {}
            for m in matches:
                sid = m["session_id"]
                if sid not in seen:
                    seen[sid] = {
                        "session_id": sid,
                        "snippet": m.get("snippet", ""),
                        "role": m.get("role"),
                        "source": m.get("source"),
                        "model": m.get("model"),
                        "session_started": m.get("session_started"),
                    }
            return {"results": list(seen.values())}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions/search failed")
        raise HTTPException(status_code=500, detail="Search failed")


def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config for the web UI.

    Ector supports ``model`` as either a bare string (``"anthropic/claude-sonnet-4"``)
    or a dict (``{default: ..., provider: ..., base_url: ...}``).  The schema is built
    from DEFAULT_CONFIG where ``model`` is a string, but user configs often have the
    dict form.  Normalize to the string form so the frontend schema matches.

    Also surfaces ``model_context_length`` as a top-level field so the web UI can
    display and edit it.  A value of 0 means "auto-detect".
    """
    config = dict(config)  # shallow copy
    model_val = config.get("model")
    if isinstance(model_val, dict):
        # Extract context_length before flattening the dict
        ctx_len = model_val.get("context_length", 0)
        config["model"] = model_val.get("default", model_val.get("name", ""))
        config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
    else:
        config["model_context_length"] = 0
    return config


@app.get("/api/config")
async def get_config():
    config = _normalize_config_for_web(load_config())
    # Strip internal keys that the frontend shouldn't see or send back
    return {k: v for k, v in config.items() if not k.startswith("_")}


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    return {"fields": CONFIG_SCHEMA, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "model_label": "(modelo)",
    "cwd": "",
    "cwd_label": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


def _short_display_cwd(cwd: str, max_len: int = 40) -> str:
    """Compact path for dashboard composer footer (parity with Ink TUI)."""
    try:
        home = os.path.expanduser("~")
    except Exception:
        home = ""
    p = cwd
    if home and p.startswith(home):
        p = "~" + p[len(home) :]
    if len(p) <= max_len:
        return p
    return "\u2026" + p[-(max_len - 1) :]


def _short_display_model(model: str) -> str:
    if not (model or "").strip():
        return "(modelo)"
    name = str(model).split("/")[-1]
    for prefix in ("claude-", "claude_", "anthropic-", "anthropic_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    name = name.replace("-", " ").replace("_", " ")
    return name.strip() or str(model)


def _ensure_terminal_cwd_bridged() -> None:
    """Bridge ``terminal.cwd`` → ``TERMINAL_CWD`` (same as CLI / gateway)."""
    try:
        from ector_cli.cli_config import load_cli_config

        load_cli_config()
    except Exception:
        pass


def _default_web_chat_cwd() -> str:
    from agent.session_cwd import default_terminal_cwd

    return default_terminal_cwd(cwd_placeholder="home")


def _configured_web_terminal_cwd() -> str:
    from agent.session_cwd import configured_terminal_cwd

    return configured_terminal_cwd(cwd_placeholder="home")


def _apply_web_dashboard_terminal_cwd(*, reset_envs: bool = False) -> str:
    """Set ``TERMINAL_CWD`` for web chat; optionally clear cached terminal envs."""
    cwd = _configured_web_terminal_cwd()
    os.environ["TERMINAL_CWD"] = cwd
    if not reset_envs:
        return cwd
    try:
        from tools.terminal_tool import _active_environments, _env_lock, cleanup_vm

        with _env_lock:
            task_ids = list(_active_environments.keys())
        for tid in task_ids:
            try:
                cleanup_vm(tid)
            except Exception:
                pass
    except Exception:
        pass
    return cwd


def _cwd_from_model_config(raw: Any) -> Optional[str]:
    from agent.session_cwd import cwd_from_model_config

    return cwd_from_model_config(raw)


def _load_persisted_session_cwd(session_id: str) -> Optional[str]:
    from agent.session_cwd import load_persisted_session_cwd

    return load_persisted_session_cwd(session_id)


def _apply_web_session_cwd(session_id: str, cwd: str) -> str:
    from agent.session_cwd import apply_session_cwd

    return apply_session_cwd(session_id, cwd)


def _prime_web_session_cwd(session_id: Optional[str]) -> None:
    from agent.session_cwd import prime_session_cwd

    prime_session_cwd(session_id, cwd_placeholder="home")


def _persist_web_session_cwd(session_id: str, cwd: str) -> None:
    from agent.session_cwd import persist_session_cwd

    persist_session_cwd(session_id, cwd, source="web")


def _cwd_from_terminal_env(task_id: str) -> Optional[str]:
    from agent.session_cwd import cwd_from_terminal_env

    return cwd_from_terminal_env(task_id)


def _live_web_terminal_cwd(session_id: Optional[str] = None) -> Optional[str]:
    from agent.session_cwd import live_terminal_cwd

    return live_terminal_cwd(session_id)


def _sync_web_session_cwd_from_env(
    session_id: str, *, allow_default_env: bool = False
) -> None:
    from agent.session_cwd import sync_session_cwd_from_env

    sync_session_cwd_from_env(
        session_id, allow_default_env=allow_default_env, source="web"
    )


def _resolve_web_chat_cwd(session_id: Optional[str] = None) -> str:
    from agent.session_cwd import resolve_chat_cwd

    return resolve_chat_cwd(session_id, cwd_placeholder="home")


def _resolve_web_chat_model_from_config() -> tuple[str, str]:
    """Resolve model + provider from config/env/runtime (ignores cached web agents)."""
    provider = ""
    try:
        cfg = load_config() or {}
    except Exception:
        cfg = {}

    raw_model = ""
    _model_cfg = cfg.get("model") or {}
    if isinstance(_model_cfg, str):
        raw_model = _model_cfg.strip()
    elif isinstance(_model_cfg, dict):
        raw_model = (
            str(_model_cfg.get("default") or _model_cfg.get("name") or "")
        ).strip()
        provider = str(_model_cfg.get("provider") or "").strip()
    if not raw_model:
        _agent_cfg = cfg.get("agent") or {}
        if isinstance(_agent_cfg, dict):
            raw_model = str(_agent_cfg.get("model") or "").strip()
    if not raw_model:
        raw_model = (
            os.environ.get("ECTOR_MODEL", "")
            or os.environ.get("ECTOR_INFERENCE_MODEL", "")
            or ""
        ).strip()
    if not raw_model:
        try:
            from ector_cli.runtime_provider import _get_model_config

            mc = _get_model_config()
            raw_model = str(mc.get("default") or mc.get("model") or "").strip()
            if not provider:
                provider = str(mc.get("provider") or "").strip()
        except Exception:
            pass
    if not raw_model:
        try:
            from ector_state import SessionDB

            db = SessionDB()
            try:
                sessions = db.list_sessions_rich(limit=5)
                for row in sessions:
                    m = row.get("model")
                    if m and str(m).strip():
                        raw_model = str(m).strip()
                        break
            finally:
                db.close()
        except Exception:
            pass
    return raw_model, provider


def _resolve_web_chat_model_for_footer() -> tuple[str, str]:
    """Resolve model + provider (config first, then cached web agents)."""
    model, provider = _resolve_web_chat_model_from_config()
    if model:
        return model, provider

    with _CHAT_AGENTS_LOCK:
        agents = list(_CHAT_AGENTS.values())
    for agent in agents:
        cached_model = getattr(agent, "model", None)
        if cached_model and str(cached_model).strip():
            prov = getattr(agent, "provider", None)
            return str(cached_model).strip(), str(prov or "").strip()
    return model, provider


def _display_show_cost_enabled() -> bool:
    try:
        from ector_cli.config import load_config

        display = (load_config() or {}).get("display") or {}
        return bool(display.get("show_cost"))
    except Exception:
        return False


def _cost_usd_from_agent(agent) -> tuple[Optional[float], str]:
    """Session cost for the web composer footer (parity with ``tui_gateway._get_usage``)."""
    try:
        actual = float(getattr(agent, "session_actual_cost_usd", 0) or 0)
        estimated = float(getattr(agent, "session_estimated_cost_usd", 0) or 0)
        status = str(getattr(agent, "session_cost_status", "") or "").strip()
        if actual > 0:
            return actual, "actual"
        if estimated > 0:
            if status == "actual":
                return estimated, "actual"
            return estimated, status if status in ("estimated", "included") else "estimated"
        model = getattr(agent, "model", "") or ""
        inp = int(
            getattr(agent, "session_input_tokens", 0)
            or getattr(agent, "session_prompt_tokens", 0)
            or 0
        )
        out = int(
            getattr(agent, "session_output_tokens", 0)
            or getattr(agent, "session_completion_tokens", 0)
            or 0
        )
        if model and (inp or out):
            from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

            cost = estimate_usage_cost(
                model,
                CanonicalUsage(
                    input_tokens=inp,
                    output_tokens=out,
                    cache_read_tokens=int(getattr(agent, "session_cache_read_tokens", 0) or 0),
                    cache_write_tokens=int(getattr(agent, "session_cache_write_tokens", 0) or 0),
                ),
                provider=getattr(agent, "provider", None),
                base_url=getattr(agent, "base_url", None),
            )
            if cost.amount_usd is not None:
                st = "actual" if status == "actual" else (cost.status or "estimated")
                return float(cost.amount_usd), st
    except Exception:
        pass
    return None, "unknown"


def _cost_usd_from_session_row(row: dict) -> tuple[Optional[float], str]:
    actual = float(row.get("actual_cost_usd") or 0)
    estimated = float(row.get("estimated_cost_usd") or 0)
    status = str(row.get("cost_status") or "").strip() or "unknown"
    if actual > 0:
        return actual, "actual"
    if estimated > 0:
        if status == "actual":
            return estimated, "actual"
        return estimated, status if status in ("estimated", "included") else "estimated"
    return None, status


def _resolve_web_session_cost(session_id: Optional[str] = None) -> tuple[Optional[float], str]:
    """Session-scoped cost only — never borrow from other live agents."""
    sid = (session_id or "").strip()
    if not sid:
        return None, "unknown"
    with _CHAT_AGENTS_LOCK:
        agent = _CHAT_AGENTS.get(sid)
    if agent is not None:
        return _cost_usd_from_agent(agent)
    try:
        from ector_state import SessionDB

        db = SessionDB()
        try:
            row = db.get_session(sid)
            if row:
                return _cost_usd_from_session_row(row)
        finally:
            db.close()
    except Exception:
        pass
    return None, "unknown"


def _chat_footer_payload(session_id: Optional[str] = None) -> Dict[str, Any]:
    model, provider = _resolve_web_chat_model_for_footer()
    cwd = _resolve_web_chat_cwd(session_id)
    cwd_label = _short_display_cwd(cwd) if cwd else ""
    show_cost = _display_show_cost_enabled()
    payload: Dict[str, Any] = {
        "model": model,
        "model_label": _short_display_model(model),
        "provider": provider,
        "cwd": cwd,
        "cwd_label": cwd_label or cwd,
        "show_cost": show_cost,
    }
    if show_cost:
        cost_usd, cost_status = _resolve_web_session_cost(session_id)
        if cost_usd is not None and cost_usd > 0:
            payload["cost_usd"] = cost_usd
            payload["cost_status"] = cost_status
    return payload


@app.get("/api/cwd")
def get_working_directory(session_id: Optional[str] = None):
    """Current working directory for the web composer footer."""
    _prime_web_session_cwd(session_id)
    cwd = _resolve_web_chat_cwd(session_id)
    label = _short_display_cwd(cwd) if cwd else ""
    return {"cwd": cwd, "cwd_label": label or cwd}


@app.get("/api/chat/context")
def get_chat_context(session_id: Optional[str] = None):
    """Model + cwd for the web chat composer footer (Ink TUI parity)."""
    try:
        _prime_web_session_cwd(session_id)
        return _chat_footer_payload(session_id)
    except Exception:
        _log.exception("GET /api/chat/context failed")
        cwd = ""
        try:
            cwd = _resolve_web_chat_cwd(session_id)
        except Exception:
            pass
        label = _short_display_cwd(cwd) if cwd else ""
        return {
            "model": "",
            "model_label": "(modelo)",
            "provider": "",
            "cwd": cwd,
            "cwd_label": label or cwd,
        }


@app.get("/api/model/options")
def get_model_options(session_id: Optional[str] = None):
    """Authenticated providers + curated models for the web composer picker (TUI parity)."""
    try:
        from ector_cli.model_switch import list_authenticated_providers

        cfg = load_config()
        current_model, current_provider = _resolve_web_chat_model_for_footer()
        sid = (session_id or "").strip()
        if sid:
            with _CHAT_AGENTS_LOCK:
                agent = _CHAT_AGENTS.get(sid)
            if agent is not None:
                agent_model = getattr(agent, "model", None)
                agent_provider = getattr(agent, "provider", None)
                if agent_model and str(agent_model).strip():
                    current_model = str(agent_model).strip()
                if agent_provider and str(agent_provider).strip():
                    current_provider = str(agent_provider).strip()
        user_providers = (
            cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
        )
        custom_providers = (
            cfg.get("custom_providers")
            if isinstance(cfg.get("custom_providers"), list)
            else []
        )
        providers = list_authenticated_providers(
            current_provider=current_provider,
            user_providers=user_providers,
            custom_providers=custom_providers,
            max_models=50,
        )
        from ector_cli.model_switch import narrow_picker_providers_to_configured

        providers = narrow_picker_providers_to_configured(
            providers,
            config=cfg,
            current_model=current_model,
            current_provider=current_provider,
        )
        return {
            "providers": providers,
            "model": current_model,
            "provider": current_provider,
        }
    except Exception:
        _log.exception("GET /api/model/options failed")
        return {"providers": [], "model": "", "provider": ""}


@app.get("/api/model/info")
def get_model_info(session_id: Optional[str] = None):
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            footer = _chat_footer_payload(session_id)
            return {
                **dict(_EMPTY_MODEL_INFO),
                "model": footer["model"],
                "model_label": footer["model_label"],
                "provider": provider or footer["provider"],
                "cwd": footer["cwd"],
                "cwd_label": footer["cwd_label"],
            }

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length
            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities
            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            pass

        footer = _chat_footer_payload(session_id)
        display_label = _short_display_model(model_name) if model_name else footer["model_label"]
        return {
            "model": model_name or footer["model"],
            "provider": provider or footer["provider"],
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
            "cwd": footer["cwd"],
            "cwd_label": footer["cwd_label"],
            "model_label": display_label,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        try:
            footer = _chat_footer_payload(session_id)
            return {
                **dict(_EMPTY_MODEL_INFO),
                "cwd": footer["cwd"],
                "cwd_label": footer["cwd_label"],
                "model_label": footer["model_label"],
                "model": footer["model"],
                "provider": footer["provider"],
            }
        except Exception:
            return dict(_EMPTY_MODEL_INFO)


def _denormalize_config_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse _normalize_config_for_web before saving.

    Reconstructs ``model`` as a dict by reading the current on-disk config
    to recover model subkeys (provider, base_url, api_mode, etc.) that were
    stripped from the GET response.  The frontend only sees model as a flat
    string; the rest is preserved transparently.

    Also handles ``model_context_length`` — writes it back into the model dict
    as ``context_length``.  A value of 0 or absent means "auto-detect" (omitted
    from the dict so get_model_context_length() uses its normal resolution).
    """
    config = dict(config)
    # Remove any _model_meta that might have leaked in (shouldn't happen
    # with the stripped GET response, but be defensive)
    config.pop("_model_meta", None)

    # Extract and remove model_context_length before processing model
    ctx_override = config.pop("model_context_length", 0)
    if not isinstance(ctx_override, int):
        try:
            ctx_override = int(ctx_override)
        except (TypeError, ValueError):
            ctx_override = 0

    model_val = config.get("model")
    if isinstance(model_val, str) and model_val:
        # Read the current disk config to recover model subkeys
        try:
            disk_config = load_config()
            disk_model = disk_config.get("model")
            if isinstance(disk_model, dict):
                # Preserve all subkeys, update default with the new value
                disk_model["default"] = model_val
                # Write context_length into the model dict (0 = remove/auto)
                if ctx_override > 0:
                    disk_model["context_length"] = ctx_override
                else:
                    disk_model.pop("context_length", None)
                config["model"] = disk_model
            else:
                # Model was previously a bare string — upgrade to dict if
                # user is setting a context_length override
                if ctx_override > 0:
                    config["model"] = {
                        "default": model_val,
                        "context_length": ctx_override,
                    }
        except Exception:
            pass  # can't read disk config — just use the string form
    return config


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        denorm = _denormalize_config_from_web(body.config)
        if "model" in body.config:
            _invalidate_web_chat_agents()
        save_config(denorm)
        return {"ok": True}
    except Exception as e:
        _log.exception("PUT /api/config failed")
        raise HTTPException(status_code=500, detail="Internal server error")


async def _inference_setup_catalog_payload() -> Dict[str, Any]:
    """Corpo JSON partilhado por ``/api/setup/catalog`` e ``/api/firstrun/providers``."""
    if is_managed():
        return {
            "managed": True,
            "managed_message": format_managed_message("alterar a configuração"),
            "providers": [],
        }

    from ector_cli.auth import PROVIDER_REGISTRY

    rows = build_setup_catalog_rows(provider_registry=PROVIDER_REGISTRY)
    return {"managed": False, "managed_message": None, "providers": rows}


@app.get("/api/setup/catalog")
async def setup_catalog():
    """Lista provedores com chave de API (assistente web)."""
    return await _inference_setup_catalog_payload()


@app.get("/api/firstrun/providers")
async def firstrun_providers_catalog():
    """Alias de :func:`setup_catalog` — evita filtros que bloqueiam ``/setup/`` na URL."""
    return await _inference_setup_catalog_payload()


@app.post("/api/setup/apply")
async def setup_apply(body: SetupApplyBody):
    """Persiste modelo, segredos, terminal, agente e toolsets (paridade com o wizard CLI)."""
    if is_managed():
        raise HTTPException(
            status_code=400,
            detail=format_managed_message("alterar a configuração pelo dashboard"),
        )

    cfg = load_config()

    if body.inference:
        block = body.inference
        _, _base, allowed_keys = _setup_resolve_provider(block.provider_id)
        allowed_set = set(allowed_keys)
        for key, val in (block.secrets or {}).items():
            k = key.strip()
            if not k:
                continue
            if k not in allowed_set:
                raise HTTPException(
                    status_code=400,
                    detail=f"Variável de ambiente não permitida para este provedor: {k}",
                )
            if val and val.strip():
                save_env_value(k, val.strip())
        _setup_merge_model_dict(
            cfg,
            block.provider_id.strip().lower(),
            block.model,
            block.base_url_override or "",
        )

    if body.terminal_backend:
        tb = body.terminal_backend.strip().lower()
        allowed_backends = {
            "local",
            "docker",
            "modal",
            "ssh",
            "daytona",
            "singularity",
        }
        if tb not in allowed_backends:
            raise HTTPException(status_code=400, detail=f"Backend de terminal inválido: {tb}")
        cfg.setdefault("terminal", {})["backend"] = tb

    if body.terminal_cwd is not None:
        cfg.setdefault("terminal", {})["cwd"] = body.terminal_cwd.strip()

    if body.apply_recommended_agent_defaults:
        _setup_apply_recommended_agent_defaults(cfg)

    if body.agent_max_turns is not None:
        mt = int(body.agent_max_turns)
        if mt < 1 or mt > 500:
            raise HTTPException(status_code=400, detail="max_turns deve estar entre 1 e 500")
        cfg.setdefault("agent", {})["max_turns"] = mt
        save_env_value("ECTOR_MAX_ITERATIONS", str(mt))

    if body.agent_tool_progress:
        mode = body.agent_tool_progress.strip().lower()
        if mode not in ("off", "new", "all", "verbose"):
            raise HTTPException(status_code=400, detail="tool_progress inválido")
        cfg.setdefault("display", {})["tool_progress"] = mode

    if body.toolsets_cli is not None:
        from ector_cli.tools_config import _save_platform_tools

        _save_platform_tools(cfg, "cli", set(body.toolsets_cli))

    if body.compression_threshold is not None:
        try:
            thr = float(body.compression_threshold)
        except Exception:
            raise HTTPException(status_code=400, detail="compression_threshold inválido")
        if thr < 0.5 or thr > 0.95:
            raise HTTPException(status_code=400, detail="compression_threshold deve estar entre 0.5 e 0.95")
        cfg.setdefault("compression", {})["threshold"] = thr

    if body.session_reset_mode is not None:
        mode = str(body.session_reset_mode).strip().lower()
        if mode not in ("daily", "idle", "both", "none"):
            raise HTTPException(status_code=400, detail="session_reset_mode inválido")
        sr = cfg.setdefault("session_reset", {})
        sr["mode"] = mode
        if body.session_reset_at_hour is not None:
            h = int(body.session_reset_at_hour)
            if h < 0 or h > 23:
                raise HTTPException(status_code=400, detail="session_reset_at_hour inválido")
            sr["at_hour"] = h
        if body.session_reset_idle_minutes is not None:
            m = int(body.session_reset_idle_minutes)
            if m < 5 or m > 60 * 24 * 30:
                raise HTTPException(status_code=400, detail="session_reset_idle_minutes inválido")
            sr["idle_minutes"] = m

    if body.tts_provider is not None:
        tp = str(body.tts_provider).strip().lower()
        allowed = {"edge", "openai", "xai", "minimax", "mistral", "elevenlabs", "neutts", "gemini", "kittentts"}
        if tp and tp not in allowed:
            raise HTTPException(status_code=400, detail="tts_provider inválido")
        if tp:
            cfg.setdefault("tts", {})["provider"] = tp

    save_config(cfg)

    if body.inference:
        _invalidate_web_chat_agents()

    try:
        from ector_cli.main import _has_any_provider_configured

        ok = bool(_has_any_provider_configured())
    except Exception:
        ok = True

    return {"ok": True, "provider_configured": ok}


def _env_var_editable_in_dashboard(var_name: str) -> bool:
    """Dashboard /env exposes provider, tool, and messaging keys only."""
    from gateway.platform_catalog import is_supported_messaging_env_var

    meta = OPTIONAL_ENV_VARS.get(var_name)
    if meta is None or meta.get("category") == "setting":
        return False
    if meta.get("category") == "messaging" and not is_supported_messaging_env_var(
        var_name
    ):
        return False
    return True


@app.get("/api/env")
async def get_env_vars():
    env_on_disk = load_env()
    result = {}
    for var_name, info in OPTIONAL_ENV_VARS.items():
        if not _env_var_editable_in_dashboard(var_name):
            continue
        value = env_on_disk.get(var_name)
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": info.get("description", ""),
            "url": info.get("url"),
            "category": info.get("category", ""),
            "is_password": info.get("password", False),
            "tools": info.get("tools", []),
            "advanced": info.get("advanced", False),
        }
    return result


@app.put("/api/env")
async def set_env_var(body: EnvVarUpdate):
    if not _env_var_editable_in_dashboard(body.key):
        raise HTTPException(
            status_code=400,
            detail=f"{body.key} não é editável pelo dashboard; use config.yaml ou a CLI.",
        )
    try:
        save_env_value(body.key, body.value)
        return {"ok": True, "key": body.key}
    except Exception as e:
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/env")
async def remove_env_var(body: EnvVarDelete):
    if not _env_var_editable_in_dashboard(body.key):
        raise HTTPException(
            status_code=400,
            detail=f"{body.key} não é editável pelo dashboard; use config.yaml ou a CLI.",
        )
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/env/reveal")
async def reveal_env_var(body: EnvVarReveal, request: Request):
    """Return the real (unredacted) value of a single env var."""
    if not _env_var_editable_in_dashboard(body.key):
        raise HTTPException(
            status_code=400,
            detail=f"{body.key} não é editável pelo dashboard.",
        )
    # --- Token check ---
    _require_token(request)

    # --- Rate limit ---
    now = time.time()
    cutoff = now - _REVEAL_WINDOW_SECONDS
    _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
    if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Muitas solicitações de revelação. Tente novamente em breve.")
    _reveal_timestamps.append(now)

    # --- Reveal ---
    env_on_disk = load_env()
    value = env_on_disk.get(body.key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{body.key} não encontrado no .env")

    _log.info("env/reveal: %s", body.key)
    return {"key": body.key, "value": value}


# ---------------------------------------------------------------------------
# OAuth provider endpoints — status + disconnect (Phase 1)
# ---------------------------------------------------------------------------
#
# Phase 1 surfaces *which OAuth providers exist* and whether each is
# connected, plus a disconnect button. The actual login flow (PKCE for
# Anthropic, device-code for Ector/Codex) still runs in the CLI for now;
# Phase 2 will add in-browser flows. For unconnected providers we return
# the canonical ``ector auth add <provider>`` command so the dashboard
# can surface a one-click copy.


def _truncate_token(value: Optional[str], visible: int = 6) -> str:
    """Return ``...XXXXXX`` (last N chars) for safe display in the UI.

    We never expose more than the trailing ``visible`` characters of an
    OAuth access token. JWT prefixes (the part before the first dot) are
    stripped first when present so the visible suffix is always part of
    the signing region rather than a meaningless header chunk.
    """
    if not value:
        return ""
    s = str(value)
    if "." in s and s.count(".") >= 2:
        # Looks like a JWT — show the trailing piece of the signature only.
        s = s.rsplit(".", 1)[-1]
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _anthropic_oauth_status() -> Dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Ector resolves Anthropic creds in this order at runtime:
    1. ``~/.ector/.anthropic_oauth.json`` — Ector-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            read_ector_oauth_credentials,
            read_claude_code_credentials,
            _ECTOR_OAUTH_FILE,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_ector_oauth_credentials = None  # type: ignore
        _ECTOR_OAUTH_FILE = None  # type: ignore

    ector_creds = None
    if read_ector_oauth_credentials:
        try:
            ector_creds = read_ector_oauth_credentials()
        except Exception:
            ector_creds = None
    if ector_creds and ector_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "ector_pkce",
            "source_label": f"Ector PKCE ({_ECTOR_OAUTH_FILE})",
            "token_preview": _truncate_token(ector_creds.get("accessToken")),
            "expires_at": ector_creds.get("expiresAt"),
            "has_refresh_token": bool(ector_creds.get("refreshToken")),
        }

    cc_creds = None
    if read_claude_code_credentials:
        try:
            cc_creds = read_claude_code_credentials()
        except Exception:
            cc_creds = None
    if cc_creds and cc_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code",
            "source_label": "Claude Code (~/.claude/.credentials.json)",
            "token_preview": _truncate_token(cc_creds.get("accessToken")),
            "expires_at": cc_creds.get("expiresAt"),
            "has_refresh_token": bool(cc_creds.get("refreshToken")),
        }

    env_token = os.getenv("ANTHROPIC_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        return {
            "logged_in": True,
            "source": "env_var",
            "source_label": "Variável de ambiente ANTHROPIC_TOKEN",
            "token_preview": _truncate_token(env_token),
            "expires_at": None,
            "has_refresh_token": False,
        }
    return {"logged_in": False, "source": None}


def _claude_code_only_status() -> Dict[str, Any]:
    """Surface Claude Code CLI credentials as their own provider entry.

    Independent of the Anthropic entry above so users can see whether their
    Claude Code subscription tokens are actively flowing into Ector even
    when they also have a separate Ector-managed PKCE login.
    """
    try:
        from agent.anthropic_adapter import read_claude_code_credentials
        creds = read_claude_code_credentials()
    except Exception:
        creds = None
    if creds and creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code_cli",
            "source_label": "~/.claude/.credentials.json",
            "token_preview": _truncate_token(creds.get("accessToken")),
            "expires_at": creds.get("expiresAt"),
            "has_refresh_token": bool(creds.get("refreshToken")),
        }
    return {"logged_in": False, "source": None}


# Provider catalog. The order matters — it's how we render the UI list.
# ``cli_command`` is what the dashboard surfaces as the copy-to-clipboard
# fallback while Phase 2 (in-browser flows) isn't built yet.
# ``flow`` describes the OAuth shape so the future modal can pick the
# right UI: ``pkce`` = open URL + paste callback code, ``device_code`` =
# show code + verification URL + poll, ``external`` = read-only (delegated
# to a third-party CLI like Claude Code or Qwen).
_OAUTH_PROVIDER_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "id": "anthropic",
        "name": "Anthropic (Claude API)",
        "flow": "pkce",
        "cli_command": "ector auth add anthropic",
        "docs_url": "https://docs.claude.com/en/api/getting-started",
        "status_fn": _anthropic_oauth_status,
    },
    {
        "id": "claude-code",
        "name": "Claude Code (assinatura)",
        "flow": "external",
        "cli_command": "claude setup-token",
        "docs_url": "https://docs.claude.com/en/docs/claude-code",
        "status_fn": _claude_code_only_status,
        "can_disconnect": True,
    },
    {
        "id": "openai-codex",
        "name": "OpenAI Codex (ChatGPT)",
        "flow": "device_code",
        "cli_command": "ector auth add openai-codex",
        "docs_url": "https://platform.openai.com/docs",
        "status_fn": None,  # dispatched via auth.get_codex_auth_status
    },
    {
        "id": "qwen-oauth",
        "name": "Qwen (via Qwen CLI)",
        "flow": "external",
        "cli_command": "ector auth add qwen-oauth",
        "docs_url": "https://github.com/QwenLM/qwen-code",
        "status_fn": None,  # dispatched via auth.get_qwen_auth_status
        "can_disconnect": True,
    },
    {
        "id": "google-gemini-cli",
        "name": "Google Gemini (OAuth / CLI)",
        "flow": "external",
        "cli_command": "ector auth add google-gemini-cli",
        "docs_url": "https://github.com/google-gemini/gemini-cli",
        "status_fn": None,  # dispatched via auth.get_gemini_oauth_auth_status
        # Login via CLI; dashboard ainda pode desconectar credenciais locais.
        "can_disconnect": True,
    },
)


def _resolve_provider_status(provider_id: str, status_fn) -> Dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return status_fn()
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
    try:
        from ector_cli import auth as hauth
        if provider_id == "openai-codex":
            raw = hauth.get_codex_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "openai_codex",
                "source_label": raw.get("auth_mode") or "OpenAI Codex",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": False,
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "qwen-oauth":
            raw = hauth.get_qwen_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "qwen_cli",
                "source_label": raw.get("auth_store_path") or "Qwen CLI",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "google-gemini-cli":
            raw = hauth.get_gemini_oauth_auth_status()
            if not raw.get("logged_in"):
                out: Dict[str, Any] = {"logged_in": False, "source": None}
                err = raw.get("error")
                if err and str(err).strip().lower() not in {"not logged in"}:
                    out["error"] = str(err)
                return out
            exp_ms = raw.get("expires_at_ms")
            expires_at = None
            if isinstance(exp_ms, (int, float)) and exp_ms > 0:
                from datetime import datetime, timezone

                expires_at = datetime.fromtimestamp(
                    float(exp_ms) / 1000.0, tz=timezone.utc
                ).isoformat()
            return {
                "logged_in": True,
                "source": raw.get("source") or "google_gemini_oauth",
                "source_label": str(raw.get("auth_file") or "Google Gemini OAuth"),
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": expires_at,
                "has_refresh_token": True,
            }
    except Exception as e:
        return {"logged_in": False, "error": str(e)}
    return {"logged_in": False}


@app.get("/api/providers/oauth")
async def list_oauth_providers():
    """Enumerate every OAuth-capable LLM provider with current status.

    Response shape (per provider):
        id              stable identifier (used in DELETE path)
        name            human label
        flow            "pkce" | "device_code" | "external"
        cli_command     fallback CLI command for users to run manually
        docs_url        external docs/portal link for the "Learn more" link
        status:
          logged_in        bool — currently has usable creds
          source           short slug ("ector_pkce", "claude_code", ...)
          source_label     human-readable origin (file path, env var name)
          token_preview    last N chars of the token, never the full token
          expires_at       ISO timestamp string or null
          has_refresh_token bool
    """
    providers = []
    for p in _OAUTH_PROVIDER_CATALOG:
        status = _resolve_provider_status(p["id"], p.get("status_fn"))
        providers.append({
            "id": p["id"],
            "name": p["name"],
            "flow": p["flow"],
            "cli_command": p["cli_command"],
            "docs_url": p["docs_url"],
            "can_disconnect": bool(p.get("can_disconnect", p["flow"] != "external")),
            "status": status,
        })
    return {"providers": providers}


@app.delete("/api/providers/oauth/{provider_id}")
async def disconnect_oauth_provider(provider_id: str, request: Request):
    """Disconnect an OAuth provider. Token-protected (matches /env/reveal)."""
    _require_token(request)

    valid_ids = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Provedor desconhecido: {provider_id}. "
                   f"Disponíveis: {', '.join(sorted(valid_ids))}",
        )

    # Anthropic and claude-code clear the same Ector-managed PKCE file
    # AND forget the Claude Code import. We don't touch ~/.claude/* directly
    # — that's owned by the Claude Code CLI; users can re-auth there if they
    # want to undo a disconnect.
    if provider_id in ("anthropic", "claude-code"):
        try:
            from agent.anthropic_adapter import _ECTOR_OAUTH_FILE
            if _ECTOR_OAUTH_FILE.exists():
                _ECTOR_OAUTH_FILE.unlink()
        except Exception:
            pass
        # Also clear the credential pool entry if present.
        try:
            from ector_cli.auth import clear_provider_auth
            clear_provider_auth("anthropic")
        except Exception:
            pass
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    if provider_id == "google-gemini-cli":
        file_cleared = False
        try:
            from agent.google_oauth import _credentials_path

            cred_path = _credentials_path()
            if cred_path.exists():
                cred_path.unlink()
                file_cleared = True
        except Exception:
            _log.exception("oauth/disconnect: unlink google_oauth creds")
        try:
            from ector_cli.auth import clear_provider_auth

            cleared = bool(clear_provider_auth(provider_id))
        except Exception as e:
            _log.exception("disconnect google-gemini-cli clear_provider_auth failed")
            raise HTTPException(status_code=500, detail=str(e)) from e
        ok = cleared or file_cleared
        _log.info("oauth/disconnect: %s (ok=%s)", provider_id, ok)
        return {"ok": ok, "provider": provider_id}

    try:
        from ector_cli.auth import clear_provider_auth

        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Phase 2 — in-browser PKCE & device-code flows
# ---------------------------------------------------------------------------
#
# Two flow shapes are supported:
#
#   PKCE (Anthropic):
#     1. POST /api/providers/oauth/anthropic/start
#          → server generates code_verifier + challenge, builds claude.ai
#            authorize URL, stashes verifier in _oauth_sessions[session_id]
#          → returns { session_id, flow: "pkce", auth_url }
#     2. UI opens auth_url in a new tab. User authorizes, copies code.
#     3. POST /api/providers/oauth/anthropic/submit { session_id, code }
#          → server exchanges (code + verifier) → tokens at console.anthropic.com
#          → persists to ~/.ector/.anthropic_oauth.json AND credential pool
#          → returns { ok: true, status: "approved" }
#
#   Device code (Ector, OpenAI Codex):
#     1. POST /api/providers/oauth/{ector|openai-codex}/start
#          → server hits provider's device-auth endpoint
#          → gets { user_code, verification_url, device_code, interval, expires_in }
#          → spawns background poller thread that polls the token endpoint
#            every `interval` seconds until approved/expired
#          → stores poll status in _oauth_sessions[session_id]
#          → returns { session_id, flow: "device_code", user_code,
#                      verification_url, expires_in, poll_interval }
#     2. UI opens verification_url in a new tab and shows user_code.
#     3. UI polls GET /api/providers/oauth/{provider}/poll/{session_id}
#          every 2s until status != "pending".
#     4. On "approved" the background thread has already saved creds; UI
#        refreshes the providers list.
#
# Sessions are kept in-memory only (single-process FastAPI) and time out
# after 15 minutes. A periodic cleanup runs on each /start call to GC
# expired sessions so the dict doesn't grow without bound.

_OAUTH_SESSION_TTL_SECONDS = 15 * 60
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_oauth_sessions_lock = threading.Lock()

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so ector web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
        _generate_pkce as _generate_pkce_pair,
    )
    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False
_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, Dict[str, Any]]:
    """Create + register a new OAuth session, return (session_id, session_dict)."""
    sid = secrets.token_urlsafe(16)
    sess = {
        "session_id": sid,
        "provider": provider_id,
        "flow": flow,
        "created_at": time.time(),
        "status": "pending",  # pending | approved | denied | expired | error
        "error_message": None,
    }
    with _oauth_sessions_lock:
        _oauth_sessions[sid] = sess
    return sid, sess


def _save_anthropic_oauth_creds(access_token: str, refresh_token: str, expires_at_ms: int) -> None:
    """Persist Anthropic PKCE creds to both Ector file AND credential pool.

    Mirrors what auth_commands.add_command does so the dashboard flow leaves
    the system in the same state as ``ector auth add anthropic``.
    """
    from agent.anthropic_adapter import _ECTOR_OAUTH_FILE
    payload = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    _ECTOR_OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ECTOR_OAUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Best-effort credential-pool insert. Failure here doesn't invalidate
    # the file write — pool registration only matters for the rotation
    # strategy, not for runtime credential resolution.
    try:
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid
        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        existing = [e for e in pool.entries() if getattr(e, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")]
        for e in existing:
            try:
                pool.remove_entry(getattr(e, "id", ""))
            except Exception:
                pass
        entry = PooledCredential(
            provider="anthropic",
            id=uuid.uuid4().hex[:6],
            label="dashboard PKCE",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_pkce",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
        )
        pool.add_entry(entry)
    except Exception as e:
        _log.warning("anthropic pool add (dashboard) failed: %s", e)


def _start_anthropic_pkce() -> Dict[str, Any]:
    """Begin PKCE flow. Returns the auth URL the UI should open."""
    if not _ANTHROPIC_OAUTH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Anthropic OAuth not available (missing adapter)")
    verifier, challenge = _generate_pkce_pair()
    sid, sess = _new_oauth_session("anthropic", "pkce")
    sess["verifier"] = verifier
    sess["state"] = verifier  # Anthropic round-trips verifier as state
    params = {
        "code": "true",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "scope": _ANTHROPIC_OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    auth_url = f"{_ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "session_id": sid,
        "flow": "pkce",
        "auth_url": auth_url,
        "expires_in": _OAUTH_SESSION_TTL_SECONDS,
    }


def _submit_anthropic_pkce(session_id: str, code_input: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens. Persists on success."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess or sess["provider"] != "anthropic" or sess["flow"] != "pkce":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    if sess["status"] != "pending":
        return {"ok": False, "status": sess["status"], "message": sess.get("error_message")}

    # Anthropic's redirect callback page formats the code as `<code>#<state>`.
    # Strip the state suffix if present (we already have the verifier server-side).
    parts = code_input.strip().split("#", 1)
    code = parts[0].strip()
    if not code:
        return {"ok": False, "status": "error", "message": "No code provided"}
    state_from_callback = parts[1] if len(parts) > 1 else ""

    exchange_data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "code": code,
        "state": state_from_callback or sess["state"],
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "code_verifier": sess["verifier"],
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "ector-dashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Token exchange failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in") or 3600)
    if not access_token:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = "No access token returned"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)
    try:
        _save_anthropic_oauth_creds(access_token, refresh_token, expires_at_ms)
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Save failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}
    with _oauth_sessions_lock:
        sess["status"] = "approved"
    _log.info("oauth/pkce: anthropic login completed (session=%s)", session_id)
    return {"ok": True, "status": "approved"}


async def _start_device_code_flow(provider_id: str) -> Dict[str, Any]:
    """Initiate a device-code flow (OpenAI Codex).

    Calls the provider's device-auth endpoint via the existing CLI helpers,
    then spawns a background poller. Returns the user-facing display fields
    so the UI can render the verification page link + user code.
    """
    if provider_id == "openai-codex":
        # Codex uses fixed OpenAI device-auth endpoints; reuse the helper.
        sid, _ = _new_oauth_session("openai-codex", "device_code")
        # Use the helper but in a thread because it polls inline.
        # We can't extract just the start step without refactoring auth.py,
        # so we run the full helper in a worker and proxy the user_code +
        # verification_url back via the session dict. The helper prints
        # to stdout — we capture nothing here, just status.
        threading.Thread(
            target=_codex_full_login_worker, args=(sid,), daemon=True,
            name=f"oauth-codex-{sid[:6]}",
        ).start()
        # Block briefly until the worker has populated the user_code, OR error.
        deadline = time.time() + 10
        while time.time() < deadline:
            with _oauth_sessions_lock:
                s = _oauth_sessions.get(sid)
            if s and (s.get("user_code") or s["status"] != "pending"):
                break
            await asyncio.sleep(0.1)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(sid, {})
        if s.get("status") == "error":
            raise HTTPException(status_code=500, detail=s.get("error_message") or "falha na autenticação do dispositivo")
        if not s.get("user_code"):
            raise HTTPException(status_code=504, detail="a autenticação do dispositivo expirou antes de retornar um código de usuário")
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": s["user_code"],
            "verification_url": s["verification_url"],
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    raise HTTPException(status_code=400, detail=f"O provedor {provider_id} não suporta o fluxo de código de dispositivo")


def _codex_full_login_worker(session_id: str) -> None:
    """Run the complete OpenAI Codex device-code flow.

    Codex doesn't use the standard OAuth device-code endpoints; it has its
    own ``/api/accounts/deviceauth/usercode`` (JSON body, returns
    ``device_auth_id``) and ``/api/accounts/deviceauth/token`` (JSON body
    polled until 200). On success the response carries an
    ``authorization_code`` + ``code_verifier`` that get exchanged at
    CODEX_OAUTH_TOKEN_URL with grant_type=authorization_code.

    The flow is replicated inline (rather than calling
    _codex_device_code_login) because that helper prints/blocks/polls in a
    single function — we need to surface the user_code to the dashboard the
    moment we receive it, well before polling completes.
    """
    try:
        import httpx
        from ector_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )
        issuer = "https://auth.openai.com"

        # Step 1: request device code
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"deviceauth/usercode returned {resp.status_code}")
        device_data = resp.json()
        user_code = device_data.get("user_code", "")
        device_auth_id = device_data.get("device_auth_id", "")
        poll_interval = max(3, int(device_data.get("interval", "5")))
        if not user_code or not device_auth_id:
            raise RuntimeError("device-code response missing user_code or device_auth_id")
        verification_url = f"{issuer}/codex/device"
        with _oauth_sessions_lock:
            sess = _oauth_sessions.get(session_id)
            if not sess:
                return
            sess["user_code"] = user_code
            sess["verification_url"] = verification_url
            sess["device_auth_id"] = device_auth_id
            sess["interval"] = poll_interval
            sess["expires_in"] = 15 * 60  # OpenAI's effective limit
            sess["expires_at"] = time.time() + sess["expires_in"]

        # Step 2: poll until authorized
        deadline = time.time() + sess["expires_in"]
        code_resp = None
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.time() < deadline:
                time.sleep(poll_interval)
                poll = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll.status_code == 200:
                    code_resp = poll.json()
                    break
                if poll.status_code in (403, 404):
                    continue  # user hasn't authorized yet
                raise RuntimeError(f"deviceauth/token poll returned {poll.status_code}")

        if code_resp is None:
            with _oauth_sessions_lock:
                sess["status"] = "expired"
                sess["error_message"] = "Código de dispositivo expirou antes da aprovação"
            return

        # Step 3: exchange authorization_code for tokens
        authorization_code = code_resp.get("authorization_code", "")
        code_verifier = code_resp.get("code_verifier", "")
        if not authorization_code or not code_verifier:
            raise RuntimeError("resposta do device-auth sem authorization_code/code_verifier")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{issuer}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_resp.status_code != 200:
            raise RuntimeError(f"token exchange returned {token_resp.status_code}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        # Persist via credential pool — same shape as auth_commands.add_command
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid as _uuid
        pool = load_pool("openai-codex")
        base_url = (
            os.getenv("ECTOR_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_CODEX_BASE_URL
        )
        entry = PooledCredential(
            provider="openai-codex",
            id=_uuid.uuid4().hex[:6],
            label="dashboard device_code",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_device_code",
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
        )
        pool.add_entry(entry)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    _require_token(request)
    _gc_oauth_sessions()
    valid = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider_id}")
    catalog_entry = next(p for p in _OAUTH_PROVIDER_CATALOG if p["id"] == provider_id)
    if catalog_entry["flow"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"{provider_id} usa um CLI externo; execute `{catalog_entry['cli_command']}` manualmente",
        )
    try:
        if catalog_entry["flow"] == "pkce":
            return _start_anthropic_pkce()
        if catalog_entry["flow"] == "device_code":
            return await _start_device_code_flow(provider_id)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("oauth/start %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=400, detail="Unsupported flow")


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@app.post("/api/providers/oauth/{provider_id}/submit")
async def submit_oauth_code(provider_id: str, body: OAuthSubmitBody, request: Request):
    """Submit the auth code for PKCE flows. Token-protected."""
    _require_token(request)
    if provider_id == "anthropic":
        return await asyncio.get_event_loop().run_in_executor(
            None, _submit_anthropic_pkce, body.session_id, body.code,
        )
    raise HTTPException(status_code=400, detail=f"submit não suportado para {provider_id}")


@app.get("/api/providers/oauth/{provider_id}/poll/{session_id}")
async def poll_oauth_session(provider_id: str, session_id: str):
    """Poll a device-code session's status (no auth — read-only state)."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Sessão não encontrada ou expirada")
    if sess["provider"] != provider_id:
        raise HTTPException(status_code=400, detail="Incompatibilidade de provedor para a sessão")
    return {
        "session_id": session_id,
        "status": sess["status"],
        "error_message": sess.get("error_message"),
        "expires_at": sess.get("expires_at"),
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    _require_token(request)
    with _oauth_sessions_lock:
        sess = _oauth_sessions.pop(session_id, None)
    if sess is None:
        return {"ok": False, "message": "sessão não encontrada"}
    return {"ok": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Session detail endpoints
# ---------------------------------------------------------------------------


def _token_stats_from_agent(agent) -> Dict[str, Any]:
    """Live token counters from an in-memory web chat agent."""
    def _g(name: str, fallback: str | None = None) -> int:
        val = getattr(agent, name, 0) or (
            getattr(agent, fallback, 0) if fallback else 0
        )
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _g("session_input_tokens", "session_prompt_tokens"),
        "output_tokens": _g("session_output_tokens", "session_completion_tokens"),
        "cache_read_tokens": _g("session_cache_read_tokens"),
        "cache_write_tokens": _g("session_cache_write_tokens"),
        "reasoning_tokens": _g("session_reasoning_tokens"),
        "api_call_count": _g("session_api_calls"),
        "model": (getattr(agent, "model", "") or "").strip(),
    }


def _token_stats_from_row(row: dict) -> Dict[str, Any]:
    def _i(key: str) -> int:
        try:
            return int(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _i("input_tokens"),
        "output_tokens": _i("output_tokens"),
        "cache_read_tokens": _i("cache_read_tokens"),
        "cache_write_tokens": _i("cache_write_tokens"),
        "reasoning_tokens": _i("reasoning_tokens"),
        "api_call_count": _i("api_call_count"),
        "model": (row.get("model") or "").strip(),
    }


def _build_session_usage_summary(session_id: str, db) -> Dict[str, Any]:
    """Aggregate usage across compression lineage (root → tip)."""
    chain = db._session_lineage_root_to_tip(session_id)
    tip_id = chain[-1] if chain else session_id

    with _CHAT_AGENTS_LOCK:
        live_agent = _CHAT_AGENTS.get(tip_id)

    models: list[str] = []
    models_seen: set[str] = set()
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    api_call_count = 0
    tool_call_count = 0
    total_cost = 0.0
    cost_statuses: list[str] = []

    for sid in chain:
        row = db.get_session(sid) or {}
        is_tip = sid == tip_id

        if is_tip and live_agent is not None:
            stats = _token_stats_from_agent(live_agent)
            seg_cost, seg_status = _cost_usd_from_agent(live_agent)
        else:
            stats = _token_stats_from_row(row)
            seg_cost, seg_status = _cost_usd_from_session_row(row)

        for key in totals:
            totals[key] += stats[key]
        api_call_count += stats["api_call_count"]
        tool_call_count += int(row.get("tool_call_count") or 0)

        if seg_cost is not None and seg_cost > 0:
            total_cost += float(seg_cost)
            if seg_status:
                cost_statuses.append(seg_status)

        model = stats.get("model") or (row.get("model") or "").strip()
        if model and model not in models_seen:
            models_seen.add(model)
            models.append(model)

    tip_row = db.get_session(tip_id) or {}
    message_count = int(tip_row.get("message_count") or 0)
    total_tokens = sum(totals.values())

    if total_cost <= 0 and total_tokens > 0:
        billing_model = (
            (live_agent.model if live_agent is not None else None)
            or tip_row.get("model")
            or (models[0] if models else "")
        )
        if billing_model:
            try:
                from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

                cost_result = estimate_usage_cost(
                    billing_model,
                    CanonicalUsage(
                        input_tokens=totals["input_tokens"],
                        output_tokens=totals["output_tokens"],
                        cache_read_tokens=totals["cache_read_tokens"],
                        cache_write_tokens=totals["cache_write_tokens"],
                    ),
                    provider=tip_row.get("billing_provider"),
                    base_url=tip_row.get("billing_base_url"),
                )
                if cost_result.amount_usd is not None and cost_result.amount_usd > 0:
                    total_cost = float(cost_result.amount_usd)
                    cost_statuses.append(
                        cost_result.status if cost_result.status else "estimated"
                    )
            except Exception:
                pass

    if any(s == "actual" for s in cost_statuses):
        cost_status = "actual"
    elif any(s == "included" for s in cost_statuses):
        cost_status = "included"
    elif any(s == "estimated" for s in cost_statuses):
        cost_status = "estimated"
    elif total_cost > 0:
        cost_status = "estimated"
    else:
        cost_status = "unknown"

    return {
        "message_count": message_count,
        "models": models,
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "cache_read_tokens": totals["cache_read_tokens"],
        "cache_write_tokens": totals["cache_write_tokens"],
        "reasoning_tokens": totals["reasoning_tokens"],
        "total_tokens": total_tokens,
        "api_call_count": api_call_count,
        "tool_call_count": tool_call_count,
        "cost_usd": total_cost if total_cost > 0 else None,
        "cost_status": cost_status,
    }


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    from ector_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        session = db.get_session(sid) if sid else None
        if not session:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        return {
            **session,
            "usage_summary": _build_session_usage_summary(sid, db),
        }
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    from ector_cli.chat_message_media import prepare_session_messages_for_dashboard
    from ector_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        messages = prepare_session_messages_for_dashboard(
            db.get_messages(sid), session_id=sid
        )
        return {"session_id": sid, "messages": messages}
    finally:
        db.close()


class SessionTitleBody(BaseModel):
    title: str


class SessionPinBody(BaseModel):
    pinned: bool


@app.put("/api/sessions/{session_id}/pin")
async def update_session_pin(session_id: str, body: SessionPinBody):
    from ector_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        ok = db.set_session_pinned(sid, body.pinned)
        if not ok:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        pinned, pinned_at = db.get_session_pinned(sid)
        return {
            "ok": True,
            "session_id": sid,
            "pinned": pinned,
            "pinned_at": pinned_at,
        }
    finally:
        db.close()


@app.put("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, body: SessionTitleBody):
    from ector_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        try:
            ok = db.set_session_title(sid, body.title, user_set=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        return {
            "ok": True,
            "session_id": sid,
            "title": db.get_session_title(sid),
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Chat endpoint — React SSE chat for /chat in the web UI
# ---------------------------------------------------------------------------

_CHAT_AGENTS: dict[str, Any] = {}
_CHAT_AGENTS_LOCK = threading.Lock()
_CHAT_INFLIGHT: dict[str, dict[str, Any]] = {}  # session_id → {request_id, started_at}
_CHAT_SESSION_DB: Any | None = None


def _mark_chat_inflight(session_id: str, request_id: str) -> None:
    with _CHAT_AGENTS_LOCK:
        _CHAT_INFLIGHT[session_id] = {
            "request_id": request_id,
            "started_at": time.time(),
        }


def _clear_chat_inflight(session_id: str) -> None:
    with _CHAT_AGENTS_LOCK:
        _CHAT_INFLIGHT.pop(session_id, None)


def _is_chat_inflight(session_id: str) -> bool:
    with _CHAT_AGENTS_LOCK:
        return session_id in _CHAT_INFLIGHT


def _list_chat_inflight_session_ids() -> list[str]:
    with _CHAT_AGENTS_LOCK:
        return list(_CHAT_INFLIGHT.keys())


def _web_chat_pending_approval(session_id: str) -> bool:
    try:
        from tools.approval import has_blocking_approval

        return has_blocking_approval(session_id)
    except Exception:
        return False


def _invalidate_web_chat_agents() -> None:
    """Drop cached web chat agents so config/model changes take effect."""
    with _CHAT_AGENTS_LOCK:
        _CHAT_AGENTS.clear()


def _resolve_web_chat_inference_for_send(
    body: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    """Model name + config provider id for web chat (optional request overrides)."""
    body = body or {}
    try:
        cfg = load_config() or {}
    except Exception:
        cfg = {}

    _agent_cfg = cfg.get("agent") or {}
    _model_cfg = cfg.get("model") or {}
    raw_model = str(body.get("model") or "").strip()
    if not raw_model:
        if isinstance(_model_cfg, str):
            raw_model = _model_cfg.strip()
        elif isinstance(_model_cfg, dict):
            raw_model = str(
                _model_cfg.get("default") or _model_cfg.get("name") or ""
            ).strip()
    if not raw_model:
        raw_model = (
            str(_agent_cfg.get("model", "")).strip()
            if isinstance(_agent_cfg, dict)
            else ""
        )
    if not raw_model:
        raw_model = (
            os.environ.get("ECTOR_MODEL", "")
            or os.environ.get("ECTOR_INFERENCE_MODEL", "")
            or ""
        ).strip()

    provider = str(body.get("provider") or "").strip()
    if not provider and isinstance(_model_cfg, dict):
        provider = str(_model_cfg.get("provider") or "").strip()
    return raw_model, provider


def _web_chat_cached_agent_stale(
    agent: Any,
    body: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when a cached agent no longer matches config (or explicit request overrides)."""
    expected_model, expected_provider_cfg = _resolve_web_chat_inference_for_send(body)
    if not expected_model:
        return False

    agent_model = str(getattr(agent, "model", "") or "").strip()
    if agent_model != expected_model:
        return True

    try:
        from ector_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider(
            requested=expected_provider_cfg or None,
            target_model=expected_model,
        )
        expected_runtime_provider = str(runtime.get("provider") or "").strip()
        agent_provider = str(getattr(agent, "provider", "") or "").strip()
        if expected_runtime_provider and agent_provider != expected_runtime_provider:
            return True
    except Exception:
        return agent_model != expected_model
    return False


_CHAT_SESSION_DB_LOCK = threading.Lock()
_WEB_RUNTIME_HOME_FALLBACK = PROJECT_ROOT / ".ector-web-runtime"


def _ensure_web_runtime_paths_writable() -> None:
    """Ensure web chat can write runtime logs/state.

    In restricted environments, writing to the user's default ECTOR_HOME may
    fail with ``Operation not permitted``. When that happens, switch to a
    project-local fallback ECTOR_HOME so web chat keeps working.
    """
    try:
        home = get_ector_home()
        logs_dir = home / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        test_path = logs_dir / "agent.log"
        with open(test_path, "a", encoding="utf-8"):
            pass
        return
    except OSError as exc:
        _log.warning(
            "web runtime logs not writable at default ECTOR_HOME (%s): %s; "
            "switching to fallback %s",
            get_ector_home(),
            exc,
            _WEB_RUNTIME_HOME_FALLBACK,
        )

    os.environ["ECTOR_HOME"] = str(_WEB_RUNTIME_HOME_FALLBACK)
    logs_dir = _WEB_RUNTIME_HOME_FALLBACK / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    test_path = logs_dir / "agent.log"
    with open(test_path, "a", encoding="utf-8"):
        pass


_WEB_CHAT_GATEWAY_ENV_KEYS = (
    "ECTOR_GATEWAY_SESSION",
    "ECTOR_EXEC_ASK",
    "ECTOR_INTERACTIVE",
)


@contextlib.contextmanager
def _web_chat_approval_context(session_id: str, notify_cb):
    """Enable gateway-style blocking approvals for one web chat agent thread."""
    from tools.approval import (
        register_gateway_notify,
        reset_current_session_key,
        set_current_session_key,
        unregister_gateway_notify,
    )

    saved_env = {k: os.environ.get(k) for k in _WEB_CHAT_GATEWAY_ENV_KEYS}
    os.environ["ECTOR_GATEWAY_SESSION"] = "1"
    os.environ["ECTOR_EXEC_ASK"] = "1"
    os.environ["ECTOR_INTERACTIVE"] = "1"
    key_token = set_current_session_key(session_id)
    register_gateway_notify(session_id, notify_cb)
    try:
        yield
    finally:
        unregister_gateway_notify(session_id)
        reset_current_session_key(key_token)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _web_chat_client_disconnect(session_id: str) -> None:
    """Handle SSE client disconnect without denying a pending approval.

    The agent thread may still be blocked waiting for the user. Only drop
    the dead SSE notify callback so a reloaded page can poll
    ``/api/chat/approval/pending`` and render the approval card again.
    """
    try:
        from tools.approval import detach_gateway_notify

        detach_gateway_notify(session_id)
    except Exception:
        pass


def _toggle_web_chat_yolo(session_id: str) -> dict:
    """Toggle session-scoped YOLO for a web chat session (parity with gateway /yolo)."""
    from tools.approval import (
        disable_session_yolo,
        enable_session_yolo,
        is_session_yolo_enabled,
    )

    if is_session_yolo_enabled(session_id):
        disable_session_yolo(session_id)
        return {
            "ok": True,
            "enabled": False,
            "message": (
                "Modo YOLO **desativado** nesta sessão — comandos perigosos exigirão aprovação."
            ),
        }
    enable_session_yolo(session_id)
    return {
        "ok": True,
        "enabled": True,
        "message": (
            "Modo YOLO **ativado** nesta sessão — todos os comandos aprovados automaticamente. "
            "Use com cuidado. (A flag `ector localhost --yolo` afeta todo o processo.)"
        ),
    }


@app.post("/api/chat/send")
async def chat_send(request: Request):
    """SSE streaming chat endpoint.

    POST JSON body::

        {"session_id": "...", "message": "...", "images": [
            {"filename": "...", "content_base64": "...", "mime": "image/png"}
        ], "documents": [
            {"filename": "...", "content_base64": "...", "mime": "application/pdf"}
        ]}

    At least one of ``message``, ``images`` or ``documents`` is required.

    Returns: ``text/event-stream`` with ``data: <chunk>`` events and a final
    ``data: DONE`` event.

    The first call with a new ``session_id`` creates an AIAgent for it;
    subsequent calls reuse the same agent so conversation context is preserved.
    """
    body = await request.json()
    session_id = str(body.get("session_id") or "").strip() or str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    message = body.get("message", "").strip()
    raw_images = body.get("images") or []
    raw_documents = body.get("documents") or body.get("document") or []
    if raw_documents and not isinstance(raw_documents, list):
        raw_documents = [raw_documents]

    from ector_cli.attachments import (
        WebChatDocumentError,
        WebChatImageError,
        prepare_web_chat_message,
        save_chat_document_payload,
        save_chat_image_payload,
        validate_web_chat_send_payload,
    )

    validation_error = validate_web_chat_send_payload(message, raw_images, raw_documents)
    if validation_error:
        return JSONResponse({"error": validation_error}, status_code=400)

    image_paths: list[str] = []
    document_paths: list[str] = []
    try:
        for item in raw_images:
            image_paths.append(str(save_chat_image_payload(item)))
    except WebChatImageError as exc:
        status_code = 413 if "exceeds" in str(exc).lower() else 400
        return JSONResponse({"error": str(exc)}, status_code=status_code)
    try:
        for item in raw_documents:
            document_paths.append(str(save_chat_document_payload(item)))
    except WebChatDocumentError as exc:
        status_code = 413 if "exceeds" in str(exc).lower() else 400
        return JSONResponse({"error": str(exc)}, status_code=status_code)

    if _WEB_CHAT_DEBUG:
        _log.info(
            "[web-chat] send start request_id=%s session=%s message_len=%d images=%d documents=%d",
            request_id,
            session_id,
            len(message),
            len(image_paths),
            len(document_paths),
        )

    try:
        _ensure_web_runtime_paths_writable()
    except OSError as exc:
        return JSONResponse(
            {
                "error": (
                    "Não foi possível inicializar diretório de runtime/logs "
                    f"do web chat: {exc}"
                )
            },
            status_code=500,
        )
    from run_agent import AIAgent

    def _get_chat_session_db():
        global _CHAT_SESSION_DB
        if _CHAT_SESSION_DB is not None:
            return _CHAT_SESSION_DB
        with _CHAT_SESSION_DB_LOCK:
            if _CHAT_SESSION_DB is None:
                from ector_state import SessionDB

                _CHAT_SESSION_DB = SessionDB()
        return _CHAT_SESSION_DB

    async def event_stream():
        with _CHAT_AGENTS_LOCK:
            if session_id in _CHAT_INFLIGHT:
                yield (
                    "data: TEXT|*Aguarde a resposta anterior terminar antes de enviar outra mensagem.*\n\n"
                )
                yield "data: DONE\n\n"
                return
            _mark_chat_inflight(session_id, request_id)

        from ector_cli import web_chat_live as _web_chat_live

        _web_chat_live.begin_turn(session_id, request_id)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _send(kind: str, payload: str = ""):
            loop.call_soon_threadsafe(queue.put_nowait, f"{kind}|{payload}")
            if _WEB_CHAT_DEBUG and kind != "TEXT":
                _log.info(
                    "[web-chat] sse event request_id=%s session=%s kind=%s payload_preview=%r",
                    request_id,
                    session_id,
                    kind,
                    (payload[:120] if isinstance(payload, str) else payload),
                )

        streamed_text = False

        def on_chunk(chunk: str):
            nonlocal streamed_text
            if chunk:
                streamed_text = True
                _web_chat_live.append_text(session_id, chunk)
                _send("TEXT", chunk)

        def on_stream_delta(delta):
            if delta is None:
                return
            on_chunk(delta)

        def on_interim_assistant(text: str, *, already_streamed: bool = False):
            if already_streamed or not str(text or "").strip():
                return
            on_chunk(text)

        def on_status(kind: str, text: str = None):
            if text:
                _web_chat_live.set_status(session_id, text)
                _send("STATUS", text)

        def on_tool_start(tc_id, name, args):
            import json as _j
            context = ""
            technical = ""
            try:
                from agent.display import (
                    build_tool_preview,
                    build_tool_technical_summary,
                )

                context = build_tool_preview(name, args, max_len=240) or ""
                technical = build_tool_technical_summary(name, args) or ""
                payload = _j.dumps(
                    {
                        "id": tc_id,
                        "name": name,
                        "args": args,
                        "context": context,
                        "technical": technical,
                    },
                    ensure_ascii=False,
                )
            except Exception:
                payload = f"{name}|{_j.dumps(args)[:200]}"
            args_str = args if isinstance(args, str) else _j.dumps(args)
            _web_chat_live.tool_start(
                session_id,
                tool_id=str(tc_id or ""),
                name=str(name or "tool"),
                args=args_str,
                live_label=context,
                live_technical=technical,
            )
            _send("TOOL_START", payload)

        def on_tool_complete(tc_id, name, args, result):
            import json as _j
            if name in ("terminal", "shell", "process"):
                _sync_web_session_cwd_from_env(session_id, allow_default_env=True)
            footer_cwd = None
            result_str = str(result) if result is not None else None
            try:
                payload_obj: dict = {
                    "id": tc_id,
                    "name": name,
                }
                if name in ("terminal", "shell", "process"):
                    footer_cwd = _resolve_web_chat_cwd(session_id)
                    if footer_cwd:
                        payload_obj["cwd"] = footer_cwd
                        payload_obj["cwd_label"] = _short_display_cwd(footer_cwd)
                if result_str is not None:
                    if name == "text_to_speech" or len(result_str) <= 8192:
                        payload_obj["result"] = result_str
                payload = _j.dumps(payload_obj, ensure_ascii=False)
            except Exception:
                payload = name
            _web_chat_live.tool_complete(
                session_id,
                tool_id=str(tc_id or ""),
                name=str(name or "tool"),
                result=result_str,
                cwd=footer_cwd,
            )
            _send("TOOL_COMPLETE", payload)
            if name == "text_to_speech" and result:
                try:
                    tts_data = _j.loads(str(result))
                    file_path = str(tts_data.get("file_path") or "").strip()
                    if tts_data.get("success") and file_path:
                        _send(
                            "TTS_AUDIO",
                            _j.dumps(
                                {
                                    "tool_call_id": tc_id,
                                    "file_path": file_path,
                                },
                                ensure_ascii=False,
                            ),
                        )
                except Exception:
                    pass
            if name in ("write_file", "edit_file", "patch", "execute_code") and result:
                try:
                    from pathlib import Path as _Path
                    from ector_cli.agent_images import (
                        extract_chat_media_from_tool_result,
                        markdown_from_tool_result,
                    )
                    from ector_cli.chat_media_paths import (
                        chat_file_preview_url,
                        chat_image_api_url,
                    )

                    md = markdown_from_tool_result(name, str(result))
                    media = extract_chat_media_from_tool_result(name, str(result))
                    attachments = []
                    for item in media:
                        raw_path = str(item.get("path") or "").strip()
                        kind = str(item.get("kind") or "").strip() or "document"
                        suffix = _Path(raw_path).suffix.lower()
                        if not raw_path:
                            continue
                        download_url = (
                            chat_image_api_url(raw_path)
                            if kind == "image"
                            else (
                                "/api/chat/files/download?"
                                f"path={urllib.parse.quote(raw_path, safe='')}"
                                f"&session_id={urllib.parse.quote(session_id, safe='')}"
                            )
                        )
                        preview_url = (
                            chat_image_api_url(raw_path)
                            if kind == "image"
                            else (
                                chat_file_preview_url(raw_path, session_id)
                                if suffix in {".svg", ".html", ".htm"}
                                else download_url
                            )
                        )
                        if not preview_url:
                            continue
                        attachments.append(
                            {
                                "id": f"tool-media-{_Path(raw_path).name}",
                                "name": _Path(raw_path).name,
                                "kind": "image"
                                if (kind == "image" or suffix == ".svg")
                                else "document",
                                "url": download_url,
                                "previewUrl": preview_url,
                                "path": raw_path,
                            }
                        )
                    if md or attachments:
                        _send(
                            "CHAT_IMAGE",
                            _j.dumps(
                                {"markdown": md or "", "attachments": attachments},
                                ensure_ascii=False,
                            ),
                        )
                except Exception:
                    pass

        def on_tool_progress(event_type, name=None, preview=None, args=None, **kwargs):
            import json as _j

            preview_text = str(preview or "")
            technical = ""
            try:
                from agent.display import build_tool_technical_summary

                if isinstance(args, dict) and name:
                    technical = build_tool_technical_summary(name, args) or ""
            except Exception:
                pass
            try:
                payload = _j.dumps(
                    {
                        "event": event_type,
                        "name": name or "",
                        "preview": preview_text[:240],
                        "technical": technical[:240],
                    },
                    ensure_ascii=False,
                )
            except Exception:
                payload = f"{event_type}|{name or ''}|{preview_text[:240]}"
            _web_chat_live.tool_progress(
                session_id,
                tool_name=str(name or ""),
                preview=preview_text,
                technical=technical,
            )
            _send("TOOL_PROGRESS", payload)

        def on_thinking(text: str):
            if text:
                _web_chat_live.set_thinking(session_id)
                _send("THINKING", text[:500])

        def on_approval_request(approval_data: dict):
            import json as _j

            try:
                payload_data = dict(approval_data or {})
                payload_data.setdefault("session_id", session_id)
                payload = _j.dumps(payload_data, ensure_ascii=False)
            except Exception:
                payload = "{}"
            _send("APPROVAL_REQUEST", payload)

        def on_done():
            loop.call_soon_threadsafe(queue.put_nowait, None)

        # Create agent lazily inside event_stream so it gets the callbacks
        should_start_thread = True
        agent = _CHAT_AGENTS.get(session_id)
        if agent is not None and _web_chat_cached_agent_stale(agent, body):
            with _CHAT_AGENTS_LOCK:
                _CHAT_AGENTS.pop(session_id, None)
            agent = None
        if agent is None:
            with _CHAT_AGENTS_LOCK:
                agent = _CHAT_AGENTS.get(session_id)
                if agent is None:
                    try:
                        from ector_cli.config import load_config
                        from ector_cli.runtime_provider import resolve_runtime_provider
                        cfg = load_config() or {}
                        _agent_cfg = cfg.get("agent") or {}
                        _model_cfg = cfg.get("model") or {}
                        raw_model = body.get("model") or ""
                        if not raw_model:
                            if isinstance(_model_cfg, str):
                                raw_model = _model_cfg
                            elif isinstance(_model_cfg, dict):
                                raw_model = _model_cfg.get("default") or _model_cfg.get("name") or ""
                        if not raw_model:
                            raw_model = _agent_cfg.get("model", "") if isinstance(_agent_cfg, dict) else ""
                        if not raw_model:
                            raw_model = os.environ.get("ECTOR_MODEL", "") or os.environ.get("ECTOR_INFERENCE_MODEL", "")
                        model = str(raw_model).strip()
                        if not model:
                            _send("TEXT", "Nenhum modelo configurado. Configure um modelo em /config ou passe model no body.")
                            on_done()
                            should_start_thread = False
                        provider = body.get("provider") or ""
                        if should_start_thread:
                            runtime = resolve_runtime_provider(requested=provider, target_model=model or None)
                            try:
                                agent = AIAgent(
                                    model=model,
                                    provider=runtime.get("provider"),
                                    base_url=runtime.get("base_url"),
                                    api_key=runtime.get("api_key"),
                                    api_mode=runtime.get("api_mode"),
                                    quiet_mode=True,
                                    platform="web",
                                    session_id=session_id,
                                    tool_start_callback=on_tool_start,
                                    tool_complete_callback=on_tool_complete,
                                    tool_progress_callback=on_tool_progress,
                                    thinking_callback=on_thinking,
                                    status_callback=on_status,
                                    session_db=_get_chat_session_db(),
                                )
                            except OSError as init_exc:
                                # Some environments block writes to ~/.ector/logs.
                                # Force project-local fallback and retry once.
                                if (
                                    "agent.log" in str(init_exc)
                                    and "Operation not permitted" in str(init_exc)
                                ):
                                    global _CHAT_SESSION_DB
                                    os.environ["ECTOR_HOME"] = str(
                                        _WEB_RUNTIME_HOME_FALLBACK
                                    )
                                    _CHAT_SESSION_DB = None
                                    _ensure_web_runtime_paths_writable()
                                    agent = AIAgent(
                                        model=model,
                                        provider=runtime.get("provider"),
                                        base_url=runtime.get("base_url"),
                                        api_key=runtime.get("api_key"),
                                        api_mode=runtime.get("api_mode"),
                                        quiet_mode=True,
                                        platform="web",
                                        session_id=session_id,
                                        tool_start_callback=on_tool_start,
                                        tool_complete_callback=on_tool_complete,
                                        tool_progress_callback=on_tool_progress,
                                        thinking_callback=on_thinking,
                                        status_callback=on_status,
                                        session_db=_get_chat_session_db(),
                                    )
                                else:
                                    raise
                    except Exception as exc:
                        _send("TEXT", f"\n\n*Erro ao criar agente: {exc}*")
                        on_done()
                        should_start_thread = False
                    if should_start_thread and agent is not None:
                        _CHAT_AGENTS[session_id] = agent
                        try:
                            from tools.terminal_tool import register_task_env_overrides

                            register_task_env_overrides(
                                session_id,
                                {"cwd": _resolve_web_chat_cwd(session_id)},
                            )
                        except Exception:
                            pass
        if agent is not None:
            # Agent instances are reused per session; refresh per-request callbacks
            # so tool/status events are emitted to the current SSE queue.
            agent.tool_start_callback = on_tool_start
            agent.tool_complete_callback = on_tool_complete
            agent.tool_progress_callback = on_tool_progress
            agent.thinking_callback = on_thinking
            agent.status_callback = on_status
            agent.stream_delta_callback = on_stream_delta
            _display_cfg = (load_config() or {}).get("display") or {}
            _interim_raw = _display_cfg.get("interim_assistant_messages", True)
            _interim_on = (
                _interim_raw is not False
                and str(_interim_raw).strip().lower() not in {"0", "false", "off", "no", "none"}
            )
            agent.interim_assistant_callback = (
                on_interim_assistant if _interim_on else None
            )

        _prime_web_session_cwd(session_id)

        def run():
            title_thread = None
            try:
                with _web_chat_approval_context(session_id, on_approval_request):
                    _prime_web_session_cwd(session_id)
                    try:
                        db = _get_chat_session_db()
                        model_name = (
                            getattr(agent, "model", None) if agent is not None else None
                        )
                        db.ensure_session(
                            session_id,
                            source="web",
                            model=model_name,
                        )
                    except Exception:
                        if _WEB_CHAT_DEBUG:
                            _log.debug(
                                "[web-chat] ensure_session failed request_id=%s session=%s",
                                request_id,
                                session_id,
                                exc_info=True,
                            )
                    conversation_history = None
                    try:
                        history = _get_chat_session_db().get_messages_as_conversation(
                            session_id
                        )
                        if history:
                            conversation_history = history
                        if _WEB_CHAT_DEBUG:
                            _log.info(
                                "[web-chat] history loaded request_id=%s session=%s count=%d",
                                request_id,
                                session_id,
                                len(history or []),
                            )
                    except Exception:
                        conversation_history = None
                        if _WEB_CHAT_DEBUG:
                            _log.exception(
                                "[web-chat] history load failed request_id=%s session=%s",
                                request_id,
                                session_id,
                            )

                    prompt = message
                    if image_paths or document_paths:
                        if image_paths:
                            on_status("vision", "Analisando imagem…")
                        if document_paths:
                            on_status("documents", "Extraindo documentos…")
                        prompt = prepare_web_chat_message(
                            message, image_paths, document_paths
                        )

                    # Stream only via stream_delta_callback — passing stream_callback
                    # too would double-fire on_chunk for every token (_fire_stream_delta).
                    result = agent.run_conversation(
                        prompt,
                        conversation_history=conversation_history,
                        task_id=session_id,
                    )
                    final = (result or {}).get("final_response") or ""
                    if _WEB_CHAT_DEBUG:
                        _log.info(
                            "[web-chat] run complete request_id=%s session=%s final_len=%d streamed_text=%s",
                            request_id,
                            session_id,
                            len(final),
                            streamed_text,
                        )
                    # Deltas already went to the client via on_chunk; re-sending
                    # ``final`` would duplicate the transcript on append-style UIs.
                    if final and not streamed_text:
                        _send("TEXT", final)

                    failed = bool((result or {}).get("failed"))
                    partial = bool((result or {}).get("partial"))
                    if final and not failed and not partial:
                        try:
                            from agent.title_generator import maybe_auto_title

                            history_after = None
                            try:
                                history_after = (
                                    _get_chat_session_db().get_messages_as_conversation(
                                        session_id
                                    )
                                )
                            except Exception:
                                history_after = conversation_history

                            def _on_session_title(title: str) -> None:
                                import json as _title_json

                                _send(
                                    "SESSION_TITLE",
                                    _title_json.dumps(
                                        {"session_id": session_id, "title": title},
                                        ensure_ascii=False,
                                    ),
                                )

                            title_thread = maybe_auto_title(
                                _get_chat_session_db(),
                                session_id,
                                message,
                                final,
                                history_after or [],
                                title_callback=_on_session_title,
                            )
                        except Exception:
                            if _WEB_CHAT_DEBUG:
                                _log.debug(
                                    "[web-chat] auto-title skipped request_id=%s session=%s",
                                    request_id,
                                    session_id,
                                    exc_info=True,
                                )
            except Exception as exc:
                _send("TEXT", f"\n\n*Erro: {exc}*")
                if _WEB_CHAT_DEBUG:
                    _log.exception(
                        "[web-chat] run failed request_id=%s session=%s",
                        request_id,
                        session_id,
                    )
            finally:
                _sync_web_session_cwd_from_env(session_id, allow_default_env=True)
                if title_thread is not None:
                    title_thread.join(timeout=2.5)
                on_done()

        if should_start_thread and agent is not None:
            thread = threading.Thread(target=run, daemon=True)
            thread.start()

        stream_completed_normally = False
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    stream_completed_normally = True
                    yield "data: DONE\n\n"
                    break
                safe = chunk.replace("\n", "\\n")
                yield f"data: {safe}\n\n"
        finally:
            if stream_completed_normally:
                _clear_chat_inflight(session_id)
                _web_chat_live.clear_turn(session_id)
            else:
                _web_chat_client_disconnect(session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat/transcribe")
async def chat_transcribe(request: Request):
    """Transcribe browser-recorded audio for the web chat composer."""
    _require_token(request)
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid body"}, status_code=400)

    from ector_cli.attachments import WebChatAudioError, decode_chat_audio_payload
    from tools.transcription_tools import transcribe_web_chat_audio

    try:
        data, ext = decode_chat_audio_payload(body)
    except WebChatAudioError as exc:
        status_code = 413 if "exceeds" in str(exc).lower() else 400
        return JSONResponse({"error": str(exc)}, status_code=status_code)

    import tempfile
    from pathlib import Path

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        result = await asyncio.to_thread(transcribe_web_chat_audio, tmp_path)
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

    if not result.get("success"):
        err = str(result.get("error") or "transcription failed")
        return JSONResponse({"error": err}, status_code=400)

    transcript = str(result.get("transcript") or "").strip()
    if not transcript:
        return JSONResponse({"error": "nenhuma fala detectada"}, status_code=400)

    return {"success": True, "transcript": transcript}


_TTS_AUDIO_SUFFIXES = frozenset({".mp3", ".ogg", ".opus", ".wav", ".m4a", ".webm", ".aac"})


def _resolve_safe_tts_audio_path(raw_path: str) -> "Path":
    """Resolve a TTS output file under ECTOR_HOME (blocks path traversal)."""
    from pathlib import Path

    if not raw_path or not str(raw_path).strip():
        raise HTTPException(status_code=400, detail="path ausente")

    candidate = Path(str(raw_path).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = get_ector_home() / candidate

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="áudio não encontrado") from None
    except OSError as exc:
        raise HTTPException(status_code=400, detail="caminho inválido") from exc

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="áudio não encontrado")

    home = get_ector_home().resolve()
    try:
        resolved.relative_to(home)
    except ValueError:
        raise HTTPException(status_code=403, detail="caminho não permitido") from None

    if resolved.suffix.lower() not in _TTS_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="formato de áudio não suportado")

    return resolved


@app.get("/api/chat/images/cache/{filename}")
async def chat_cache_image(request: Request, filename: str):
    """Serve a generated image from ``{ECTOR_HOME}/cache/images``."""
    from ector_cli.chat_media_paths import (
        image_media_type,
        resolve_chat_image_file,
    )

    _require_token(request)
    try:
        image_path = resolve_chat_image_file(filename, bucket="cache")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="imagem não encontrada") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(image_path, media_type=image_media_type(image_path))


@app.get("/api/chat/images/{filename}")
async def chat_image(request: Request, filename: str):
    """Serve a persisted web-chat image from ``{ECTOR_HOME}/images``."""
    from ector_cli.chat_media_paths import (
        image_media_type,
        resolve_chat_image_file,
    )

    _require_token(request)
    try:
        image_path = resolve_chat_image_file(filename, bucket="images")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="imagem não encontrada") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(image_path, media_type=image_media_type(image_path))


def _chat_file_preview_response(
    request: Request,
    *,
    path: str,
    session_id: str,
):
    """Serve a readable file (image, HTML, SVG) from session cwd, home, or ECTOR_HOME."""
    from ector_cli.chat_media_paths import (
        ARTIFACT_SUFFIXES,
        PREVIEW_FILE_SUFFIXES,
        _CHAT_IMAGE_SUFFIXES,
        artifact_media_type,
        image_media_type,
        resolve_readable_file,
    )

    _require_token(request)
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id é obrigatório")
    raw = str(path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path é obrigatório")
    allowed = PREVIEW_FILE_SUFFIXES
    try:
        resolved = resolve_readable_file(
            raw,
            session_cwd=_resolve_web_chat_cwd(sid),
            allowed_suffixes=allowed,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ficheiro não encontrado") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="caminho não permitido") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    suffix = resolved.suffix.lower()
    if suffix in _CHAT_IMAGE_SUFFIXES:
        return FileResponse(resolved, media_type=image_media_type(resolved))

    response = FileResponse(resolved, media_type=artifact_media_type(resolved))
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; "
        "font-src data:; sandbox"
    )
    return response


def _chat_file_download_response(
    request: Request,
    *,
    path: str,
    session_id: str,
):
    """Serve a download for a session-scoped file path under allowed roots."""
    from ector_cli.chat_media_paths import _allowed_roots

    _require_token(request)
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id é obrigatório")
    raw = str(path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path é obrigatório")
    text = raw[7:] if raw.startswith("file://") else raw
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path(_resolve_web_chat_cwd(sid)).expanduser() / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="ficheiro não encontrado") from None
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="ficheiro não encontrado")
    roots = _allowed_roots(_resolve_web_chat_cwd(sid))
    for root in roots:
        try:
            resolved.relative_to(root)
            return FileResponse(
                resolved,
                media_type="application/octet-stream",
                filename=resolved.name,
            )
        except ValueError:
            continue
    raise HTTPException(status_code=403, detail="caminho não permitido")


@app.get("/api/chat/files/preview")
async def chat_file_preview(
    request: Request,
    path: str = "",
    session_id: str = "",
):
    """Serve images and HTML/SVG artifacts by absolute or cwd-relative path."""
    return _chat_file_preview_response(
        request, path=path, session_id=session_id
    )


@app.get("/api/chat/files/download")
async def chat_file_download(
    request: Request,
    path: str = "",
    session_id: str = "",
):
    """Download any generated file under session cwd/home/ECTOR_HOME."""
    return _chat_file_download_response(
        request, path=path, session_id=session_id
    )


@app.get("/api/chat/artifacts/preview")
async def chat_artifact_preview(
    request: Request,
    path: str = "",
    session_id: str = "",
):
    """Legacy alias for :func:`chat_file_preview`."""
    return _chat_file_preview_response(
        request, path=path, session_id=session_id
    )


@app.get("/api/chat/tts-audio")
async def chat_tts_audio(request: Request, path: str = ""):
    """Stream a TTS file generated by ``text_to_speech`` for in-browser playback."""
    _require_token(request)
    audio_path = _resolve_safe_tts_audio_path(path)
    media_types = {
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".aac": "audio/aac",
    }
    media_type = media_types.get(audio_path.suffix.lower(), "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@app.post("/api/chat/interrupt")
async def chat_interrupt(request: Request):
    """Request the in-flight web chat agent for *session_id* to stop."""
    body = await request.json()
    session_id = (body.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)
    with _CHAT_AGENTS_LOCK:
        agent = _CHAT_AGENTS.get(session_id)
    if agent is not None:
        try:
            agent.interrupt()
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
    _clear_chat_inflight(session_id)
    try:
        from ector_cli import web_chat_live as _web_chat_live

        _web_chat_live.clear_turn(session_id)
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/chat/status")
async def chat_status(request: Request, session_id: str = ""):
    """Report whether a web chat session has an in-flight agent turn."""
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id is required"}, status_code=400)
    return {
        "session_id": sid,
        "busy": _is_chat_inflight(sid),
        "pending_approval": _web_chat_pending_approval(sid),
    }


@app.get("/api/chat/turn")
async def chat_turn(request: Request, session_id: str = ""):
    """Authoritative chat view: persisted messages + optional live turn overlay."""
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    from ector_cli.chat_message_media import prepare_session_messages_for_dashboard
    from ector_cli import web_chat_live as _web_chat_live

    busy = _is_chat_inflight(sid)
    pending_approval = _web_chat_pending_approval(sid)
    messages: list[dict[str, Any]] = []
    try:
        from ector_state import SessionDB

        db = SessionDB()
        try:
            messages = prepare_session_messages_for_dashboard(
                db.get_messages(sid), session_id=sid
            )
        finally:
            db.close()
    except Exception:
        messages = []

    live = _web_chat_live.live_for_api(sid) if busy else None
    revision = int((live or {}).get("revision") or 0)
    return {
        "session_id": sid,
        "busy": busy,
        "revision": revision,
        "pending_approval": pending_approval,
        "messages": messages,
        "live": live,
    }


@app.get("/api/chat/active")
async def chat_active_sessions(request: Request):
    """Session ids with an in-flight web chat turn (for sidebar badges)."""
    return {"sessions": _list_chat_inflight_session_ids()}


@app.get("/api/chat/approval/pending")
async def chat_approval_pending(request: Request, session_id: str = ""):
    """Return the oldest pending approval for a web chat session (for UI restore)."""
    _require_token(request)
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id is required"}, status_code=400)
    try:
        from tools.approval import peek_actionable_gateway_approval

        data = peek_actionable_gateway_approval(sid)
        if not data:
            return {"pending": False}
        return {
            "pending": True,
            "command": data.get("command") or "",
            "description": data.get("description") or "",
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/chat/approval")
async def chat_approval(request: Request):
    """Resolve one pending approval request for a web chat session."""
    _require_token(request)
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid body"}, status_code=400)

    session_id = str(body.get("session_id") or "").strip()
    choice_raw = str(body.get("choice") or "deny").strip().lower()
    resolve_all = bool(body.get("all", choice_raw in {"session"}))

    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    # The approval engine expects "once/session/always/deny".
    choice_map = {
        "approve": "once",
        "once": "once",
        "session": "session",
        "always": "always",
        "deny": "deny",
    }
    choice = choice_map.get(choice_raw)
    if choice is None:
        return JSONResponse(
            {"error": "choice must be one of approve|deny|once|session|always"},
            status_code=400,
        )

    try:
        from tools.approval import resolve_gateway_approval

        resolved = resolve_gateway_approval(session_id, choice, resolve_all=resolve_all)
        return {"ok": True, "resolved": resolved}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/chat/yolo")
async def chat_yolo(request: Request):
    """Toggle session-scoped YOLO (skip dangerous-command approvals) for web chat."""
    _require_token(request)
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid body"}, status_code=400)

    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    try:
        return _toggle_web_chat_yolo(session_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/sessions")
async def delete_all_sessions_endpoint():
    from ector_state import SessionDB
    db = SessionDB()
    try:
        count = db.delete_all_sessions()
        return {"ok": True, "deleted": count}
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    from ector_state import SessionDB
    db = SessionDB()
    try:
        if not db.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Log viewer endpoint
# ---------------------------------------------------------------------------


@app.get("/api/logs")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
):
    from ector_cli.logs import _read_tail, LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Arquivo de log desconhecido: {file}")
    log_path = get_ector_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from ector_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Componente desconhecido: {component}. "
                       f"Disponíveis: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path, min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [l for l in result if needle in l.lower()][-min(lines, 500):]
    return {"file": file, "lines": result}


# ---------------------------------------------------------------------------
# Cron job management endpoints
# ---------------------------------------------------------------------------


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"


class CronJobUpdate(BaseModel):
    updates: dict


@app.get("/api/cron/jobs")
async def list_cron_jobs():
    from cron.jobs import list_jobs
    return list_jobs(include_disabled=True)


@app.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str):
    from cron.jobs import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return job


@app.post("/api/cron/jobs")
async def create_cron_job(body: CronJobCreate):
    from cron.jobs import create_job
    try:
        job = create_job(prompt=body.prompt, schedule=body.schedule,
                         name=body.name, deliver=body.deliver)
        return job
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    from cron.jobs import update_job
    job = update_job(job_id, body.updates)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return job


@app.post("/api/cron/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str):
    from cron.jobs import pause_job
    job = pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return job


@app.post("/api/cron/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str):
    from cron.jobs import resume_job
    job = resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return job


@app.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str):
    from cron.jobs import trigger_job
    job = trigger_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return job


@app.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str):
    from cron.jobs import remove_job
    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Skills & Tools endpoints
# ---------------------------------------------------------------------------


class SkillToggle(BaseModel):
    name: str
    enabled: bool


class SkillCreateBody(BaseModel):
    name: str
    content: str
    category: str | None = None


class SkillContentBody(BaseModel):
    content: str


class ToolsetToggle(BaseModel):
    name: str
    enabled: bool


def _skill_is_editable(name: str) -> bool:
    from tools.skill_manager_tool import _find_skill, _is_local_skill

    existing = _find_skill(name)
    return existing is not None and _is_local_skill(existing["path"])


@app.get("/api/skills")
async def get_skills():
    from tools.skills_tool import _find_all_skills
    from ector_cli.skills_config import get_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    skills = _find_all_skills(skip_disabled=True)
    for s in skills:
        s["enabled"] = s["name"] not in disabled
        s["editable"] = _skill_is_editable(s["name"])
    return skills


@app.get("/api/skills/{name}/content")
async def get_skill_content(name: str):
    from tools.skill_manager_tool import _find_skill, _is_local_skill

    existing = _find_skill(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Skill não encontrada: {name}")
    if not _is_local_skill(existing["path"]):
        raise HTTPException(
            status_code=403,
            detail="Skill em diretório externo — somente leitura.",
        )
    skill_md = existing["path"] / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(status_code=404, detail="SKILL.md não encontrado.")
    return {
        "name": name,
        "content": skill_md.read_text(encoding="utf-8"),
        "path": str(existing["path"]),
    }


@app.post("/api/skills")
async def create_skill(body: SkillCreateBody):
    import json as _json

    from tools.skill_manager_tool import skill_manage

    raw = skill_manage(
        action="create",
        name=body.name.strip(),
        content=body.content,
        category=(body.category or "").strip() or None,
    )
    result = _json.loads(raw)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Falha ao criar skill"))
    return result


@app.put("/api/skills/{name}/content")
async def update_skill_content(name: str, body: SkillContentBody):
    import json as _json

    from tools.skill_manager_tool import _find_skill, skill_manage

    if not _find_skill(name):
        raise HTTPException(status_code=404, detail=f"Skill não encontrada: {name}")
    raw = skill_manage(action="edit", name=name, content=body.content)
    result = _json.loads(raw)
    if not result.get("success"):
        status = 403 if "external directory" in str(result.get("error", "")).lower() else 400
        raise HTTPException(status_code=status, detail=result.get("error", "Falha ao salvar skill"))
    return result


@app.put("/api/skills/toggle")
async def toggle_skill(body: SkillToggle):
    from ector_cli.skills_config import get_disabled_skills, save_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    if body.enabled:
        disabled.discard(body.name)
    else:
        disabled.add(body.name)
    save_disabled_skills(config, disabled)
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@app.put("/api/tools/toolsets/toggle")
async def toggle_toolset(body: ToolsetToggle):
    from ector_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _save_platform_tools,
    )

    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    valid_names = {entry[0] for entry in _get_effective_configurable_toolsets()}
    if name not in valid_names:
        raise HTTPException(status_code=404, detail=f"Toolset desconhecido: {name}")

    config = load_config()
    enabled = set(
        _get_platform_tools(
            config,
            "cli",
            include_default_mcp_servers=False,
        )
    )
    if body.enabled:
        enabled.add(name)
    else:
        enabled.discard(name)
    _save_platform_tools(config, "cli", enabled)
    return {"ok": True, "name": name, "enabled": body.enabled}


@app.get("/api/tools/toolsets")
async def get_toolsets():
    from ector_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        is_enabled = name in enabled_toolsets
        result.append({
            "name": name, "label": label, "description": desc,
            "enabled": is_enabled,
            "available": is_enabled,
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
        })
    return result


# ---------------------------------------------------------------------------
# Raw YAML config endpoint
# ---------------------------------------------------------------------------


class RawConfigUpdate(BaseModel):
    yaml_text: str


@app.get("/api/config/raw")
async def get_config_raw():
    path = get_config_path()
    if not path.exists():
        return {"yaml": ""}
    return {"yaml": path.read_text(encoding="utf-8")}


@app.put("/api/config/raw")
async def update_config_raw(body: RawConfigUpdate):
    try:
        parsed = yaml.safe_load(body.yaml_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="O YAML deve ser um mapeamento")
        save_config(parsed)
        return {"ok": True}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML inválido: {e}")


# ---------------------------------------------------------------------------
# Token / cost analytics endpoint
# ---------------------------------------------------------------------------


@app.get("/api/analytics/usage")
async def get_usage_analytics(days: int = 30):
    from ector_state import SessionDB
    from agent.stats import StatsEngine

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)
        cur = db._conn.execute("""
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """, (cutoff,))
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute("""
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute("""
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ?
        """, (cutoff,))
        totals = dict(cur3.fetchone())
        stats_report = StatsEngine(db).generate(days=days)
        skills = stats_report.get("skills", {
            "summary": {
                "total_skill_loads": 0,
                "total_skill_edits": 0,
                "total_skill_actions": 0,
                "distinct_skills_used": 0,
            },
            "top_skills": [],
        })
        tools = stats_report.get("tools", [])

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
            "skills": skills,
            "tools": tools,
        }
    finally:
        db.close()


def mount_spa(application: FastAPI):
    """Mount the built SPA. Falls back to index.html for client-side routing.

    The session token is injected into index.html via a ``<script>`` tag so
    the SPA can authenticate against protected API endpoints without a
    separate (unauthenticated) token-dispensing endpoint.
    """
    if not WEB_DIST.exists() or not (WEB_DIST / "index.html").is_file():
        dashboard_dir = PROJECT_ROOT / "frontend" / "dashboard"
        try:
            from ector_cli.web_build import (
                web_can_build_from_source,
                web_prebuilt_missing_message,
            )

            if not web_can_build_from_source(dashboard_dir):
                detail = web_prebuilt_missing_message(PROJECT_ROOT)
            else:
                detail = (
                    "Frontend não compilado. Execute: cd frontend/dashboard && npm run build"
                )
        except Exception:
            detail = (
                "Frontend não compilado. Execute: cd frontend/dashboard && npm run build"
            )

        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse({"error": detail}, status_code=404)
        return

    _index_path = WEB_DIST / "index.html"

    def _serve_index():
        """Return index.html with the session token injected."""
        html = _index_path.read_text()
        try:
            footer_json = json.dumps(
                _chat_footer_payload(),
                ensure_ascii=False,
            ).replace("<", "\\u003c")
        except Exception:
            _log.exception("composer footer inject failed")
            footer_json = "{}"
        token_script = (
            f'<script>window.__ECTOR_SESSION_TOKEN__="{_SESSION_TOKEN}";'
            f"window.__ECTOR_COMPOSER_FOOTER__={footer_json};</script>"
        )
        html = html.replace("</head>", f"{token_script}</head>", 1)
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    application.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Do not fall back to index.html for /api/* — missing routes would return
        # HTML 200 and break ``fetch(...).json()`` in the SPA (SyntaxError on "<!doctype").
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={
                    "detail": (
                        "Rota API não encontrada ou backend desatualizado. "
                        "Reinicie o painel (`ector localhost`) após atualizar o Ector."
                    ),
                },
            )
        file_path = WEB_DIST / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(WEB_DIST.resolve())
            and file_path.exists()
            and file_path.is_file()
        ):
            return FileResponse(file_path)
        return _serve_index()


# ---------------------------------------------------------------------------
# Dashboard theme endpoints
# ---------------------------------------------------------------------------


def _parse_theme_layer(value: Any, default_hex: str, default_alpha: float = 1.0) -> Optional[Dict[str, Any]]:
    """Normalise a theme layer spec from YAML into `{hex, alpha}` form.

    Accepts shorthand (a bare hex string) or full dict form.  Returns
    ``None`` on garbage input so the caller can fall back to a built-in
    default rather than blowing up.
    """
    if value is None:
        return {"hex": default_hex, "alpha": default_alpha}
    if isinstance(value, str):
        return {"hex": value, "alpha": default_alpha}
    if isinstance(value, dict):
        hex_val = value.get("hex", default_hex)
        alpha_val = value.get("alpha", default_alpha)
        if not isinstance(hex_val, str):
            return None
        try:
            alpha_f = float(alpha_val)
        except (TypeError, ValueError):
            alpha_f = default_alpha
        return {"hex": hex_val, "alpha": max(0.0, min(1.0, alpha_f))}
    return None


_THEME_DEFAULT_TYPOGRAPHY: Dict[str, str] = {
    "fontSans": 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    "fontMono": 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace',
    "baseSize": "15px",
    "lineHeight": "1.55",
    "letterSpacing": "0",
}

_THEME_DEFAULT_LAYOUT: Dict[str, str] = {
    "radius": "0.5rem",
    "density": "comfortable",
}

_THEME_OVERRIDE_KEYS = {
    "card", "cardForeground", "popover", "popoverForeground",
    "primary", "primaryForeground", "secondary", "secondaryForeground",
    "muted", "mutedForeground", "accent", "accentForeground",
    "destructive", "destructiveForeground", "success", "warning",
    "border", "input", "ring",
}

# Well-known named asset slots themes can populate.  Any other keys under
# ``assets.custom`` are exposed as ``--theme-asset-custom-<key>`` CSS vars
# for plugin/shell use.
_THEME_NAMED_ASSET_KEYS = {"bg", "hero", "logo", "crest", "sidebar", "header"}

# Component-style buckets themes can override.  The value under each bucket
# is a mapping from camelCase property name to CSS string; each pair emits
# ``--component-<bucket>-<kebab-property>`` on :root.  The frontend's shell
# components (Card, App header, Backdrop, etc.) consume these vars so themes
# can restyle chrome (clip-path, border-image, segmented progress, etc.)
# without shipping their own CSS.
_THEME_COMPONENT_BUCKETS = {
    "card", "header", "footer", "sidebar", "tab",
    "progress", "badge", "backdrop", "page",
}

_THEME_LAYOUT_VARIANTS = {"standard", "cockpit", "tiled"}

# Cap on customCSS length so a malformed/oversized theme YAML can't blow up
# the response payload or the <style> tag.  32 KiB is plenty for every
# practical reskin (the Strike Freedom demo is ~2 KiB).
_THEME_CUSTOM_CSS_MAX = 32 * 1024


def _normalise_theme_definition(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a user theme YAML into the wire format `ThemeProvider`
    expects.  Returns ``None`` if the theme is unusable.

    Accepts both the full schema (palette/typography/layout) and a loose
    form with bare hex strings, so hand-written YAMLs stay friendly.
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    # Palette
    palette_src = data.get("palette", {}) if isinstance(data.get("palette"), dict) else {}
    # Allow top-level `colors.background` as a shorthand too.
    colors_src = data.get("colors", {}) if isinstance(data.get("colors"), dict) else {}

    def _layer(key: str, default_hex: str, default_alpha: float = 1.0) -> Dict[str, Any]:
        spec = palette_src.get(key, colors_src.get(key))
        parsed = _parse_theme_layer(spec, default_hex, default_alpha)
        return parsed if parsed is not None else {"hex": default_hex, "alpha": default_alpha}

    palette = {
        "background": _layer("background", "#041c1c", 1.0),
        "midground": _layer("midground", "#ffe6cb", 1.0),
        "foreground": _layer("foreground", "#ffffff", 0.0),
        "warmGlow": palette_src.get("warmGlow") or data.get("warmGlow") or "rgba(255, 189, 56, 0.35)",
        "noiseOpacity": 1.0,
    }
    raw_noise = palette_src.get("noiseOpacity", data.get("noiseOpacity"))
    try:
        palette["noiseOpacity"] = float(raw_noise) if raw_noise is not None else 1.0
    except (TypeError, ValueError):
        palette["noiseOpacity"] = 1.0

    # Typography
    typo_src = data.get("typography", {}) if isinstance(data.get("typography"), dict) else {}
    typography = dict(_THEME_DEFAULT_TYPOGRAPHY)
    for key in ("fontSans", "fontMono", "fontDisplay", "fontUrl", "baseSize", "lineHeight", "letterSpacing"):
        val = typo_src.get(key)
        if isinstance(val, str) and val.strip():
            typography[key] = val

    # Layout
    layout_src = data.get("layout", {}) if isinstance(data.get("layout"), dict) else {}
    layout = dict(_THEME_DEFAULT_LAYOUT)
    radius = layout_src.get("radius")
    if isinstance(radius, str) and radius.strip():
        layout["radius"] = radius
    density = layout_src.get("density")
    if isinstance(density, str) and density in ("compact", "comfortable", "spacious"):
        layout["density"] = density

    # Color overrides — keep only valid keys with string values.
    overrides_src = data.get("colorOverrides", {})
    color_overrides: Dict[str, str] = {}
    if isinstance(overrides_src, dict):
        for key, val in overrides_src.items():
            if key in _THEME_OVERRIDE_KEYS and isinstance(val, str) and val.strip():
                color_overrides[key] = val

    # Assets — named slots + arbitrary user-defined keys.  Values must be
    # strings (URLs or CSS ``url(...)``/``linear-gradient(...)`` expressions).
    # We don't fetch remote assets here; the frontend just injects them as
    # CSS vars.  Empty values are dropped so a theme can explicitly clear a
    # slot by setting ``hero: ""``.
    assets_out: Dict[str, Any] = {}
    assets_src = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    for key in _THEME_NAMED_ASSET_KEYS:
        val = assets_src.get(key)
        if isinstance(val, str) and val.strip():
            assets_out[key] = val
    custom_assets_src = assets_src.get("custom")
    if isinstance(custom_assets_src, dict):
        custom_assets: Dict[str, str] = {}
        for key, val in custom_assets_src.items():
            if (
                isinstance(key, str)
                and key.replace("-", "").replace("_", "").isalnum()
                and isinstance(val, str)
                and val.strip()
            ):
                custom_assets[key] = val
        if custom_assets:
            assets_out["custom"] = custom_assets

    # Custom CSS — raw CSS text the frontend injects as a scoped <style>
    # tag on theme apply.  Clipped to _THEME_CUSTOM_CSS_MAX to keep the
    # payload bounded.  We intentionally do NOT parse/sanitise the CSS
    # here — the dashboard is localhost-only and themes are user-authored
    # YAML in ~/.ector/, same trust level as the config file itself.
    custom_css_val = data.get("customCSS")
    custom_css: Optional[str] = None
    if isinstance(custom_css_val, str) and custom_css_val.strip():
        custom_css = custom_css_val[:_THEME_CUSTOM_CSS_MAX]

    # Component style overrides — per-bucket dicts of camelCase CSS
    # property -> CSS string.  The frontend converts these into CSS vars
    # that shell components (Card, App header, Backdrop) consume.
    component_styles_src = data.get("componentStyles", {})
    component_styles: Dict[str, Dict[str, str]] = {}
    if isinstance(component_styles_src, dict):
        for bucket, props in component_styles_src.items():
            if bucket not in _THEME_COMPONENT_BUCKETS or not isinstance(props, dict):
                continue
            clean: Dict[str, str] = {}
            for prop, value in props.items():
                if (
                    isinstance(prop, str)
                    and prop.replace("-", "").replace("_", "").isalnum()
                    and isinstance(value, (str, int, float))
                    and str(value).strip()
                ):
                    clean[prop] = str(value)
            if clean:
                component_styles[bucket] = clean

    layout_variant_src = data.get("layoutVariant")
    layout_variant = (
        layout_variant_src
        if isinstance(layout_variant_src, str) and layout_variant_src in _THEME_LAYOUT_VARIANTS
        else "standard"
    )

    result: Dict[str, Any] = {
        "name": name,
        "label": data.get("label") or name,
        "description": data.get("description", ""),
        "palette": palette,
        "typography": typography,
        "layout": layout,
        "layoutVariant": layout_variant,
    }
    if color_overrides:
        result["colorOverrides"] = color_overrides
    if assets_out:
        result["assets"] = assets_out
    if custom_css is not None:
        result["customCSS"] = custom_css
    if component_styles:
        result["componentStyles"] = component_styles
    return result


def _discover_user_themes() -> list:
    """Scan ~/.ector/dashboard-themes/*.yaml for user-created themes.

    Returns a list of fully-normalised theme definitions ready to ship
    to the frontend, so the client can apply them without a secondary
    round-trip or a built-in stub.
    """
    themes_dir = get_ector_home() / "dashboard-themes"
    if not themes_dir.is_dir():
        return []
    result = []
    for f in sorted(themes_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalised = _normalise_theme_definition(data)
        if normalised is not None:
            result.append(normalised)
    return result


"""
Dashboard themes are controlled client-side (dark/light/system) via localStorage
in `frontend/dashboard/src/themes/context.tsx`. The server does not expose a theme registry.
"""

mount_spa(app)


def start_server(
    host: str = "127.0.0.1",
    port: int = 9000,
    open_browser: bool = True,
    allow_public: bool = False,
    *,
    open_url: Optional[str] = None,
):
    """Start the web UI server."""
    import uvicorn

    _LOCALHOST = ("127.0.0.1", "localhost", "::1")
    if host not in _LOCALHOST and not allow_public:
        raise SystemExit(
            f"Recusando vincular a {host} — o dashboard expõe chaves de API "
            f"e configuração sem autenticação robusta.\n"
            f"Use --insecure para sobrescrever (NÃO recomendado em redes não confiáveis)."
        )
    if host not in _LOCALHOST:
        _log.warning(
            "Vinculando a %s com --insecure — o dashboard não tem "
            "autenticação robusta. Use apenas em redes confiáveis.", host,
        )

    # Record the bound host so host_header_middleware can validate incoming
    # Host headers against it. Defends against DNS rebinding (GHSA-ppp5-vxwm-4cf7).
    app.state.bound_host = host
    app.state.bound_port = port

    # Web chat must not inherit the server's process cwd (repo checkout / ~/.ector).
    _apply_web_dashboard_terminal_cwd(reset_envs=True)

    # Record PID so `ector localhost kill` can stop it later.
    write_dashboard_pid_file()

    if open_browser:
        def _open():
            open_dashboard_browser(open_url, host=host, port=port)

        threading.Thread(target=_open, daemon=True).start()

    friendly = get_dashboard_local_hostname()
    display_host = friendly if friendly and host in _LOCALHOST else host
    primary_url = f"http://{display_host}:{port}"
    print(f"  Ector Web UI → {primary_url}")
    if open_url and open_url != primary_url and open_url != f"http://{host}:{port}":
        print(f"  Ector Web UI (auth) → {open_url}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        clear_dashboard_pid_file()
