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


def _translate_cli_py_argv(argv: list[str]) -> list[str] | None:
    """Return new argv for ``ector``, or None to use legacy list-only handlers."""
    if not argv:
        return ["ector"]

    if any(a in _LEGACY_LIST_ONLY for a in argv):
        return None

    out: list[str] = ["ector"]
    i = 0
    n = len(argv)
    chat_mode = False

    while i < n:
        arg = argv[i]
        if arg in ("-h", "--help", "-help"):
            out.extend(argv[i:])
            return out
        if arg in ("--gateway", "-gateway"):
            out.extend(["gateway", "run"])
            i += 1
            continue
        if arg in ("-q", "--query", "-query"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.extend(["-q", argv[i + 1]] if i + 1 < n else ["-q"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("--image", "-image"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.extend(["--image", argv[i + 1]] if i + 1 < n else ["--image"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("--quiet", "-quiet", "-Q"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.append("-Q")
            i += 1
            continue
        if arg in ("--resume", "-resume", "-r"):
            out.extend(["--resume", argv[i + 1]] if i + 1 < n else ["--resume"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("-w", "--worktree", "-worktree"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.append("-w")
            if i + 1 < n and not argv[i + 1].startswith("-"):
                print(
                    "Aviso: worktree via `python cli.py -w` ainda não é suportado no TUI; "
                    "o isolamento git pode não aplicar-se.",
                    file=sys.stderr,
                )
            i += 1
            continue
        if arg in ("-m", "--model", "-model"):
            out.extend(["-m", argv[i + 1]] if i + 1 < n else ["-m"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("--provider", "-provider"):
            out.extend(["--provider", argv[i + 1]] if i + 1 < n else ["--provider"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("--toolsets", "-toolsets", "-t"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.extend(["-t", argv[i + 1]] if i + 1 < n else ["-t"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("--skills", "-skills", "-s"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.extend(["-s", argv[i + 1]] if i + 1 < n else ["-s"])
            i += 2 if i + 1 < n else 1
            continue
        if arg in ("--ignore-user-config", "--ignore-rules", "--yolo", "--pass-session-id"):
            out.append(arg)
            i += 1
            continue
        if arg.startswith("-"):
            if not chat_mode:
                out.append("chat")
                chat_mode = True
            out.append(arg)
            i += 1
            continue
        # Positional: treat as one-shot prompt
        if not chat_mode:
            out.append("chat")
            chat_mode = True
        out.extend(["-q", arg])
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
        "(ex.: `ector`, `ector chat`, `ector -z \"pergunta\"`).",
        file=sys.stderr,
    )

    os.execv(
        sys.executable,
        [sys.executable, "-m", "ector_cli.main", *translated[1:]],
    )
