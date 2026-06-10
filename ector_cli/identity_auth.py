"""Identity authentication against the Ector identity API (ector.cc).

This module manages the user's *identity* session — distinct from the
*provider* credentials (Anthropic / OpenAI / OpenRouter / etc.) which
live in ``~/.ector/auth.json`` and are owned by
:mod:`ector_cli.auth`.

Endpoints consumed (default base ``https://ector.cc``):

- ``GET /agent/auth?source=cli&cli_port=<port>&state=<state>``
    OAuth da CLI (loopback): ``source=cli`` e ``cli_port`` (1024–65535).
    O browser usa a sessão (cookie) do site; em sucesso redireciona para
    ``http://127.0.0.1:<port>/oauth/callback?...``.
- ``POST /agent/auth/device/start`` — inicia fluxo device code (SSH/headless).
- ``POST /agent/auth/device/poll`` — body ``{ "deviceCode": string }``; polling.
- ``POST /agent/auth/device/authorize`` — browser autoriza com cookie do site.
- ``GET /agent/auth/me`` — header ``Authorization: Bearer <access_token>``.
    Perfil do utilizador; campos espelhados em ``~/.ector/config.yaml``
    (``user.*``) via :func:`_sync_user_profile_to_config`.
- ``POST /agent/auth/refresh`` — corpo ``{"refreshToken": string}``.
    Devolve ``{"accessToken", "refreshToken", "expiresIn"}``; o refresh
    roda a cada chamada e a família é revogada em reutilização.
- ``POST /agent/auth/logout`` — corpo opcional ``{"refreshToken"?: string}``;
    resposta ``204``; idempotente.

Persistence: ``~/.ector/identity.json`` (chmod 0600, atomic rename,
cross-process advisory lock at ``identity.json.lock``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import secrets
import socket
import stat
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from ector_cli.colors import Colors, color
from ector_cli.device_identity import (
    cli_oauth_query_params,
    device_auth_headers,
    get_or_create_install_id,
    register_device_with_api,
)
from ector_constants import get_ector_home

logger = logging.getLogger(__name__)

try:
    import fcntl
except Exception:
    fcntl = None
try:
    import msvcrt
except Exception:
    msvcrt = None


# ---------------------------------------------------------------------------
# Constants & configuration
# ---------------------------------------------------------------------------

IDENTITY_STORE_VERSION = 1
DEFAULT_AUTH_BASE_URL = "https://ector.cc"
DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_TIMEOUT_SECONDS = 180
DEFAULT_REFRESH_SKEW_SECONDS = 300        # refresh 5 min before expiry
DEFAULT_ME_CACHE_SECONDS = 900            # 15 min between /me probes
DEFAULT_OFFLINE_GRACE_SECONDS = 86400       # 24 h offline proceed after last /me
DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0
DEFAULT_DEVICE_TIMEOUT_SECONDS = 900
DEFAULT_DEVICE_POLL_INTERVAL_SECONDS = 5

REMOTE_LOGIN_FAILURE_MESSAGE = (
    "Falha ao iniciar o login remoto.\n"
    "Se você estiver conectado via SSH, utilize:\n"
    "ector login --device"
)
LOCK_TIMEOUT_SECONDS = 15.0
CALLBACK_PATH = "/oauth/callback"


class IdentityAuthError(Exception):
    """Raised when identity auth fails.

    ``relogin_required=True`` signals that the persisted session is
    unrecoverable (refresh expired / family revoked / account disabled)
    and the caller should prompt the user to run ``ector login`` again.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "identity_auth_error",
        relogin_required: bool = False,
        access_level: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.relogin_required = relogin_required
        self.access_level = access_level
        self.payload = payload or {}


@dataclass(frozen=True)
class IdentitySession:
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    expires_at: datetime

    def to_bearer(self) -> str:
        return f"Bearer {self.access_token}"


# ---------------------------------------------------------------------------
# Config / env resolution
# ---------------------------------------------------------------------------

def _load_auth_config() -> Dict[str, Any]:
    """Read the ``auth`` section from ~/.ector/config.yaml (best-effort).

    Returns a dict with sensible defaults so this module remains usable
    even on first launch before config.yaml has been materialised.
    """
    cfg: Dict[str, Any] = {}
    try:
        from ector_cli.config import load_config
        full = load_config()
        if isinstance(full, dict) and isinstance(full.get("auth"), dict):
            cfg = dict(full["auth"])
    except Exception:
        logger.debug("identity_auth: load_config() failed; using defaults", exc_info=True)
    return cfg


