"""
Shared platform registry for Ector Agent.

Single source of truth for platform metadata consumed by both
skills_config (label display) and tools_config (default toolset
resolution).  Import ``PLATFORMS`` from here instead of maintaining
duplicate dicts in each module.
"""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="ector-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="ector-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="ector-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="ector-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="ector-whatsapp")),
    ("cron",           PlatformInfo(label="⏰ Cron",            default_toolset="ector-cron")),
])


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key, or *default*."""
    info = PLATFORMS.get(key)
    return info.label if info is not None else default
