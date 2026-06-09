"""Legacy tool / toolset ids that map to the current Wiser (``wiser``) surface.

Centralizes compatibility tokens so transcripts, YAML, and provider emissions
stay consistent without scattering string literals across the codebase.
"""

from __future__ import annotations

from typing import Final

# Tool call names from older models or stored sessions (before ``wiser``).
WISER_LEGACY_TOOL_IDS: Final[frozenset[str]] = frozenset({"ask_user", "clarify"})

# Toolset YAML keys removed from ``TOOLSETS`` but still accepted in configs.
_LEGACY_TOOLSET_ALIASES: Final[dict[str, str]] = {
    "clarify": "wiser",

    # Rebrand: accept legacy `ector-*` toolset ids
    "ector-cli": "ector-cli",
    "ector-cron": "ector-cron",
    "ector-telegram": "ector-telegram",
    "ector-discord": "ector-discord",
    "ector-whatsapp": "ector-whatsapp",
    "ector-slack": "ector-slack",
    "ector-gateway": "ector-gateway",
    "ector-api-server": "ector-api-server",
}

LEGACY_WISER_TOOLSET_KEYS: Final[frozenset[str]] = frozenset(_LEGACY_TOOLSET_ALIASES)


def canonical_wiser_tool_name(name: str) -> str:
    if name in WISER_LEGACY_TOOL_IDS:
        return "wiser"
    return name


def canonical_wiser_toolset_name(name: str) -> str:
    return _LEGACY_TOOLSET_ALIASES.get(name, name)
