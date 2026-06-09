"""Whether agent status lines should be delivered as chat bubbles on a platform."""

from __future__ import annotations

from gateway.config import Platform, SUPPORTED_CHANNEL_PLATFORMS

# Human-facing messaging channels: lifecycle/warn lines go to logs/TUI only.
_CHAT_PLATFORMS = SUPPORTED_CHANNEL_PLATFORMS


def should_deliver_status_to_chat(platform: Platform | None, event_type: str) -> bool:
    """Return True when ``status_callback`` may post ``message`` via ``adapter.send``."""
    if platform is None or platform not in _CHAT_PLATFORMS:
        return False
    if event_type in ("lifecycle", "warn"):
        return False
    return True
