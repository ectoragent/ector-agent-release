"""Best-effort process display name (Activity Monitor, ps, top).

Import-safe — no dependencies beyond optional ``setproctitle``.
"""

from __future__ import annotations


def set_process_title(title: str) -> None:
    """Set the OS-visible process name; never raises."""
    if not title:
        return
    try:
        import setproctitle

        setproctitle.setproctitle(title)
    except Exception:
        pass
