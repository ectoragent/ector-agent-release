"""Translate legacy ``python cli.py`` argv to ``ector`` and re-exec.

Legacy ``python cli.py --list-tools`` / ``--list-toolsets`` only (no interactive REPL).
"""

from __future__ import annotations

import os
import sys


_LEGACY_LIST_ONLY = frozenset(
    {
        "--list-tools",
        "--list-toolsets",
        "-list-tools",
        "-list-toolsets",
    }
)

_LEGACY_CHAT_FLAGS = frozenset(
    {
        "-q",
        "--query",
        "-query",
        "--quiet",
        "-quiet",
        "-Q",
        "--image",
        "-image",
        "--resume",
        "-resume",
        "-r",
        "-w",
        "--worktree",
        "-worktree",
        "-m",
        "--model",
        "-model",
        "--provider",
        "-provider",
        "--toolsets",
        "-toolsets",
        "-t",
        "--skills",
        "-skills",
        "-s",
        "--ignore-user-config",
        "--ignore-rules",
        "--yolo",
        "--pass-session-id",
    }
)


def _warn_legacy_chat_flag(flag: str, detail: str = "") -> None:
    msg = (
        f"Aviso: `{flag}` via `python cli.py` não é mais suportado; "
        "use o painel web (`ector`)."
    )
    if detail:
        msg = f"{msg} {detail}"
    print(msg, file=sys.stderr)


def _translate_cli_py_argv(argv: list[str]) -> list[str] | None:
    """Return new argv for ``ector``, or None to use legacy list-only handlers."""
    if not argv:
        return ["ector"]

    if any(a in _LEGACY_LIST_ONLY for a in argv):
        return None

    out: list[str] = ["ector"]
    i = 0
    n = len(argv)

    while i < n:
        arg = argv[i]
        if arg in ("-h", "--help", "-help"):
            out.extend(argv[i:])
            return out
        if arg in ("--gateway", "-gateway"):
            out.extend(["gateway", "run"])
            i += 1
            continue
        if arg in _LEGACY_CHAT_FLAGS:
            _warn_legacy_chat_flag(arg)
            if arg in ("-q", "--query", "-query", "--image", "-image", "-m", "--model", "-model",
                       "--provider", "-provider", "--toolsets", "-toolsets", "-t",
                       "--skills", "-skills", "-s", "--resume", "-resume", "-r"):
                i += 2 if i + 1 < n else 1
            else:
                i += 1
            continue
        if arg.startswith("-"):
            out.append(arg)
            i += 1
            continue
        _warn_legacy_chat_flag("prompt posicional")
        i += 1

    return out


def run_cli_py_entry(argv: list[str] | None = None) -> None:
    """Entry for ``python cli.py`` — redirect to ``ector`` except list-only flags."""
    raw = list(argv if argv is not None else sys.argv[1:])

    if any(a in _LEGACY_LIST_ONLY for a in raw):
        import subprocess

        list_toolsets = "--list-toolsets" in raw or "-list-toolsets" in raw
        if list_toolsets:
            raise SystemExit(
                subprocess.call(
                    [sys.executable, "-m", "ector_cli.main", "tools", "list"]
                )
            )
        raise SystemExit(
            subprocess.call(
                [
                    sys.executable,
                    "-c",
                    "from model_tools import get_tool_definitions; "
                    "from toolsets import get_toolset_for_tool; "
                    "tools = get_tool_definitions(quiet_mode=True); "
                    "by = {}; "
                    "[by.setdefault(get_toolset_for_tool(t['function']['name']) or '?', []).append(t['function']['name']) for t in tools]; "
                    "print('Tools (%d):' % len(tools)); "
                    "[print('  %s: %s' % (k, ', '.join(sorted(v)[:12]) + ('…' if len(v)>12 else ''))) for k,v in sorted(by.items())]; "
                    "import sys; sys.exit(0)",
                ]
            )
        )

    translated = _translate_cli_py_argv(raw)
    if translated is None:
        return

    print(
        "Aviso: `python cli.py` está obsoleto. Use o comando `ector` "
        "(abre o painel web).",
        file=sys.stderr,
    )

    os.execv(
        sys.executable,
        [sys.executable, "-m", "ector_cli.main", *translated[1:]],
    )
