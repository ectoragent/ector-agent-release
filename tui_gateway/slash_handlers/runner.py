"""Run EctorCLI.process_command in-process (replaces slash_worker subprocess)."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli import EctorCLI


class InProcessSlashRunner:
    """Thread-safe wrapper around a single EctorCLI instance per session."""

    def __init__(self, session_key: str, model: str):
        self._lock = threading.Lock()
        self._cli = self._build_cli(session_key, model)

    @staticmethod
    def _build_cli(session_key: str, model: str) -> "EctorCLI":
        import cli as cli_mod
        from cli import EctorCLI

        os.environ["ECTOR_SESSION_KEY"] = session_key
        os.environ["ECTOR_INTERACTIVE"] = "1"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            return EctorCLI(
                model=model or None,
                resume=session_key,
                verbose=False,
            )

    def run(self, command: str) -> str:
        cmd = (command or "").strip()
        if not cmd:
            return ""
        if not cmd.startswith("/"):
            cmd = f"/{cmd}"

        buf = io.StringIO()
        os.environ["ECTOR_SLASH_WORKER"] = "1"

        import cli as cli_mod
        from rich.console import Console

        _cols, _ = shutil.get_terminal_size(fallback=(100, 24))
        _w = max(min(_cols, 120), 52)
        self._cli.console = Console(
            file=buf,
            force_terminal=True,
            width=_w,
            color_system="standard",
        )

        old_cprint = getattr(cli_mod, "_cprint", None)
        if old_cprint is not None:
            cli_mod._cprint = lambda text: print(text)

        try:
            from ector_cli.slash_handlers.dispatch import try_dispatch

            with self._lock:
                fast = try_dispatch(cmd)
                if fast is not None:
                    return fast
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    self._cli.process_command(cmd)
        finally:
            os.environ.pop("ECTOR_SLASH_WORKER", None)
            if old_cprint is not None:
                cli_mod._cprint = old_cprint

        return buf.getvalue().rstrip()

    def close(self):
        """No-op — kept for parity with the old subprocess worker API."""
        return None
