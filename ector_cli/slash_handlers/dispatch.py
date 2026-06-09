"""Lightweight slash handlers (avoid full EctorCLI when possible)."""

from __future__ import annotations

from typing import Callable

from ector_cli.slash_resolve import parse_slash

_Handler = Callable[[str, str], str]


def _run_profile(_arg: str, _raw: str) -> str:
    from ector_constants import display_ector_home
    from ector_cli.profiles import get_active_profile_name

    return "\n".join(
        [
            f"Perfil: {get_active_profile_name()}",
            f"Pasta: {display_ector_home()}",
        ]
    )


def _run_platforms(_arg: str, _raw: str) -> str:
    from gateway.config import Platform, load_gateway_config

    try:
        config = load_gateway_config()
    except Exception as e:
        return f"gateway config error: {e}"

    rows = []
    for platform, (name, env_var) in {
        Platform.TELEGRAM: ("Telegram", "TELEGRAM_BOT_TOKEN"),
        Platform.DISCORD: ("Discord", "DISCORD_BOT_TOKEN"),
        Platform.WHATSAPP: ("WhatsApp", "WHATSAPP_ENABLED"),
    }.items():
        pconfig = config.platforms.get(platform)
        if pconfig and pconfig.enabled:
            home = config.get_home_channel(platform)
            detail = f"Canal: {home.name}" if home else "—"
            rows.append(f"✔ {name}: Ativada — {detail}")
        else:
            rows.append(f"✖ {name}: Não configurada (defina {env_var})")
    policy = getattr(config, "default_reset_policy", None)
    if policy is not None:
        rows.append("")
        rows.append(f"Política de reinício: {policy}")
    return "\n".join(rows) if rows else "(no platforms)"


def _run_gquota(_arg: str, _raw: str) -> str:
    try:
        from agent.google_code_assist import CodeAssistError, retrieve_user_quota
        from agent.google_oauth import GoogleOAuthError, get_valid_access_token, load_credentials
    except ImportError as exc:
        return f"Gemini modules unavailable: {exc}"

    try:
        access_token = get_valid_access_token()
    except GoogleOAuthError as exc:
        return f"{exc}\nRun /provider and pick Google Gemini (OAuth) to sign in."

    creds = load_credentials()
    project_id = (creds.project_id if creds else "") or ""
    try:
        buckets = retrieve_user_quota(access_token, project_id=project_id)
    except CodeAssistError as exc:
        return f"Quota lookup failed: {exc}"

    if not buckets:
        return "No quota buckets reported (account may be on legacy/unmetered tier)."

    buckets.sort(key=lambda b: (b.model_id, b.token_type))
    lines = [f"Gemini Code Assist quota (project: {project_id or '(auto)'})"]
    for b in buckets:
        pct = max(0.0, min(1.0, b.remaining_fraction))
        width = 20
        filled = int(round(pct * width))
        bar = "▓" * filled + "░" * (width - filled)
        header = b.model_id + (f" [{b.token_type}]" if b.token_type else "")
        lines.append(f"  {header:40s}  {bar}  {int(pct * 100):3d}%")
    return "\n".join(lines)


_HANDLERS: dict[str, _Handler] = {
    "profile": _run_profile,
    "platforms": _run_platforms,
    "gquota": _run_gquota,
}


def try_dispatch(command: str) -> str | None:
    """Run a migrated slash command without EctorCLI; return output or None."""
    raw = (command or "").strip()
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = f"/{raw}"
    parsed = parse_slash(raw)
    handler = _HANDLERS.get(parsed.canonical)
    if not handler:
        return None
    return handler(parsed.arg, parsed.raw) or "(no output)"
