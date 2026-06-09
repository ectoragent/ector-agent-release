"""Idle presence nudge — optional gateway reminder after user inactivity."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from gateway.config import Platform

_PRESENCE_NUDGE_DEFAULT_MESSAGE = (
    "Oi! Faz um tempo que não conversamos — estou por aqui se precisar de algo."
)

# Skip platforms with no stable outbound "channel" semantics for this feature.
_PRESENCE_NUDGE_SKIP_PLATFORMS: frozenset[Platform] = frozenset((Platform.LOCAL,))

_DISABLE_PATTERNS = (
    re.compile(
        r"\b(?:desativ\w*|deslig\w*)\b.*\b(?:lembrete|presen[çc]a|check[-\s]?in|nudge|reminder)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:stop|disable|turn\s+off)\b.*\b(?:presence|nudge|reminder|check[-\s]?in)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:pare|para)\s+de\s+(?:mandar|enviar)\b.*\b(?:lembrete|presen[çc]a|check[-\s]?in|nudge)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bparar?\s+(?:o\s+)?lembrete\b", re.IGNORECASE),
    re.compile(r"\bno\s+more\b.*\b(?:presence|nudge|reminders?)\b", re.IGNORECASE),
    re.compile(
        r"\bsem\b.*\b(?:lembrete|mensagens?\s+autom[aá]ticas?|check[-\s]?in)\b",
        re.IGNORECASE,
    ),
)

_ENABLE_PATTERNS = (
    re.compile(
        r"\breativ\w*\b.*\b(?:lembrete|presen[çc]a|check[-\s]?in|nudge|reminder)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:enable|turn\s+on)\b.*\b(?:presence|nudge|reminder|check[-\s]?in)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ativar|ligar)\s+(?:o\s+)?(?:lembrete|presen[çc]a)\b",
        re.IGNORECASE,
    ),
)


def default_presence_nudge_message() -> str:
    return _PRESENCE_NUDGE_DEFAULT_MESSAGE


def parse_presence_nudge_chat_intent(text: str) -> Optional[Literal["disable", "enable"]]:
    """Detect opt-out / opt-in from free-form chat (PT/EN)."""
    s = (text or "").strip()
    if len(s) < 6:
        return None
    if any(r.search(s) for r in _DISABLE_PATTERNS):
        return "disable"
    if any(r.search(s) for r in _ENABLE_PATTERNS):
        return "enable"
    return None


def presence_nudge_skip_platform(platform: Optional[Platform]) -> bool:
    return platform is None or platform in _PRESENCE_NUDGE_SKIP_PLATFORMS


def _display_dict_from_config(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        d = config.get("display")
        return dict(d) if isinstance(d, dict) else {}
    d = getattr(config, "display", None)
    return dict(d) if isinstance(d, dict) else {}


def resolve_presence_nudge_settings(config: Any) -> dict[str, Any]:
    """Read ``display.presence_nudge`` from config.

    ``GatewayConfig`` has no ``display`` section — values are merged from
    ``ector_cli.config.load_config()`` (same merged YAML as CLI) so
    ``config.yaml`` → ``display.presence_nudge`` applies to the gateway watcher.
    """
    overlay = _display_dict_from_config(config).get("presence_nudge")
    if not isinstance(overlay, dict):
        overlay = {}

    base: dict[str, Any] = {}
    try:
        from ector_cli.config import load_config as _load_ector_config

        full = _load_ector_config()
        if isinstance(full, dict):
            pn = (full.get("display") or {}).get("presence_nudge")
            if isinstance(pn, dict):
                base = dict(pn)
    except Exception:
        pass

    raw = {**base, **overlay}
    msg = str(raw.get("message") or "").strip()
    return {
        "enabled": bool(raw.get("enabled", False)),
        "idle_hours": max(1.0, float(raw.get("idle_hours", 15))),
        "check_interval_seconds": max(60, int(raw.get("check_interval_seconds", 1800))),
        "message": msg or default_presence_nudge_message(),
    }


def should_send_presence_nudge(
    *,
    now: datetime,
    last_user_message_at: Optional[datetime],
    last_presence_nudge_at: Optional[datetime],
    presence_nudge_disabled: bool,
    idle_hours: float,
) -> bool:
    if presence_nudge_disabled or last_user_message_at is None:
        return False
    idle = timedelta(hours=idle_hours)
    if now - last_user_message_at < idle:
        return False
    if last_presence_nudge_at is not None and last_user_message_at <= last_presence_nudge_at:
        return False
    return True
