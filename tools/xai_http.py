"""Shared helpers for direct xAI HTTP integrations."""

from __future__ import annotations


def ector_xai_user_agent() -> str:
    """Return a stable Ector-specific User-Agent for xAI HTTP calls."""
    try:
        from ector_cli import __version__
    except Exception:
        __version__ = "unknown"
    return f"Ector-Agent/{__version__}"
