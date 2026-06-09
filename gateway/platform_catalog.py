"""
Gateway messaging platform catalog — shared by CLI setup and dashboard API.

Reads platform definitions from ``ector_cli.gateway._PLATFORMS`` and exposes
structured status / apply helpers without terminal prompts.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

from ector_cli.config import get_env_value, get_ector_home, is_managed, remove_env_value, save_env_value

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Platforms suportadas no produto.
_SUPPORTED_KEYS = frozenset(
    {"whatsapp", "telegram", "discord", "slack"}
)

SUPPORTED_MESSAGING_ENV_PREFIXES: tuple[str, ...] = (
    "WHATSAPP_",
    "TELEGRAM_",
    "DISCORD_",
    "SLACK_",
)

# Variáveis de infraestrutura do gateway (sem prefixo de plataforma).
_MESSAGING_INFRA_ENV_VARS = frozenset(
    {
        "GATEWAY_ALLOW_ALL_USERS",
        "GATEWAY_PROXY_URL",
        "GATEWAY_PROXY_KEY",
    }
)

_WHATSAPP_KEY = "whatsapp"

# Display order: most-used messaging channels first (dashboard / API consumers).
PLATFORM_POPULARITY_ORDER: tuple[str, ...] = (
    "whatsapp",
    "telegram",
    "discord",
    "slack",
)


def _platform_popularity_rank(key: str) -> tuple[int, int, str]:
    try:
        return (0, PLATFORM_POPULARITY_ORDER.index(key), "")
    except ValueError:
        return (1, 0, key)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def is_supported_messaging_env_var(name: str) -> bool:
    """Whether a ``.env`` key belongs to a supported messaging channel."""
    if name in _MESSAGING_INFRA_ENV_VARS:
        return True
    return any(name.startswith(prefix) for prefix in SUPPORTED_MESSAGING_ENV_PREFIXES)


def _platforms_raw() -> list[dict]:
    from ector_cli.gateway import _PLATFORMS

    return [p for p in _PLATFORMS if p.get("key") in _SUPPORTED_KEYS]


def get_platform_def(key: str) -> dict | None:
    for plat in _platforms_raw():
        if plat.get("key") == key:
            return plat
    return None


def list_platform_keys() -> list[str]:
    return [p["key"] for p in _platforms_raw()]


def _public_var_schema(var: dict) -> dict:
    return {
        "name": var["name"],
        "prompt": var.get("prompt", ""),
        "help": var.get("help", ""),
        "password": bool(var.get("password", False)),
        "is_allowlist": bool(var.get("is_allowlist", False)),
    }


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return value[:2] + "•" * min(12, len(value) - 4) + value[-2:]


def _var_values_for_platform(platform: dict, *, mask_secrets: bool) -> list[dict]:
    out: list[dict] = []
    for var in platform.get("vars") or []:
        name = var["name"]
        raw = get_env_value(name) or ""
        is_set = bool(str(raw).strip())
        display = _mask_secret(raw) if mask_secrets and var.get("password") else raw
        out.append(
            {
                "name": name,
                "is_set": is_set,
                "value": display if is_set else "",
                "password": bool(var.get("password", False)),
                "is_allowlist": bool(var.get("is_allowlist", False)),
            }
        )
    return out


def platform_status_text(platform: dict) -> str:
    try:
        from ector_cli.gateway import _platform_status

        return _strip_ansi(_platform_status(platform))
    except Exception:
        token_var = platform.get("token_var", "")
        val = get_env_value(token_var) if token_var else ""
        if platform.get("key") == _WHATSAPP_KEY:
            if val and val.lower() == "true":
                home = get_ector_home()
                creds_paths = (
                    home / "whatsapp" / "session" / "creds.json",
                    home / "platforms" / "whatsapp" / "session" / "creds.json",
                )
                return (
                    "configurado + pareado"
                    if any(path.exists() for path in creds_paths)
                    else "habilitado, não pareado"
                )
            return "não configurado"
        return "configurado" if val else "não configurado"


def platform_state(platform: dict) -> str:
    """Machine-readable state: not_configured | partial | configured | paired."""
    key = platform.get("key", "")
    text = platform_status_text(platform).lower().strip()

    # "não configurado" contains "configurado" — check negation and partial first.
    if "não configurado" in text or "not configured" in text or "nao configurado" in text:
        return "not_configured"
    if "parcial" in text or "partial" in text:
        return "partial"

    if key == _WHATSAPP_KEY:
        if "pareado" in text or "paired" in text:
            return "paired"
        if "habilitado" in text and "não" not in text:
            return "partial"
        return "not_configured"

    if "configurado" in text or "configured" in text:
        return "configured"
    return "not_configured"


def setup_kind(key: str) -> str:
    if key == _WHATSAPP_KEY:
        return "whatsapp_wizard"
    plat = get_platform_def(key)
    if plat and plat.get("vars"):
        return "form"
    return "terminal_only"


def platform_public_meta(platform: dict) -> dict:
    key = platform["key"]
    return {
        "key": key,
        "label": platform.get("label", key),
        "emoji": platform.get("emoji", ""),
        "token_var": platform.get("token_var", ""),
        "setup_instructions": list(platform.get("setup_instructions") or []),
        "vars": [_public_var_schema(v) for v in (platform.get("vars") or [])],
        "setup_kind": setup_kind(key),
        "status_text": platform_status_text(platform),
        "state": platform_state(platform),
    }


def list_platforms() -> list[dict]:
    platforms = [platform_public_meta(p) for p in _platforms_raw()]
    platforms.sort(key=lambda p: _platform_popularity_rank(p["key"]))
    return platforms


def _telegram_bot_url() -> str | None:
    """Public t.me link from getMe when a bot token is configured."""
    token = (get_env_value("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return None
    try:
        with urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, ValueError, TimeoutError) as exc:
        logger.debug("Telegram getMe for bot_url failed: %s", exc)
        return None
    if not data.get("ok"):
        return None
    username = (data.get("result") or {}).get("username")
    if not username:
        return None
    return f"https://t.me/{username}"


def get_platform_detail(key: str, *, mask_secrets: bool = True) -> dict:
    plat = get_platform_def(key)
    if plat is None:
        raise KeyError(key)
    meta = platform_public_meta(plat)
    meta["vars_values"] = _var_values_for_platform(plat, mask_secrets=mask_secrets)
    if key == _WHATSAPP_KEY:
        meta["whatsapp_mode"] = get_env_value("WHATSAPP_MODE") or "self-chat"
        meta["whatsapp_enabled"] = (get_env_value("WHATSAPP_ENABLED") or "").lower() == "true"
        meta["whatsapp_allowed_users"] = get_env_value("WHATSAPP_ALLOWED_USERS") or ""
    if key == "telegram":
        bot_url = _telegram_bot_url()
        if bot_url:
            meta["bot_url"] = bot_url
    return meta


def _clean_allowlist(value: str, var_name: str) -> str:
    cleaned = value.replace(" ", "")
    if "DISCORD" in var_name:
        parts = []
        for uid in cleaned.split(","):
            uid = uid.strip()
            if uid.startswith("<@") and uid.endswith(">"):
                uid = uid.lstrip("<@!").rstrip(">")
            if uid.lower().startswith("user:"):
                uid = uid[5:]
            if uid:
                parts.append(uid)
        cleaned = ",".join(parts)
    return cleaned


def apply_platform_env(
    key: str,
    values: dict[str, str] | None = None,
    *,
    allowlist_access: str | None = None,
) -> dict:
    """
    Persist platform configuration to ``~/.ector/.env``.

    ``allowlist_access`` when an allowlist var is empty: ``open``, ``pairing``, ``deny``.
    """
    if is_managed():
        raise PermissionError(
            "Configuração de canais não está disponível em instalações gerenciadas (NixOS)."
        )

    plat = get_platform_def(key)
    if plat is None:
        raise KeyError(key)

    if setup_kind(key) == "terminal_only":
        raise ValueError(
            f"{plat.get('label', key)} requer configuração no terminal: "
            f"execute `ector gateway setup` e escolha esta plataforma."
        )

    if key == _WHATSAPP_KEY:
        saved: list[str] = []
        body = values or {}
        if "WHATSAPP_ENABLED" in body:
            enabled = str(body["WHATSAPP_ENABLED"]).strip().lower() in ("true", "1", "yes", "on")
            save_env_value("WHATSAPP_ENABLED", "true" if enabled else "false")
            saved.append("WHATSAPP_ENABLED")
        if "WHATSAPP_MODE" in body:
            mode = str(body["WHATSAPP_MODE"]).strip() or "self-chat"
            if mode not in ("bot", "self-chat"):
                mode = "self-chat"
            save_env_value("WHATSAPP_MODE", mode)
            saved.append("WHATSAPP_MODE")
        if "WHATSAPP_ALLOWED_USERS" in body:
            save_env_value(
                "WHATSAPP_ALLOWED_USERS",
                str(body["WHATSAPP_ALLOWED_USERS"]).replace(" ", ""),
            )
            saved.append("WHATSAPP_ALLOWED_USERS")
        return {"ok": True, "saved": saved, "state": platform_state(plat)}

    if not plat.get("vars"):
        raise ValueError(f"Plataforma {key} não suporta configuração por formulário.")

    body = values or {}
    token_var = plat.get("token_var", "")
    saved: list[str] = []

    for var in plat["vars"]:
        name = var["name"]
        if name not in body:
            continue
        raw = str(body[name] or "").strip()

        if var.get("is_allowlist"):
            if raw:
                save_env_value(name, _clean_allowlist(raw, name))
                saved.append(name)
            else:
                mode = (allowlist_access or "pairing").strip().lower()
                if mode == "open":
                    save_env_value("GATEWAY_ALLOW_ALL_USERS", "true")
                    saved.append("GATEWAY_ALLOW_ALL_USERS")
                elif mode == "pairing":
                    pass
                elif mode == "deny":
                    save_env_value(name, "")
                    saved.append(name)
            continue

        if raw:
            save_env_value(name, raw)
            saved.append(name)
        elif name == token_var:
            raise ValueError(f"Campo obrigatório ausente: {name}")

    if token_var and token_var not in saved and not get_env_value(token_var):
        raise ValueError(f"Token obrigatório ({token_var}) não fornecido.")

    # Telegram home channel hint from first allowlist id
    if key == "telegram":
        allowed = get_env_value("TELEGRAM_ALLOWED_USERS") or ""
        home = get_env_value("TELEGRAM_HOME_CHANNEL") or ""
        if allowed and not home and body.get("TELEGRAM_AUTO_HOME", "").lower() in (
            "true",
            "1",
            "yes",
        ):
            first_id = allowed.split(",")[0].strip()
            if first_id:
                save_env_value("TELEGRAM_HOME_CHANNEL", first_id)
                saved.append("TELEGRAM_HOME_CHANNEL")

    plat = get_platform_def(key) or plat
    return {"ok": True, "saved": saved, "state": platform_state(plat)}


def disconnect_platform(key: str) -> dict:
    """
    Remove platform credentials from ``~/.ector/.env`` and clear local session data.

    The gateway must be restarted to stop an already-connected adapter.
    """
    if is_managed():
        raise PermissionError(
            "Configuração de canais não está disponível em instalações gerenciadas (NixOS)."
        )

    plat = get_platform_def(key)
    if plat is None:
        raise KeyError(key)

    removed: list[str] = []

    if key == _WHATSAPP_KEY:
        from gateway.whatsapp_pairing import cancel_pairing

        cancel_pairing()
        for name in ("WHATSAPP_ENABLED", "WHATSAPP_ALLOWED_USERS", "WHATSAPP_MODE"):
            if remove_env_value(name):
                removed.append(name)
        home = get_ector_home()
        session_dirs = (
            home / "whatsapp" / "session",
            home / "platforms" / "whatsapp" / "session",
        )
        session_cleared = False
        for session_dir in session_dirs:
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
                session_cleared = True
        plat = get_platform_def(key) or plat
        return {
            "ok": True,
            "removed": removed,
            "session_cleared": session_cleared,
            "state": platform_state(plat),
        }

    names: list[str] = []
    token_var = plat.get("token_var", "")
    if token_var:
        names.append(token_var)
    for var in plat.get("vars") or []:
        n = var.get("name", "")
        if n and n not in names:
            names.append(n)

    if not names:
        raise ValueError(
            f"{plat.get('label', key)} não tem credenciais no dashboard para remover. "
            f"Use `ector gateway setup` no terminal."
        )

    for name in names:
        if remove_env_value(name):
            removed.append(name)

    plat = get_platform_def(key) or plat
    return {"ok": True, "removed": removed, "state": platform_state(plat)}


def _gateway_running() -> bool:
    try:
        from gateway.status import is_gateway_running

        return bool(is_gateway_running())
    except Exception:
        return False


def _platform_agent_entry(platform: dict) -> dict:
    """Compact platform row for ``gateway_inspect`` (smaller LLM context)."""
    return {
        "key": platform["key"],
        "label": platform["label"],
        "setup_kind": platform["setup_kind"],
        "status_text": platform["status_text"],
        "state": platform["state"],
    }


def _runtime_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    """Extract actionable runtime health fields from ``gateway_state.json``."""
    if not runtime:
        return {}

    summary: dict[str, Any] = {}
    for key in ("gateway_state", "exit_reason", "active_agents", "restart_requested"):
        if key in runtime and runtime[key] is not None:
            summary[key] = runtime[key]

    platform_errors: dict[str, Any] = {}
    for plat_key, pdata in (runtime.get("platforms") or {}).items():
        if not isinstance(pdata, dict):
            continue
        state = pdata.get("state")
        if state not in ("fatal", "disconnected"):
            continue
        entry: dict[str, Any] = {"state": state}
        if pdata.get("error_message"):
            entry["error_message"] = pdata["error_message"]
        if pdata.get("error_code") is not None:
            entry["error_code"] = pdata["error_code"]
        platform_errors[plat_key] = entry

    if platform_errors:
        summary["platform_errors"] = platform_errors
    return summary


def _build_next_steps(
    *,
    gateway_running: bool,
    configured: list[str],
    partial: list[str],
    runtime: dict[str, Any],
    managed: bool,
) -> list[str]:
    steps: list[str] = []

    if partial:
        steps.append("Conclua o emparelhamento (ex.: WhatsApp QR em /channels).")

    if configured and not gateway_running:
        steps.append(
            "Canal(is) configurado(s), mas o gateway está parado — inicie ou reinicie em "
            "/channels ou com `ector gateway start` / `ector gateway restart`."
        )

    for plat_key, pdata in (runtime.get("platforms") or {}).items():
        if not isinstance(pdata, dict) or pdata.get("state") != "fatal":
            continue
        label = plat_key
        msg = pdata.get("error_message") or "erro desconhecido"
        steps.append(
            f"{label}: {msg} — verifique credenciais em /channels ou /env."
        )

    gateway_state = runtime.get("gateway_state")
    exit_reason = runtime.get("exit_reason")
    if gateway_state == "startup_failed":
        if exit_reason:
            steps.append(f"Gateway falhou ao iniciar: {exit_reason}.")
        else:
            steps.append(
                "Gateway falhou ao iniciar — veja `ector logs --follow` e a página /channels."
            )

    if managed:
        steps.append(
            "Instalação gerenciada (Nix): configure canais pelo sistema, não pelo dashboard."
        )

    return steps


def snapshot(*, agent: bool = False) -> dict:
    """Gateway + platform snapshot for dashboard API and ``gateway_inspect``.

    When ``agent=True``, omits bulky per-platform fields (``setup_instructions``,
    ``vars`` schemas) to keep tool results small for the LLM.
    """
    platforms_full = list_platforms()
    configured = [p["key"] for p in platforms_full if p["state"] in ("configured", "paired")]
    partial = [p["key"] for p in platforms_full if p["state"] == "partial"]

    runtime: dict[str, Any] = {}
    try:
        from gateway.status import read_runtime_status

        runtime = read_runtime_status() or {}
    except Exception:
        pass

    gateway_running = _gateway_running()
    managed = is_managed()
    platforms = (
        [_platform_agent_entry(p) for p in platforms_full] if agent else platforms_full
    )

    return {
        "managed": managed,
        "gateway_running": gateway_running,
        "gateway_state": runtime.get("gateway_state"),
        "runtime_summary": _runtime_summary(runtime),
        "platforms": platforms,
        "configured_keys": configured,
        "partial_keys": partial,
        "next_steps": _build_next_steps(
            gateway_running=gateway_running,
            configured=configured,
            partial=partial,
            runtime=runtime,
            managed=managed,
        ),
        "channels_ui_path": "/channels",
        "env_ui_path": "/env",
    }


def check_managed() -> None:
    if is_managed():
        raise PermissionError(
            "Configuração de canais não está disponível em instalações gerenciadas (NixOS)."
        )
