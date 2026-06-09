"""Detached runner for `ector localhost`.

This module exists so the CLI can spawn a background web UI process without
blocking the initiating terminal.
"""

from __future__ import annotations

import os

from ector_cli.web_server import start_server


def main() -> None:
    try:
        from ector_process import set_process_title

        set_process_title("Ector Web")
    except Exception:
        pass

    host = os.environ.get("ECTOR_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("ECTOR_DASHBOARD_PORT", "9000"))
    allow_public = os.environ.get("ECTOR_DASHBOARD_INSECURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    open_url = os.environ.get("ECTOR_DASHBOARD_OPEN_URL") or None

    # Detached runner should not open browsers.
    start_server(
        host=host,
        port=port,
        open_browser=False,
        allow_public=allow_public,
        open_url=open_url,
    )


if __name__ == "__main__":
    main()
