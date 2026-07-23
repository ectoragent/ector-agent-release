"""Progressive subdirectory hint discovery.

As the agent navigates into subdirectories via tool calls (read_file, terminal,
search_files, etc.), this module discovers and loads project context files
(AGENTS.md, CLAUDE.md, .cursorrules) from those directories.  Discovered hints
are appended to the tool result so the model gets relevant context at the moment
it starts working in a new area of the codebase.

This complements the startup context loading in ``prompt_builder.py`` which only
loads from the CWD.  Subdirectory hints are discovered lazily and injected into
the conversation without modifying the system prompt (preserving prompt caching).

Inspired by Block/goose's SubdirectoryHintTracker.
"""

import logging
import os
import shlex
from pathlib import Path
from typing import Dict, Any, Optional, Set

from agent.prompt_builder import _scan_context_content

logger = logging.getLogger(__name__)

# Context files to look for in subdirectories, in priority order.
# First match wins *per directory* (same as startup loading).
_HINT_FILENAMES = [
    "AGENTS.md", "agents.md",
    "CLAUDE.md", "claude.md",
    ".cursorrules",
]

# Maximum chars per hint file to prevent context bloat
_MAX_HINT_CHARS = 8_000

# Tool argument keys that typically contain file paths
_PATH_ARG_KEYS = {"path", "file_path", "workdir"}

# Tools that take shell commands where we should extract paths
_COMMAND_TOOLS = {"terminal"}

# How many parent directories to walk up when looking for hints.
# Prevents scanning all the way to / for deeply nested paths.
_MAX_ANCESTOR_WALK = 5