def get_auth_base_url() -> str:
    """Return the configured backend base URL (no trailing slash).

    Precedence: ``auth.base_url`` in config.yaml > :data:`DEFAULT_AUTH_BASE_URL`
    (``https://ector.cc``).  ``ECTOR_AUTH_BASE_URL`` in the process environment
    is honoured only for tests/CI overrides — it is not listed in
    ``OPTIONAL_ENV_VARS`` and must not be set via ``~/.ector/.env`` or the
    dashboard ``/env`` UI.
    """
    env = os.environ.get("ECTOR_AUTH_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    cfg = _load_auth_config()
    val = str(cfg.get("base_url") or "").strip()
    if val:
        return val.rstrip("/")
    return DEFAULT_AUTH_BASE_URL


def _get_int_setting(key: str, default: int) -> int:
    cfg = _load_auth_config()
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_bool_setting(key: str, default: bool = False) -> bool:
    cfg = _load_auth_config()
    val = cfg.get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return bool(val)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _is_ssh_session() -> bool:
    return bool(os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"))


def resolve_login_mode(*, force_device: bool = False, force_local: bool = False) -> str:
    """Return ``loopback`` or ``device`` for ``ector login``."""
    if force_device and force_local:
        raise ValueError("Não use --device e --local ao mesmo tempo.")
    if force_local:
        return "loopback"
    if force_device:
        return "device"
    cfg = _load_auth_config()
    configured = str(cfg.get("login_mode") or "auto").strip().lower()
    if configured in ("loopback", "device"):
        return configured
    if _is_ssh_session():
        return "device"
    if not sys.stdin.isatty():
        return "device"
    return "loopback"


def get_active_session() -> Optional[IdentitySession]:
    """Return the current session from disk or env override (no network I/O)."""
    return get_persisted_session() or _env_token_override()


def _effective_session() -> Optional[IdentitySession]:
    """Alias for :func:`get_active_session` (internal callers)."""
    return get_active_session()


def get_cached_access_level() -> str:
    """Return the last known ``access_level`` from disk (empty if unknown)."""
    state = _read_store()
    if not state:
        return ""
    return str(state.get("access_level") or "").strip().lower()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _identity_file_path() -> Path:
    path = get_ector_home() / "identity.json"
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # ``Path.home()`` is often monkeypatched in tests; ``expanduser``
        # reads ``$HOME`` directly so it still points at the real user
        # home and the seat-belt fires only when ECTOR_HOME was actually
        # forgotten in the fixture.
        try:
            real_root = Path(os.path.expanduser("~")) / ".ector"
            real = (real_root / "identity.json").resolve(strict=False)
            resolved = path.resolve(strict=False)
        except Exception:
            real = None
            resolved = path
        if real is not None and resolved == real:
            raise RuntimeError(
                f"Refusing to touch real user identity store during test run: {path}. "
                "Set ECTOR_HOME to a tmp_path in your test fixture."
            )
    return path


def _identity_lock_path() -> Path:
    return _identity_file_path().with_suffix(".lock")


_lock_holder = threading.local()


@contextmanager
def _identity_store_lock(timeout_seconds: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Cross-process advisory lock for identity.json reads+writes.

    Reentrant within a thread (matches the pattern used by
    :func:`ector_cli.auth._auth_store_lock`). Crucial because the
    backend rotates the refresh token on every call and revokes the
    family on reuse — two concurrent ``ector`` invocations *must not*
    refresh independently.
    """
    if getattr(_lock_holder, "depth", 0) > 0:
        _lock_holder.depth += 1
        try:
            yield
        finally:
            _lock_holder.depth -= 1
        return

    lock_path = _identity_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None and msvcrt is None:
        _lock_holder.depth = 1
        try:
            yield
        finally:
            _lock_holder.depth = 0
        return

    if msvcrt and (not lock_path.exists() or lock_path.stat().st_size == 0):
        lock_path.write_text(" ", encoding="utf-8")

    with lock_path.open("r+" if msvcrt else "a+") as lock_file:
        deadline = time.time() + max(1.0, timeout_seconds)
        while True:
            try:
                if fcntl:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except (BlockingIOError, OSError, PermissionError):
                if time.time() >= deadline:
                    raise TimeoutError("Timed out waiting for identity store lock")
                time.sleep(0.05)

        _lock_holder.depth = 1
        try:
            yield
        finally:
            _lock_holder.depth = 0
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass


def _read_store() -> Optional[Dict[str, Any]]:
    path = _identity_file_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("identity_auth: failed to parse %s (%s); ignoring", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _write_store(data: Dict[str, Any]) -> Path:
    path = _identity_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = IDENTITY_STORE_VERSION
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def _clear_store() -> None:
    path = _identity_file_path()
    with contextlib.suppress(FileNotFoundError, OSError):
        path.unlink()


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        # fromisoformat accepts "+00:00" but not the trailing "Z".
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _store_to_session(state: Dict[str, Any]) -> Optional[IdentitySession]:
    try:
        access_token = str(state["access_token"]).strip()
        refresh_token = str(state["refresh_token"]).strip()
        user_id = str(state["user_id"]).strip()
        email = str(state["email"]).strip()
        expires_at = _parse_iso(state.get("expires_at"))
    except (KeyError, TypeError):
        return None
    if not (access_token and refresh_token and user_id and expires_at):
        return None
    return IdentitySession(
        user_id=user_id,
        email=email,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def _is_expiring(state: Dict[str, Any], skew_seconds: int) -> bool:
    expires_at = _parse_iso(state.get("expires_at"))
    if expires_at is None:
        return True
    now = datetime.now(timezone.utc)
    return (expires_at - now).total_seconds() <= max(0, skew_seconds)


def _env_token_override() -> Optional[IdentitySession]:
    """Allow CI / headless to inject a token via env vars.

    Honoured only when *both* ``ECTOR_ACCESS_TOKEN`` and
    ``ECTOR_REFRESH_TOKEN`` are present. We can't realistically validate
    the JWT locally (no shared secret), so we trust the caller to have
    obtained a valid pair.
    """
    access = os.environ.get("ECTOR_ACCESS_TOKEN", "").strip()
    refresh = os.environ.get("ECTOR_REFRESH_TOKEN", "").strip()
    if not access or not refresh:
        return None
    user_id = os.environ.get("ECTOR_USER_ID", "env-user").strip() or "env-user"
    email = os.environ.get("ECTOR_USER_EMAIL", "").strip()
    # Assume far-future expiry; the caller is responsible for rotating.
    return IdentitySession(
        user_id=user_id,
        email=email,
        access_token=access,
        refresh_token=refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _detect_terminal_app() -> str:
    term_program = os.environ.get("TERM_PROGRAM", "").strip()
    if term_program:
        lowered = term_program.lower()
        if lowered == "vscode":
            return "VS Code"
        if lowered == "cursor":
            return "Cursor"
        if "iterm" in lowered:
            return "iTerm"
        if "warp" in lowered:
            return "Warp"
        return term_program
    if os.environ.get("WT_SESSION"):
        return "Windows Terminal"
    if os.environ.get("VSCODE_INJECTION") or os.environ.get("VSCODE_GIT_IPC_HANDLE"):
        return "VS Code"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_SESSION"):
        return "Cursor"
    return "Terminal"


def _detect_os_name() -> str:
    import platform

    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Windows":
        return "Windows"
    if system == "Linux":
        return "Linux"
    return system or "Unknown"


def _build_cli_user_agent() -> str:
    try:
        from ector_cli import __version__

        version = str(__version__)
    except Exception:
        version = "0.0.0"
    term = _detect_terminal_app()
    os_name = _detect_os_name()
    return f"ector-cli/{version} ({os_name}; {term})"


# ---------------------------------------------------------------------------
# HTTP calls to backend
# ---------------------------------------------------------------------------

def _http_client(timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> httpx.Client:
    headers = {
        "User-Agent": _build_cli_user_agent(),
        "Accept": "application/json",
    }
    headers.update(device_auth_headers())
    return httpx.Client(timeout=httpx.Timeout(timeout), headers=headers)


def _post_refresh(base_url: str, refresh_token: str) -> Dict[str, Any]:
    """Call ``POST /agent/auth/refresh``. Rotates refresh token."""
    url = f"{base_url}/agent/auth/refresh"
    try:
        with _http_client() as client:
            response = client.post(url, json={"refreshToken": refresh_token})
    except httpx.HTTPError as exc:
        raise IdentityAuthError(
            f"Falha de rede ao atualizar a sessão: {exc}",
            code="network_error",
        ) from exc

    if response.status_code in (200, 201):
        payload = _safe_json(response)
        access = str(payload.get("accessToken") or "").strip()
        new_refresh = str(payload.get("refreshToken") or "").strip()
        expires_in = _coerce_int(payload.get("expiresIn"), 3600)
        if not access or not new_refresh:
            raise IdentityAuthError(
                "Resposta de refresh inválida (sem accessToken/refreshToken).",
                code="invalid_response",
                relogin_required=True,
            )
        return {
            "access_token": access,
            "refresh_token": new_refresh,
            "expires_in": expires_in,
        }

    if response.status_code == 401:
        raise IdentityAuthError(
            "Sessão revogada ou expirada. Faça login novamente com `ector login`.",
            code="refresh_unauthorized",
            relogin_required=True,
        )

    if response.status_code == 403:
        raise _access_forbidden_error(response)

    raise IdentityAuthError(
        f"Refresh falhou com HTTP {response.status_code}.",
        code=f"refresh_http_{response.status_code}",
    )


def _post_logout(base_url: str, refresh_token: str) -> None:
    """Call ``POST /agent/auth/logout``. Body optional ``{refreshToken?}``; 204 — never raises."""
    url = f"{base_url}/agent/auth/logout"
    body: Dict[str, str] = {}
    rt = (refresh_token or "").strip()
    if rt:
        body["refreshToken"] = rt
    try:
        with _http_client(timeout=10.0) as client:
            client.post(url, json=body)
    except httpx.HTTPError as exc:
        logger.debug("identity_auth: logout request failed: %s", exc)


def _get_me(base_url: str, access_token: str) -> Dict[str, Any]:
    """Call ``GET /agent/auth/me`` with ``Authorization: Bearer <access_token>``."""
    url = f"{base_url}/agent/auth/me"
    try:
        with _http_client() as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise IdentityAuthError(
            f"Falha de rede ao consultar /me: {exc}",
            code="network_error",
        ) from exc

    if response.status_code == 200:
        return _safe_json(response)
    if response.status_code == 401:
        raise IdentityAuthError(
            "Sessão inválida. Faça login novamente com `ector login`.",
            code="me_unauthorized",
            relogin_required=True,
        )
    if response.status_code == 403:
        raise _access_forbidden_error(response)
    raise IdentityAuthError(
        f"Consulta /me falhou com HTTP {response.status_code}.",
        code=f"me_http_{response.status_code}",
    )


def _safe_json(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _access_forbidden_error(response: httpx.Response) -> IdentityAuthError:
    """403 com conta autenticada mas sem acesso ativo (ex.: assinatura)."""
    payload = _safe_json(response)
    access_level = str(payload.get("accessLevel") or "blocked").strip() or "blocked"
    message = str(
        payload.get("message")
        or "Sua conta não tem acesso ativo ao agente."
    ).strip()
    return IdentityAuthError(
        message,
        code=str(payload.get("error") or "subscription_required").strip().lower(),
        access_level=access_level,
        payload=payload,
    )


def _http_ok(status_code: int) -> bool:
    """True for successful HTTP responses (Nest may return 200 or 201)."""
    return 200 <= int(status_code) < 300


def identity_auth_user_message(exc: IdentityAuthError) -> str:
    """Mensagem curta para o utilizador (sem detalhes HTTP técnicos)."""
    if exc.code in ("device_start_failed", "device_poll_failed", "device_timeout"):
        return REMOTE_LOGIN_FAILURE_MESSAGE
    if exc.access_level == "blocked":
        return str(exc).strip()
    if exc.relogin_required or exc.code == "not_authenticated":
        return str(exc).strip()
    if exc.code.startswith(("refresh_http_", "me_http_")):
        return "Não foi possível validar a sessão. Execute `ector login` para continuar."
    msg = str(exc).strip()
    if "HTTP " in msg and "falhou" in msg.lower():
        return "Não foi possível validar a sessão. Execute `ector login` para continuar."
    return msg


_SUBSCRIPTION_PORTAL_CTA_RE = re.compile(
    r"\s*(?:Renove|Atualize(?:\s+sua\s+assinatura)?)"
    r"(?:\s+(?:em|no))?\s+(?:https?://)?(?:www\.)?ector\.cc(?:/[^\s.]*)?"
    r"(?:\s+para\s+(?:continuar|usar(?:\s+o\s+agente)?)\.?)?$",
    re.IGNORECASE,
)


def _normalize_subscription_reason(reason: str) -> str:
    """Remove CTAs redundantes já mostrados no rodapé da mensagem."""
    text = str(reason or "").strip()
    if not text:
        return "Nenhuma assinatura ativa encontrada."
    cleaned = _SUBSCRIPTION_PORTAL_CTA_RE.sub("", text).strip().rstrip(".")
    return cleaned or "Nenhuma assinatura ativa encontrada."


def _subscription_portal_url() -> str:
    return str(get_identity_plan_hints().get("portal_url") or "https://ector.cc").rstrip("/")


def print_subscription_blocked_message(
    reason: str,
    *,
    offline_cache: bool = False,
    variant: str = "error",
    file: Any = None,
) -> None:
    """Imprime bloqueio de assinatura sem repetir o mesmo CTA duas vezes."""
    import sys as _sys

    out = file if file is not None else _sys.stderr
    detail = _normalize_subscription_reason(reason)
    portal = _subscription_portal_url()
    title = "Acesso ao agente bloqueado"
    if offline_cache:
        title += " (sem conexão)"

    use_color = hasattr(out, "isatty") and out.isatty()
    if use_color:
        icon = "!" if variant == "warning" else "✖"
        icon_color = Colors.YELLOW if variant == "warning" else Colors.RED
        print(
            color(icon, icon_color, Colors.BOLD)
            + color(f" {title}", Colors.BOLD),
            file=out,
        )
        print(color(f"  {detail}.", Colors.DIM), file=out)
        print(
            color("  → Renove em ", Colors.DIM) + color(portal, Colors.CYAN),
            file=out,
        )
        return

    print(f"{title}: {detail}.", file=out)
    print(f"Renove em {portal}", file=out)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _me_access_level(me: Dict[str, Any]) -> str:
    return str(me.get("accessLevel") or "").strip().lower()


def _subscription_warning(me: Dict[str, Any]) -> str:
    warning = me.get("subscriptionWarning")
    if isinstance(warning, str):
        return warning.strip()
    if isinstance(warning, Mapping):
        return _first_text(
            warning.get("message"),
            warning.get("description"),
            warning.get("reason"),
        )
    return ""


def _coerce_model_id_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, Mapping):
            mid = _first_text(item.get("id"), item.get("model"), item.get("slug"))
            if mid:
                out.append(mid)
    return out


def _plan_hints_from_me(me: Dict[str, Any]) -> Dict[str, Any]:
    """Extract billing/plan fields from ``/me`` for the model picker."""
    if not isinstance(me, dict):
        me = {}
    billing = _mapping_value(me.get("billing"))
    plan = _mapping_value(me.get("plan"))
    unavailable = (
        me.get("unavailableModels")
        or me.get("unavailable_models")
        or billing.get("unavailableModels")
        or billing.get("unavailable_models")
        or plan.get("unavailableModels")
        or plan.get("unavailable_models")
        or me.get("lockedModels")
        or me.get("locked_models")
    )
    portal = _first_text(
        me.get("portalUrl"),
        me.get("portal_url"),
        billing.get("portalUrl"),
        billing.get("portal_url"),
        plan.get("portalUrl"),
        plan.get("portal_url"),
    )
    return {
        "unavailable_models": _coerce_model_id_list(unavailable),
        "portal_url": portal or "https://ector.cc",
    }


def get_identity_plan_hints() -> Dict[str, Any]:
    """Return cached plan hints from ``identity.json`` (no network I/O)."""
    state = _read_store() or {}
    models = state.get("unavailable_models")
    if not isinstance(models, list):
        models = []
    portal = str(state.get("portal_url") or "").strip() or "https://ector.cc"
    return {
        "unavailable_models": [str(m).strip() for m in models if str(m).strip()],
        "portal_url": portal,
    }


def identity_model_picker_kwargs() -> Dict[str, Any]:
    """Kwargs for :func:`ector_cli.auth._prompt_model_selection` from identity cache."""
    hints = get_identity_plan_hints()
    unavailable = hints.get("unavailable_models") or []
    return {
        "unavailable_models": unavailable or None,
        "portal_url": hints.get("portal_url") or "https://ector.cc",
    }


def _assert_agent_access(me: Dict[str, Any]) -> None:
    access_level = _me_access_level(me)
    if access_level == "blocked":
        raise IdentityAuthError(
            str(me.get("message") or "Nenhuma assinatura ativa encontrada.").strip(),
            code=str(me.get("error") or "subscription_required").strip().lower(),
            access_level=access_level,
            payload=me,
        )


def _write_me_state(me: Dict[str, Any], *, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    profile = _me_payload_to_profile(me)
    state = dict(fallback or {})
    state["user_id"] = profile.get("user_id") or str(state.get("user_id") or "")
    state["email"] = profile.get("email") or str(state.get("email") or "")
    state["access_level"] = _me_access_level(me)
    state["subscription_warning"] = _subscription_warning(me)
    plan_hints = _plan_hints_from_me(me)
    state["unavailable_models"] = plan_hints["unavailable_models"]
    state["portal_url"] = plan_hints["portal_url"]
    state["last_me_check_at"] = datetime.now(timezone.utc).isoformat()
    _write_store(state)
    return state


# ---------------------------------------------------------------------------
# User profile sync (config.yaml ``user.*``)
# ---------------------------------------------------------------------------

# Keys we mirror from /agent/auth/me into ~/.ector/config.yaml under
# ``user.*``. Listed here (not implicit) so the contract is explicit and
# tests can assert the surface.
USER_PROFILE_CONFIG_KEYS: Tuple[str, ...] = (
    "user_id",
    "email",
    "nickname",
    "personality",
    "personality_description",
    "behavior",
    "behavior_description",
    "custom_instructions",
    "timezone",
)


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif value is not None and not isinstance(value, (Mapping, list, tuple, set)):
            text = str(value).strip()
            if text:
                return text
    return ""


def _preference_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return _first_text(
            value.get("name"),
            value.get("slug"),
            value.get("id"),
            value.get("key"),
            value.get("value"),
            value.get("label"),
            value.get("title"),
        )
    return _first_text(value)


def _preference_description(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return _first_text(
        value.get("description"),
        value.get("desc"),
        value.get("details"),
        value.get("detail"),
    )


def _me_payload_to_profile(me: Dict[str, Any]) -> Dict[str, str]:
    """Project a raw ``/agent/auth/me`` JSON payload onto our config keys.

    The backend uses camelCase; the config uses snake_case to match the
    rest of ``DEFAULT_CONFIG``. Missing fields collapse to empty strings
    so the previous values (if any) are still overwritten cleanly.
    """
    if not isinstance(me, dict):
        me = {}
    preferences = _mapping_value(me.get("preferences"))
    user = _mapping_value(me.get("user"))
    profile = _mapping_value(me.get("profile"))
    personality_value = _first_text(
        me.get("personality"),
        preferences.get("personality"),
        profile.get("personality"),
    )
    behavior_value = _first_text(
        me.get("behavior"),
        preferences.get("behavior"),
        profile.get("behavior"),
    )
    if not personality_value:
        personality_value = _preference_name(preferences.get("personality"))
    if not behavior_value:
        behavior_value = _preference_name(preferences.get("behavior"))
    return {
        "user_id": _first_text(
            me.get("userId"),
            me.get("user_id"),
            me.get("id"),
            user.get("id"),
            profile.get("userId"),
            profile.get("user_id"),
        ),
        "email": _first_text(me.get("email"), user.get("email"), profile.get("email")),
        "nickname": _first_text(
            me.get("nickname"),
            me.get("name"),
            preferences.get("nickname"),
            preferences.get("name"),
            user.get("nickname"),
            user.get("name"),
            profile.get("nickname"),
            profile.get("name"),
        ),
        "personality": personality_value,
        "personality_description": _first_text(
            me.get("personalityDescription"),
            me.get("personality_description"),
            preferences.get("personalityDescription"),
            preferences.get("personality_description"),
            _preference_description(preferences.get("personality")),
        ),
        "behavior": behavior_value,
        "behavior_description": _first_text(
            me.get("behaviorDescription"),
            me.get("behavior_description"),
            preferences.get("behaviorDescription"),
            preferences.get("behavior_description"),
            _preference_description(preferences.get("behavior")),
        ),
        "custom_instructions": _first_text(
            me.get("customInstructions"),
            me.get("custom_instructions"),
            preferences.get("customInstructions"),
            preferences.get("custom_instructions"),
        ),
        "timezone": _first_text(
            me.get("timezone"),
            preferences.get("timezone"),
        ),
    }


def _sync_user_profile_to_config(me: Dict[str, Any]) -> None:
    """Write the ``user.*`` block in ``config.yaml`` from a /me payload.

    Best-effort: identity auth must never fail because the config writer
    couldn't acquire a lock or the YAML parser tripped on user edits.
    """
    profile = _me_payload_to_profile(me)
    try:
        from ector_cli.config import load_config, save_config
    except Exception:
        logger.debug("identity_auth: cannot import config helpers", exc_info=True)
        return
    try:
        cfg = load_config()
        if not isinstance(cfg, dict):
            cfg = {}
        block = cfg.get("user")
        if not isinstance(block, dict):
            block = {}
            cfg["user"] = block
        for key in USER_PROFILE_CONFIG_KEYS:
            block[key] = profile.get(key, "")
        cloud_tz = (profile.get("timezone") or "").strip()
        if cloud_tz:
            cfg["timezone"] = cloud_tz
        save_config(cfg)
    except Exception:
        logger.debug(
            "identity_auth: failed to sync user profile to config.yaml",
            exc_info=True,
        )


def _clear_user_profile_in_config() -> None:
    """Reset the ``user.*`` block in ``config.yaml`` to empty strings.

    Called on ``logout()``. Best-effort: never raises.
    """
    try:
        from ector_cli.config import load_config, save_config
    except Exception:
        logger.debug("identity_auth: cannot import config helpers", exc_info=True)
        return
    try:
        cfg = load_config()
        if not isinstance(cfg, dict):
            return
        block = cfg.get("user")
        if not isinstance(block, dict):
            return
        had_value = any(str(block.get(key) or "").strip() for key in USER_PROFILE_CONFIG_KEYS)
        if not had_value:
            return
        for key in USER_PROFILE_CONFIG_KEYS:
            block[key] = ""
        save_config(cfg)
    except Exception:
        logger.debug(
            "identity_auth: failed to clear user profile in config.yaml",
            exc_info=True,
        )


def get_user_profile() -> Dict[str, str]:
    """Return the persisted ``user.*`` block, or empty strings.

    Convenience accessor for the prompt builder so it doesn't have to
    know the config key layout.
    """
    try:
        from ector_cli.config import load_config
    except Exception:
        return {key: "" for key in USER_PROFILE_CONFIG_KEYS}
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    block = cfg.get("user") if isinstance(cfg, dict) else None
    if not isinstance(block, dict):
        return {key: "" for key in USER_PROFILE_CONFIG_KEYS}
    return {key: str(block.get(key) or "").strip() for key in USER_PROFILE_CONFIG_KEYS}


def resolve_preferred_user_display_name(
    platform_user_name: str | None = None,
    *,
    use_profile: bool = True,
) -> str | None:
    """Name to use when addressing the user in prompts and memory scoping.

    Prefer ``config.user.nickname`` (ector.cc / dashboard / TUI profile) over
    the messaging-platform display name (e.g. WhatsApp push name) when
    *use_profile* is true.
    """
    if use_profile:
        nickname = (get_user_profile().get("nickname") or "").strip()
        if nickname:
            return nickname
    trimmed = (platform_user_name or "").strip()
    return trimmed or None


# ---------------------------------------------------------------------------
# Local callback HTTP server
# ---------------------------------------------------------------------------

# Layout alinhado à identidade visual de ector.cc:
#   - paleta: fundo #05050a, cartão #0a0a18, accent ciano #06b6d4 →
#     hover #67e8f9, gradient ciano→azul (#06b6d4 → #3b82f6);
#   - tipografia: stack do sistema (Geist quando disponível), tracking
#     justo no headline e tamanho confortável no corpo;
#   - efeitos: glow ciano sutil (box-shadow), partículas decorativas
#     puramente em CSS (sem JS) e check-mark animado.
#
# Mantemos tudo inline (sem assets remotos) para que a página continue
# renderizando offline e sem flash de fonte. Usamos chaves duplicadas
# ``{{`` / ``}}`` no ``.format()`` para escapar os blocos CSS que
# precisam de chaves literais.
_CALLBACK_BASE_STYLE = """\
*,*::before,*::after {{ box-sizing:border-box; }}
:root {{
  --bg:#05050a; --surface:#0a0a18; --text:#f1f0ff; --muted:#a5a0c0;
  --accent:#06b6d4; --accent-hi:#67e8f9; --accent-2:#3b82f6;
  --danger:#ef4444; --danger-soft:#f87171;
  --border:rgba(6,182,212,0.18); --border-soft:rgba(6,182,212,0.10);
  --glow:rgba(6,182,212,0.25);
}}
html,body {{ height:100%; }}
body {{
  margin:0; min-height:100vh; background:var(--bg); color:var(--text);
  font-family: "Geist", -apple-system, BlinkMacSystemFont, "Segoe UI",
               system-ui, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale;
  display:flex; align-items:center; justify-content:center; padding:24px;
  position:relative; overflow:hidden;
}}
.bg-orb {{
  position:absolute; border-radius:9999px; filter:blur(80px);
  pointer-events:none; opacity:0.55;
}}
.bg-orb.cyan  {{ top:-120px; right:-80px;  width:340px; height:340px;
                 background:radial-gradient(circle, #06b6d4 0%, transparent 60%); }}
.bg-orb.blue  {{ bottom:-140px; left:-100px; width:380px; height:380px;
                 background:radial-gradient(circle, #3b82f6 0%, transparent 60%); }}
.particles {{ position:absolute; inset:0; pointer-events:none; }}
.particle {{
  position:absolute; width:3px; height:3px; border-radius:9999px;
  background:#06b6d4; opacity:0.35;
  animation: float 14s ease-in-out infinite;
}}
.particle:nth-child(1) {{ top:18%; left:12%; animation-delay:0s;  }}
.particle:nth-child(2) {{ top:32%; left:78%; animation-delay:2s;  background:#67e8f9; }}
.particle:nth-child(3) {{ top:64%; left:22%; animation-delay:4s;  }}
.particle:nth-child(4) {{ top:74%; left:68%; animation-delay:6s;  background:#3b82f6; }}
.particle:nth-child(5) {{ top:46%; left:50%; animation-delay:8s;  background:#67e8f9; }}
.particle:nth-child(6) {{ top:88%; left:42%; animation-delay:10s; }}
@keyframes float {{
  0%,100% {{ transform:translateY(0)    scale(1);   opacity:0.20; }}
  50%     {{ transform:translateY(-22px) scale(1.4); opacity:0.55; }}
}}
.card {{
  position:relative; z-index:1; background:rgba(10,10,24,0.85);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  border:1px solid var(--border); border-radius:20px;
  padding:48px 44px; max-width:480px; width:100%; text-align:center;
  box-shadow: 0 24px 80px rgba(0,0,0,0.55),
              0 0 0 1px rgba(6,182,212,0.06),
              0 0 64px -16px var(--glow);
  animation: rise 0.5s cubic-bezier(0.16,1,0.3,1) both;
}}
@keyframes rise {{
  from {{ opacity:0; transform:translateY(12px); }}
  to   {{ opacity:1; transform:translateY(0);    }}
}}
.brand {{
  display:inline-flex; align-items:center; gap:8px;
  font-size:12px; font-weight:600; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--accent-hi);
  background:rgba(6,182,212,0.08); border:1px solid var(--border-soft);
  padding:6px 12px; border-radius:9999px; margin-bottom:24px;
}}
.brand .dot {{
  width:6px; height:6px; border-radius:9999px; background:var(--accent);
  box-shadow:0 0 8px var(--accent);
  animation: pulse 1.8s ease-in-out infinite;
}}
@keyframes pulse {{
  0%,100% {{ opacity:1;   transform:scale(1);   }}
  50%     {{ opacity:0.55; transform:scale(0.85); }}
}}
.icon {{
  width:72px; height:72px; margin:0 auto 20px; border-radius:9999px;
  display:flex; align-items:center; justify-content:center;
  background:linear-gradient(135deg, rgba(6,182,212,0.18) 0%, rgba(59,130,246,0.18) 100%);
  border:1px solid var(--border); box-shadow:0 0 32px -8px var(--glow);
}}
.icon svg {{ width:32px; height:32px; }}
.icon.success svg {{ stroke:var(--accent-hi); }}
.icon.error   svg {{ stroke:var(--danger-soft); }}
.icon.error   {{ background:linear-gradient(135deg, rgba(239,68,68,0.16) 0%, rgba(239,68,68,0.06) 100%);
                 border-color:rgba(239,68,68,0.30);
                 box-shadow:0 0 32px -8px rgba(239,68,68,0.32); }}
h1 {{
  margin:0 0 10px; font-size:1.6rem; font-weight:700; letter-spacing:-0.01em;
  background:linear-gradient(90deg, #f1f0ff 0%, #67e8f9 60%, #3b82f6 100%);
  -webkit-background-clip:text; background-clip:text; color:transparent;
}}
h1.error {{ background:linear-gradient(90deg, #f1f0ff 0%, #f87171 100%);
            -webkit-background-clip:text; background-clip:text; color:transparent; }}
p {{ margin:6px 0; color:var(--muted); line-height:1.6; font-size:0.95rem; }}
.email {{
  color:var(--text); font-weight:600;
  background:rgba(6,182,212,0.10); border:1px solid var(--border-soft);
  padding:2px 10px; border-radius:8px; font-size:0.95rem;
  font-family:"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  /* h1 usa background-clip:text + color:transparent para o gradient;
     resetamos aqui para que o chip do email continue sólido. */
  -webkit-text-fill-color: var(--text);
  -webkit-background-clip: padding-box;
          background-clip: padding-box;
  vertical-align: 2px;
}}
.hint {{
  margin-top:24px; padding-top:20px; border-top:1px solid var(--border-soft);
  font-size:0.82rem; color:var(--muted);
}}
.hint kbd {{
  font-family:"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:0.78rem; color:var(--accent-hi);
  background:rgba(6,182,212,0.10); border:1px solid var(--border-soft);
  padding:2px 6px; border-radius:6px;
}}
@media (prefers-reduced-motion: reduce) {{
  .card, .particle, .brand .dot {{ animation:none; }}
}}
"""

_CALLBACK_DECOR = """\
<div class="bg-orb cyan"  aria-hidden="true"></div>
<div class="bg-orb blue"  aria-hidden="true"></div>
<div class="particles" aria-hidden="true">
  <span class="particle"></span><span class="particle"></span><span class="particle"></span>
  <span class="particle"></span><span class="particle"></span><span class="particle"></span>
</div>
"""

_CALLBACK_SUCCESS_HTML = (
    """\
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ector — Sessão ativa</title>
  <style>"""
    + _CALLBACK_BASE_STYLE
    + """</style>
</head>
<body>
"""
    + _CALLBACK_DECOR
    + """\
  <main class="card" role="status" aria-live="polite">
    <div class="icon success" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2.4"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M20 6L9 17l-5-5"/>
      </svg>
    </div>
    <h1>Olá {greeting}!</h1>
    <p>Sua sessão Ector está ativa.</p>
    <div class="hint">Pode fechar esta aba e voltar para o terminal.</div>
  </main>
</body>
</html>
"""
)

_CALLBACK_ERROR_HTML = (
    """\
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ector — Falha no login</title>
  <style>"""
    + _CALLBACK_BASE_STYLE
    + """</style>
</head>
<body>
"""
    + _CALLBACK_DECOR
    + """\
  <main class="card" role="alert">
    <div class="brand"><span class="dot"></span>Ector</div>
    <div class="icon error" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2.4"
           stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="9"/>
        <path d="M12 8v5"/>
        <circle cx="12" cy="16.5" r="0.6" fill="currentColor" stroke="none"/>
      </svg>
    </div>
    <h1 class="error">Falha no login</h1>
    <p>{message}</p>
    <div class="hint">Volte ao terminal e rode <kbd>ector login</kbd> novamente.</div>
  </main>
</body>
</html>
"""
)


def _bind_free_port(host: str) -> Tuple[socket.socket, int]:
    """Bind a TCP socket to ``(host, 0)`` and return ``(sock, port)``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    return sock, port


def _make_callback_handler(
    expected_state: str,
    sink: Dict[str, Any],
    base_url: str,
) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            params = parse_qs(parsed.query)
            error = (params.get("error", [None])[0] or "").strip()
            if error:
                description = (params.get("error_description", [None])[0] or error).strip()
                sink["error"] = description
                self._send_html(400, _CALLBACK_ERROR_HTML.format(message=description))
                return


            # CSRF state: always sent on /agent/auth and required on callback.
            state = (params.get("state", [None])[0] or "").strip()
            if expected_state:
                if not state:
                    sink["error"] = "missing state in callback"
                    self._send_html(
                        400,
                        _CALLBACK_ERROR_HTML.format(
                            message="resposta sem parâmetro state",
                        ),
                    )
                    return
                if state != expected_state:
                    sink["error"] = "state mismatch"
                    self._send_html(400, _CALLBACK_ERROR_HTML.format(message="state CSRF mismatch"))
                    return

            code = (params.get("code", [None])[0] or "").strip()
            if code:
                if not base_url:
                    sink["error"] = "code exchange requires auth base_url"
                    self._send_html(
                        400,
                        _CALLBACK_ERROR_HTML.format(message="exchange indisponível"),
                    )
                    return
                try:
                    exchanged = _exchange_cli_oauth_code(
                        base_url,
                        code=code,
                        state=state or expected_state,
                    )
                except IdentityAuthError as exc:
                    sink["error"] = str(exc)
                    self._send_html(
                        400,
                        _CALLBACK_ERROR_HTML.format(message=str(exc)),
                    )
                    return
                sink.update(exchanged)
            else:
                access = (params.get("access_token", [None])[0] or "").strip()
                refresh = (params.get("refresh_token", [None])[0] or "").strip()
                expires_in = (params.get("expires_in", [None])[0] or "").strip()
                user_id = (params.get("user_id", [None])[0] or "").strip()
                email = (params.get("email", [None])[0] or "").strip()

                if not access or not refresh or not user_id:
                    sink["error"] = "missing tokens in callback"
                    self._send_html(
                        400,
                        _CALLBACK_ERROR_HTML.format(message="resposta sem tokens"),
                    )
                    return

                sink["access_token"] = access
                sink["refresh_token"] = refresh
                sink["expires_in"] = _coerce_int(expires_in, 3600)
                sink["user_id"] = user_id
                sink["email"] = email

            # Best-effort: pega o ``nickname`` direto do /me para
            # personalizar a saudação na página. Mantemos o timeout curto
            # (4s) para não atrasar a UX caso o backend esteja lento, e
            # cacheamos o payload no sink para que ``_persist_login_result``
            # reaproveite sem precisar bater no /me uma segunda vez.
            # ``base_url=""`` desativa o probe — útil em testes unitários
            # do handler que não querem latência de rede.
            nickname = ""
            me_payload: Dict[str, Any] = {}
            if base_url:
                try:
                    with _http_client(timeout=4.0) as client:
                        me_resp = client.get(
                            f"{base_url}/agent/auth/me",
                            headers={"Authorization": f"Bearer {access}"},
                        )
                    if me_resp.status_code == 200:
                        me_payload = _safe_json(me_resp)
                        nickname = str(me_payload.get("nickname") or "").strip()
                except Exception:
                    logger.debug(
                        "identity_auth: nickname probe in callback handler failed",
                        exc_info=True,
                    )

            sink["nickname"] = nickname
            sink["me_payload"] = me_payload

            greeting = nickname or email or "tudo certo"
            self._send_html(200, _CALLBACK_SUCCESS_HTML.format(greeting=greeting))

        def _send_html(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return _Handler


def _tokens_from_exchange_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize token fields from ``/agent/auth/cli/exchange`` or legacy callback."""
    access = _first_text(data.get("accessToken"), data.get("access_token"))
    refresh = _first_text(data.get("refreshToken"), data.get("refresh_token"))
    user_id = _first_text(data.get("userId"), data.get("user_id"))
    email = _first_text(data.get("email"))
    expires_in = _coerce_int(
        data.get("expiresIn", data.get("expires_in")),
        3600,
    )
    if not (access and refresh and user_id):
        raise IdentityAuthError(
            "Resposta de exchange sem tokens completos.",
            code="exchange_incomplete",
            payload=data,
        )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "user_id": user_id,
        "email": email,
    }


def _exchange_cli_oauth_code(
    base_url: str,
    *,
    code: str,
    state: str,
) -> Dict[str, Any]:
    """Exchange a short-lived CLI OAuth ``code`` for tokens (preferred over query tokens)."""
    if not base_url.strip():
        raise IdentityAuthError(
            "Exchange OAuth requer base_url configurada.",
            code="exchange_no_base_url",
        )
    url = f"{base_url.rstrip('/')}/agent/auth/cli/exchange"
    try:
        with _http_client() as client:
            response = client.post(
                url,
                json={"code": code, "state": state},
            )
    except httpx.HTTPError as exc:
        raise IdentityAuthError(
            f"Falha de rede no exchange OAuth: {exc}",
            code="exchange_network_error",
        ) from exc
    if not _http_ok(response.status_code):
        payload = _safe_json(response)
        message = _first_text(
            payload.get("message"),
            payload.get("error"),
        ) or f"Exchange OAuth falhou com HTTP {response.status_code}."
        raise IdentityAuthError(
            message,
            code=str(payload.get("error") or "exchange_failed").strip().lower(),
            payload=payload,
        )
    return _tokens_from_exchange_payload(_safe_json(response))


def _wait_for_callback(
    sock: socket.socket,
    host: str,
    port: int,
    expected_state: str,
    timeout_seconds: float,
    base_url: str,
) -> Dict[str, Any]:
    sink: Dict[str, Any] = {}
    handler_cls = _make_callback_handler(expected_state, sink, base_url)

    server = HTTPServer.__new__(HTTPServer)
    HTTPServer.__init__(server, (host, port), handler_cls, bind_and_activate=False)
    server.socket = sock
    server.server_address = sock.getsockname()

    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.1},
        daemon=True,
    )
    thread.start()

    deadline = time.time() + max(5.0, timeout_seconds)
    cancelled = False
    try:
        try:
            while time.time() < deadline:
                if sink.get("access_token") or sink.get("error"):
                    return sink
                time.sleep(0.1)
        except KeyboardInterrupt:
            # Usuário apertou Ctrl+C enquanto esperávamos o callback.
            # Sai limpo e propaga como ``IdentityAuthError`` para o caller
            # imprimir uma linha amigável em vez de um traceback.
            cancelled = True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)

    if cancelled:
        raise IdentityAuthError(
            "Login cancelado pelo usuário.",
            code="user_cancelled",
        )

    raise IdentityAuthError(
        "O navegador não retornou em tempo. Tente novamente com `ector login`.",
        code="callback_timeout",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_persisted_session() -> Optional[IdentitySession]:
    """Read the persisted session from disk, without any network I/O."""
    state = _read_store()
    if not state:
        return None
    return _store_to_session(state)


def is_logged_in() -> bool:
    """True when a refresh-capable session is present (env or disk)."""
    if _env_token_override() is not None:
        return True
    return get_persisted_session() is not None


def _post_device_start(base_url: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/agent/auth/device/start"
    try:
        with _http_client() as client:
            response = client.post(url)
    except httpx.HTTPError as exc:
        raise IdentityAuthError(
            REMOTE_LOGIN_FAILURE_MESSAGE,
            code="device_start_failed",
        ) from exc
    if response.status_code == 429:
        raise IdentityAuthError(
            "Muitas tentativas de iniciar login. Aguarde cerca de 1 minuto e execute `ector login --device` novamente.",
            code="rate_limited",
        )
    if not _http_ok(response.status_code):
        payload = _safe_json(response)
        raise IdentityAuthError(
            REMOTE_LOGIN_FAILURE_MESSAGE,
            code="device_start_failed",
            payload=payload,
        )
    payload = _safe_json(response)
    device_code = _first_text(payload.get("deviceCode"), payload.get("device_code"))
    user_code = _first_text(payload.get("userCode"), payload.get("user_code"))
    verification_uri = _first_text(payload.get("verificationUri"), payload.get("verification_uri"))
    if not device_code or not verification_uri:
        raise IdentityAuthError(
            REMOTE_LOGIN_FAILURE_MESSAGE,
            code="device_start_failed",
            relogin_required=True,
        )
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": verification_uri,
        "interval": _coerce_int(payload.get("interval"), DEFAULT_DEVICE_POLL_INTERVAL_SECONDS),
        "expires_in": _coerce_int(payload.get("expiresIn", payload.get("expires_in")), DEFAULT_DEVICE_TIMEOUT_SECONDS),
    }


def _post_device_poll(base_url: str, device_code: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/agent/auth/device/poll"
    try:
        with _http_client() as client:
            response = client.post(url, json={"deviceCode": device_code})
    except httpx.HTTPError as exc:
        raise IdentityAuthError(
            f"Falha de rede ao aguardar autorização: {exc}",
            code="network_error",
        ) from exc
    if response.status_code == 429:
        return {"status": "rate_limited"}
    if response.status_code == 410:
        payload = _safe_json(response)
        message = _first_text(payload.get("message")) or "Autorização expirada. Execute `ector login` novamente."
        raise IdentityAuthError(message, code="expired", relogin_required=True, payload=payload)
    if response.status_code == 401:
        raise IdentityAuthError(
            "Código de dispositivo inválido. Execute `ector login` novamente.",
            code="invalid_device_code",
            relogin_required=True,
        )
    if not _http_ok(response.status_code):
        payload = _safe_json(response)
        message = _first_text(payload.get("message"), payload.get("error")) or (
            f"Polling falhou com HTTP {response.status_code}."
        )
        raise IdentityAuthError(message, code="device_poll_failed", payload=payload)
    return _safe_json(response)


def login_device_code(
    *,
    open_browser: bool = True,
    timeout_seconds: Optional[float] = None,
) -> IdentitySession:
    """Device authorization grant — login sem callback em 127.0.0.1 (SSH/headless)."""
    base_url = get_auth_base_url()
    timeout = float(
        timeout_seconds
        if timeout_seconds is not None
        else _get_int_setting("device_timeout_seconds", DEFAULT_DEVICE_TIMEOUT_SECONDS)
    )
    started = _post_device_start(base_url)
    device_code = started["device_code"]
    user_code = started.get("user_code") or ""
    verification_uri = started["verification_uri"]
    interval = max(2, int(started.get("interval") or DEFAULT_DEVICE_POLL_INTERVAL_SECONDS))

    if user_code and "user_code=" not in verification_uri:
        sep = "&" if "?" in verification_uri else "?"
        verification_uri = f"{verification_uri}{sep}user_code={user_code}"

    print(
        color("✦ Ector", Colors.CYAN, Colors.BOLD)
        + color("  ·  login remoto (device code)", Colors.DIM),
        file=sys.stderr,
    )
    if user_code:
        print(
            color("→", Colors.CYAN)
            + " No navegador (qualquer máquina), abra o link e confirme o código:",
            file=sys.stderr,
        )
        print("  " + color(verification_uri, Colors.CYAN), file=sys.stderr)
        print(
            color("  Código: ", Colors.DIM)
            + color(user_code, Colors.CYAN, Colors.BOLD),
            file=sys.stderr,
        )
    else:
        print(
            color("→", Colors.CYAN)
            + " Abra esta URL no navegador para autorizar a CLI:",
            file=sys.stderr,
        )
        print("  " + color(verification_uri, Colors.CYAN), file=sys.stderr)

    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(verification_uri, new=1, autoraise=True)

    print(color("  Aguardando autorização no site…", Colors.DIM), file=sys.stderr)

    deadline = time.time() + max(30.0, timeout)
    rate_limit_waits = 0
    try:
        while time.time() < deadline:
            payload = _post_device_poll(base_url, device_code)
            status = str(payload.get("status") or "").strip().lower()
            if status == "rate_limited":
                rate_limit_waits += 1
                if rate_limit_waits > 24:
                    raise IdentityAuthError(
                        "Servidor ocupado (limite de consultas). Aguarde 1–2 minutos e execute `ector login --device` novamente.",
                        code="rate_limited",
                    )
                wait = min(float(interval) * (1 + min(rate_limit_waits, 6)), 45.0)
                print(
                    color(
                        f"  Limite temporário — nova tentativa em {int(wait)}s…",
                        Colors.DIM,
                    ),
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            if status == "pending":
                time.sleep(interval)
                continue
            if status == "authorized":
                access = _first_text(payload.get("accessToken"), payload.get("access_token"))
                refresh = _first_text(payload.get("refreshToken"), payload.get("refresh_token"))
                user_id = _first_text(payload.get("userId"), payload.get("user_id"))
                email = _first_text(payload.get("email"))
                expires_in = _coerce_int(payload.get("expiresIn", payload.get("expires_in")), 3600)
                if not (access and refresh and user_id):
                    raise IdentityAuthError(
                        "Resposta de autorização incompleta.",
                        code="invalid_response",
                        relogin_required=True,
                    )
                return _persist_login_result(
                    {
                        "access_token": access,
                        "refresh_token": refresh,
                        "expires_in": expires_in,
                        "user_id": user_id,
                        "email": email,
                    },
                    base_url=base_url,
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        raise IdentityAuthError(
            "Login cancelado pelo usuário.",
            code="user_cancelled",
        ) from None

    raise IdentityAuthError(
        REMOTE_LOGIN_FAILURE_MESSAGE,
        code="device_timeout",
    )


def login_loopback(
    *,
    prefer_browser: bool = True,
    open_browser: bool = True,
    timeout_seconds: Optional[float] = None,
    callback_host: Optional[str] = None,
) -> IdentitySession:
    """OAuth da CLI com callback em ``127.0.0.1`` (máquina local com browser)."""
    base_url = get_auth_base_url()
    host = (callback_host or _load_auth_config().get("callback_host") or DEFAULT_CALLBACK_HOST).strip()
    timeout = float(
        timeout_seconds
        if timeout_seconds is not None
        else _get_int_setting("callback_timeout_seconds", DEFAULT_CALLBACK_TIMEOUT_SECONDS)
    )

    sock, port = _bind_free_port(host)
    state = secrets.token_urlsafe(24)

    oauth_params = {
        "source": "cli",
        "cli_port": str(port),
        "state": state,
        "cli_ua": _build_cli_user_agent(),
    }
    oauth_params.update(cli_oauth_query_params())
    get_or_create_install_id()
    auth_url = f"{base_url}/agent/auth?" + urlencode(oauth_params)

    opened = False
    if prefer_browser and open_browser:
        try:
            opened = bool(webbrowser.open(auth_url, new=1, autoraise=True))
        except Exception:
            opened = False

    # Compact branded header — ciano accent + tagline em DIM. Casa com a
    # paleta do site (#06b6d4 → #00D1FF no TUI) e com o banner usado no
    # ``ector setup``.
    print(
        color("✦ Ector", Colors.CYAN, Colors.BOLD)
        + color("  ·  identifique-se para continuar", Colors.DIM),
        file=sys.stderr,
    )
    if opened:
        print(
            color("→", Colors.CYAN)
            + " Abrindo o navegador para você fazer login…",
            file=sys.stderr,
        )
    else:
        print(
            color("→", Colors.CYAN)
            + " Abra esta URL no navegador para fazer login:",
            file=sys.stderr,
        )
        print("  " + color(auth_url, Colors.CYAN), file=sys.stderr)
    print(color("  Aguardando resposta…", Colors.DIM), file=sys.stderr)

    try:
        result = _wait_for_callback(sock, host, port, state, timeout, base_url)
    except IdentityAuthError:
        with contextlib.suppress(OSError):
            sock.close()
        raise

    if result.get("error"):
        raise IdentityAuthError(
            f"Login falhou: {result['error']}",
            code="callback_error",
        )

    return _persist_login_result(result, base_url=base_url)


def login(
    *,
    prefer_browser: bool = True,
    open_browser: bool = True,
    timeout_seconds: Optional[float] = None,
    callback_host: Optional[str] = None,
    force_device: bool = False,
    force_local: bool = False,
) -> IdentitySession:
    """Login da identidade Ector — loopback local ou device code (SSH)."""
    mode = resolve_login_mode(force_device=force_device, force_local=force_local)
    if mode == "device":
        return login_device_code(open_browser=open_browser, timeout_seconds=timeout_seconds)
    return login_loopback(
        prefer_browser=prefer_browser,
        open_browser=open_browser,
        timeout_seconds=timeout_seconds,
        callback_host=callback_host,
    )


def _persist_login_result(result: Dict[str, Any], *, base_url: str) -> IdentitySession:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_coerce_int(result.get("expires_in"), 3600))
    state = {
        "version": IDENTITY_STORE_VERSION,
        "access_token": str(result["access_token"]),
        "refresh_token": str(result["refresh_token"]),
        "expires_at": expires_at.isoformat(),
        "user_id": str(result["user_id"]),
        "email": str(result.get("email") or ""),
        "base_url": base_url,
        "obtained_at": now.isoformat(),
        "last_me_check_at": now.isoformat(),
    }
    with _identity_store_lock():
        _write_store(state)
    session = _store_to_session(state)
    if session is None:
        raise IdentityAuthError(
            "Estado de identidade inválido após login.",
            code="internal_error",
        )

    register_device_with_api(base_url=base_url, access_token=session.access_token)

    # Fetch the full profile from /me right after login so the user's
    # nickname / personality / behavior land in config.yaml immediately
    # — without waiting for the next ``whoami`` cache miss. The callback
    # only carries (access_token, refresh_token, user_id, email).
    #
    # Reaproveita o payload buscado pelo handler do callback (best-effort,
    # já feito sob bandeira de timeout curto antes de renderizar a página)
    # quando disponível, evitando um segundo round-trip a /me.
    nickname = str(result.get("nickname") or "").strip()
    cached_payload = result.get("me_payload")
    me_payload: Dict[str, Any] = cached_payload if isinstance(cached_payload, dict) else {}
    needs_remote_me = not (isinstance(cached_payload, dict) and cached_payload)
    access_warning = ""

    if needs_remote_me:
        try:
            me_payload = _get_me(base_url, session.access_token)
        except IdentityAuthError as exc:
            if exc.access_level == "blocked":
                access_warning = str(exc).strip()
                with _identity_store_lock():
                    persisted = _read_store() or state
                    persisted["access_level"] = "blocked"
                    persisted["subscription_warning"] = access_warning
                    persisted["last_me_check_at"] = datetime.now(timezone.utc).isoformat()
                    _write_store(persisted)
            else:
                logger.warning(
                    "identity_auth: post-login /me probe failed (%s); profile fields "
                    "will be synced on the next whoami() call",
                    exc,
                )
            me_payload = {}
        except Exception:
            logger.debug("identity_auth: unexpected error during post-login /me", exc_info=True)
            me_payload = {}

    if me_payload:
        try:
            _assert_agent_access(me_payload)
        except IdentityAuthError as exc:
            access_warning = str(exc).strip()
        _sync_user_profile_to_config(me_payload)
        # Prefere o nickname já capturado pelo handler; fallback para o
        # payload (caso a página venha de outro fluxo no futuro).
        nickname = nickname or str(me_payload.get("nickname") or "").strip()
        # Keep identity.json in sync with the freshly fetched email/userId.
        with _identity_store_lock():
            persisted = _read_store() or state
            persisted = _write_me_state(me_payload, fallback=persisted)
            session = _store_to_session(persisted) or session

    print(
        color("✓", Colors.GREEN, Colors.BOLD)
        + color(" Login realizado com sucesso.", Colors.BOLD),
        file=sys.stderr,
    )
    if nickname:
        print(
            color("  Olá ", Colors.DIM)
            + color(nickname, Colors.CYAN, Colors.BOLD)
            + color("!", Colors.DIM),
            file=sys.stderr,
        )
    if access_warning:
        print_subscription_blocked_message(
            access_warning,
            variant="warning",
            file=sys.stderr,
        )
    else:
        # Fase 4: onboarding automático da biblioteca em primeiro login e
        # sincronização imediata em background para reduzir fricção inicial.
        try:
            from tools.cloud_skills_sync import (
                ensure_onboarding_skill_in_library,
                schedule_cloud_skills_sync,
            )

            ensure_onboarding_skill_in_library(quiet=True)
            schedule_cloud_skills_sync(quiet=True)
        except Exception:
            logger.debug("identity_auth: post-login cloud skill bootstrap failed", exc_info=True)
    return session


def logout(*, revoke_remote: bool = True) -> bool:
    """Revoke the persisted session.

    Returns ``True`` if there was a session to revoke. Always tries to
    delete the local file (idempotent). The ``user.*`` block in
    ``config.yaml`` (mirrored from /agent/auth/me) is also cleared so
    nickname/personality/behavior don't leak into the next user that
    logs in on the same machine.
    """
    base_url = get_auth_base_url()
    had_session = False
    with _identity_store_lock():
        state = _read_store()
        if state and isinstance(state.get("refresh_token"), str) and state["refresh_token"]:
            had_session = True
            if revoke_remote:
                _post_logout(base_url, state["refresh_token"])
        _clear_store()
    try:
        # Remove apenas skills sincronizadas da biblioteca cloud deste usuário.
        from tools.cloud_skills_sync import clear_cloud_skills_local_state

        clear_cloud_skills_local_state(remove_files=True)
    except Exception:
        logger.debug("identity_auth: failed to clear cloud skills on logout", exc_info=True)
    _clear_user_profile_in_config()
    return had_session


def _refresh_locked(state: Dict[str, Any], *, base_url: str) -> Dict[str, Any]:
    """Refresh and persist, assuming the caller already holds the lock."""
    refreshed = _post_refresh(base_url, state["refresh_token"])
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=refreshed["expires_in"])
    state.update({
        "access_token": refreshed["access_token"],
        "refresh_token": refreshed["refresh_token"],
        "expires_at": expires_at.isoformat(),
        "obtained_at": now.isoformat(),
    })
    _write_store(state)
    return state


def whoami(*, force: bool = False) -> Optional[Dict[str, str]]:
    """Return ``{user_id, email}`` for the current session, or ``None``.

    Cached on disk (``last_me_check_at`` in ``identity.json``) so repeated
    calls within :data:`DEFAULT_ME_CACHE_SECONDS` are local-only. Use
    ``force=True`` to bypass the cache.
    """
    env_session = _env_token_override()
    if env_session is not None:
        return {"user_id": env_session.user_id, "email": env_session.email}

    base_url = get_auth_base_url()
    me_cache = _get_int_setting("me_cache_seconds", DEFAULT_ME_CACHE_SECONDS)
    skew = _get_int_setting("refresh_skew_seconds", DEFAULT_REFRESH_SKEW_SECONDS)

    with _identity_store_lock():
        state = _read_store()
        if not state:
            return None

        if _is_expiring(state, skew):
            try:
                state = _refresh_locked(state, base_url=base_url)
            except IdentityAuthError as exc:
                if exc.relogin_required:
                    _clear_store()
                raise

        last_check = _parse_iso(state.get("last_me_check_at"))
        if not force and last_check is not None:
            age = (datetime.now(timezone.utc) - last_check).total_seconds()
            if age < me_cache:
                return {
                    "user_id": str(state.get("user_id") or ""),
                    "email": str(state.get("email") or ""),
                }

        access_token = str(state["access_token"])

    try:
        me = _get_me(base_url, access_token)
    except IdentityAuthError as exc:
        if exc.relogin_required:
            with _identity_store_lock():
                _clear_store()
            _clear_user_profile_in_config()
        elif exc.access_level == "blocked":
            with _identity_store_lock():
                state = _read_store() or {}
                state["access_level"] = "blocked"
                state["subscription_warning"] = str(exc)
                state["last_me_check_at"] = datetime.now(timezone.utc).isoformat()
                _write_store(state)
        raise

    _assert_agent_access(me)
    profile = _me_payload_to_profile(me)
    user_id = profile.get("user_id", "")
    email = profile.get("email", "")
    if not user_id:
        raise IdentityAuthError(
            "Resposta de /me sem userId.",
            code="invalid_response",
            relogin_required=True,
        )

    with _identity_store_lock():
        state = _read_store() or {}
        _write_me_state(me, fallback=state)

    # Mirror nickname / personality / behavior fields to config.yaml so
    # the prompt builder can read them without re-hitting the backend.
    _sync_user_profile_to_config(me)

    return {"user_id": user_id, "email": email}


def sync_user_profile_from_cloud() -> bool:
    """Best-effort: mirror ector.cc user preferences into ``config.user.*``.

    Called on agent startup so dashboard edits apply without ``ector me``.
    Never raises — callers already validated access.
    """
    env_session = _env_token_override()
    base_url = get_auth_base_url()
    skew = _get_int_setting("refresh_skew_seconds", DEFAULT_REFRESH_SKEW_SECONDS)

    try:
        if env_session is not None:
            if not _env_truthy("ECTOR_IDENTITY_STRICT"):
                return False
            me = _get_me(base_url, env_session.access_token)
            _sync_user_profile_to_config(me)
            return True

        with _identity_store_lock():
            state = _read_store()
            if not state:
                return False
            if _is_expiring(state, skew):
                state = _refresh_locked(state, base_url=base_url)
            access_token = str(state["access_token"])

        me = _get_me(base_url, access_token)
        _sync_user_profile_to_config(me)
        with _identity_store_lock():
            state = _read_store() or {}
            _write_me_state(me, fallback=state)
        return True
    except Exception:
        logger.debug(
            "identity_auth: could not sync user profile from cloud",
            exc_info=True,
        )
        return False


def validate_agent_access(*, force: bool = False) -> Dict[str, str]:
    """Validate ``GET /agent/auth/me`` access fields for agent execution.

    A valid token is not enough: the API can return ``403`` when the user
    is authenticated but lacks an active subscription. Agent-starting
    commands call this gate before launching any expensive/runtime work.
    """
    env_session = _env_token_override()
    if env_session is not None and not _env_truthy("ECTOR_IDENTITY_STRICT"):
        # Headless/CI callers own token provisioning; avoid a surprise network
        # dependency for env-only sessions unless strict validation is requested.
        return {"access_level": "env", "subscription_warning": ""}

    base_url = get_auth_base_url()
    me_cache = _get_int_setting("me_cache_seconds", DEFAULT_ME_CACHE_SECONDS)
    skew = _get_int_setting("refresh_skew_seconds", DEFAULT_REFRESH_SKEW_SECONDS)

    env_session = _env_token_override()
    if env_session is not None and _env_truthy("ECTOR_IDENTITY_STRICT"):
        try:
            me = _get_me(base_url, env_session.access_token)
            _assert_agent_access(me)
        except IdentityAuthError:
            raise
        return {
            "access_level": _me_access_level(me) or "full",
            "subscription_warning": _subscription_warning(me),
        }

    with _identity_store_lock():
        state = _read_store()
        if not state:
            raise IdentityAuthError(
                "Não autenticado. Execute `ector login`.",
                code="not_authenticated",
                relogin_required=True,
            )

        cached_access = str(state.get("access_level") or "").strip().lower()
        last_check = _parse_iso(state.get("last_me_check_at"))
        if not force and cached_access and last_check is not None:
            age = (datetime.now(timezone.utc) - last_check).total_seconds()
            if age < me_cache:
                if cached_access == "blocked":
                    raise IdentityAuthError(
                        str(
                            state.get("subscription_warning")
                            or "Nenhuma assinatura ativa encontrada."
                        ),
                        code="subscription_required",
                        access_level="blocked",
                    )
                return {
                    "access_level": cached_access,
                    "subscription_warning": str(state.get("subscription_warning") or ""),
                }

        if _is_expiring(state, skew):
            try:
                state = _refresh_locked(state, base_url=base_url)
            except IdentityAuthError as exc:
                if exc.relogin_required:
                    _clear_store()
                elif exc.access_level == "blocked":
                    state["access_level"] = "blocked"
                    state["subscription_warning"] = str(exc)
                    state["last_me_check_at"] = datetime.now(timezone.utc).isoformat()
                    _write_store(state)
                raise

        access_token = str(state["access_token"])

    try:
        me = _get_me(base_url, access_token)
        _assert_agent_access(me)
    except IdentityAuthError as exc:
        if exc.relogin_required:
            with _identity_store_lock():
                _clear_store()
            _clear_user_profile_in_config()
        elif exc.access_level == "blocked":
            with _identity_store_lock():
                state = _read_store() or {}
                state["access_level"] = "blocked"
                state["subscription_warning"] = str(exc)
                state["last_me_check_at"] = datetime.now(timezone.utc).isoformat()
                _write_store(state)
        raise

    _sync_user_profile_to_config(me)
    with _identity_store_lock():
        state = _read_store() or {}
        _write_me_state(me, fallback=state)

    return {
        "access_level": _me_access_level(me) or "full",
        "subscription_warning": _subscription_warning(me),
    }


def ensure_authenticated(*, interactive: bool = True) -> IdentitySession:
    """Garante uma sessão utilizável, renovando ou voltando ao login.

    Se o refresh falhar por **rede** e ``interactive=True``, chama :func:`login`
    de imediato (equivalente a ``ector login``), em vez de falhar só com mensagem.

    Raises :class:`IdentityAuthError` com ``relogin_required=True`` quando a sessão
    em disco é inválida ou em modo não interativo sem ``ECTOR_*_TOKEN`` no ambiente.
    """
    env_session = _env_token_override()
    if env_session is not None:
        return env_session

    base_url = get_auth_base_url()
    skew = _get_int_setting("refresh_skew_seconds", DEFAULT_REFRESH_SKEW_SECONDS)

    retry_interactive_login = False

    with _identity_store_lock():
        state = _read_store()
        if state:
            if _is_expiring(state, skew):
                try:
                    state = _refresh_locked(state, base_url=base_url)
                except IdentityAuthError as exc:
                    if exc.relogin_required:
                        _clear_store()
                        state = None
                    elif exc.access_level == "blocked":
                        raise
                    elif interactive:
                        if exc.code == "network_error":
                            # Rede indisponível no refresh: não manter o utilizador
                            # bloqueado — abre o mesmo fluxo que `ector login`.
                            retry_interactive_login = True
                        else:
                            # Resposta inesperada (ex.: HTTP 5xx) — reautenticar.
                            _clear_store()
                            state = None
                    else:
                        raise
            if state is not None and not retry_interactive_login:
                session = _store_to_session(state)
                if session is not None:
                    return session

    if retry_interactive_login:
        print(
            color(
                "Não foi possível renovar a sessão na rede. Iniciando o login…",
                Colors.DIM,
            ),
            file=sys.stderr,
        )
        return login()

    if not interactive:
        raise IdentityAuthError(
            "Não autenticado. Defina ECTOR_ACCESS_TOKEN/ECTOR_REFRESH_TOKEN "
            "ou execute `ector login` em um terminal interativo.",
            code="not_authenticated",
            relogin_required=True,
        )

    return login()


def get_access_token(*, auto_refresh: bool = True) -> Optional[str]:
    """Convenience accessor for downstream code that needs the bearer.

    Returns ``None`` if no session exists. When ``auto_refresh=True`` and
    the access token is near expiry, transparently refreshes (with lock).
    """
    env_session = _env_token_override()
    if env_session is not None:
        return env_session.access_token

    base_url = get_auth_base_url()
    skew = _get_int_setting("refresh_skew_seconds", DEFAULT_REFRESH_SKEW_SECONDS)
    with _identity_store_lock():
        state = _read_store()
        if not state:
            return None
        if auto_refresh and _is_expiring(state, skew):
            try:
                state = _refresh_locked(state, base_url=base_url)
            except IdentityAuthError as exc:
                if exc.relogin_required:
                    _clear_store()
                return None
        token = state.get("access_token")
        return str(token) if isinstance(token, str) and token else None


def can_proceed_with_offline_identity() -> bool:
    """Return True when a network blip may fall back to the on-disk session.

    Requires a recent successful ``/me`` probe, a non-blocked cache, and a
    still-valid access token. Env-only sessions (CI) keep the prior trust
    model unless ``ECTOR_IDENTITY_STRICT`` is set.
    """
    if not is_logged_in():
        return False
    if get_cached_access_level() == "blocked":
        return False

    env_session = _env_token_override()
    if env_session is not None:
        if _env_truthy("ECTOR_IDENTITY_STRICT"):
            return False
        expires_at = env_session.expires_at
        return expires_at > datetime.now(timezone.utc)

    state = _read_store()
    if not state:
        return False
    last_check = _parse_iso(state.get("last_me_check_at"))
    if last_check is None:
        return False
    grace = _get_int_setting("offline_grace_seconds", DEFAULT_OFFLINE_GRACE_SECONDS)
    age = (datetime.now(timezone.utc) - last_check).total_seconds()
    if age > max(0, grace):
        return False
    expires_at = _parse_iso(state.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        return False
    return True


def _print_identity_auth_failure(exc: IdentityAuthError, *, interactive: bool) -> None:
    """Imprime orientação de login sem detalhes HTTP técnicos."""
    import sys as _sys

    print(identity_auth_user_message(exc), file=_sys.stderr)
    if not interactive and (
        exc.relogin_required or exc.code == "not_authenticated"
    ):
        print("Execute: ector login", file=_sys.stderr)


def enforce_agent_runtime_access(*, interactive: Optional[bool] = None) -> None:
    """Validate identity before starting any agent runtime (CLI or module entry).

    Mirrors :func:`ector_cli.main._enforce_identity_auth` without argparse. On
    failure prints to stderr and calls :func:`sys.exit` with code ``2``.
    """
    import sys as _sys

    if interactive is None:
        interactive = _sys.stdin.isatty() and _sys.stderr.isatty()

    try:
        ensure_authenticated(interactive=interactive)
        access = validate_agent_access()
        sync_user_profile_from_cloud()
        warning = str(access.get("subscription_warning") or "").strip()
        if warning:
            print(f"Aviso de assinatura: {warning}", file=_sys.stderr)
    except KeyboardInterrupt:
        print("Cancelado.", file=_sys.stderr)
        _sys.exit(130)
    except IdentityAuthError as exc:
        if exc.access_level == "blocked":
            print_subscription_blocked_message(str(exc), file=_sys.stderr)
        elif exc.code == "network_error":
            if get_cached_access_level() == "blocked":
                state = _read_store() or {}
                cached_reason = str(
                    state.get("subscription_warning") or exc
                ).strip()
                print_subscription_blocked_message(
                    cached_reason,
                    offline_cache=True,
                    file=_sys.stderr,
                )
            elif can_proceed_with_offline_identity():
                print(
                    f"Aviso: não foi possível validar a sessão online ({exc}). "
                    "Prosseguindo com a sessão local.",
                    file=_sys.stderr,
                )
                return
            else:
                _print_identity_auth_failure(exc, interactive=interactive)
        else:
            if exc.code == "user_cancelled":
                print("Login cancelado.", file=_sys.stderr)
            else:
                _print_identity_auth_failure(exc, interactive=interactive)
        _sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        if can_proceed_with_offline_identity():
            print(
                f"Aviso: não foi possível validar a sessão online ({exc}). "
                "Prosseguindo com a sessão local.",
                file=_sys.stderr,
            )
            return
        print(f"Falha na autenticação: {exc}", file=_sys.stderr)
        print("Execute: ector login", file=_sys.stderr)
        _sys.exit(2)


def session_for_subprocess() -> Optional[Dict[str, str]]:
    """Return a small env dict suitable for ``subprocess.Popen(env=...)``.

    Only includes the *access* token (never the refresh token, which
    must stay scoped to the parent process holding the file lock).
    """
    token = get_access_token(auto_refresh=True)
    if not token:
        return None
    sess = _effective_session()
    env: Dict[str, str] = {"ECTOR_ACCESS_TOKEN": token}
    if sess and sess.user_id:
        env["ECTOR_USER_ID"] = sess.user_id
    if sess and sess.email:
        env["ECTOR_USER_EMAIL"] = sess.email
    return env


__all__ = [
    "DEFAULT_AUTH_BASE_URL",
    "DEFAULT_OFFLINE_GRACE_SECONDS",
    "IdentityAuthError",
    "IdentitySession",
    "USER_PROFILE_CONFIG_KEYS",
    "can_proceed_with_offline_identity",
    "enforce_agent_runtime_access",
    "ensure_authenticated",
    "get_access_token",
    "get_active_session",
    "get_auth_base_url",
    "resolve_login_mode",
    "login_device_code",
    "login_loopback",
    "get_cached_access_level",
    "get_identity_plan_hints",
    "get_persisted_session",
    "get_user_profile",
    "identity_model_picker_kwargs",
    "identity_auth_user_message",
    "REMOTE_LOGIN_FAILURE_MESSAGE",
    "is_logged_in",
    "login",
    "logout",
    "session_for_subprocess",
    "sync_user_profile_from_cloud",
    "validate_agent_access",
    "whoami",
]