class SubdirectoryHintTracker:
    """Track which directories the agent visits and load hints on first access.

    Usage::

        tracker = SubdirectoryHintTracker(working_dir="/path/to/project")

        # After each tool call:
        hints = tracker.check_tool_call("read_file", {"path": "backend/src/main.py"})
        if hints:
            tool_result += hints  # append to the tool result string
    """

    def __init__(self, working_dir: Optional[str] = None):
        self.working_dir = Path(working_dir or os.getcwd()).resolve()
        self._loaded_dirs: Set[Path] = set()
        # Pre-mark the working dir as loaded (startup context handles it)
        self._loaded_dirs.add(self.working_dir)

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> Optional[str]:
        """Check tool call arguments for new directories and load any hint files.

        Returns formatted hint text to append to the tool result, or None.
        """
        dirs = self._extract_directories(tool_name, tool_args)
        if not dirs:
            return None

        all_hints = []
        for d in dirs:
            hints = self._load_hints_for_directory(d)
            if hints:
                all_hints.append(hints)

        if not all_hints:
            return None

        return "\n\n" + "\n\n".join(all_hints)

    def _extract_directories(
        self, tool_name: str, args: Dict[str, Any]
    ) -> list:
        """Extract directory paths from tool call arguments."""
        candidates: Set[Path] = set()

        # Direct path arguments
        for key in _PATH_ARG_KEYS:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                self._add_path_candidate(val, candidates)

        # Shell commands — extract path-like tokens
        if tool_name in _COMMAND_TOOLS:
            cmd = args.get("command", "")
            if isinstance(cmd, str):
                self._extract_paths_from_command(cmd, candidates)

        return list(candidates)

    def _add_path_candidate(self, raw_path: str, candidates: Set[Path]):
        """Resolve a raw path and add its directory + ancestors to candidates.

        Walks up from the resolved directory toward the filesystem root,
        stopping at the first directory already in ``_loaded_dirs`` (or after
        ``_MAX_ANCESTOR_WALK`` levels).  This ensures that reading
        ``project/src/main.py`` discovers ``project/AGENTS.md`` even when
        ``project/src/`` has no hint files of its own.
        """
        try:
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = self.working_dir / p
            p = p.resolve()
            # Use parent if it's a file path (has extension or doesn't exist as dir)
            if p.suffix or (p.exists() and p.is_file()):
                p = p.parent
            # Walk up ancestors — stop at already-loaded or root
            for _ in range(_MAX_ANCESTOR_WALK):
                if p in self._loaded_dirs:
                    break
                if self._is_valid_subdir(p):
                    candidates.add(p)
                parent = p.parent
                if parent == p:
                    break  # filesystem root
                p = parent
        except (OSError, ValueError):
            pass

    def _extract_paths_from_command(self, cmd: str, candidates: Set[Path]):
        """Extract path-like tokens from a shell command string."""
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()

        for token in tokens:
            # Skip flags
            if token.startswith("-"):
                continue
            # Must look like a path (contains / or .)
            if "/" not in token and "." not in token:
                continue
            # Skip URLs
            if token.startswith(("http://", "https://", "git@")):
                continue
            self._add_path_candidate(token, candidates)

    def _is_valid_subdir(self, path: Path) -> bool:
        """Check if path is a valid directory to scan for hints."""
        try:
            if not path.is_dir():
                return False
        except OSError:
            return False
        if path in self._loaded_dirs:
            return False
        return True

    def _display_rel(self, path: Path) -> str:
        """Best-effort path relative to working_dir or home."""
        try:
            return str(path.relative_to(self.working_dir))
        except ValueError:
            try:
                return "~/" + str(path.relative_to(Path.home()))
            except ValueError:
                return str(path)

    def _read_hint_file(self, hint_path: Path) -> Optional[tuple]:
        """Read and sanitize one hint file. Returns (rel_path, content) or None."""
        try:
            if not hint_path.is_file():
                return None
            content = hint_path.read_text(encoding="utf-8").strip()
            if not content:
                return None
            rel_path = self._display_rel(hint_path)
            content = _scan_context_content(content, rel_path)
            if len(content) > _MAX_HINT_CHARS:
                content = (
                    content[:_MAX_HINT_CHARS]
                    + f"\n\n[...truncated {hint_path.name}: {len(content):,} chars total]"
                )
            return (rel_path, content)
        except Exception as exc:
            logger.debug("Could not read %s: %s", hint_path, exc)
            return None

    def _load_hints_for_directory(self, directory: Path) -> Optional[str]:
        """Load hint files from a directory. Returns formatted text or None."""
        self._loaded_dirs.add(directory)

        found_hints = []
        for filename in _HINT_FILENAMES:
            loaded = self._read_hint_file(directory / filename)
            if loaded:
                found_hints.append(loaded)
                # First match wins per directory (like startup loading)
                break

        # Also surface package-local Cursor rules even when AGENTS.md won above.
        rules_dir = directory / ".cursor" / "rules"
        if rules_dir.is_dir():
            try:
                mdc_files = sorted(rules_dir.glob("*.mdc"))
            except OSError:
                mdc_files = []
            for mdc_file in mdc_files:
                loaded = self._read_hint_file(mdc_file)
                if loaded:
                    found_hints.append(loaded)

        # Package identity helps in monorepos when no AGENTS.md is present.
        # Only for classic package roots (apps/foo, packages/bar) to avoid noise.
        if not found_hints and directory.parent.name in {
            "apps",
            "packages",
            "services",
            "libs",
            "crates",
            "modules",
        }:
            package_json = directory / "package.json"
            try:
                if package_json.is_file():
                    import json

                    data = json.loads(package_json.read_text(encoding="utf-8"))
                    name = data.get("name")
                    if isinstance(name, str) and name.strip():
                        rel = self._display_rel(directory)
                        found_hints.append(
                            (
                                f"{rel}/package.json",
                                f"Package workspace: `{name.strip()}` em `{rel}`. "
                                "Use este package como alvo para install/build/test "
                                "neste caminho (filter do monorepo quando aplicável).",
                            )
                        )
            except Exception as exc:
                logger.debug("Could not read package.json in %s: %s", directory, exc)

        if not found_hints:
            return None

        sections = []
        for rel_path, content in found_hints:
            sections.append(
                f"[Subdirectory context discovered: {rel_path}]\n{content}"
            )

        logger.debug(
            "Loaded subdirectory hints from %s: %s",
            directory,
            [h[0] for h in found_hints],
        )
        return "\n\n".join(sections)
