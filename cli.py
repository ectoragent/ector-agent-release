#!/usr/bin/env python3
"""
Legacy EctorCLI module — slash-command backend for gateway paths.

Interactive chat uses the web dashboard via ``ector``. This module remains for
``EctorCLI.process_command()`` in-process slash runner and narrow
``python cli.py --list-tools`` listing.

Preferred usage:
    ector                    # web dashboard
"""

import logging
import os
import re
import shutil
import sys
import json
import re
import concurrent.futures
import base64
import atexit
import errno
import tempfile
import time
import uuid
import textwrap
from urllib.parse import unquote, urlparse
from contextlib import contextmanager, nullcontext
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Suppress startup messages for clean CLI experience
os.environ["ECTOR_QUIET"] = "1"

import yaml

# prompt_toolkit for fixed input area TUI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl, ConditionalContainer
from prompt_toolkit.layout.processors import Processor, Transformation, PasswordProcessor, ConditionalProcessor
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
try:
    from prompt_toolkit.cursor_shapes import CursorShape
    _STEADY_CURSOR = CursorShape.BLOCK  # Non-blinking block cursor
except (ImportError, AttributeError):
    _STEADY_CURSOR = None
import threading
import queue

from agent.usage_pricing import (
    CanonicalUsage,
    estimate_usage_cost,
    format_duration_compact,
    format_token_count_compact,
)
from agent.account_usage import fetch_account_usage, render_account_usage_lines
from ector_cli.presentation import _format_context_length

_COMMAND_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


# Load .env from ~/.ector/.env first, then project root as dev fallback.
# User-managed env files should override stale shell exports on restart.
from ector_constants import get_ector_home, display_ector_home, safe_getcwd
from ector_cli.env_loader import load_ector_dotenv
from utils import base_url_host_matches

_ector_home = get_ector_home()
_project_env = Path(__file__).parent / '.env'
load_ector_dotenv(ector_home=_ector_home, project_env=_project_env)


_REASONING_TAGS = (
    "REASONING_SCRATCHPAD",
    "think",
    "thinking",
    "reasoning",
    "thought",
)


def _strip_reasoning_tags(text: str) -> str:
    """Remove reasoning/thinking blocks from displayed text.

    Handles every case:
      * Closed pairs ``<tag>…</tag>`` (case-insensitive, multi-line).
      * Unterminated open tags that run to end-of-text (e.g. truncated
        generations on NIM/MiniMax where the close tag is dropped).
      * Stray orphan close tags (``stuff</think>answer``) left behind by
        partial-content dumps.

    Covers the variants emitted by reasoning models today: ``<think>``,
    ``<thinking>``, ``<reasoning>``, ``<REASONING_SCRATCHPAD>``, and
    ``<thought>`` (Gemma 4).  Must stay in sync with
    ``run_agent.py::_strip_think_blocks`` and the stream consumer's
    ``_OPEN_THINK_TAGS`` / ``_CLOSE_THINK_TAGS`` tuples.

    Also strips tool-call XML blocks some open models leak into visible
    content (``<tool_call>``, ``<function_calls>``, Gemma-style
    ``<function name="…">…</function>``) when models emit tool calls as
    XML in content instead of the structured ``tool_calls`` field.
    """
    cleaned = text
    for tag in _REASONING_TAGS:
        # Closed pair — case-insensitive so <THINK>…</THINK> is handled too.
        cleaned = re.sub(
            rf"<{tag}>.*?</{tag}>\s*",
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Unterminated open tag — strip from the tag to end of text.
        cleaned = re.sub(
            rf"<{tag}>.*$",
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Stray orphan close tag left behind by partial dumps.
        cleaned = re.sub(
            rf"</{tag}>\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    # Tool-call XML blocks in assistant content.
    for tc_tag in ("tool_call", "tool_calls", "tool_result",
                   "function_call", "function_calls"):
        cleaned = re.sub(
            rf"<{tc_tag}\b[^>]*>.*?</{tc_tag}>\s*",
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # <function name="..."> — boundary + attribute gated to avoid prose FPs.
    cleaned = re.sub(
        r'(?:(?<=^)|(?<=[\n\r.!?:]))[ \t]*'
        r'<function\b[^>]*\bname\s*=[^>]*>'
        r'(?:(?:(?!</function>).)*)</function>\s*',
        '',
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Stray tool-call close tags.
    cleaned = re.sub(
        r'</(?:tool_call|tool_calls|tool_result|function_call|function_calls|function)>\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _assistant_content_as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p)
    return str(content)


def _assistant_copy_text(content: Any) -> str:
    return _strip_reasoning_tags(_assistant_content_as_text(content))


# =============================================================================
# Configuration Loading
# =============================================================================

def _load_prefill_messages(file_path: str) -> List[Dict[str, Any]]:
    """Load ephemeral prefill messages from a JSON file.
    
    The file should contain a JSON array of {role, content} dicts, e.g.:
        [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}]
    
    Relative paths are resolved from ~/.ector/.
    Returns an empty list if the path is empty or the file doesn't exist.
    """
    if not file_path:
        return []
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = _ector_home / path
    if not path.exists():
        logger.warning("Prefill messages file not found: %s", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning("Prefill messages file must contain a JSON array: %s", path)
            return []
        return data
    except Exception as e:
        logger.warning("Failed to load prefill messages from %s: %s", path, e)
        return []


def _parse_reasoning_config(effort: str) -> dict | None:
    """Parse a reasoning effort level into an OpenRouter reasoning config dict."""
    from ector_constants import parse_reasoning_effort
    result = parse_reasoning_effort(effort)
    if effort and effort.strip() and result is None:
        logger.warning("Unknown reasoning_effort '%s', using default (medium)", effort)
    return result


def _parse_service_tier_config(raw: str) -> str | None:
    """Parse a persisted service-tier preference into a Responses API value."""
    value = str(raw or "").strip().lower()
    if not value or value in {"normal", "default", "standard", "off", "none"}:
        return None
    if value in {"fast", "priority", "on"}:
        return "priority"
    logger.warning("Unknown service_tier '%s', ignoring", raw)
    return None



def _get_chrome_debug_candidates(system: str) -> list[str]:
    """Return likely browser executables for local CDP auto-launch."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add_candidate(path: str | None) -> None:
        if not path:
            return
        normalized = os.path.normcase(os.path.normpath(path))
        if normalized in seen:
            return
        if os.path.isfile(path):
            candidates.append(path)
            seen.add(normalized)

    def _add_from_path(*names: str) -> None:
        for name in names:
            _add_candidate(shutil.which(name))

    if system == "Darwin":
        for app in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            _add_candidate(app)
    elif system == "Windows":
        _add_from_path(
            "chrome.exe", "msedge.exe", "brave.exe", "chromium.exe",
            "chrome", "msedge", "brave", "chromium",
        )

        for base in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if not base:
                continue
            for parts in (
                ("Google", "Chrome", "Application", "chrome.exe"),
                ("Chromium", "Application", "chrome.exe"),
                ("Chromium", "Application", "chromium.exe"),
                ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
                ("Microsoft", "Edge", "Application", "msedge.exe"),
            ):
                _add_candidate(os.path.join(base, *parts))
    else:
        _add_from_path(
            "google-chrome", "google-chrome-stable", "chromium-browser",
            "chromium", "brave-browser", "microsoft-edge",
        )

    return candidates


from ector_cli.cli_config import CLI_CONFIG, load_cli_config  # noqa: E402


# Initialize centralized logging early — agent.log + errors.log in ~/.ector/logs/
# This ensures CLI sessions produce a log trail even before AIAgent is instantiated.
try:
    from ector_logging import setup_logging
    setup_logging(mode="cli")
except Exception:
    pass  # Logging setup is best-effort — don't crash the CLI

# Validate config structure early — print warnings before user hits cryptic errors
try:
    from ector_cli.config import print_config_warnings
    print_config_warnings()
except Exception:
    pass

# Skin engine removed - using hardcoded ECTOR theme

# Initialize tool preview length from config
try:
    from agent.display import set_tool_preview_max_len
    _tpl = CLI_CONFIG.get("display", {}).get("tool_preview_length", 0)
    set_tool_preview_max_len(int(_tpl) if _tpl else 0)
except Exception:
    pass

# Neuter AsyncHttpxClientWrapper.__del__ before any AsyncOpenAI clients are
# created.  The SDK's __del__ schedules aclose() on asyncio.get_running_loop()
# which, during CLI idle time, finds prompt_toolkit's event loop and tries to
# close TCP transports bound to dead worker loops — producing
# "Event loop is closed" / "Press ENTER to continue..." errors.
try:
    from agent.auxiliary_client import neuter_async_httpx_del
    neuter_async_httpx_del()
except Exception:
    pass

from rich import box as rich_box
from rich.console import Console, Group
from rich.markup import escape as _escape
from rich.panel import Panel
from rich.table import Table as _RichTable
from rich.text import Text as _RichText

import fire

# Import the agent and tool systems
from run_agent import AIAgent
from model_tools import get_tool_definitions, get_toolset_for_tool

# Extracted CLI modules (Phase 3)
from ector_cli.commands import SlashCommandCompleter, SlashCommandAutoSuggest
from toolsets import get_all_toolsets, get_toolset_info, validate_toolset

# Cron job system for scheduled tasks (execution is handled by the gateway)
from cron import get_job

# Resource cleanup imports for safe shutdown (terminal VMs, browser sessions)
from tools.terminal_tool import cleanup_all_environments as _cleanup_all_terminals
from tools.terminal_tool import set_sudo_password_callback, set_approval_callback
from tools.skills_tool import set_secret_capture_callback
from ector_cli.callbacks import prompt_for_secret
from tools.browser_tool import _emergency_cleanup_all_sessions as _cleanup_all_browsers

# Guard to prevent cleanup from running multiple times on exit
_cleanup_done = False
# Weak reference to the active AIAgent for memory provider shutdown at exit
_active_agent_ref = None

def _run_cleanup():
    """Run resource cleanup exactly once."""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    try:
        _cleanup_all_terminals()
    except Exception:
        pass
    try:
        _cleanup_all_browsers()
    except Exception:
        pass
    try:
        from tools.mcp_tool import shutdown_mcp_servers
        shutdown_mcp_servers()
    except Exception:
        pass
    # Close cached auxiliary LLM clients (sync + async) so that
    # AsyncHttpxClientWrapper.__del__ doesn't fire on a closed event loop
    # and trigger prompt_toolkit's "Press ENTER to continue..." handler.
    try:
        from agent.auxiliary_client import shutdown_cached_clients
        shutdown_cached_clients()
    except Exception:
        pass
    # Shut down memory provider (on_session_end + shutdown_all) at actual
    # session boundary — NOT per-turn inside run_conversation().
    try:
        from ector_cli.plugins import invoke_hook as _invoke_hook
        _invoke_hook("on_session_finalize", session_id=_active_agent_ref.session_id if _active_agent_ref else None, platform="cli")
    except Exception:
        pass
    try:
        if _active_agent_ref and hasattr(_active_agent_ref, 'shutdown_memory_provider'):
            _active_agent_ref.shutdown_memory_provider(
                getattr(_active_agent_ref, 'conversation_history', None) or []
            )
    except Exception:
        pass


# =============================================================================
# Git worktree — see ector_cli/worktree.py
from ector_cli.worktree import (
    _active_worktree,
    _cleanup_worktree,
    _git_repo_root,
    _path_is_within_root,
    _prune_orphaned_branches,
    _prune_stale_worktrees,
    _setup_worktree,
)

def _run_state_db_auto_maintenance(session_db) -> None:
    """Call ``SessionDB.maybe_auto_prune_and_vacuum`` using current config.

    Reads the ``sessions:`` section from config.yaml via
    :func:`ector_cli.config.load_config` (the authoritative loader that
    deep-merges DEFAULT_CONFIG, so unmigrated configs still get default
    values). Honours ``auto_prune`` / ``retention_days`` /
    ``vacuum_after_prune`` / ``min_interval_hours``, and delegates to the
    DB. Never raises — maintenance must never block interactive startup.
    """
    if session_db is None:
        return
    try:
        from ector_cli.config import load_config as _load_full_config
        from ector_constants import get_ector_home as _get_ector_home
        cfg = (_load_full_config().get("sessions") or {})
        if not cfg.get("auto_prune", False):
            return
        session_db.maybe_auto_prune_and_vacuum(
            retention_days=int(cfg.get("retention_days", 90)),
            min_interval_hours=int(cfg.get("min_interval_hours", 24)),
            vacuum=bool(cfg.get("vacuum_after_prune", True)),
            sessions_dir=_get_ector_home() / "sessions",
        )
    except Exception as exc:
        logger.debug("state.db auto-maintenance skipped: %s", exc)


def _run_checkpoint_auto_maintenance() -> None:
    """Call ``checkpoint_manager.maybe_auto_prune_checkpoints`` using current config.

    Reads the ``checkpoints:`` section from config.yaml via
    :func:`ector_cli.config.load_config`. Honours ``auto_prune`` /
    ``retention_days`` / ``delete_orphans`` / ``min_interval_hours``.
    Never raises — maintenance must never block interactive startup.
    """
    try:
        from ector_cli.config import load_config as _load_full_config
        cfg = (_load_full_config().get("checkpoints") or {})
        if not cfg.get("auto_prune", False):
            return
        from tools.checkpoint_manager import maybe_auto_prune_checkpoints
        maybe_auto_prune_checkpoints(
            retention_days=int(cfg.get("retention_days", 7)),
            min_interval_hours=int(cfg.get("min_interval_hours", 24)),
            delete_orphans=bool(cfg.get("delete_orphans", True)),
        )
    except Exception as exc:
        logger.debug("checkpoint auto-maintenance skipped: %s", exc)


def _hex_to_ansi(hex_color: str, *, bold: bool = False) -> str:
    """Convert a hex color like '#268bd2' to a true-color ANSI escape."""
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        prefix = "1;" if bold else ""
        return f"\033[{prefix}38;2;{r};{g};{b}m"
    except (ValueError, IndexError):
        return _ACCENT_ANSI_DEFAULT if bold else "\033[38;2;72;61;139m"


_ACCENT = _hex_to_ansi("#00D1FF", bold=True)
_DIM = _hex_to_ansi("#00D1FF")


def _accent_hex() -> str:
    """Return the global accent color for legacy CLI output lines."""
    return "#00D1FF"


def _rich_text_from_ansi(text: str) -> _RichText:
    """Safely render assistant/tool output that may contain ANSI escapes.

    Using Rich Text.from_ansi preserves literal bracketed text like
    ``[not markup]`` while still interpreting real ANSI color codes.
    """
    return _RichText.from_ansi(text or "")


def _strip_markdown_syntax(text: str) -> str:
    """Best-effort markdown marker removal for plain-text display."""
    plain = _rich_text_from_ansi(text or "").plain
    plain = re.sub(r"^\s{0,3}(?:[-*_]\s*){3,}$", "", plain, flags=re.MULTILINE)
    plain = re.sub(r"^\s{0,3}#{1,6}\s+", "", plain, flags=re.MULTILINE)
    # Preserve blockquotes, lists, and checkboxes because they carry structure.
    plain = re.sub(r"(```+|~~~+)", "", plain)
    plain = re.sub(r"`([^`]*)`", r"\1", plain)
    plain = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", plain)
    plain = re.sub(r"\*\*\*([^*]+)\*\*\*", r"\1", plain)
    plain = re.sub(r"(?<!\w)___([^_]+)___(?!\w)", r"\1", plain)
    plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", plain)
    plain = re.sub(r"(?<!\w)__([^_]+)__(?!\w)", r"\1", plain)
    plain = re.sub(r"\*([^*]+)\*", r"\1", plain)
    plain = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", plain)
    plain = re.sub(r"~~([^~]+)~~", r"\1", plain)
    plain = re.sub(r"\n{3,}", "\n\n", plain)
    return plain.strip("\n")


def _render_final_assistant_content(text: str, mode: str = "render"):
    """Render final assistant content as markdown, stripped text, or raw text."""
    from rich.markdown import Markdown

    normalized_mode = str(mode or "render").strip().lower()
    if normalized_mode == "strip":
        return _RichText(_strip_markdown_syntax(text))
    if normalized_mode == "raw":
        return _rich_text_from_ansi(text or "")

    plain = _rich_text_from_ansi(text or "").plain
    return Markdown(plain)


def _cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's native renderer.

    Raw ANSI escapes written via print() are swallowed by patch_stdout's
    StdoutProxy.  Routing through print_formatted_text(ANSI(...)) lets
    prompt_toolkit parse the escapes and render real colors.
    """
    _pt_print(_PT_ANSI(text))


# ---------------------------------------------------------------------------
# File-drop / local attachment detection (shared module + CLI-only helpers).
# ---------------------------------------------------------------------------

from ector_cli.attachments import (
    IMAGE_EXTENSIONS as _IMAGE_EXTENSIONS,
    collect_query_images as _collect_query_images,
    detect_file_drop as _detect_file_drop,
    resolve_attachment_path as _resolve_attachment_path,
    split_path_input as _split_path_input,
    termux_example_image_path as _termux_example_image_path,
)
from ector_constants import is_termux as _is_termux_environment


def _format_process_notification(evt: dict) -> "str | None":
    """Format a process notification event into a [IMPORTANT: ...] message.

    Handles both completion events (notify_on_complete) and watch pattern
    match events from the unified completion_queue.
    """
    evt_type = evt.get("type", "completion")
    _sid = evt.get("session_id", "unknown")
    _cmd = evt.get("command", "unknown")

    if evt_type == "watch_disabled":
        return f"[IMPORTANT: {evt.get('message', '')}]"

    if evt_type == "watch_match":
        _pat = evt.get("pattern", "?")
        _out = evt.get("output", "")
        _sup = evt.get("suppressed", 0)
        text = (
            f"[IMPORTANT: Background process {_sid} matched "
            f"watch pattern \"{_pat}\".\n"
            f"Command: {_cmd}\n"
            f"Matched output:\n{_out}"
        )
        if _sup:
            text += f"\n({_sup} earlier matches were suppressed by rate limit)"
        text += "]"
        return text

    # Default: completion event
    _exit = evt.get("exit_code", "?")
    _out = evt.get("output", "")
    return (
        f"[IMPORTANT: Background process {_sid} completed "
        f"(exit code {_exit}).\n"
        f"Command: {_cmd}\n"
        f"Output:\n{_out}]"
    )


def _format_image_attachment_badges(attached_images: list[Path], image_counter: int, width: int | None = None) -> str:
    """Format the attached-image badge row for the interactive CLI.

    Narrow terminals such as Termux should get a compact summary that fits on a
    single row, while wider terminals can show the classic per-image badges.
    """
    if not attached_images:
        return ""

    width = width or shutil.get_terminal_size((80, 24)).columns

    def _trunc(name: str, limit: int) -> str:
        return name if len(name) <= limit else name[: max(1, limit - 3)] + "..."

    if width < 52:
        if len(attached_images) == 1:
            return f"[📎 {_trunc(attached_images[0].name, 20)}]"
        return f"[📎 {len(attached_images)} images attached]"

    if width < 80:
        if len(attached_images) == 1:
            return f"[📎 {_trunc(attached_images[0].name, 32)}]"
        first = _trunc(attached_images[0].name, 20)
        extra = len(attached_images) - 1
        return f"[📎 {first}] [+{extra}]"

    base = image_counter - len(attached_images) + 1
    return " ".join(
        f"[📎 Image #{base + i}]"
        for i in range(len(attached_images))
    )


def _should_auto_attach_clipboard_image_on_paste(pasted_text: str) -> bool:
    """Auto-attach clipboard images only for image-only paste gestures."""
    return not pasted_text.strip()


def _strip_leaked_bracketed_paste_wrappers(text: str) -> str:
    """Strip leaked bracketed-paste wrapper markers from user-visible text.

    Defensive normalization for cases where terminal/prompt_toolkit parsing
    fails and bracketed-paste markers end up in the buffer as literal text.

    We strip canonical wrappers unconditionally and also handle degraded
    visible forms like ``[200~`` / ``[201~`` and ``00~`` / ``01~`` when they
    look like wrapper boundaries, not arbitrary user content.
    """
    if not text:
        return text

    text = (
        text.replace("\x1b[200~", "")
        .replace("\x1b[201~", "")
        .replace("^[[200~", "")
        .replace("^[[201~", "")
    )
    text = re.sub(r"(^|[\s\n>:\]\)])\[200~", r"\1", text)
    text = re.sub(r"\[201~(?=$|[\s\n<\[\(\):;.,!?])", "", text)
    text = re.sub(r"(^|[\s\n>:\]\)])00~", r"\1", text)
    text = re.sub(r"01~(?=$|[\s\n<\[\(\):;.,!?])", "", text)
    return text


# Cursor Position Report (CPR / DSR) response, format ``ESC[<row>;<col>R``.
# prompt_toolkit's _on_resize() + renderer send ``ESC[6n`` queries to the
# terminal; under resize storms or tab switches the terminal's reply can
# race past the input parser and end up in the input buffer as literal
# text (see issue #14692). Also matches the visible-form ``^[[<row>;<col>R``
# that appears when the ESC byte was stripped by a prior filter.
_DSR_CPR_ESC_RE = re.compile(r"\x1b\[\d+;\d+R")
_DSR_CPR_VISIBLE_RE = re.compile(r"\^\[\[\d+;\d+R")


def _strip_leaked_terminal_responses(text: str) -> str:
    """Strip leaked terminal control-response sequences from user input.

    Covers Cursor Position Report (CPR / DSR) responses — ``ESC[<row>;<col>R``
    and the visible ``^[[<row>;<col>R`` form. These are replies the terminal
    sends back to queries prompt_toolkit makes during ``_on_resize`` /
    ``_request_absolute_cursor_position``. When the input parser drops one
    (resize storms, multiplexer focus changes, slow PTYs) the response
    lands in the input buffer as literal text and corrupts what the user
    typed.
    """
    if not text:
        return text
    text = _DSR_CPR_ESC_RE.sub("", text)
    text = _DSR_CPR_VISIBLE_RE.sub("", text)
    return text


class ChatConsole:
    """Rich Console adapter for prompt_toolkit's patch_stdout context.

    Captures Rich's rendered ANSI output and routes it through _cprint
    so colors and markup render correctly inside the interactive chat loop.
    Drop-in replacement for Rich Console — just pass this to any function
    that expects a console.print() interface.
    """

    def __init__(self):
        from io import StringIO
        self._buffer = StringIO()
        self._inner = Console(
            file=self._buffer,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
        )

    def print(self, *args, **kwargs):
        self._buffer.seek(0)
        self._buffer.truncate()
        # Read terminal width at render time so panels adapt to current size
        self._inner.width = shutil.get_terminal_size((80, 24)).columns
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        for line in output.rstrip("\n").split("\n"):
            _cprint(line)

    @contextmanager
    def status(self, *_args, **_kwargs):
        """Provide a no-op Rich-compatible status context.

        Some slash command helpers use ``console.status(...)`` when running in
        the standalone CLI. Interactive chat routes those helpers through
        ``ChatConsole()``, which historically only implemented ``print()``.
        Returning a silent context manager keeps slash commands compatible
        without duplicating the higher-level busy indicator already shown by
        ``EctorCLI._busy_command()``.
        """
        yield self

# ============================================================================
# Slash-command detection helper
# ============================================================================

def _looks_like_slash_command(text: str) -> bool:
    """Return True if *text* looks like a slash command, not a file path.

    Slash commands are ``/help``, ``/provider gpt-4``, ``/q``, etc.
    File paths like ``/Users/ironin/file.md:45-46 can you fix this?``
    also start with ``/`` but contain additional ``/`` characters in
    the first whitespace-delimited word.  This helper distinguishes
    the two so that pasted paths are sent to the agent instead of
    triggering "Unknown command".
    """
    if not text or not text.startswith("/"):
        return False
    first_word = text.split()[0]
    # After stripping the leading /, a command name has no slashes.
    # A path like /Users/foo/bar.md always does.
    return "/" not in first_word[1:]


# ============================================================================
# Skill Slash Commands — dynamic commands generated from installed skills
# ============================================================================

from agent.skill_commands import (
    scan_skill_commands,
    build_skill_invocation_message,
    build_preloaded_skills_prompt,
)

_skill_commands = scan_skill_commands()


def sync_skill_commands_from_agent() -> None:
    """Keep CLI module-level slash commands in sync with agent.skill_commands."""
    global _skill_commands
    _skill_commands = scan_skill_commands()


def _get_plugin_cmd_handler_names() -> set:
    """Return plugin command names (without slash prefix) for dispatch matching."""
    try:
        from ector_cli.plugins import get_plugin_manager
        return set(get_plugin_manager()._plugin_commands.keys())
    except Exception:
        return set()


def _parse_skills_argument(skills: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize a CLI skills flag into a deduplicated list of skill identifiers."""
    if not skills:
        return []

    if isinstance(skills, str):
        raw_values = [skills]
    elif isinstance(skills, (list, tuple)):
        raw_values = [str(item) for item in skills if item is not None]
    else:
        raw_values = [str(skills)]

    parsed: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for part in raw.split(","):
            normalized = part.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)
    return parsed


from ector_cli.config import save_config_value




# ============================================================================
# EctorCLI Class
# ============================================================================

class EctorCLI:
    """
    Interactive CLI for the ECTOR Agent.
    
    Provides a REPL interface with rich formatting, command history,
    and tool execution capabilities.
    """
    
    def __init__(
        self,
        model: str = None,
        toolsets: List[str] = None,
        provider: str = None,
        api_key: str = None,
        base_url: str = None,
        max_turns: int = None,
        verbose: bool = False,
        resume: str = None,
        checkpoints: bool = False,
        pass_session_id: bool = False,
        ignore_rules: bool = False,
    ):
        """
        Initialize the ECTOR CLI.

        Args:
            model: Model to use (default: from env or claude-sonnet)
            toolsets: List of toolsets to enable (default: all)
            provider: Inference provider ("auto", "openrouter", "ector", "openai-codex", "zai", "kimi-coding", "minimax", "minimax-cn")
            api_key: API key (default: from environment)
            base_url: API base URL (default: OpenRouter)
            max_turns: Maximum tool-calling iterations shared with subagents (default: 90)
            verbose: Enable verbose logging
            resume: Session ID to resume (restores conversation history from SQLite)
            pass_session_id: Include the session ID in the agent's system prompt
        """
        # Initialize Rich console
        self.console = Console()
        self.config = CLI_CONFIG
        # tool_progress: "off", "new", "all", "verbose" (from config.yaml display section)
        # YAML 1.1 parses bare `off` as boolean False — normalise to string.
        _raw_tp = CLI_CONFIG["display"].get("tool_progress", "all")
        self.tool_progress_mode = "off" if _raw_tp is False else str(_raw_tp)
        # resume_display: "full" (show history) | "minimal" (one-liner only)
        self.resume_display = CLI_CONFIG["display"].get("resume_display", "full")
        # bell_on_complete: play terminal bell (\a) when agent finishes a response
        self.bell_on_complete = CLI_CONFIG["display"].get("bell_on_complete", False)
        # show_reasoning: display model thinking/reasoning before the response
        self.show_reasoning = CLI_CONFIG["display"].get("show_reasoning", True)
        self.show_cost = bool(CLI_CONFIG["display"].get("show_cost", False))
        # busy_input_mode: "interrupt" (Enter interrupts current run),
        # "queue" (Enter queues for next turn), or "steer" (Enter injects
        # mid-run via /steer, arriving after the next tool call).
        _bim = str(CLI_CONFIG["display"].get("busy_input_mode", "interrupt")).strip().lower()
        if _bim == "queue":
            self.busy_input_mode = "queue"
        elif _bim == "steer":
            self.busy_input_mode = "steer"
        else:
            self.busy_input_mode = "interrupt"

        self.verbose = verbose if verbose is not None else (self.tool_progress_mode == "verbose")
        
        # streaming: stream tokens to the terminal as they arrive (display.streaming in config.yaml)
        self.streaming_enabled = CLI_CONFIG["display"].get("streaming", True)
        self.final_response_markdown = str(
            CLI_CONFIG["display"].get("final_response_markdown", "strip")
        ).strip().lower() or "strip"
        if self.final_response_markdown not in {"render", "strip", "raw"}:
            self.final_response_markdown = "strip"

        # Inline diff previews for write actions (display.inline_diffs in config.yaml)
        self._inline_diffs_enabled = CLI_CONFIG["display"].get("inline_diffs", True)

        # Submitted multiline user-message preview (display.user_message_preview in config.yaml)
        _ump = CLI_CONFIG["display"].get("user_message_preview", {})
        if not isinstance(_ump, dict):
            _ump = {}
        try:
            _ump_first_lines = int(_ump.get("first_lines", 2))
        except (TypeError, ValueError):
            _ump_first_lines = 2
        try:
            _ump_last_lines = int(_ump.get("last_lines", 2))
        except (TypeError, ValueError):
            _ump_last_lines = 2
        self.user_message_preview_first_lines = max(1, _ump_first_lines)
        self.user_message_preview_last_lines = max(0, _ump_last_lines)

        # Streaming display state
        self._stream_buf = ""        # Partial line buffer for line-buffered rendering
        self._stream_started = False  # True once first delta arrives
        self._stream_box_opened = False  # True once the response box header is printed
        self._reasoning_preview_buf = ""  # Coalesce tiny reasoning chunks for [thinking] output
        self._pending_edit_snapshots = {}
        
        # Configuration - priority: CLI args > env vars > config file
        # Model comes from: CLI arg or config.yaml (single source of truth).
        # LLM_MODEL/OPENAI_MODEL env vars are NOT checked — config.yaml is
        # authoritative.  This avoids conflicts in multi-agent setups where
        # env vars would stomp each other.
        _model_config = CLI_CONFIG.get("model", {})
        _config_model = (_model_config.get("default") or _model_config.get("model") or "") if isinstance(_model_config, dict) else (_model_config or "")
        _DEFAULT_CONFIG_MODEL = ""
        self.model = model or _config_model or _DEFAULT_CONFIG_MODEL
        # Auto-detect model from local server if still on default
        if self.model == _DEFAULT_CONFIG_MODEL:
            _base_url = (_model_config.get("base_url") or "") if isinstance(_model_config, dict) else ""
            if "localhost" in _base_url or "127.0.0.1" in _base_url:
                from ector_cli.runtime_provider import _auto_detect_local_model
                _detected = _auto_detect_local_model(_base_url)
                if _detected:
                    self.model = _detected
        # Track whether model was explicitly chosen by the user or fell back
        # to the global default.  Provider-specific normalisation may override
        # the default silently but should warn when overriding an explicit choice.
        # A config model that matches the global fallback is NOT considered an
        # explicit choice — the user just never changed it.  But a config model
        # like "gpt-5.3-codex" IS explicit and must be preserved.
        self._model_is_default = not model and (
            not _config_model or _config_model == _DEFAULT_CONFIG_MODEL
        )

        self._explicit_api_key = api_key
        self._explicit_base_url = base_url

        # Provider selection is resolved lazily at use-time via _ensure_runtime_credentials().
        self.requested_provider = (
            provider
            or CLI_CONFIG["model"].get("provider")
            or os.getenv("ECTOR_INFERENCE_PROVIDER")
            or "auto"
        )
        self._provider_source: Optional[str] = None
        self.provider = self.requested_provider
        self.api_mode = "chat_completions"
        self.acp_command: Optional[str] = None
        self.acp_args: list[str] = []
        self.base_url = (
            base_url
            or CLI_CONFIG["model"].get("base_url", "")
            or os.getenv("OPENROUTER_BASE_URL", "")
        ) or None
        # Match key to resolved base_url: OpenRouter URL → prefer OPENROUTER_API_KEY,
        # custom endpoint → prefer OPENAI_API_KEY (issue #560).
        # Note: _ensure_runtime_credentials() re-resolves this before first use.
        if self.base_url and base_url_host_matches(self.base_url, "openrouter.ai"):
            self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        else:
            self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        # Max turns priority: CLI arg > config file > env var > default
        if max_turns is not None:  # CLI arg was explicitly set
            self.max_turns = max_turns
        elif CLI_CONFIG["agent"].get("max_turns"):
            self.max_turns = CLI_CONFIG["agent"]["max_turns"]
        elif CLI_CONFIG.get("max_turns"):  # Backwards compat: root-level max_turns
            self.max_turns = CLI_CONFIG["max_turns"]
        elif os.getenv("ECTOR_MAX_ITERATIONS"):
            self.max_turns = int(os.getenv("ECTOR_MAX_ITERATIONS"))
        else:
            self.max_turns = 90
        
        # Parse and validate toolsets
        self.enabled_toolsets = toolsets
        if toolsets and "all" not in toolsets and "*" not in toolsets:
            # Validate each toolset — MCP server names are resolved via
            # live registry aliases (registered during discover_mcp_tools),
            # but discovery hasn't run yet at this point, so exclude them.
            mcp_names = set((CLI_CONFIG.get("mcp_servers") or {}).keys())
            invalid = [t for t in toolsets if not validate_toolset(t) and t not in mcp_names]
            if invalid:
                self._console_print(f"[bold red]Aviso: toolsets desconhecidos: {', '.join(invalid)}[/]")
        
        # Filesystem checkpoints: CLI flag > config
        cp_cfg = CLI_CONFIG.get("checkpoints", {})
        if isinstance(cp_cfg, bool):
            cp_cfg = {"enabled": cp_cfg}
        self.checkpoints_enabled = checkpoints or cp_cfg.get("enabled", False)
        self.checkpoint_max_snapshots = cp_cfg.get("max_snapshots", 50)
        self.pass_session_id = pass_session_id
        # --ignore-rules: honor either the constructor flag or the env var set
        # by `ector chat --ignore-rules` in ector_cli/main.py. When true we
        # pass skip_context_files=True and skip_memory=True to AIAgent so
        # AGENTS.md/SOUL.md/.cursorrules and persistent memory are not loaded.
        self.ignore_rules = ignore_rules or os.environ.get("ECTOR_IGNORE_RULES") == "1"
        
        # Ephemeral system prompt: env var takes precedence, then config
        self.system_prompt = (
            os.getenv("ECTOR_EPHEMERAL_SYSTEM_PROMPT", "")
            or CLI_CONFIG["agent"].get("system_prompt", "")
        )
        self.personalities = CLI_CONFIG["agent"].get("personalities", {})
        
        # Ephemeral prefill messages (few-shot priming, never persisted)
        self.prefill_messages = _load_prefill_messages(
            CLI_CONFIG["agent"].get("prefill_messages_file", "")
        )
        
        # Reasoning config (OpenRouter reasoning effort level)
        self.reasoning_config = _parse_reasoning_config(
            CLI_CONFIG["agent"].get("reasoning_effort", "")
        )
        self.service_tier = _parse_service_tier_config(
            CLI_CONFIG["agent"].get("service_tier", "")
        )
        
        # OpenRouter provider routing preferences
        pr = CLI_CONFIG.get("provider_routing", {}) or {}
        self._provider_sort = pr.get("sort")
        self._providers_only = pr.get("only")
        self._providers_ignore = pr.get("ignore")
        self._providers_order = pr.get("order")
        self._provider_require_params = pr.get("require_parameters", False)
        self._provider_data_collection = pr.get("data_collection")
        
        # Fallback provider chain — tried in order when primary fails after retries.
        # Supports new list format (fallback_providers) and legacy single-dict (fallback_model).
        fb = CLI_CONFIG.get("fallback_providers") or CLI_CONFIG.get("fallback_model") or []
        # Normalize legacy single-dict to a one-element list
        if isinstance(fb, dict):
            fb = [fb] if fb.get("provider") and fb.get("model") else []
        self._fallback_model = fb

        # Signature of the currently-initialised agent's runtime.  Used to
        # rebuild the agent when provider / model / base_url changes across
        # turns (e.g. after /provider or credential rotation).
        self._active_agent_route_signature = None

        # Agent will be initialized on first use
        self.agent: Optional[AIAgent] = None
        self._app = None  # prompt_toolkit Application (set in run())
        
        # Conversation state
        self.conversation_history: List[Dict[str, Any]] = []
        self.session_start = datetime.now()
        self._resumed = False
        # Per-prompt elapsed timer — started at the beginning of each chat turn,
        # frozen when the agent thread completes, displayed in the status bar.
        self._prompt_start_time: Optional[float] = None  # time.time() when turn started
        self._prompt_duration: float = 0.0  # frozen duration of last completed turn
        # Initialize SQLite session store early so /title works before first message
        self._session_db = None
        try:
            from ector_state import SessionDB
            self._session_db = SessionDB()
        except Exception as e:
            logger.warning("Failed to initialize SessionDB — session will NOT be indexed for search: %s", e)

        # Opportunistic state.db maintenance — runs at most once per
        # min_interval_hours, tracked via state_meta in state.db itself so
        # it's shared across all ECTOR processes for this ECTOR_HOME.
        # Never blocks startup on failure.
        _run_state_db_auto_maintenance(self._session_db)

        # Opportunistic shadow-repo cleanup — deletes orphan/stale
        # checkpoint repos under ~/.ector/checkpoints/.  Opt-in via
        # checkpoints.auto_prune, idempotent via .last_prune marker.
        _run_checkpoint_auto_maintenance()

        # Deferred title: stored in memory until the session is created in the DB
        self._pending_title: Optional[str] = None
        
        # Session ID: reuse existing one when resuming, otherwise generate fresh
        if resume:
            self.session_id = resume
            self._resumed = True
        else:
            timestamp_str = self.session_start.strftime("%Y%m%d_%H%M%S")
            short_uuid = uuid.uuid4().hex[:6]
            self.session_id = f"{timestamp_str}_{short_uuid}"
        
        # History file for persistent input recall across sessions
        self._history_file = _ector_home / ".ector_history"
        self._last_invalidate: float = 0.0  # throttle UI repaints
        self._app = None

        # State shared by interactive run() and single-query chat mode.
        # These must exist before any direct chat() call because single-query
        # mode does not go through run().
        self._agent_running = False
        self._pending_input = queue.Queue()
        self._interrupt_queue = queue.Queue()
        self._should_exit = False
        self._last_ctrl_c_time = 0
        self._wiser_state = None
        self._wiser_freetext = False
        self._wiser_deadline = 0
        self._sudo_state = None
        self._sudo_deadline = 0
        self._modal_input_snapshot = None
        self._approval_state = None
        self._approval_deadline = 0
        self._approval_lock = threading.Lock()
        self._model_picker_state = None
        self._secret_state = None
        self._secret_deadline = 0
        self._spinner_text: str = ""  # thinking spinner text for TUI
        self._tool_start_time: float = 0.0  # monotonic timestamp when current tool started (for live elapsed)
        self._pending_tool_info: dict = {}  # function_name -> list of (preview, args) for stacked scrollback
        self._last_scrollback_tool: str = ""  # last tool name printed to scrollback (for "new" dedup)
        self._command_running = False
        self._command_status = ""
        self._attached_images: list[Path] = []
        self._image_counter = 0
        self.preloaded_skills: list[str] = []
        self._startup_skills_line_shown = False

        # Voice mode state (also reinitialized inside run() for interactive TUI).
        self._voice_lock = threading.Lock()
        self._voice_mode = False
        self._voice_tts = False
        self._voice_recorder = None
        self._voice_recording = False
        self._voice_processing = False
        self._voice_continuous = False
        self._voice_tts_done = threading.Event()
        self._voice_tts_done.set()

        # Status bar visibility (toggled via /statusbar)
        self._status_bar_visible = True

        # Background task tracking: {task_id: threading.Thread}
        self._background_tasks: Dict[str, threading.Thread] = {}
        self._background_task_counter = 0

    def _invalidate(self, min_interval: float = 0.25) -> None:
        """Throttled UI repaint — prevents terminal blinking on slow/SSH connections."""
        now = time.monotonic()
        if hasattr(self, "_app") and self._app and (now - self._last_invalidate) >= min_interval:
            self._last_invalidate = now
            self._app.invalidate()

    def _force_full_redraw(self) -> None:
        """Force a clean full-screen repaint of the prompt_toolkit UI.

        Used to recover from terminal buffer drift caused by external
        redraws we can't detect — e.g. macOS cmux / tmux tab switches,
        ``clear`` issued from a subshell, or SSH window restores. These
        wipe or repaint the terminal without firing SIGWINCH, so
        prompt_toolkit's tracked ``_cursor_pos`` no longer matches reality
        and the next incremental redraw stacks on top of stale content
        (ghost status bars, duplicated prompts).

        Bound to Ctrl+L and exposed as the ``/redraw`` slash command,
        matching the standard terminal-UX convention (bash, zsh, fish,
        vim, htop).
        """
        app = getattr(self, "_app", None)
        if not app:
            return
        try:
            renderer = app.renderer
            out = renderer.output
            out.reset_attributes()
            out.erase_screen()
            out.cursor_goto(0, 0)
            out.flush()
            # Drop prompt_toolkit's cached screen + cursor state so the
            # next _redraw() starts from a known (0, 0) origin and
            # re-renders every cell rather than diffing against stale.
            renderer.reset(leave_alternate_screen=False)
        except Exception:
            pass
        try:
            app.invalidate()
        except Exception:
            pass

    def _status_bar_context_style(self, percent_used: Optional[int]) -> str:
        if percent_used is None:
            return "class:status-bar-dim"
        if percent_used >= 95:
            return "class:status-bar-critical"
        if percent_used > 80:
            return "class:status-bar-bad"
        if percent_used >= 50:
            return "class:status-bar-warn"
        return "class:status-bar-good"

    def _context_bar_fragments(
        self, percent_used: Optional[int], width: int = 10
    ) -> List[Tuple[str, str]]:
        """Unicode context meter: thin caps + filled blocks + dim track (no [])."""
        safe_percent = max(0, min(100, percent_used or 0))
        filled = round((safe_percent / 100.0) * width)
        filled = max(0, min(width, filled))
        empty = width - filled
        bar_style = self._status_bar_context_style(percent_used)
        return [
            ("class:status-bar-dim", "\u258f"),
            (bar_style, "\u2588" * filled),
            ("class:status-bar-dim", "\u2592" * empty),
            ("class:status-bar-dim", "\u2595"),
        ]

    @staticmethod
    def _format_prompt_elapsed(prompt_start_time: Optional[float], prompt_duration: float, live: bool = False) -> str:
        """Format per-prompt elapsed time for the status bar.

        Returns an empty string while elapsed time is 0s.
        Keeps seconds visible at all scales so it increments smoothly:
            59s → 1m → 1m 1s → ... → 1m 59s → 2m → 2m 1s → ...
            59m 59s → 1h → 1h 0m 1s → ...
            23h 59m 59s → 1d → 1d 0h 1m → ...

        Emoji prefix: ⏱ when turn is live, ⏲ when frozen or fresh start.
        Uses width-1 (no variation selector) glyphs so the status bar stays
        aligned in monospace terminals.
        """
        elapsed = time.time() - prompt_start_time if prompt_start_time is not None else prompt_duration
        elapsed = max(0.0, elapsed)
        if elapsed < 1.0:
            return ""

        days = int(elapsed // 86400)
        remaining = elapsed % 86400
        hours = int(remaining // 3600)
        remaining = remaining % 3600
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)

        if days > 0:
            time_str = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            time_str = f"{hours}h {minutes}m {seconds}s" if seconds else f"{hours}h {minutes}m"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
        else:
            time_str = f"{int(elapsed)}s"

        emoji = "⏱" if live else "⏲"
        return f"{emoji} {time_str}"

    def _get_status_bar_snapshot(self) -> Dict[str, Any]:
        # Prefer the agent's model name — it updates on fallback.
        # self.model reflects the originally configured model and never
        # changes mid-session, so the TUI would show a stale name after
        # _try_activate_fallback() switches provider/model.
        agent = getattr(self, "agent", None)
        model_name = (getattr(agent, "model", None) or self.model or "unknown")
        model_short = model_name.split("/")[-1] if "/" in model_name else model_name
        if model_short.endswith(".gguf"):
            model_short = model_short[:-5]
        if len(model_short) > 26:
            model_short = f"{model_short[:23]}..."

        elapsed_seconds = max(0.0, (datetime.now() - self.session_start).total_seconds())
        snapshot = {
            "model_name": model_name,
            "model_short": model_short,
            "duration": format_duration_compact(elapsed_seconds),
            "prompt_elapsed": self._format_prompt_elapsed(
                getattr(self, "_prompt_start_time", None),
                getattr(self, "_prompt_duration", 0.0),
                live=getattr(self, "_prompt_start_time", None) is not None,
            ),
            "context_tokens": 0,
            "context_length": None,
            "context_percent": None,
            "session_input_tokens": 0,
            "session_output_tokens": 0,
            "session_cache_read_tokens": 0,
            "session_cache_write_tokens": 0,
            "session_prompt_tokens": 0,
            "session_completion_tokens": 0,
            "session_total_tokens": 0,
            "session_api_calls": 0,
            "compressions": 0,
        }

        if not agent:
            return snapshot

        snapshot["session_input_tokens"] = getattr(agent, "session_input_tokens", 0) or 0
        snapshot["session_output_tokens"] = getattr(agent, "session_output_tokens", 0) or 0
        snapshot["session_cache_read_tokens"] = getattr(agent, "session_cache_read_tokens", 0) or 0
        snapshot["session_cache_write_tokens"] = getattr(agent, "session_cache_write_tokens", 0) or 0
        snapshot["session_prompt_tokens"] = getattr(agent, "session_prompt_tokens", 0) or 0
        snapshot["session_completion_tokens"] = getattr(agent, "session_completion_tokens", 0) or 0
        snapshot["session_total_tokens"] = getattr(agent, "session_total_tokens", 0) or 0
        snapshot["session_api_calls"] = getattr(agent, "session_api_calls", 0) or 0

        compressor = getattr(agent, "context_compressor", None)
        if compressor:
            context_tokens = getattr(compressor, "last_prompt_tokens", 0) or 0
            context_length = getattr(compressor, "context_length", 0) or 0
            snapshot["context_tokens"] = context_tokens
            snapshot["context_length"] = context_length or None
            snapshot["compressions"] = getattr(compressor, "compression_count", 0) or 0
            if context_length:
                snapshot["context_percent"] = max(0, min(100, round((context_tokens / context_length) * 100)))

        return snapshot

    @staticmethod
    def _status_bar_display_width(text: str) -> int:
        """Return terminal cell width for status-bar text.

        len() is not enough for prompt_toolkit layout decisions because some
        glyphs can render wider than one Python codepoint. Keeping the status
        bar within the real display width prevents it from wrapping onto a
        second line and leaving behind duplicate rows.
        """
        try:
            from prompt_toolkit.utils import get_cwidth
            return get_cwidth(text or "")
        except Exception:
            return len(text or "")

    @classmethod
    def _trim_status_bar_text(cls, text: str, max_width: int) -> str:
        """Trim status-bar text to a single terminal row."""
        if max_width <= 0:
            return ""
        try:
            from prompt_toolkit.utils import get_cwidth
        except Exception:
            get_cwidth = None

        if cls._status_bar_display_width(text) <= max_width:
            return text

        ellipsis = "..."
        ellipsis_width = cls._status_bar_display_width(ellipsis)
        if max_width <= ellipsis_width:
            return ellipsis[:max_width]

        out = []
        width = 0
        for ch in text:
            ch_width = get_cwidth(ch) if get_cwidth else len(ch)
            if width + ch_width + ellipsis_width > max_width:
                break
            out.append(ch)
            width += ch_width
        return "".join(out).rstrip() + ellipsis

    @staticmethod
    def _get_tui_terminal_width(default: tuple[int, int] = (80, 24)) -> int:
        """Return the live prompt_toolkit width, falling back to ``shutil``.

        The TUI layout can be narrower than ``shutil.get_terminal_size()`` reports,
        especially on Termux/mobile shells, so prefer prompt_toolkit's width whenever
        an app is active.
        """
        try:
            from prompt_toolkit.application import get_app
            return get_app().output.get_size().columns
        except Exception:
            return shutil.get_terminal_size(default).columns

    def _use_minimal_tui_chrome(self, width: Optional[int] = None) -> bool:
        """Hide low-value chrome on narrow/mobile terminals to preserve rows."""
        if width is None:
            width = self._get_tui_terminal_width()
        return width < 64

    def _tui_input_rule_height(self, position: str, width: Optional[int] = None) -> int:
        """Return the visible height for the top/bottom input separator rules."""
        if position not in {"top", "bottom"}:
            raise ValueError(f"Unknown input rule position: {position}")
        if position == "top":
            return 1
        return 0 if self._use_minimal_tui_chrome(width=width) else 1

    def _agent_spacer_height(self, width: Optional[int] = None) -> int:
        """Return the spacer height shown above the status bar while the agent runs."""
        if not getattr(self, "_agent_running", False):
            return 0
        return 0 if self._use_minimal_tui_chrome(width=width) else 1

    def _spinner_widget_height(self, width: Optional[int] = None) -> int:
        """Return the visible height for the spinner/status text line above the status bar."""
        spinner_line = self._render_spinner_text()
        if not spinner_line:
            return 0
        if self._use_minimal_tui_chrome(width=width):
            return 0
        width = width or self._get_tui_terminal_width()
        if width and width > 10:
            import math
            text_width = self._status_bar_display_width(spinner_line)
            return max(1, math.ceil(text_width / width))
        return 1

    def _render_spinner_text(self) -> str:
        """Return the live spinner/status text exactly as rendered in the TUI."""
        txt = getattr(self, "_spinner_text", "")
        if not txt:
            return ""
        t0 = getattr(self, "_tool_start_time", 0) or 0
        if t0 > 0:
            elapsed = time.monotonic() - t0
            if elapsed >= 60:
                _m, _s = int(elapsed // 60), int(elapsed % 60)
                elapsed_str = f"{_m}m {_s}s"
            else:
                elapsed_str = f"{elapsed:.1f}s"
            return f"  {txt}  ({elapsed_str})"
        return f"  {txt}"

    def _get_voice_status_fragments(self, width: Optional[int] = None):
        """Return the voice status bar fragments for the interactive TUI."""
        width = width or self._get_tui_terminal_width()
        compact = self._use_minimal_tui_chrome(width=width)
        if self._voice_recording:
            if compact:
                return [("class:voice-status-recording", " ● REC ")]
            return [("class:voice-status-recording", " ● REC  Ctrl+B to stop ")]
        if self._voice_processing:
            if compact:
                return [("class:voice-status", " ◉ STT ")]
            return [("class:voice-status", " ◉ Transcribing... ")]
        if compact:
            return [("class:voice-status", " 🎤 Ctrl+B ")]
        tts = " | TTS on" if self._voice_tts else ""
        cont = " | Continuous" if self._voice_continuous else ""
        return [("class:voice-status", f" 🎤 Voice mode{tts}{cont}  —  Ctrl+B to record ")]

    def _build_status_bar_text(self, width: Optional[int] = None) -> str:
        """Return a compact one-line session status string for the TUI footer."""
        try:
            snapshot = self._get_status_bar_snapshot()
            if width is None:
                width = self._get_tui_terminal_width()
            has_context_usage = int(snapshot.get("context_tokens") or 0) > 0
            percent = snapshot["context_percent"]
            percent_label = f"{percent}%" if percent is not None else "--"
            duration_label = snapshot["duration"]

            if width < 52:
                text = f"⚡ {snapshot['model_short']} · {duration_label}"
                return self._trim_status_bar_text(text, width)
            if width < 76:
                parts = [f"⚡ {snapshot['model_short']}"]
                if has_context_usage:
                    parts.append(percent_label)
                parts.append(duration_label)
                return self._trim_status_bar_text(" · ".join(parts), width)

            if has_context_usage and snapshot["context_length"]:
                ctx_total = _format_context_length(snapshot["context_length"])
                ctx_used = format_token_count_compact(snapshot["context_tokens"])
                context_label = f"{ctx_used}/{ctx_total}"
                parts = [f"⚡ {snapshot['model_short']}", context_label, percent_label]
            elif has_context_usage:
                parts = [f"⚡ {snapshot['model_short']}", percent_label]
            else:
                parts = [f"⚡ {snapshot['model_short']}"]
            parts.append(duration_label)
            prompt_elapsed = snapshot.get("prompt_elapsed")
            if prompt_elapsed:
                parts.append(prompt_elapsed)
            return self._trim_status_bar_text(" │ ".join(parts), width)
        except Exception:
            return f"⚡ {self.model if getattr(self, 'model', None) else 'ECTOR'}"

    def _get_status_bar_fragments(self):
        if not self._status_bar_visible or getattr(self, '_model_picker_state', None):
            return []
        try:
            snapshot = self._get_status_bar_snapshot()
            # Use prompt_toolkit's own terminal width when running inside the
            # TUI — shutil.get_terminal_size() can return stale or fallback
            # values (especially on SSH) that differ from what prompt_toolkit
            # actually renders, causing the fragments to overflow to a second
            # line and produce duplicated status bar rows over long sessions.
            width = self._get_tui_terminal_width()
            duration_label = snapshot["duration"]
            has_context_usage = int(snapshot.get("context_tokens") or 0) > 0

            if width < 52:
                frags = [
                    ("class:status-bar", " ⚡ "),
                    ("class:status-bar-strong", snapshot["model_short"]),
                    ("class:status-bar-dim", " ⬡ "),
                    ("class:status-bar-dim", duration_label),
                    ("class:status-bar", " "),
                ]
            else:
                percent = snapshot["context_percent"]
                percent_label = f"{percent}%" if percent is not None else "--"
                if width < 76:
                    frags = [
                        ("class:status-bar", " ⚡ "),
                        ("class:status-bar-strong", snapshot["model_short"]),
                        ("class:status-bar-dim", " ⬡ "),
                        ("class:status-bar-dim", duration_label),
                        ("class:status-bar", " "),
                    ]
                    if has_context_usage:
                        frags = [
                            ("class:status-bar", " ⚡ "),
                            ("class:status-bar-strong", snapshot["model_short"]),
                            ("class:status-bar-dim", " ⬡ "),
                            (self._status_bar_context_style(percent), percent_label),
                            ("class:status-bar-dim", " ⬡ "),
                            ("class:status-bar-dim", duration_label),
                            ("class:status-bar", " "),
                        ]
                else:
                    if has_context_usage and snapshot["context_length"]:
                        ctx_total = _format_context_length(snapshot["context_length"])
                        ctx_used = format_token_count_compact(snapshot["context_tokens"])
                        context_label = f"{ctx_used}/{ctx_total}"
                    elif has_context_usage:
                        context_label = ""
                    else:
                        context_label = ""

                    bar_style = self._status_bar_context_style(percent)
                    frags = [("class:status-bar", " ⚡ "), ("class:status-bar-strong", snapshot["model_short"])]
                    if has_context_usage:
                        frags.extend([
                            ("class:status-bar-dim", "  "),
                            ("class:status-bar-dim", context_label),
                            ("class:status-bar-dim", "  "),
                        ])
                        frags.extend(self._context_bar_fragments(percent))
                        frags.extend([
                            ("class:status-bar-dim", " "),
                            (bar_style, percent_label),
                        ])
                    frags.extend([
                        ("class:status-bar-dim", "  "),
                        ("class:status-bar-dim", duration_label),
                    ])
                    # Position 7: per-prompt elapsed timer (live or frozen)
                    prompt_elapsed = snapshot.get("prompt_elapsed")
                    if prompt_elapsed:
                        frags.append(("class:status-bar-dim", "  "))
                        frags.append(("class:status-bar-dim", prompt_elapsed))
                    frags.append(("class:status-bar", " "))

            total_width = sum(self._status_bar_display_width(text) for _, text in frags)
            if total_width > width:
                plain_text = "".join(text for _, text in frags)
                trimmed = self._trim_status_bar_text(plain_text, width)
                return [("class:status-bar", trimmed)]
            return frags
        except Exception:
            return [("class:status-bar", f" {self._build_status_bar_text()} ")]

    def _normalize_model_for_provider(self, resolved_provider: str) -> bool:
        """Normalize provider-specific model IDs and routing."""
        current_model = (self.model or "").strip()
        changed = False

        try:
            from ector_cli.model_normalize import (
                _AGGREGATOR_PROVIDERS,
                normalize_model_for_provider,
            )

            if resolved_provider not in _AGGREGATOR_PROVIDERS:
                normalized_model = normalize_model_for_provider(current_model, resolved_provider)
                if normalized_model and normalized_model != current_model:
                    if not self._model_is_default:
                        self._console_print(
                            f"[yellow]▲  Normalized model '{current_model}' to '{normalized_model}' for {resolved_provider}.[/]"
                        )
                    self.model = normalized_model
                    current_model = normalized_model
                    changed = True
        except Exception:
            pass

        if resolved_provider == "copilot":
            try:
                from ector_cli.models import copilot_model_api_mode, normalize_copilot_model_id

                canonical = normalize_copilot_model_id(current_model, api_key=self.api_key)
                if canonical and canonical != current_model:
                    if not self._model_is_default:
                        self._console_print(
                            f"[yellow]▲  Normalized Copilot model '{current_model}' to '{canonical}'.[/]"
                        )
                    self.model = canonical
                    current_model = canonical
                    changed = True

                resolved_mode = copilot_model_api_mode(current_model, api_key=self.api_key)
                if resolved_mode != self.api_mode:
                    self.api_mode = resolved_mode
                    changed = True
            except Exception:
                pass
            return changed

        if resolved_provider != "openai-codex":
            return changed

        # 1. Strip provider prefix ("openai/gpt-5.4" → "gpt-5.4")
        if "/" in current_model:
            slug = current_model.split("/", 1)[1]
            if not self._model_is_default:
                self._console_print(
                    f"[yellow]▲  Stripped provider prefix from '{current_model}'; "
                    f"using '{slug}' for OpenAI Codex.[/]"
                )
            self.model = slug
            current_model = slug
            changed = True

        # 2. Replace untouched default with a Codex model
        if self._model_is_default:
            fallback_model = "gpt-5.3-codex"
            try:
                from ector_cli.codex_models import get_codex_model_ids

                available = get_codex_model_ids(
                    access_token=self.api_key if self.api_key else None,
                )
                if available:
                    fallback_model = available[0]
            except Exception:
                pass

            if current_model != fallback_model:
                self.model = fallback_model
                changed = True

        return changed

    def _on_thinking(self, text: str) -> None:
        """Called by agent when thinking starts/stops. Updates TUI spinner."""
        if not text:
            self._flush_reasoning_preview(force=True)
        self._spinner_text = text or ""
        self._tool_start_time = 0.0  # clear tool timer when switching to thinking
        self._invalidate()

    # ── Streaming display ────────────────────────────────────────────────

    def _current_reasoning_callback(self):
        """Return the active reasoning display callback for the current mode."""
        if self.show_reasoning and self.streaming_enabled:
            return self._stream_reasoning_delta
        if self.verbose and not self.show_reasoning:
            return self._on_reasoning
        return None

    def _emit_reasoning_preview(self, reasoning_text: str) -> None:
        """Render a buffered reasoning preview as a single [thinking] block."""
        preview_text = reasoning_text.strip()
        if not preview_text:
            return

        try:
            term_width = shutil.get_terminal_size().columns
        except Exception:
            term_width = 80
        prefix = "  [pensando] "
        wrap_width = max(30, term_width - len(prefix) - 2)

        paragraphs = []
        raw_paragraphs = re.split(r"\n\s*\n+", preview_text.replace("\r\n", "\n"))
        for paragraph in raw_paragraphs:
            compact = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
            if compact:
                paragraphs.append(textwrap.fill(compact, width=wrap_width))
        preview_text = "\n".join(paragraphs)
        if not preview_text:
            return

        if self.verbose:
            _cprint(f"  {_DIM}[pensando] {preview_text}{_RST}")
            return

        lines = preview_text.splitlines()
        if len(lines) > 5:
            preview = "\n".join(lines[:5])
            preview += f"\n  ... ({len(lines) - 5} mais linhas)"
        else:
            preview = preview_text
        _cprint(f"  {_DIM}[pensando] {preview}{_RST}")

    def _flush_reasoning_preview(self, *, force: bool = False) -> None:
        """Flush buffered reasoning text at natural boundaries.

        Some providers stream reasoning in tiny word or punctuation chunks.
        Buffer them here so the preview path does not print one `[thinking]`
        line per token.
        """
        buf = getattr(self, "_reasoning_preview_buf", "")
        if not buf:
            return

        try:
            term_width = shutil.get_terminal_size().columns
        except Exception:
            term_width = 80
        target_width = max(40, term_width - len("  [thinking] ") - 4)

        flush_text = ""

        if force:
            flush_text = buf
            buf = ""
        else:
            line_break = buf.rfind("\n")
            min_newline_flush = max(16, target_width // 3)
            if line_break != -1 and (
                line_break >= min_newline_flush
                or buf.endswith("\n\n")
                or buf.endswith(".\n")
                or buf.endswith("!\n")
                or buf.endswith("?\n")
                or buf.endswith(":\n")
            ):
                flush_text = buf[: line_break + 1]
                buf = buf[line_break + 1 :]
            elif len(buf) >= target_width:
                search_start = max(20, target_width // 2)
                search_end = min(len(buf), max(target_width + (target_width // 3), target_width + 8))
                cut = -1
                for boundary in (" ", "\t", ".", "!", "?", ",", ";", ":"):
                    cut = max(cut, buf.rfind(boundary, search_start, search_end))
                if cut != -1:
                    flush_text = buf[: cut + 1]
                    buf = buf[cut + 1 :]

        self._reasoning_preview_buf = buf.lstrip() if flush_text else buf
        if flush_text:
            self._emit_reasoning_preview(flush_text)

    def _format_submitted_user_message_preview(self, user_input: str) -> str:
        """Format the submitted user-message scrollback preview."""
        lines = user_input.split("\n")
        if len(lines) <= 1:
            return f"[bold {_accent_hex()}]●[/] [bold]{_escape(user_input)}[/]"

        first_lines = int(getattr(self, "user_message_preview_first_lines", 2))
        last_lines = int(getattr(self, "user_message_preview_last_lines", 2))
        first_lines = max(1, first_lines)
        last_lines = max(0, last_lines)
        head = lines[:first_lines]
        remaining_after_head = max(0, len(lines) - len(head))
        tail_count = min(last_lines, remaining_after_head)
        tail = lines[-tail_count:] if tail_count else []

        hidden_middle_count = len(lines) - len(head) - len(tail)
        if hidden_middle_count < 0:
            hidden_middle_count = 0
            tail = []

        preview_lines = [
            f"[bold {_accent_hex()}]●[/] [bold]{_escape(head[0])}[/]"
        ]
        preview_lines.extend(f"[bold]{_escape(line)}[/]" for line in head[1:])

        if hidden_middle_count > 0:
            noun = "line" if hidden_middle_count == 1 else "lines"
            preview_lines.append(f"[dim]... (+{hidden_middle_count} more {noun})[/]")

        preview_lines.extend(f"[bold]{_escape(line)}[/]" for line in tail)
        return "\n".join(preview_lines)

    def _expand_paste_references(self, text: str | None) -> str:
        """Expand [Pasted text #N -> file] placeholders into file contents."""
        if not isinstance(text, str) or "[Pasted text #" not in text:
            return text or ""
        paste_ref_re = re.compile(r'\[Pasted text #\d+: \d+ lines \u2192 (.+?)\]')

        def _expand_ref(match):
            path = Path(match.group(1))
            return path.read_text(encoding="utf-8") if path.exists() else match.group(0)

        return paste_ref_re.sub(_expand_ref, text)

    def _print_user_message_preview(self, user_input: str) -> None:
        """Render a user message using the normal chat scrollback style."""
        ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
        text = str(user_input or "")
        if "\n" in text:
            ChatConsole().print(self._format_submitted_user_message_preview(text))
        else:
            ChatConsole().print(f"[bold {_accent_hex()}]●[/] [bold]{_escape(text)}[/]")

    def _stream_reasoning_delta(self, text: str) -> None:
        """Stream reasoning/thinking tokens into a dim box above the response.

        Opens a dim reasoning box on first token, streams line-by-line.
        The box is closed automatically when content tokens start arriving
        (via _stream_delta → _emit_stream_text).

        Once the response box is open, suppress any further reasoning
        rendering — a late thinking block (e.g. after an interrupt) would
        otherwise draw a reasoning box inside the response box.
        """
        if not text:
            return
        self._reasoning_shown_this_turn = True
        if getattr(self, "_stream_box_opened", False):
            return

        # Open reasoning box on first reasoning token
        if not getattr(self, "_reasoning_box_opened", False):
            self._reasoning_box_opened = True
            w = shutil.get_terminal_size().columns
            r_label = " Reasoning "
            r_fill = w - 2 - len(r_label)
            _cprint(f"\n{_DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{_RST}")

        self._reasoning_buf = getattr(self, "_reasoning_buf", "") + text

        # Emit complete lines, and force-flush long partial lines so
        # reasoning is visible in real-time even without newlines.
        while "\n" in self._reasoning_buf:
            line, self._reasoning_buf = self._reasoning_buf.split("\n", 1)
            _cprint(f"{_DIM}{line}{_RST}")
        if len(self._reasoning_buf) > 80:
            _cprint(f"{_DIM}{self._reasoning_buf}{_RST}")
            self._reasoning_buf = ""

    def _close_reasoning_box(self) -> None:
        """Close the live reasoning box if it's open."""
        if getattr(self, "_reasoning_box_opened", False):
            # Flush remaining reasoning buffer
            buf = getattr(self, "_reasoning_buf", "")
            if buf:
                _cprint(f"{_DIM}{buf}{_RST}")
                self._reasoning_buf = ""
            w = shutil.get_terminal_size().columns
            _cprint(f"{_DIM}└{'─' * (w - 2)}┘{_RST}")
            self._reasoning_box_opened = False

            # Flush any content that was deferred while reasoning was rendering.
            deferred = getattr(self, "_deferred_content", "")
            if deferred:
                self._deferred_content = ""
                self._emit_stream_text(deferred)

    def _stream_delta(self, text) -> None:
        """Line-buffered streaming callback for real-time token rendering.

        Receives text deltas from the agent as tokens arrive. Buffers
        partial lines and emits complete lines via _cprint to work
        reliably with prompt_toolkit's patch_stdout.

        Reasoning/thinking blocks (<REASONING_SCRATCHPAD>, <think>, etc.)
        are suppressed during streaming since they'd display raw XML tags.
        The agent strips them from the final response anyway.

        A ``None`` value signals an intermediate turn boundary (tools are
        about to execute).  Flushes any open boxes and resets state so
        tool feed lines render cleanly between turns.
        """
        if text is None:
            self._flush_stream()
            self._reset_stream_state()
            return
        if not text:
            return

        self._stream_started = True

        # ── Tag-based reasoning suppression ──
        # Track whether we're inside a reasoning/thinking block.
        # These tags are model-generated (system prompt tells the model
        # to use them) and get stripped from final_response. We must
        # suppress them during streaming too — unless show_reasoning is
        # enabled, in which case we route the inner content to the
        # reasoning display box instead of discarding it.
        _OPEN_TAGS = ("<REASONING_SCRATCHPAD>", "<think>", "<reasoning>", "<THINKING>", "<thinking>", "<thought>")
        _CLOSE_TAGS = ("</REASONING_SCRATCHPAD>", "</think>", "</reasoning>", "</THINKING>", "</thinking>", "</thought>")

        # Append to a pre-filter buffer first
        self._stream_prefilt = getattr(self, "_stream_prefilt", "") + text

        # Check if we're entering a reasoning block.
        # Only match tags that appear at a "block boundary": start of the
        # stream, after a newline (with optional whitespace), or when nothing
        # but whitespace has been emitted on the current line.
        # This prevents false positives when models *mention* tags in prose
        # like "(/think not producing <think> tags)".
        #
        # _stream_last_was_newline tracks whether the last character emitted
        # (or the start of the stream) is a line boundary.  It's True at
        # stream start and set True whenever emitted text ends with '\n'.
        if not hasattr(self, "_stream_last_was_newline"):
            self._stream_last_was_newline = True  # start of stream = boundary

        if not getattr(self, "_in_reasoning_block", False):
            for tag in _OPEN_TAGS:
                search_start = 0
                while True:
                    idx = self._stream_prefilt.find(tag, search_start)
                    if idx == -1:
                        break
                    # Check if this is a block boundary position
                    preceding = self._stream_prefilt[:idx]
                    if idx == 0:
                        # At buffer start — only a boundary if we're at
                        # a line start (stream start or last emit ended
                        # with newline)
                        is_block_boundary = getattr(self, "_stream_last_was_newline", True)
                    else:
                        # Find last newline in the buffer before the tag
                        last_nl = preceding.rfind("\n")
                        if last_nl == -1:
                            # No newline in buffer — boundary only if
                            # last emit was a newline AND only whitespace
                            # has accumulated before the tag
                            is_block_boundary = (
                                getattr(self, "_stream_last_was_newline", True)
                                and preceding.strip() == ""
                            )
                        else:
                            # Text between last newline and tag must be
                            # whitespace-only
                            is_block_boundary = preceding[last_nl + 1:].strip() == ""
                    if is_block_boundary:
                        # Emit everything before the tag
                        if preceding:
                            self._emit_stream_text(preceding)
                            self._stream_last_was_newline = preceding.endswith("\n")
                        self._in_reasoning_block = True
                        self._stream_prefilt = self._stream_prefilt[idx + len(tag):]
                        break
                    # Not a block boundary — keep searching after this occurrence
                    search_start = idx + 1
                if getattr(self, "_in_reasoning_block", False):
                    break

            # Could also be a partial open tag at the end — hold it back
            if not getattr(self, "_in_reasoning_block", False):
                # Check for partial tag match at the end
                safe = self._stream_prefilt
                for tag in _OPEN_TAGS:
                    for i in range(1, len(tag)):
                        if self._stream_prefilt.endswith(tag[:i]):
                            safe = self._stream_prefilt[:-i]
                            break
                if safe:
                    self._emit_stream_text(safe)
                    self._stream_last_was_newline = safe.endswith("\n")
                    self._stream_prefilt = self._stream_prefilt[len(safe):]
                return

        # Inside a reasoning block — look for close tag.
        # Keep accumulating _stream_prefilt because close tags can arrive
        # split across multiple tokens (e.g. "</REASONING_SCRATCH" + "PAD>...").
        if getattr(self, "_in_reasoning_block", False):
            for tag in _CLOSE_TAGS:
                idx = self._stream_prefilt.find(tag)
                if idx != -1:
                    self._in_reasoning_block = False
                    # When show_reasoning is on, route inner content to
                    # the reasoning display box instead of discarding.
                    if self.show_reasoning:
                        inner = self._stream_prefilt[:idx]
                        if inner:
                            self._stream_reasoning_delta(inner)
                    after = self._stream_prefilt[idx + len(tag):]
                    self._stream_prefilt = ""
                    # Process remaining text after close tag through full
                    # filtering (it could contain another open tag)
                    if after:
                        self._stream_delta(after)
                    return
            # When show_reasoning is on, stream reasoning content live
            # instead of silently accumulating. Keep only the tail that
            # could be a partial close tag prefix.
            max_tag_len = max(len(t) for t in _CLOSE_TAGS)
            if len(self._stream_prefilt) > max_tag_len:
                if self.show_reasoning:
                    # Route the safe prefix to reasoning display
                    safe_reasoning = self._stream_prefilt[:-max_tag_len]
                    self._stream_reasoning_delta(safe_reasoning)
                self._stream_prefilt = self._stream_prefilt[-max_tag_len:]
            return

    def _emit_stream_text(self, text: str) -> None:
        """Emit filtered text to the streaming display."""
        if not text:
            return

        # When show_reasoning is on and reasoning is still rendering,
        # defer content until the reasoning box closes.  This ensures the
        # reasoning block always appears BEFORE the response in the terminal.
        if self.show_reasoning and getattr(self, "_reasoning_box_opened", False):
            self._deferred_content = getattr(self, "_deferred_content", "") + text
            return

        # Close the live reasoning box before opening the response box
        self._close_reasoning_box()

        # Open the response box header on the very first visible text
        if not self._stream_box_opened:
            # Strip leading whitespace/newlines before first visible content
            text = text.lstrip("\n")
            if not text:
                return
            self._stream_box_opened = True
            label = " ECTOR "
            _text_hex = "#E6E6FA"
            # Build a true-color ANSI escape for the response text color
            # so streamed content matches the Rich Panel appearance.
            try:
                _r = int(_text_hex[1:3], 16)
                _g = int(_text_hex[3:5], 16)
                _b = int(_text_hex[5:7], 16)
                self._stream_text_ansi = f"\033[38;2;{_r};{_g};{_b}m"
            except (ValueError, IndexError):
                self._stream_text_ansi = ""
            w = shutil.get_terminal_size().columns
            fill = w - 4 - len(label)
            _cprint(f"\n{_ACCENT}╭── {label} {'─' * max(fill - 1, 0)}╮{_RST}")

        self._stream_buf += text

        # Emit complete lines, keep partial remainder in buffer
        _tc = getattr(self, "_stream_text_ansi", "")
        while "\n" in self._stream_buf:
            line, self._stream_buf = self._stream_buf.split("\n", 1)
            if self.final_response_markdown == "strip":
                line = _strip_markdown_syntax(line)
            _cprint(f"{_STREAM_PAD}{_tc}{line}{_RST}" if _tc else f"{_STREAM_PAD}{line}")

    def _flush_stream(self) -> None:
        """Emit any remaining partial line from the stream buffer and close the box."""
        # If we're still inside a "reasoning block" at end-of-stream, it was
        # a false positive — the model mentioned a tag like <think> in prose
        # but never closed it.  Recover the buffered content as regular text.
        if getattr(self, "_in_reasoning_block", False) and getattr(self, "_stream_prefilt", ""):
            self._in_reasoning_block = False
            self._emit_stream_text(self._stream_prefilt)
            self._stream_prefilt = ""

        # Close reasoning box if still open (in case no content tokens arrived)
        self._close_reasoning_box()

        if self._stream_buf:
            _tc = getattr(self, "_stream_text_ansi", "")
            line = _strip_markdown_syntax(self._stream_buf) if self.final_response_markdown == "strip" else self._stream_buf
            _cprint(f"{_STREAM_PAD}{_tc}{line}{_RST}" if _tc else f"{_STREAM_PAD}{line}")
            self._stream_buf = ""

        # Close the response box
        if self._stream_box_opened:
            w = shutil.get_terminal_size().columns
            _cprint(f"{_ACCENT}╰{'─' * (w - 2)}╯{_RST}")

    def _reset_stream_state(self) -> None:
        """Reset streaming state before each agent invocation."""
        self._stream_buf = ""
        self._stream_started = False
        self._stream_box_opened = False
        self._stream_text_ansi = ""
        self._stream_prefilt = ""
        self._in_reasoning_block = False
        self._stream_last_was_newline = True
        self._reasoning_box_opened = False
        self._reasoning_buf = ""
        self._reasoning_preview_buf = ""
        self._deferred_content = ""

    def _slow_command_status(self, command: str) -> str:
        """Return a user-facing status message for slower slash commands."""
        cmd_lower = command.lower().strip()
        if cmd_lower.startswith("/skills search"):
            return "Searching skills..."
        if cmd_lower.startswith("/skills browse"):
            return "Loading skills..."
        if cmd_lower.startswith("/skills inspect"):
            return "Inspecting skill..."
        if cmd_lower.startswith("/skills install"):
            return "Installing skill..."
        if cmd_lower.startswith("/skills"):
            return "Processing skills command..."
        if cmd_lower == "/reload-mcp":
            return "Reloading MCP servers..."
        if cmd_lower.startswith("/browser"):
            return "Configuring browser..."
        return "Processing command..."

    def _command_spinner_frame(self) -> str:
        """Return the current spinner frame for slow slash commands."""
        frame_idx = int(time.monotonic() * 10) % len(_COMMAND_SPINNER_FRAMES)
        return _COMMAND_SPINNER_FRAMES[frame_idx]

    @contextmanager
    def _busy_command(self, status: str):
        """Expose a temporary busy state in the TUI while a slash command runs."""
        self._command_running = True
        self._command_status = status
        self._invalidate(min_interval=0.0)
        try:
            print(f"⏳ {status}")
            yield
        finally:
            self._command_running = False
            self._command_status = ""
            self._invalidate(min_interval=0.0)

    def _open_external_editor(self, buffer=None) -> bool:
        """Open the active input buffer in an external editor."""
        app = getattr(self, "_app", None)
        if not app:
            _cprint(f"{_DIM}Editor externo disponível apenas no CLI interativo.{_RST}")
            return False
        if self._command_running:
            _cprint(f"{_DIM}Aguarde o comando atual terminar antes de abrir o editor.{_RST}")
            return False
        if self._sudo_state or self._secret_state or self._approval_state or self._wiser_state:
            _cprint(f"{_DIM}Finalize o prompt ativo antes de abrir o editor.{_RST}")
            return False
        target_buffer = buffer or getattr(app, "current_buffer", None)
        if target_buffer is None:
            _cprint(f"{_DIM}Nenhum buffer de entrada ativo disponível para o editor externo.{_RST}")
            return False
        try:
            existing_text = getattr(target_buffer, "text", "")
            expanded_text = self._expand_paste_references(existing_text)
            if expanded_text != existing_text and hasattr(target_buffer, "text"):
                self._skip_paste_collapse = True
                target_buffer.text = expanded_text
                if hasattr(target_buffer, "cursor_position"):
                    target_buffer.cursor_position = len(expanded_text)
            # Set skip flag (again) so the text-change event fired when the
            # editor closes does not re-collapse the returned content.
            self._skip_paste_collapse = True
            target_buffer.open_in_editor(validate_and_handle=False)
            return True
        except Exception as exc:
            _cprint(f"{_DIM}Falha ao abrir o editor externo: {exc}{_RST}")
            return False

    def _ensure_runtime_credentials(self) -> bool:
        """
        Ensure runtime credentials are resolved before agent use.
        Re-resolves provider credentials so key rotation and token refresh
        are picked up without restarting the CLI.
        Returns True if credentials are ready, False on auth failure.
        """
        from ector_cli.runtime_provider import (
            resolve_runtime_provider,
            format_runtime_provider_error,
        )

        _primary_exc = None
        runtime = None
        try:
            runtime = resolve_runtime_provider(
                requested=self.requested_provider,
                explicit_api_key=self._explicit_api_key,
                explicit_base_url=self._explicit_base_url,
            )
        except Exception as exc:
            _primary_exc = exc

        # Primary provider auth failed — try fallback providers before giving up.
        if runtime is None and _primary_exc is not None:
            from ector_cli.auth import AuthError
            if isinstance(_primary_exc, AuthError):
                _fb_chain = self._fallback_model if isinstance(self._fallback_model, list) else []
                for _fb in _fb_chain:
                    _fb_provider = (_fb.get("provider") or "").strip().lower()
                    _fb_model = (_fb.get("model") or "").strip()
                    if not _fb_provider or not _fb_model:
                        continue
                    try:
                        runtime = resolve_runtime_provider(requested=_fb_provider)
                        logger.warning(
                            "Primary provider auth failed (%s). Falling through to fallback: %s/%s",
                            _primary_exc, _fb_provider, _fb_model,
                        )
                        _cprint(f"▲  Autenticação principal falhou — trocando para fallback: {_fb_provider} / {_fb_model}")
                        self.requested_provider = _fb_provider
                        self.model = _fb_model
                        _primary_exc = None
                        break
                    except Exception:
                        continue

        if runtime is None:
            message = format_runtime_provider_error(_primary_exc) if _primary_exc else "Provider resolution failed."
            ChatConsole().print(f"[bold red]{message}[/]")
            return False

        api_key = runtime.get("api_key")
        base_url = runtime.get("base_url")
        resolved_provider = runtime.get("provider", "openrouter")
        resolved_api_mode = runtime.get("api_mode", self.api_mode)
        resolved_acp_command = runtime.get("command")
        resolved_acp_args = list(runtime.get("args") or [])
        resolved_credential_pool = runtime.get("credential_pool")
        if not isinstance(api_key, str) or not api_key:
            # Custom / local endpoints (llama.cpp, ollama, vLLM, etc.) often
            # don't require authentication.  When a base_url IS configured but
            # no API key was found, use a placeholder so the OpenAI SDK
            # doesn't reject the request and local servers just ignore it.
            _source = runtime.get("source", "")
            _has_custom_base = isinstance(base_url, str) and base_url and "openrouter.ai" not in base_url
            if _has_custom_base:
                api_key = "no-key-required"
                logger.debug(
                    "No API key for custom endpoint %s (source=%s), "
                    "using placeholder — local servers typically ignore auth",
                    base_url, _source,
                )
            else:
                print("\n▲  O resolvedor de provider retornou API key vazia. "
                      "Defina OPENROUTER_API_KEY ou execute: ector setup")
                return False
        if not isinstance(base_url, str) or not base_url:
            print("\n▲  O resolvedor de provider retornou base URL vazia. "
                  "Verifique sua configuração de provider ou execute: ector setup")
            return False

        credentials_changed = api_key != self.api_key or base_url != self.base_url
        routing_changed = (
            resolved_provider != self.provider
            or resolved_api_mode != self.api_mode
            or resolved_acp_command != self.acp_command
            or resolved_acp_args != self.acp_args
        )
        self.provider = resolved_provider
        self.api_mode = resolved_api_mode
        self.acp_command = resolved_acp_command
        self.acp_args = resolved_acp_args
        self._credential_pool = resolved_credential_pool
        self._provider_source = runtime.get("source")
        self.api_key = api_key
        self.base_url = base_url

        # When a custom_provider entry carries an explicit `model` field,
        # use it as the effective model name.  Without this, running
        # `ector chat --model <provider-name>` sends the provider name
        # (e.g. "my-provider") as the model string to the API instead of
        # the configured model (e.g. "qwen3.6-plus"), causing 400 errors.
        runtime_model = runtime.get("model")
        if runtime_model and isinstance(runtime_model, str):
            # Only use runtime model if: model is unset, or model equals provider name
            should_use_runtime_model = (
                not self.model or  # No model configured yet
                self.model == self.provider or  # Model is the provider slug
                self.model == runtime.get("name")  # Model matches provider display name
            )
            if should_use_runtime_model:
                self.model = runtime_model

        # If model is still empty (e.g. user ran `ector auth add openai-codex`
        # without `ector provider`), fall back to the provider's first catalog
        # model so the API call doesn't fail with "model must be non-empty".
        if not self.model and resolved_provider:
            try:
                from ector_cli.models import get_default_model_for_provider
                _default = get_default_model_for_provider(resolved_provider)
                if _default:
                    self.model = _default
                    logger.info(
                        "No model configured — defaulting to %s for provider %s",
                        _default, resolved_provider,
                    )
            except Exception:
                pass

        # Normalize model for the resolved provider (e.g. swap non-Codex
        # models when provider is openai-codex).  Fixes #651.
        model_changed = self._normalize_model_for_provider(resolved_provider)

        # AIAgent/OpenAI client holds auth at init time, so rebuild if key,
        # routing, or the effective model changed.
        if (credentials_changed or routing_changed or model_changed) and self.agent is not None:
            self.agent = None
            self._active_agent_route_signature = None

        return True

    def _resolve_turn_agent_config(self, user_message: str) -> dict:
        """Build the effective model/runtime config for a single user turn.

        Always uses the session's primary model/provider.  If the user has
        toggled `/fast` on and the current model supports Priority
        Processing / Anthropic fast mode, attach `request_overrides` so the
        API call is marked accordingly.
        """
        from ector_cli.models import resolve_fast_mode_overrides

        runtime = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "provider": self.provider,
            "api_mode": self.api_mode,
            "command": self.acp_command,
            "args": list(self.acp_args or []),
            "credential_pool": getattr(self, "_credential_pool", None),
        }
        route = {
            "model": self.model,
            "runtime": runtime,
            "signature": (
                self.model,
                runtime["provider"],
                runtime["base_url"],
                runtime["api_mode"],
                runtime["command"],
                tuple(runtime["args"]),
            ),
        }

        service_tier = getattr(self, "service_tier", None)
        if not service_tier:
            route["request_overrides"] = None
            return route

        try:
            overrides = resolve_fast_mode_overrides(route["model"])
        except Exception:
            overrides = None
        route["request_overrides"] = overrides
        return route

    @contextmanager
    def _agent_init_spinner(self):
        """Braille spinner on one line while ``AIAgent`` is constructed (TTY only)."""
        if not sys.stdout.isatty():
            yield
            return

        stop = threading.Event()

        def _spin_loop():
            idx = 0
            label = "Inicializando agente..."
            while True:
                frame = _COMMAND_SPINNER_FRAMES[idx % len(_COMMAND_SPINNER_FRAMES)]
                idx += 1
                try:
                    cols = max(shutil.get_terminal_size().columns, 24)
                except Exception:
                    cols = 80
                pad = max(0, cols - (len(label) + 3))
                line = f"\r{_DIM}{frame} {label}{' ' * pad}{_RST}"
                try:
                    _pt_print(_PT_ANSI(line), end="")
                    sys.stdout.flush()
                except Exception:
                    pass
                if stop.wait(0.09):
                    break

        worker = threading.Thread(target=_spin_loop, daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join(timeout=0.3)
            try:
                cols = max(shutil.get_terminal_size().columns, 24)
            except Exception:
                cols = 80
            try:
                _pt_print(_PT_ANSI(f"\r{' ' * min(cols, 200)}\r"), end="")
                sys.stdout.flush()
            except Exception:
                pass

    def _init_agent(self, *, model_override: str = None, runtime_override: dict = None, request_overrides: dict | None = None) -> bool:
        """
        Initialize the agent on first use.
        When resuming a session, restores conversation history from SQLite.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if self.agent is not None:
            return True

        if not self._ensure_runtime_credentials():
            return False

        # Initialize SQLite session store for CLI sessions (if not already done in __init__)
        if self._session_db is None:
            try:
                from ector_state import SessionDB
                self._session_db = SessionDB()
            except Exception as e:
                logger.warning("SQLite session store not available — session will NOT be indexed: %s", e)
        
        # If resuming, validate the session exists and load its history.
        # _preload_resumed_session() may have already loaded it (called from
        # run() for immediate display).  In that case, conversation_history
        # is non-empty and we skip the DB round-trip.
        if self._resumed and self._session_db and not self.conversation_history:
            session_meta = self._session_db.get_session(self.session_id)
            if not session_meta:
                _cprint(f"\033[1;31mSessão não encontrada: {self.session_id}{_RST}")
                _cprint(f"{_DIM}Use um ID de sessão de uma execução anterior do CLI (ector sessions list).{_RST}")
                return False
            # If the requested session is the (empty) head of a compression
            # chain, walk to the descendant that actually holds the messages.
            # See #15000 and SessionDB.resolve_resume_session_id.
            try:
                resolved_id = self._session_db.resolve_resume_session_id(self.session_id)
            except Exception:
                resolved_id = self.session_id
            if resolved_id and resolved_id != self.session_id:
                ChatConsole().print(
                    f"[{_DIM}]A sessão {_escape(self.session_id)} foi comprimida em "
                    f"{_escape(resolved_id)}; retomando a descendente com o seu "
                    f"histórico.[/]"
                )
                self.session_id = resolved_id
                resolved_meta = self._session_db.get_session(self.session_id)
                if resolved_meta:
                    session_meta = resolved_meta
            restored = self._session_db.get_messages_as_conversation(self.session_id)
            if restored:
                restored = [m for m in restored if m.get("role") != "session_meta"]
                self.conversation_history = restored
                msg_count = len([m for m in restored if m.get("role") == "user"])
                title_part = ""
                if session_meta.get("title"):
                    title_part = f" \"{session_meta['title']}\""
                ChatConsole().print(
                    f"[bold {_accent_hex()}]↻ Sessão retomada[/] "
                    f"[bold]{_escape(self.session_id)}[/]"
                    f"[bold {_accent_hex()}]{_escape(title_part)}[/] "
                    f"({msg_count} mensagem{'s' if msg_count != 1 else ''} de usuário, {len(restored)} mensagens no total)"
                )
            else:
                ChatConsole().print(
                    f"[bold {_accent_hex()}]Sessão {_escape(self.session_id)} encontrada, mas sem mensagens. Iniciando do zero.[/]"
                )
            # Re-open the session (clear ended_at so it's active again)
            try:
                self._session_db._conn.execute(
                    "UPDATE sessions SET ended_at = NULL, end_reason = NULL WHERE id = ?",
                    (self.session_id,),
                )
                self._session_db._conn.commit()
            except Exception:
                pass
        
        try:
            runtime = runtime_override or {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "provider": self.provider,
                "api_mode": self.api_mode,
                "command": self.acp_command,
                "args": list(self.acp_args or []),
                "credential_pool": getattr(self, "_credential_pool", None),
            }
            effective_model = model_override or self.model
            self.agent = AIAgent(
                model=effective_model,
                api_key=runtime.get("api_key"),
                base_url=runtime.get("base_url"),
                provider=runtime.get("provider"),
                api_mode=runtime.get("api_mode"),
                acp_command=runtime.get("command"),
                acp_args=runtime.get("args"),
                credential_pool=runtime.get("credential_pool"),
                max_iterations=self.max_turns,
                enabled_toolsets=self.enabled_toolsets,
                verbose_logging=self.verbose,
                quiet_mode=not self.verbose,
                ephemeral_system_prompt=self.system_prompt if self.system_prompt else None,
                prefill_messages=self.prefill_messages or None,
                reasoning_config=self.reasoning_config,
                service_tier=self.service_tier,
                request_overrides=request_overrides,
                providers_allowed=self._providers_only,
                providers_ignored=self._providers_ignore,
                providers_order=self._providers_order,
                provider_sort=self._provider_sort,
                provider_require_parameters=self._provider_require_params,
                provider_data_collection=self._provider_data_collection,
                session_id=self.session_id,
                platform="cli",
                session_db=self._session_db,
                wiser_callback=self._wiser_callback,
                reasoning_callback=self._current_reasoning_callback(),

                fallback_model=self._fallback_model,
                thinking_callback=self._on_thinking,
                checkpoints_enabled=self.checkpoints_enabled,
                checkpoint_max_snapshots=self.checkpoint_max_snapshots,
                pass_session_id=self.pass_session_id,
                skip_context_files=self.ignore_rules,
                skip_memory=self.ignore_rules,
                tool_progress_callback=self._on_tool_progress,
                tool_start_callback=self._on_tool_start if self._inline_diffs_enabled else None,
                tool_complete_callback=self._on_tool_complete if self._inline_diffs_enabled else None,
                stream_delta_callback=self._stream_delta if self.streaming_enabled else None,
                tool_gen_callback=self._on_tool_gen_start if self.streaming_enabled else None,
            )
            # Store reference for atexit memory provider shutdown
            global _active_agent_ref
            _active_agent_ref = self.agent
            # Route agent status output through prompt_toolkit so ANSI escape
            # sequences aren't garbled by patch_stdout's StdoutProxy (#2262).
            self.agent._print_fn = _cprint
            self._active_agent_route_signature = (
                effective_model,
                runtime.get("provider"),
                runtime.get("base_url"),
                runtime.get("api_mode"),
                runtime.get("command"),
                tuple(runtime.get("args") or ()),
            )

            if self._pending_title and self._session_db:
                try:
                    self._session_db.set_session_title(
                        self.session_id, self._pending_title, user_set=True
                    )
                    _cprint(f"  Título da sessão aplicado: {self._pending_title}")
                    self._pending_title = None
                except (ValueError, Exception) as e:
                    _cprint(f"  Não foi possível aplicar o título pendente: {e}")
                    self._pending_title = None
            return True
        except Exception as e:
            ChatConsole().print(f"[bold red]Falha ao inicializar o agente: {e}[/]")
            return False
    
    def _preload_resumed_session(self) -> bool:
        """Load a resumed session's history from the DB early (before first chat).

        Called from run() so the conversation history is available for display
        before the user sends their first message.  Sets
        ``self.conversation_history`` and prints the one-liner status.  Returns
        True if history was loaded, False otherwise.

        The corresponding block in ``_init_agent()`` checks whether history is
        already populated and skips the DB round-trip.
        """
        if not self._resumed or not self._session_db:
            return False

        session_meta = self._session_db.get_session(self.session_id)
        if not session_meta:
            self._console_print(
                f"[bold red]Sessão não encontrada: {self.session_id}[/]"
            )
            self._console_print(
                "[dim]Use um ID de sessão de uma execução anterior do CLI "
                "(ector sessions list).[/]"
            )
            return False

        # If the requested session is the (empty) head of a compression chain,
        # walk to the descendant that actually holds the messages. See #15000.
        try:
            resolved_id = self._session_db.resolve_resume_session_id(self.session_id)
        except Exception:
            resolved_id = self.session_id
        if resolved_id and resolved_id != self.session_id:
            self._console_print(
                f"[dim]A sessão {self.session_id} foi comprimida em "
                f"{resolved_id}; retomando a descendente com o seu histórico.[/]"
            )
            self.session_id = resolved_id
            resolved_meta = self._session_db.get_session(self.session_id)
            if resolved_meta:
                session_meta = resolved_meta

        restored = self._session_db.get_messages_as_conversation(self.session_id)
        if restored:
            restored = [m for m in restored if m.get("role") != "session_meta"]
            self.conversation_history = restored
            msg_count = len([m for m in restored if m.get("role") == "user"])
            title_part = ""
            if session_meta.get("title"):
                title_part = f' "{session_meta["title"]}"'
            accent_color = _accent_hex()
            self._console_print(
                f"[{accent_color}]↻ Resumed session [bold]{self.session_id}[/bold]"
                f"{title_part} "
                f"({msg_count} user message{'s' if msg_count != 1 else ''}, "
                f"{len(restored)} total messages)[/]"
            )
        else:
            accent_color = _accent_hex()
            self._console_print(
                f"[{accent_color}]Session {self.session_id} found but has no "
                f"messages. Starting fresh.[/]"
            )
            return False

        # Re-open the session (clear ended_at so it's active again)
        try:
            self._session_db._conn.execute(
                "UPDATE sessions SET ended_at = NULL, end_reason = NULL "
                "WHERE id = ?",
                (self.session_id,),
            )
            self._session_db._conn.commit()
        except Exception:
            pass

        return True

    def _display_resumed_history(self):
        """Render a compact recap of previous conversation messages.

        Uses Rich markup with dim/muted styling so the recap is visually
        distinct from the active conversation.  Caps the display at the
        last ``MAX_DISPLAY_EXCHANGES`` user/assistant exchanges and shows
        an indicator for earlier hidden messages.
        """
        if not self.conversation_history:
            return

        # Check config: resume_display setting
        if self.resume_display == "minimal":
            return

        MAX_DISPLAY_EXCHANGES = 10   # max user+assistant pairs to show
        MAX_USER_LEN = 300           # truncate user messages
        MAX_ASST_LEN = 200           # truncate assistant text
        MAX_ASST_LINES = 3           # max lines of assistant text

        # Collect displayable entries (skip system, tool-result messages)
        entries = []  # list of (role, display_text)
        _last_asst_idx = None       # index of last assistant entry
        _last_asst_full = None      # un-truncated display text for last assistant
        for msg in self.conversation_history:
            role = msg.get("role", "")
            content = msg.get("content")
            tool_calls = msg.get("tool_calls") or []

            if role == "system":
                continue
            if role == "tool":
                continue

            if role == "user":
                text = "" if content is None else str(content)
                # Handle multimodal content (list of dicts)
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                        elif isinstance(part, dict) and part.get("type") == "image_url":
                            parts.append("[image]")
                    text = " ".join(parts)
                if len(text) > MAX_USER_LEN:
                    text = text[:MAX_USER_LEN] + "..."
                entries.append(("user", text))

            elif role == "assistant":
                text = "" if content is None else str(content)
                text = _strip_reasoning_tags(text)
                parts = []
                full_parts = []  # un-truncated version
                if text:
                    full_parts.append(text)
                    lines = text.splitlines()
                    if len(lines) > MAX_ASST_LINES:
                        text = "\n".join(lines[:MAX_ASST_LINES]) + " ..."
                    if len(text) > MAX_ASST_LEN:
                        text = text[:MAX_ASST_LEN] + "..."
                    parts.append(text)
                if tool_calls:
                    tc_count = len(tool_calls)
                    # Extract tool names
                    names = []
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        name = fn.get("name", "unknown") if isinstance(fn, dict) else "unknown"
                        if name not in names:
                            names.append(name)
                    names_str = ", ".join(names[:4])
                    if len(names) > 4:
                        names_str += ", ..."
                    noun = "call" if tc_count == 1 else "calls"
                    tc_summary = f"[{tc_count} tool {noun}: {names_str}]"
                    parts.append(tc_summary)
                    full_parts.append(tc_summary)
                if not parts:
                    # Skip pure-reasoning messages that have no visible output
                    continue
                entries.append(("assistant", " ".join(parts)))
                _last_asst_idx = len(entries) - 1
                _last_asst_full = " ".join(full_parts)

        if not entries:
            return

        # Determine if we need to truncate
        skipped = 0
        if len(entries) > MAX_DISPLAY_EXCHANGES * 2:
            skipped = len(entries) - MAX_DISPLAY_EXCHANGES * 2
            entries = entries[skipped:]

        # Replace last assistant entry with full (un-truncated) text
        # so the user can see where they left off without wasting tokens.
        if _last_asst_idx is not None and _last_asst_full:
            adj_idx = _last_asst_idx - skipped
            if 0 <= adj_idx < len(entries):
                entries[adj_idx] = ("assistant_last", _last_asst_full)

        # Build the display using Rich
        from rich.panel import Panel
        from rich.text import Text

        _history_text_c = "#E6E6FA"
        _session_label_c = "#00D1FF"
        _session_border_c = "#00D1FF"
        _assistant_label_c = "#50C878"

        lines = Text()
        if skipped:
            lines.append(
                f"  ... {skipped} earlier messages ...\n\n",
                style="dim italic",
            )

        for i, (role, text) in enumerate(entries):
            if role == "user":
                lines.append("  ● You: ", style=f"dim bold {_session_label_c}")
                # Show first line inline, indent rest
                msg_lines = text.splitlines()
                lines.append(msg_lines[0] + "\n", style="dim")
                for ml in msg_lines[1:]:
                    lines.append(f"         {ml}\n", style="dim")
            elif role == "assistant_last":
                # Last assistant response shown in full, non-dim
                lines.append("  ◆ ECTOR: ", style=f"bold {_assistant_label_c}")
                msg_lines = text.splitlines()
                lines.append(msg_lines[0] + "\n", style="")
                for ml in msg_lines[1:]:
                    lines.append(f"            {ml}\n", style="")
            else:
                lines.append("  ◆ ECTOR: ", style=f"dim bold {_assistant_label_c}")
                msg_lines = text.splitlines()
                lines.append(msg_lines[0] + "\n", style="dim")
                for ml in msg_lines[1:]:
                    lines.append(f"            {ml}\n", style="dim")
            if i < len(entries) - 1:
                lines.append("")  # small gap

        panel = Panel(
            lines,
            title=f"[dim {_session_label_c}]Previous Conversation[/]",
            border_style=f"dim {_session_border_c}",
            padding=(0, 1),
            style=_history_text_c,
        )
        self._console_print(panel)

    def _try_attach_clipboard_image(self) -> bool:
        """Check clipboard for an image and attach it if found.

        Saves the image to ~/.ector/images/ and appends the path to
        ``_attached_images``.  Returns True if an image was attached.
        """
        from ector_cli.clipboard import save_clipboard_image

        img_dir = get_ector_home() / "images"
        self._image_counter += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = img_dir / f"clip_{ts}_{self._image_counter}.png"

        if save_clipboard_image(img_path):
            self._attached_images.append(img_path)
            return True
        self._image_counter -= 1
        return False

    def _handle_rollback_command(self, command: str):
        """Handle /rollback — list, diff, or restore filesystem checkpoints.

        Syntax:
            /rollback                 — list checkpoints
            /rollback <N>             — restore checkpoint N (also undoes last chat turn)
            /rollback diff <N>        — preview changes since checkpoint N
            /rollback <N> <file>      — restore a single file from checkpoint N
        """
        from tools.checkpoint_manager import format_checkpoint_list

        if not hasattr(self, 'agent') or not self.agent:
            print("  Nenhuma sessão ativa do agente.")
            return

        mgr = self.agent._checkpoint_mgr
        if not mgr.enabled:
            print("  Checkpoints não estão habilitados.")
            print("  Habilite com: ector --checkpoints")
            print("  Ou no config.yaml: checkpoints: { enabled: true }")
            return

        cwd = os.getenv("TERMINAL_CWD", safe_getcwd())
        parts = command.split()
        args = parts[1:] if len(parts) > 1 else []

        if not args:
            # List checkpoints
            checkpoints = mgr.list_checkpoints(cwd)
            print(format_checkpoint_list(checkpoints, cwd))
            return

        # Handle /rollback diff <N>
        if args[0].lower() == "diff":
            if len(args) < 2:
                print("  Uso: /rollback diff <N>")
                return
            checkpoints = mgr.list_checkpoints(cwd)
            if not checkpoints:
                print(f"  Nenhum checkpoint encontrado para {cwd}")
                return
            target_hash = self._resolve_checkpoint_ref(args[1], checkpoints)
            if not target_hash:
                return
            result = mgr.diff(cwd, target_hash)
            if result["success"]:
                stat = result.get("stat", "")
                diff = result.get("diff", "")
                if not stat and not diff:
                    print("  Nenhuma mudança desde este checkpoint.")
                else:
                    if stat:
                        print(f"\n{stat}")
                    if diff:
                        # Limit diff output to avoid terminal flood
                        diff_lines = diff.splitlines()
                        if len(diff_lines) > 80:
                            print("\n".join(diff_lines[:80]))
                            print(f"\n  ... ({len(diff_lines) - 80} linhas a mais, exibindo as primeiras 80)")
                        else:
                            print(f"\n{diff}")
            else:
                print(f"  ✖ {result['error']}")
            return

        # Resolve checkpoint reference (number or hash)
        checkpoints = mgr.list_checkpoints(cwd)
        if not checkpoints:
            print(f"  Nenhum checkpoint encontrado para {cwd}")
            return

        target_hash = self._resolve_checkpoint_ref(args[0], checkpoints)
        if not target_hash:
            return

        # Check for file-level restore: /rollback <N> <file>
        file_path = args[1] if len(args) > 1 else None

        result = mgr.restore(cwd, target_hash, file_path=file_path)
        if result["success"]:
            if file_path:
                print(f"  ✔ Restaurado {file_path} do checkpoint {result['restored_to']}: {result['reason']}")
            else:
                print(f"  ✔ Restaurado para o checkpoint {result['restored_to']}: {result['reason']}")
            print("  Um snapshot pré-rollback foi salvo automaticamente.")

            # Also undo the last conversation turn so the agent's context
            # matches the restored filesystem state
            if self.conversation_history:
                self.undo_last()
                print("  A rodada do chat foi desfeita para combinar com o estado restaurado dos arquivos.")
        else:
            print(f"  ✖ {result['error']}")

    def _resolve_checkpoint_ref(self, ref: str, checkpoints: list) -> str | None:
        """Resolve a checkpoint number or hash to a full commit hash."""
        try:
            idx = int(ref) - 1  # 1-indexed for user
            if 0 <= idx < len(checkpoints):
                return checkpoints[idx]["hash"]
            else:
                print(f"  Número de checkpoint inválido. Use 1-{len(checkpoints)}.")
                return None
        except ValueError:
            # Treat as a git hash
            return ref

    def _handle_snapshot_command(self, command: str):
        """Handle /snapshot — lightweight state snapshots for ECTOR config/state.

        Syntax:
            /snapshot                  — list recent snapshots
            /snapshot create [label]   — create a snapshot
            /snapshot restore <id>     — restore state from snapshot
            /snapshot prune [N]        — prune to N snapshots (default 20)
        """
        from ector_cli.backup import (
            create_quick_snapshot, list_quick_snapshots,
            restore_quick_snapshot, prune_quick_snapshots,
        )
        from ector_constants import display_ector_home

        parts = command.split()
        subcmd = parts[1].lower() if len(parts) > 1 else "list"

        if subcmd in ("list", "ls"):
            snaps = list_quick_snapshots()
            if not snaps:
                print("  Ainda não há snapshots de estado.")
                print("  Crie um: /snapshot create [label]")
                return
            print(f"  Snapshots de estado ({display_ector_home()}/state-snapshots/):\n")
            print(f"  {'#':>3}  {'ID':<35} {'Files':>5} {'Size':>10} {'Label'}")
            print(f"  {'─'*3}  {'─'*35} {'─'*5} {'─'*10} {'─'*20}")
            for i, s in enumerate(snaps, 1):
                size = s.get("total_size", 0)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.0f} KB"
                else:
                    size_str = f"{size / 1024 / 1024:.1f} MB"
                label = s.get("label") or ""
                print(f"  {i:3}  {s['id']:<35} {s.get('file_count', 0):>5} {size_str:>10} {label}")

        elif subcmd == "create":
            label = " ".join(parts[2:]) if len(parts) > 2 else None
            snap_id = create_quick_snapshot(label=label)
            if snap_id:
                print(f"  Snapshot criado: {snap_id}")
            else:
                print("  Nenhum arquivo de estado encontrado para snapshot.")

        elif subcmd in ("restore", "rewind"):
            if len(parts) < 3:
                print("  Uso: /snapshot restore <snapshot-id>")
                # Show hint with most recent snapshot
                snaps = list_quick_snapshots(limit=1)
                if snaps:
                    print(f"  Mais recente: {snaps[0]['id']}")
                return
            snap_id = parts[2]
            # Allow restore by number (1-indexed)
            try:
                idx = int(snap_id)
                snaps = list_quick_snapshots()
                if 1 <= idx <= len(snaps):
                    snap_id = snaps[idx - 1]["id"]
                else:
                    print(f"  Número de snapshot inválido. Use 1-{len(snaps)}.")
                    return
            except ValueError:
                pass
            if restore_quick_snapshot(snap_id):
                print(f"  Estado restaurado de: {snap_id}")
                print("  Reinício recomendado para mudanças em state.db entrarem em vigor.")
            else:
                print(f"  Snapshot não encontrado: {snap_id}")

        elif subcmd == "prune":
            keep = 20
            if len(parts) > 2:
                try:
                    keep = int(parts[2])
                except ValueError:
                    print("  Uso: /snapshot prune [keep-count]")
                    return
            deleted = prune_quick_snapshots(keep=keep)
            print(f"  {deleted} snapshot(s) antigos removidos (mantendo {keep}).")

        else:
            print(f"  Subcomando desconhecido: {subcmd}")
            print("  Uso: /snapshot [list|create [label]|restore <id>|prune [N]]")

    def _handle_stop_command(self):
        """Handle /stop — kill all running background processes.

        Inspired by OpenAI Codex's separation of interrupt (stop current turn)
        from /stop (clean up background processes). See openai/codex#14602.
        """
        from tools.process_registry import process_registry

        processes = process_registry.list_sessions()
        running = [p for p in processes if p.get("status") == "running"]

        if not running:
            print("  Nenhum processo em segundo plano em execução.")
            return

        print(f"  Encerrando {len(running)} processo(s) em segundo plano...")
        killed = process_registry.kill_all()
        print(f"  ✔ {killed} processo(s) encerrado(s).")

    def _handle_agents_command(self):
        """Handle /agents — show background processes and agent status."""
        from tools.process_registry import format_uptime_short, process_registry

        processes = process_registry.list_sessions()
        running = [p for p in processes if p.get("status") == "running"]
        finished = [p for p in processes if p.get("status") != "running"]

        _cprint(f"  Processos em execução: {len(running)}")
        for p in running:
            cmd = p.get("command", "")[:80]
            up = format_uptime_short(p.get("uptime_seconds", 0))
            _cprint(f"    {p.get('session_id', '?')} · {up} · {cmd}")

        if finished:
            _cprint(f"  Finalizados recentemente: {len(finished)}")

        agent_running = getattr(self, "_agent_running", False)
        _cprint(f"  Agente: {'em execução' if agent_running else 'ocioso'}")

    def _handle_paste_command(self):
        """Handle /paste — explicitly check clipboard for an image.

        This is the reliable fallback for terminals where BracketedPaste
        doesn't fire for image-only clipboard content (e.g., VSCode terminal,
        Windows Terminal with WSL2).
        """
        if _is_termux_environment():
            _cprint(
                f"  {_DIM}Colagem de imagem da área de transferência não disponível no Termux — "
                f"use /image <caminho> ou cole um caminho de imagem local como "
                f"{_termux_example_image_path()}{_RST}"
            )
            return

        from ector_cli.clipboard import has_clipboard_image
        if has_clipboard_image():
            if self._try_attach_clipboard_image():
                n = len(self._attached_images)
                _cprint(f"  📎 Imagem #{n} anexada da área de transferência")
            else:
                _cprint(f"  {_DIM}(>_<) A área de transferência possui uma imagem, mas a extração falhou{_RST}")
        else:
            _cprint(f"  {_DIM}(._.) Nenhuma imagem encontrada na área de transferência{_RST}")

    def _write_osc52_clipboard(self, text: str) -> None:
        """Copy *text* to terminal clipboard via OSC 52."""
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        seq = f"\x1b]52;c;{payload}\x07"
        out = getattr(self, "_app", None)
        output = getattr(out, "output", None) if out else None
        if output and hasattr(output, "write_raw"):
            output.write_raw(seq)
            output.flush()
            return
        if output and hasattr(output, "write"):
            output.write(seq)
            output.flush()
            return
        sys.stdout.write(seq)
        sys.stdout.flush()

    def _handle_copy_command(self, cmd_original: str) -> None:
        """Handle /copy [number] — copy assistant output to clipboard."""
        parts = cmd_original.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        assistant = [m for m in self.conversation_history if m.get("role") == "assistant"]
        if not assistant:
            _cprint("  Nada para copiar ainda.")
            return

        if arg:
            try:
                idx = int(arg) - 1
            except ValueError:
                _cprint("  Uso: /copy [número]")
                return
            if idx < 0 or idx >= len(assistant):
                _cprint(f"  Número de resposta inválido. Use 1-{len(assistant)}.")
                return
        else:
            idx = len(assistant) - 1
            while idx >= 0 and not _assistant_copy_text(assistant[idx].get("content")):
                idx -= 1
            if idx < 0:
                _cprint("  Nada para copiar nas respostas do assistente ainda.")
                return

        text = _assistant_copy_text(assistant[idx].get("content"))
        if not text:
            _cprint("  Nada para copiar nessa resposta do assistente.")
            return

        try:
            self._write_osc52_clipboard(text)
            _cprint(f"  Resposta do assistente #{idx + 1} copiada para a área de transferência")
        except Exception as e:
            _cprint(f"  Falha ao copiar para a área de transferência: {e}")

    def _handle_image_command(self, cmd_original: str):
        """Handle /image <path> — attach a local image file for the next prompt."""
        raw_args = (cmd_original.split(None, 1)[1].strip() if " " in cmd_original else "")
        if not raw_args:
            hint = _termux_example_image_path() if _is_termux_environment() else "/path/to/image.png"
            _cprint(f"  {_DIM}Uso: /image <caminho>  ex: /image {hint}{_RST}")
            return

        path_token, _remainder = _split_path_input(raw_args)
        image_path = _resolve_attachment_path(path_token)
        if image_path is None:
            _cprint(f"  {_DIM}(>_<) Arquivo não encontrado: {path_token}{_RST}")
            return
        if image_path.suffix.lower() not in _IMAGE_EXTENSIONS:
            _cprint(f"  {_DIM}(._.) Formato de imagem não suportado: {image_path.name}{_RST}")
            return

        self._attached_images.append(image_path)
        _cprint(f"  📎 Imagem anexada: {image_path.name}")
        if _remainder:
            _cprint(f"  {_DIM}Agora digite seu prompt (ou use --image no modo de consulta única): {_remainder}{_RST}")
        elif _is_termux_environment():
            _cprint(
                f"  {_DIM}Dica: digite sua próxima mensagem, ou execute "
                f"ector chat --image {_termux_example_image_path(image_path.name)} -q \"O que você vê?\"{_RST}"
            )

    def _preprocess_images_with_vision(self, text: str, images: list, *, announce: bool = True) -> str:
        """Analyze attached images via the vision tool and return enriched text.

        Instead of embedding raw base64 ``image_url`` content parts in the
        conversation (which only works with vision-capable models), this
        pre-processes each image through the auxiliary vision model (Gemini
        Flash) and prepends the descriptions to the user's message — the
        same approach the messaging gateway uses.

        The local file path is included so the agent can re-examine the
        image later with ``vision_analyze`` if needed.
        """
        import asyncio as _asyncio
        from agent.document_stack.extract import extract_document
        from agent.document_stack.local_image import understand_image_local
        from agent.document_stack.markers import (
            format_document_context_block,
        )
        from agent.vision_prompts import (
            build_preanalysis_prompt,
            ensure_image_persistence_marker,
            format_image_context_block,
            format_image_context_failed,
        )
        from tools.vision_tools import vision_analyze_tool

        analysis_prompt = build_preanalysis_prompt(text)

        enriched_parts = []
        for img_path in images:
            if not img_path.exists():
                continue
            size_kb = img_path.stat().st_size // 1024
            if announce:
                _cprint(f"  {_DIM}👁️  analisando {img_path.name} ({size_kb}KB)...{_RST}")
            vision_ok = False
            try:
                result_json = _asyncio.run(
                    vision_analyze_tool(image_url=str(img_path), user_prompt=analysis_prompt)
                )
                result = json.loads(result_json)
                if result.get("success"):
                    description = result.get("analysis", "")
                    if description:
                        vision_ok = True
                        enriched_parts.append(
                            format_image_context_block(description, str(img_path))
                        )
                        if announce:
                            _cprint(f"  {_DIM}✔ imagem analisada{_RST}")
            except Exception:
                pass

            if vision_ok:
                continue

            # Vision unavailable or failed (e.g. main model is text-only):
            # fall back to local Tesseract (+ Florence-2 when installed).
            if announce:
                _cprint(f"  {_DIM}▲ visão indisponível — tentando OCR/VLM local...{_RST}")
            try:
                local = understand_image_local(str(img_path))
            except Exception:
                local = {"success": False}
            if local.get("success") and (local.get("markdown") or "").strip():
                block = format_document_context_block(
                    local.get("markdown", ""),
                    str(img_path),
                    local.get("backend", "tesseract+florence"),
                )
                enriched_parts.append(
                    ensure_image_persistence_marker(block, str(img_path))
                )
                if announce:
                    _cprint(
                        f"  {_DIM}✔ lido via local ({local.get('backend', 'ocr')}){_RST}"
                    )
                continue

            try:
                extracted = extract_document(str(img_path), force_ocr=True)
            except Exception:
                extracted = {"success": False}
            if extracted.get("success"):
                block = format_document_context_block(
                    extracted.get("markdown", ""),
                    str(img_path),
                    extracted.get("backend", "ocr"),
                )
                enriched_parts.append(
                    ensure_image_persistence_marker(block, str(img_path))
                )
                if announce:
                    _cprint(
                        f"  {_DIM}✔ lido via OCR local ({extracted.get('backend', 'ocr')}){_RST}"
                    )
            else:
                enriched_parts.append(format_image_context_failed(str(img_path)))
                if announce:
                    _cprint(f"  {_DIM}▲ falha na análise de visão e no OCR local — caminho incluído para nova tentativa{_RST}")

        # Combine: vision descriptions first, then the user's original text
        user_text = text if isinstance(text, str) and text else ""
        if enriched_parts:
            prefix = "\n\n".join(enriched_parts)
            return f"{prefix}\n\n{user_text}" if user_text else prefix
        return user_text or "What do you see in this image?"

    def _show_session_status(self):
        """Show gateway-style status for the current CLI session."""
        session_meta = {}
        if self._session_db:
            try:
                session_meta = self._session_db.get_session(self.session_id) or {}
            except Exception:
                session_meta = {}

        title = (session_meta.get("title") or "").strip()

        created_at = self.session_start
        started_at = session_meta.get("started_at")
        if started_at:
            try:
                created_at = datetime.fromtimestamp(float(started_at))
            except Exception:
                created_at = self.session_start

        updated_at = created_at
        for field in ("updated_at", "last_updated_at", "last_activity_at"):
            value = session_meta.get(field)
            if not value:
                continue
            try:
                updated_at = datetime.fromtimestamp(float(value))
                break
            except Exception:
                pass

        agent = getattr(self, "agent", None)
        total_tokens = getattr(agent, "session_total_tokens", 0) or 0
        provider = getattr(self, "provider", None) or "unknown"
        model = getattr(self, "model", None) or "(unknown)"
        is_running = bool(getattr(self, "_agent_running", False))

        lines = [
            "ECTOR CLI Status",
            "",
            f"Session ID: {self.session_id}",
            f"Path: {display_ector_home()}",
        ]
        if title:
            lines.append(f"Title: {title}")
        lines.extend([
            f"Model: {model} ({provider})",
            f"Created: {created_at.strftime('%Y-%m-%d %H:%M')}",
            f"Last Activity: {updated_at.strftime('%Y-%m-%d %H:%M')}",
            f"Tokens: {total_tokens:,}",
            f"Agent Running: {'Yes' if is_running else 'No'}",
        ])
        self._console_print("\n".join(lines), highlight=False, markup=False)
    
    def _fast_command_available(self) -> bool:
        try:
            from ector_cli.models import model_supports_fast_mode
        except Exception:
            return False
        agent = getattr(self, "agent", None)
        model = getattr(agent, "model", None) or getattr(self, "model", None)
        return model_supports_fast_mode(model)

    def _command_available(self, slash_command: str) -> bool:
        if slash_command == "/fast":
            return self._fast_command_available()
        return True

    def show_help(self):
        """Ajuda dos comandos com barra: tabelas Rich por categoria (pt-BR)."""
        from ector_cli.commands import COMMANDS_BY_CATEGORY

        accent = _accent_hex()
        blocks: list = []
        blocks.append(
            Panel.fit(
                "[bold #00D1FF]Comandos disponíveis[/]",
                border_style="#00D1FF",
            )
        )

        for category, commands in COMMANDS_BY_CATEGORY.items():
            ct = _RichTable(
                show_header=True,
                box=rich_box.SIMPLE,
                pad_edge=False,
                padding=(0, 1),
                expand=True,
            )
            ct.add_column("Comando", style=f"bold {accent}", width=24, overflow="fold", no_wrap=False)
            ct.add_column("Descrição", overflow="fold", no_wrap=False)
            any_row = False
            for cmd, desc in commands.items():
                if not self._command_available(cmd):
                    continue
                ct.add_row(cmd, _escape(desc))
                any_row = True
            if any_row:
                blocks.append(Panel(ct, title=f"[bold]{category}[/]", border_style="dim cyan"))

        if _skill_commands:
            st = _RichTable(
                show_header=True,
                box=rich_box.SIMPLE,
                pad_edge=False,
                padding=(0, 1),
                expand=True,
            )
            st.add_column("Comando", style=f"bold {accent}", width=26, overflow="fold", no_wrap=False)
            st.add_column("Descrição", overflow="fold", no_wrap=False)
            for cmd, info in sorted(_skill_commands.items()):
                st.add_row(cmd, _escape(info["description"]))
            blocks.append(
                Panel(
                    st,
                    title=f"[bold]Skills[/] ({len(_skill_commands)} instalados)",
                    border_style="dim cyan",
                )
            )

        tip = (
            "[dim]Dica: digite sua mensagem para conversar com o ECTOR. "
            "Multilinha: Alt+Enter. Rascunho: Ctrl+G (Alt+G no VS Code/Cursor). "
        )
        if _is_termux_environment():
            tip += (
                f"Imagem (Termux): /image {_termux_example_image_path()} "
                "ou comece o prompt com um caminho de imagem local.[/dim]"
            )
        else:
            tip += "Colar imagem: Alt+V ou /paste.[/dim]"

        body = Group(*blocks)
        ctx, console, pager_ok = self._cli_pager_ctx()
        footer = (
            "[dim]"
            + (
                "Pager: [bold]q[/bold] sair · [bold]ECTOR_NO_PAGER=1[/bold] desativa. "
                if pager_ok
                else ""
            )
            + "[/dim]"
        )
        try:
            with ctx:
                console.print()
                console.print(body)
                console.print(tip)
                console.print(footer)
                console.print()
        except Exception:
            console.print()
            console.print(body)
            console.print(tip)
            console.print(footer)
            console.print()
    
    def show_tools(self):
        """Lista ferramentas disponíveis agrupadas por toolset (Rich, pager opcional)."""
        tools = get_tool_definitions(enabled_toolsets=self.enabled_toolsets, quiet_mode=True)

        if not tools:
            print("(;_;) Nenhuma ferramenta disponível")
            return

        term_w = max(shutil.get_terminal_size().columns, 48)
        toolsets_map: dict[str, list[tuple[str, str]]] = {}
        for tool in sorted(tools, key=lambda t: t["function"]["name"]):
            name = tool["function"]["name"]
            toolset = get_toolset_for_tool(name) or "desconhecido"
            if toolset not in toolsets_map:
                toolsets_map[toolset] = []
            desc = tool["function"].get("description", "")
            desc = desc.split("\n")[0]
            if ". " in desc:
                desc = desc[: desc.index(". ") + 1]
            toolsets_map[toolset].append((name, desc))

        blocks: list = []
        for toolset in sorted(toolsets_map.keys()):
            tbl = _RichTable(
                show_header=True,
                box=rich_box.SIMPLE,
                pad_edge=False,
                padding=(0, 1),
                width=term_w,
                expand=True,
            )
            tbl.add_column("Ferramenta", style="bold cyan", width=26, overflow="fold", no_wrap=False)
            tbl.add_column("Descrição (resumo)", overflow="fold", no_wrap=False)
            for name, desc in toolsets_map[toolset]:
                tbl.add_row(name, _escape(desc))
            blocks.append(Panel(tbl, title=f"[bold]{toolset}[/]", border_style="cyan"))

        body = Group(*blocks)
        summary = f"[bold]Total:[/] {len(tools)} ferramentas  [dim]ヽ(^o^)ノ[/]"
        ctx, console, pager_ok = self._cli_pager_ctx()
        footer = (
            "[dim]"
            + (
                "Pager: [bold]q[/bold] sair · [bold]ECTOR_NO_PAGER=1[/bold] desativa. "
                if pager_ok
                else ""
            )
            + "[/dim]"
        )
        try:
            with ctx:
                console.print()
                console.print(
                    Panel(
                        body,
                        title="[bold]Ferramentas disponíveis[/]",
                        border_style="bright_blue",
                        padding=(1, 1),
                    )
                )
                console.print(summary)
                console.print(footer)
                console.print()
        except Exception:
            console.print()
            console.print(
                Panel(
                    body,
                    title="[bold]Ferramentas disponíveis[/]",
                    border_style="bright_blue",
                    padding=(1, 1),
                )
            )
            console.print(summary)
            console.print(footer)
            console.print()

    def _handle_tools_command(self, cmd: str):
        """Handle /tools [list|disable|enable] slash commands.

        /tools (no args) shows the tool list.
        /tools list shows enabled/disabled status per toolset.
        /tools disable/enable saves the change to config and resets
        the session so the new tool set takes effect cleanly (no
        prompt-cache breakage mid-conversation).
        """
        import shlex
        from argparse import Namespace
        from contextlib import redirect_stdout
        from io import StringIO
        from ector_cli.tools_config import tools_disable_enable_command

        def _run_capture(ns: Namespace) -> None:
            """Run tools_disable_enable_command, routing its ANSI-colored
            print() output through _cprint when inside the interactive TUI
            so escapes aren't mangled by patch_stdout's StdoutProxy into
            garbled '?[32m...?[0m' text.

            Outside the TUI (standalone mode, tests), call straight through
            so real stdout / pytest capture works as expected.
            """
            # Standalone/tests, run as usual
            if getattr(self, "_app", None) is None:
                tools_disable_enable_command(ns)
                return

            # Buffer reports isatty()=True so color() in ector_cli/colors.py
            # still emits ANSI escapes. StringIO.isatty() is False, which
            # would otherwise strip all colors before we re-render them.
            class _TTYBuf(StringIO):
                def isatty(self) -> bool:
                    return True

            buf = _TTYBuf()
            with redirect_stdout(buf):
                tools_disable_enable_command(ns)
            for line in buf.getvalue().splitlines():
                _cprint(line)

        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()

        subcommand = parts[1] if len(parts) > 1 else ""
        if subcommand not in ("list", "disable", "enable"):
            self.show_tools()
            return

        if subcommand == "list":
            _run_capture(Namespace(tools_action="list", platform="cli"))
            return

        names = parts[2:]
        if not names:
            print(f"(._.) Uso: /tools {subcommand} <nome> [nome ...]")
            print(f"  Toolset interno:   /tools {subcommand} web")
            print(f"  Ferramenta MCP:    /tools {subcommand} github:create_issue")
            return

        # Apply the change directly — the user typing the command is implicit
        # consent.  Do NOT use input() here; it hangs inside prompt_toolkit's
        # TUI event loop (known pitfall).
        verb = "Desativando" if subcommand == "disable" else "Ativando"
        label = ", ".join(names)
        _cprint(f"{_ACCENT}{verb} {label}...{_RST}")

        _run_capture(Namespace(tools_action=subcommand, names=names, platform="cli"))

        # Reset session so the new tool config is picked up from a clean state
        from ector_cli.tools_config import _get_platform_tools
        from ector_cli.config import load_config
        self.enabled_toolsets = _get_platform_tools(load_config(), "cli")
        self.new_session()
        _cprint(f"{_DIM}Sessão reiniciada. A nova configuração de ferramentas está ativa.{_RST}")

    def show_toolsets(self):
        """Lista conjuntos de ferramentas (toolsets) em tabela Rich com pager opcional."""
        all_toolsets = get_all_toolsets()
        names_sorted = sorted(all_toolsets.keys())
        term_w = max(shutil.get_terminal_size().columns, 48)

        raw = self.enabled_toolsets
        if raw is not None:
            parts = {str(x) for x in raw}
            lows = {p.lower() for p in parts}
            if lows & {"all", "*"}:
                active_set = None
            else:
                active_set = parts
        else:
            try:
                from ector_cli.tools_config import _get_platform_tools
                from ector_cli.config import load_config

                active_set = _get_platform_tools(load_config(), "cli")
            except Exception:
                active_set = None

        def _is_active(name: str) -> bool:
            if active_set is None:
                return True
            return name in active_set

        max_name = max((len(n) for n in names_sorted), default=12)
        name_w = min(max(max_name + 2, 18), max(22, term_w // 4))

        ctx, console, pager_ok = self._cli_pager_ctx()

        inner_w = max(term_w - 4, 48)
        table = _RichTable(
            box=rich_box.SIMPLE,
            show_header=True,
            header_style="bold",
            show_lines=False,
            pad_edge=False,
            collapse_padding=True,
            padding=(0, 1),
            width=inner_w,
            expand=True,
        )
        table.add_column(
            "Conjunto",
            style="bold cyan",
            no_wrap=False,
            overflow="fold",
            width=name_w,
        )
        table.add_column("Qtd.", justify="right", style="dim", no_wrap=True, width=5)
        table.add_column("Descrição", overflow="fold", no_wrap=False)
        table.add_column("Ativo", justify="center", no_wrap=True, width=5)

        for name in names_sorted:
            info = get_toolset_info(name)
            if not info:
                continue
            tool_count = info["tool_count"]
            desc = info["description"]
            active_cell = "[green]sim[/]" if _is_active(name) else "[dim]não[/]"
            table.add_row(name, str(tool_count), desc, active_cell)

        outer = Panel(
            table,
            title="[bold]Toolsets[/]",
            subtitle="[dim]Conjuntos de ferramentas disponíveis[/]",
            border_style="cyan",
            width=term_w,
            padding=(0, 1),
        )

        footer = (
            "[dim]«Ativo» = habilitado para a plataforma [bold]cli[/bold] no config atual "
            "(ou filtro desta sessão se você passou [bold]--toolsets[/bold]). "
            "Ajuste com [bold]ector tools[/bold]. "
            + ("Navegue com ↑↓ ou PageDown; [bold]q[/bold] sai do pager. "
               "[bold]ECTOR_NO_PAGER=1[/bold] imprime tudo de uma vez no buffer do terminal. "
               if pager_ok
               else "")
            + "[/dim]"
        )

        try:
            with ctx:
                console.print()
                console.print(outer)
                console.print(footer)
                console.print()
        except Exception:
            console.print()
            console.print(outer)
            console.print(footer)
            console.print()

    def _cli_pager_ctx(self):
        """Pager Rich (less) em TTY; retorna (context_manager, console, pager_ativo)."""
        console = getattr(self, "console", None) or Console()
        if str(os.environ.get("ECTOR_DASHBOARD_EMBED", "")).lower() in ("1", "true", "yes"):
            return nullcontext(), console, False
        if str(os.environ.get("ECTOR_SLASH_WORKER", "")).lower() in ("1", "true", "yes"):
            return nullcontext(), console, False
        pager_on = (
            sys.stdout.isatty()
            and str(os.environ.get("ECTOR_NO_PAGER", "")).lower() not in ("1", "true", "yes")
        )
        if pager_on:
            try:
                return console.pager(styles=True), console, True
            except Exception:
                pass
        return nullcontext(), console, False

    def _handle_profile_command(self):
        """Exibe o perfil ativo e o diretório ECTOR_HOME de exibição."""
        from ector_constants import display_ector_home
        from ector_cli.profiles import get_active_profile_name

        display = display_ector_home()
        profile_name = get_active_profile_name()

        console = getattr(self, "console", None) or Console()
        tbl = _RichTable(show_header=False, box=None, padding=(0, 1))
        tbl.add_column(style="dim", width=12)
        tbl.add_column(overflow="fold")
        tbl.add_row("Perfil", profile_name)
        tbl.add_row("Pasta", display)
        console.print()
        console.print(Panel(tbl, title="[bold]Perfil[/]", border_style="cyan"))
        console.print()

    def show_config(self):
        """Mostra a configuração atual (Rich, pt-BR, pager opcional)."""
        terminal_env = os.getenv("TERMINAL_ENV", "local")
        terminal_cwd = os.getenv("TERMINAL_CWD", safe_getcwd())
        terminal_timeout = os.getenv("TERMINAL_TIMEOUT", "60")

        user_config_path = _ector_home / "config.yaml"
        project_config_path = Path(__file__).parent / "cli-config.yaml"
        if user_config_path.exists():
            config_path = user_config_path
        else:
            config_path = project_config_path
        if config_path.exists():
            config_status = "[dim](carregado)[/]"
        else:
            config_status = "[yellow](não encontrado)[/]"

        if self.api_key and len(self.api_key) > 4:
            api_key_display = f"********{self.api_key[-4:]}"
        else:
            api_key_display = "[yellow]Não definida[/]"

        if self.enabled_toolsets is not None:
            toolsets_display = ", ".join(sorted(str(x) for x in self.enabled_toolsets))
        else:
            toolsets_display = "todos"

        verbose_display = "Sim" if self.verbose else "Não"

        def _pair_panel(title: str, pairs: list[tuple[str, str]]) -> Panel:
            inner = _RichTable(show_header=False, box=None, padding=(0, 1), expand=True)
            inner.add_column(style="dim", width=22, overflow="fold", no_wrap=False)
            inner.add_column(overflow="fold")
            for label, value in pairs:
                inner.add_row(label, value)
            return Panel(
                inner,
                title=f"[bold]{title}[/]",
                border_style="cyan",
                padding=(0, 1),
            )

        model_panel = _pair_panel(
            "Modelo",
            [
                ("Modelo", str(self.model)),
                ("URL base", str(self.base_url or "—")),
                ("Chave de API", api_key_display),
            ],
        )

        term_pairs: list[tuple[str, str]] = [("Ambiente", terminal_env)]
        if terminal_env == "ssh":
            ssh_host = os.getenv("TERMINAL_SSH_HOST", "não definido")
            ssh_user = os.getenv("TERMINAL_SSH_USER", "não definido")
            ssh_port = os.getenv("TERMINAL_SSH_PORT", "22")
            term_pairs.append(("Destino SSH", f"{ssh_user}@{ssh_host}:{ssh_port}"))
        term_pairs.extend(
            [
                ("Diretório de trabalho", str(terminal_cwd)),
                ("Tempo limite", f"{terminal_timeout}s"),
            ]
        )
        term_panel = _pair_panel("Terminal", term_pairs)

        agent_panel = _pair_panel(
            "Agente",
            [
                ("Máx. de turnos", str(self.max_turns)),
                ("Toolsets", toolsets_display),
                ("Modo verboso", verbose_display),
            ],
        )

        sess_panel = _pair_panel(
            "Sessão",
            [
                ("Início", self.session_start.strftime("%Y-%m-%d %H:%M:%S")),
                ("Arquivo de config.", f"{config_path} {config_status}"),
            ],
        )

        body = Group(model_panel, term_panel, agent_panel, sess_panel)
        ctx, console, pager_ok = self._cli_pager_ctx()
        footer = (
            "[dim]"
            + (
                "Pager: ↑↓ PageDown · [bold]q[/bold] sair · [bold]ECTOR_NO_PAGER=1[/bold] desativa. "
                if pager_ok
                else ""
            )
            + "[/dim]"
        )
        try:
            with ctx:
                console.print()
                console.print(
                    Panel(
                        body,
                        title="[bold](^_^ ) Configuração[/]",
                        border_style="bright_blue",
                        padding=(1, 1),
                    )
                )
                console.print(footer)
                console.print()
        except Exception:
            console.print()
            console.print(
                Panel(
                    body,
                    title="[bold](^_^ ) Configuração[/]",
                    border_style="bright_blue",
                    padding=(1, 1),
                )
            )
            console.print(footer)
            console.print()
    
    def _list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent CLI sessions for in-chat browsing/resume affordances."""
        if not self._session_db:
            return []
        try:
            sessions = self._session_db.list_sessions_rich(
                source="cli",
                exclude_sources=["tool"],
                limit=limit,
            )
        except Exception:
            return []
        return [s for s in sessions if s.get("id") != self.session_id]

    def _show_recent_sessions(self, *, reason: str = "history", limit: int = 10) -> bool:
        """Render recent sessions inline from the active chat TUI.

        Returns True when something was shown, False if no session list was available.
        """
        sessions = self._list_recent_sessions(limit=limit)
        if not sessions:
            return False

        from ector_cli.main import _relative_time

        console = getattr(self, "console", None) or Console()
        console.print()
        if reason == "history":
            console.print(
                "(._.) [dim]Ainda não há mensagens neste chat — sessões recentes que você pode retomar:[/]"
            )
        else:
            console.print("[bold]Sessões recentes[/]")

        tbl = _RichTable(
            box=rich_box.SIMPLE,
            show_header=True,
            header_style="bold",
            padding=(0, 1),
            expand=True,
        )
        tbl.add_column("Título", style="cyan", width=28, overflow="fold", no_wrap=False)
        tbl.add_column("Prévia", overflow="fold", no_wrap=False)
        tbl.add_column("Última atividade", style="dim", width=16, no_wrap=False)
        tbl.add_column("ID", overflow="fold")
        for session in sessions:
            title = (session.get("title") or "—")[:120]
            preview = (session.get("preview") or "")[:200]
            last_active = _relative_time(session.get("last_active"))
            tbl.add_row(title, preview, last_active, session["id"])
        console.print()
        console.print(tbl)
        console.print()
        console.print(
            "[dim]Use [bold]/resume[/bold] com o ID ou parte do título para continuar de onde parou.[/]"
        )
        console.print()
        return True

    def show_history(self):
        """Mostra o histórico da conversa (pager opcional, pt-BR)."""
        if not self.conversation_history:
            if not self._show_recent_sessions(reason="history"):
                print("(._.) Ainda não há histórico de conversa.")
            return

        ctx, console, _ = self._cli_pager_ctx()
        preview_limit = 400
        visible_index = 0
        hidden_tool_messages = 0

        def flush_tool_summary():
            nonlocal hidden_tool_messages
            if not hidden_tool_messages:
                return
            console.print()
            console.print("  [bold magenta]«Ferramentas»[/]")
            console.print(
                f"    [dim]({hidden_tool_messages} "
                f"{'mensagem de ferramenta omitida' if hidden_tool_messages == 1 else 'mensagens de ferramenta omitidas'})[/]"
            )
            hidden_tool_messages = 0

        def _emit_history() -> None:
            nonlocal visible_index, hidden_tool_messages
            visible_index = 0
            hidden_tool_messages = 0
            console.print()
            console.print(Panel.fit("[bold]Histórico da conversa[/]", border_style="cyan"))
            for msg in self.conversation_history:
                role = msg.get("role", "unknown")

                if role == "tool":
                    hidden_tool_messages += 1
                    continue

                if role not in {"user", "assistant"}:
                    continue

                flush_tool_summary()
                visible_index += 1

                content = msg.get("content")
                content_text = "" if content is None else str(content)

                if role == "user":
                    console.print()
                    console.print(f"  [bold green]Você #{visible_index}[/]")
                    snippet = content_text[:preview_limit] + (
                        "…" if len(content_text) > preview_limit else ""
                    )
                    console.print(f"    {_escape(snippet)}")
                    continue

                console.print()
                console.print(f"  [bold blue]ECTOR #{visible_index}[/]")
                tool_calls = msg.get("tool_calls") or []
                if content_text:
                    preview = content_text[:preview_limit]
                    suffix = "…" if len(content_text) > preview_limit else ""
                    console.print(f"    {_escape(preview + suffix)}")
                elif tool_calls:
                    tool_count = len(tool_calls)
                    if tool_count == 1:
                        console.print("    [dim](1 chamada de ferramenta)[/]")
                    else:
                        console.print(f"    [dim]({tool_count} chamadas de ferramentas)[/]")
                else:
                    console.print("    [dim](sem texto na resposta)[/]")

            flush_tool_summary()
            console.print()

        try:
            with ctx:
                _emit_history()
        except Exception:
            _emit_history()
    
    def _notify_session_boundary(self, event_type: str) -> None:
        """Fire a session-boundary plugin hook (on_session_finalize or on_session_reset).

        Non-blocking — errors are caught and logged.  Safe to call from any
        lifecycle point (shutdown, /new, /reset).
        """
        try:
            from ector_cli.plugins import invoke_hook as _invoke_hook
            _invoke_hook(
                event_type,
                session_id=self.agent.session_id if self.agent else None,
                platform=getattr(self, "platform", None) or "cli",
            )
        except Exception:
            pass

    def new_session(self, silent=False):
        """Start a fresh session with a new session ID and cleared agent state."""
        if self.agent and self.conversation_history:
            # Trigger memory extraction on the old session before session_id rotates.
            self.agent.commit_memory_session(self.conversation_history)
            self._notify_session_boundary("on_session_finalize")
        elif self.agent:
            # First session or empty history — still finalize the old session
            self._notify_session_boundary("on_session_finalize")

        old_session_id = self.session_id
        if self._session_db and old_session_id:
            try:
                self._session_db.end_session(old_session_id, "new_session")
            except Exception:
                pass

        self.session_start = datetime.now()
        timestamp_str = self.session_start.strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        self.session_id = f"{timestamp_str}_{short_uuid}"
        self.conversation_history = []
        self._pending_title = None
        self._resumed = False

        if self.agent:
            self.agent.session_id = self.session_id
            self.agent.session_start = self.session_start
            self.agent.reset_session_state()
            if hasattr(self.agent, "_last_flushed_db_idx"):
                self.agent._last_flushed_db_idx = 0
            if hasattr(self.agent, "_todo_store"):
                try:
                    from tools.todo_tool import TodoStore
                    self.agent._todo_store = TodoStore()
                except Exception:
                    pass
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

            if self._session_db:
                try:
                    self._session_db.create_session(
                        session_id=self.session_id,
                        source=os.environ.get("ECTOR_SESSION_SOURCE", "cli"),
                        model=self.model,
                        model_config={
                            "max_iterations": self.max_turns,
                            "reasoning_config": self.reasoning_config,
                        },
                    )
                except Exception:
                    pass
            self._notify_session_boundary("on_session_reset")

        if not silent:
            print("v Nova sessão iniciada!")

    def _handle_resume_command(self, cmd_original: str) -> None:
        """Handle /resume <session_id_or_title> — switch to a previous session mid-conversation."""
        parts = cmd_original.split(None, 1)
        target = parts[1].strip() if len(parts) > 1 else ""

        if not target:
            _cprint("  Uso: /resume <id_ou_título_da_sessão>")
            if self._show_recent_sessions(reason="resume"):
                return
            _cprint("  Dica: use /history ou `ector sessions list` para listar sessões.")
            return

        if not self._session_db:
            _cprint("  Banco de sessões indisponível.")
            return

        # Resolve title or ID
        from ector_cli.main import _resolve_session_by_name_or_id
        resolved = _resolve_session_by_name_or_id(target)
        target_id = resolved or target

        session_meta = self._session_db.get_session(target_id)
        if not session_meta:
            _cprint(f"  Sessão não encontrada: {target}")
            _cprint("  Use /history ou `ector sessions list` para ver as sessões disponíveis.")
            return

        # If the target is the empty head of a compression chain, redirect to
        # the descendant that actually holds the transcript. See #15000.
        try:
            resolved_id = self._session_db.resolve_resume_session_id(target_id)
        except Exception:
            resolved_id = target_id
        if resolved_id and resolved_id != target_id:
            _cprint(
                f"  A sessão {target_id} foi comprimida em {resolved_id}; "
                f"retomando a descendente com o seu histórico."
            )
            target_id = resolved_id
            resolved_meta = self._session_db.get_session(target_id)
            if resolved_meta:
                session_meta = resolved_meta

        if target_id == self.session_id:
            _cprint("  Você já está nesta sessão.")
            return

        # End current session
        try:
            self._session_db.end_session(self.session_id, "resumed_other")
        except Exception:
            pass

        # Switch to the target session
        self.session_id = target_id
        self._resumed = True
        self._pending_title = None

        # Load conversation history (strip transcript-only metadata entries)
        restored = self._session_db.get_messages_as_conversation(target_id)
        restored = [m for m in (restored or []) if m.get("role") != "session_meta"]
        self.conversation_history = restored

        # Re-open the target session so it's not marked as ended
        try:
            self._session_db.reopen_session(target_id)
        except Exception:
            pass

        # Sync the agent if already initialised
        if self.agent:
            self.agent.session_id = target_id
            self.agent.reset_session_state()
            if hasattr(self.agent, "_last_flushed_db_idx"):
                self.agent._last_flushed_db_idx = len(self.conversation_history)
            if hasattr(self.agent, "_todo_store"):
                try:
                    from tools.todo_tool import TodoStore
                    self.agent._todo_store = TodoStore()
                except Exception:
                    pass
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

        title_part = f" \"{session_meta['title']}\"" if session_meta.get("title") else ""
        msg_count = len([m for m in self.conversation_history if m.get("role") == "user"])
        if self.conversation_history:
            _cprint(
                f"  ↻ Resumed session {target_id}{title_part}"
                f" ({msg_count} user message{'s' if msg_count != 1 else ''},"
                f" {len(self.conversation_history)} total)"
            )
        else:
            _cprint(f"  ↻ Resumed session {target_id}{title_part} — no messages, starting fresh.")

    def _handle_branch_command(self, cmd_original: str) -> None:
        """Handle /branch [name] — fork the current session into a new independent copy.

        Copies the full conversation history to a new session so the user can
        explore a different approach without losing the original session state.
        Inspired by Claude Code's /branch command.
        """
        if not self.conversation_history:
            _cprint("  Não há conversa para ramificar — envie uma mensagem primeiro.")
            return

        if not self._session_db:
            _cprint("  Banco de sessões indisponível.")
            return

        parts = cmd_original.split(None, 1)
        branch_name = parts[1].strip() if len(parts) > 1 else ""

        # Generate the new session ID
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        new_session_id = f"{timestamp_str}_{short_uuid}"

        # Determine branch title
        if branch_name:
            branch_title = branch_name
        else:
            # Auto-generate from the current session title
            current_title = None
            if self._session_db:
                current_title = self._session_db.get_session_title(self.session_id)
            base = current_title or "branch"
            branch_title = self._session_db.get_next_title_in_lineage(base)

        # Save the current session's state before branching
        parent_session_id = self.session_id

        # End the old session
        try:
            self._session_db.end_session(self.session_id, "branched")
        except Exception:
            pass

        # Create the new session with parent link
        try:
            self._session_db.create_session(
                session_id=new_session_id,
                source=os.environ.get("ECTOR_SESSION_SOURCE", "cli"),
                model=self.model,
                model_config={
                    "max_iterations": self.max_turns,
                    "reasoning_config": self.reasoning_config,
                },
                parent_session_id=parent_session_id,
            )
        except Exception as e:
            _cprint(f"  Falha ao criar sessão ramificada: {e}")
            return

        # Copy conversation history to the new session
        for msg in self.conversation_history:
            try:
                self._session_db.append_message(
                    session_id=new_session_id,
                    role=msg.get("role", "user"),
                    content=msg.get("content"),
                    tool_name=msg.get("tool_name") or msg.get("name"),
                    tool_calls=msg.get("tool_calls"),
                    tool_call_id=msg.get("tool_call_id"),
                    reasoning=msg.get("reasoning"),
                )
            except Exception:
                pass  # Best-effort copy

        # Set title on the branch
        try:
            self._session_db.set_session_title(new_session_id, branch_title)
        except Exception:
            pass

        # Switch to the new session
        self.session_id = new_session_id
        self.session_start = now
        self._pending_title = None
        self._resumed = True  # Prevents auto-title generation

        # Sync the agent
        if self.agent:
            self.agent.session_id = new_session_id
            self.agent.session_start = now
            # Redirect the JSON session log to the new branch session file so
            # messages written after branching land in the correct file.
            if hasattr(self.agent, "session_log_file") and hasattr(self.agent, "logs_dir"):
                self.agent.session_log_file = (
                    self.agent.logs_dir / f"session_{new_session_id}.json"
                )
            self.agent.reset_session_state()
            if hasattr(self.agent, "_last_flushed_db_idx"):
                self.agent._last_flushed_db_idx = len(self.conversation_history)
            if hasattr(self.agent, "_todo_store"):
                try:
                    from tools.todo_tool import TodoStore
                    self.agent._todo_store = TodoStore()
                except Exception:
                    pass
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

        msg_count = len([m for m in self.conversation_history if m.get("role") == "user"])
        _cprint(
            f"  ⑂ Sessão ramificada \"{branch_title}\""
            f" ({msg_count} mensagem(ns) do usuário)"
        )
        _cprint(f"  Sessão original: {parent_session_id}")
        _cprint(f"  Sessão da ramificação: {new_session_id}")

    def save_conversation(self):
        """Save the current conversation to a JSON snapshot under ~/.ector/sessions/saved/.

        The snapshot is a convenience export for sharing or off-line inspection;
        every message is already persisted incrementally to the SQLite session
        DB, so the live session remains resumable via ``ector sessions browse``
        regardless of whether the user ever runs ``/save``.
        """
        if not self.conversation_history:
            print("(;_;) Não há conversa para salvar.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_dir = get_ector_home() / "sessions" / "saved"
        try:
            saved_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"(x_x) Falha ao criar o diretório de salvamento {saved_dir}: {e}")
            return
        path = saved_dir / f"ector_conversation_{timestamp}.json"

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "model": self.model,
                    "session_id": self.session_id,
                    "session_start": self.session_start.isoformat(),
                    "messages": self.conversation_history,
                }, f, indent=2, ensure_ascii=False)
            print(f"v Snapshot da conversa salvo em: {path}")
            if self.session_id:
                print(f"       Retome a sessão ativa com: ector sessions browse")
        except Exception as e:
            print(f"(x_x) Falha ao salvar: {e}")
    
    def retry_last(self):
        """Retry the last user message by removing the last exchange and re-sending.
        
        Removes the last assistant response (and any tool-call messages) and
        the last user message, then re-sends that user message to the agent.
        Returns the message to re-send, or None if there's nothing to retry.
        """
        if not self.conversation_history:
            print("(._.) Não há mensagens para tentar de novo.")
            return None
        
        # Walk backwards to find the last user message
        last_user_idx = None
        for i in range(len(self.conversation_history) - 1, -1, -1):
            if self.conversation_history[i].get("role") == "user":
                last_user_idx = i
                break
        
        if last_user_idx is None:
            print("(._.) Nenhuma mensagem do usuário encontrada para repetir.")
            return None
        
        # Extract the message text and remove everything from that point forward
        last_message = self.conversation_history[last_user_idx].get("content", "")
        self.conversation_history = self.conversation_history[:last_user_idx]
        
        print(f"b Tentando novamente: \"{last_message[:60]}{'...' if len(last_message) > 60 else ''}\"")
        return last_message
    
    def undo_last(self):
        """Remove the last user/assistant exchange from conversation history.
        
        Walks backwards and removes all messages from the last user message
        onward (including assistant responses, tool calls, etc.).
        """
        if not self.conversation_history:
            print("(._.) Não há mensagens para desfazer.")
            return
        
        # Walk backwards to find the last user message
        last_user_idx = None
        for i in range(len(self.conversation_history) - 1, -1, -1):
            if self.conversation_history[i].get("role") == "user":
                last_user_idx = i
                break
        
        if last_user_idx is None:
            print("(._.) Nenhuma mensagem do usuário encontrada para desfazer.")
            return
        
        # Count how many messages we're removing
        removed_count = len(self.conversation_history) - last_user_idx
        removed_msg = self.conversation_history[last_user_idx].get("content", "")
        
        # Truncate history to before the last user message
        self.conversation_history = self.conversation_history[:last_user_idx]
        
        print(f"b Desfeito(s) {removed_count} mensagem(ns). Removido: \"{removed_msg[:60]}{'...' if len(removed_msg) > 60 else ''}\"")
        remaining = len(self.conversation_history)
        print(f"  {remaining} mensagem(ns) restantes no histórico.")
    
    def _run_curses_picker(self, title: str, items: list[str], default_index: int = 0) -> int | None:
        """Run curses_single_select via run_in_terminal so prompt_toolkit handles terminal ownership cleanly."""
        import threading
        from ector_cli.curses_ui import curses_single_select

        result = [None]

        def _pick():
            result[0] = curses_single_select(title, items, default_index=default_index)

        # run_in_terminal requires an asyncio event loop — only exists in the
        # main prompt_toolkit thread.  If we're in a background thread (e.g.
        # process_loop), fall back to direct curses call.
        in_main_thread = threading.current_thread() is threading.main_thread()

        if self._app and in_main_thread:
            from prompt_toolkit.application import run_in_terminal
            was_visible = self._status_bar_visible
            self._status_bar_visible = False
            self._app.invalidate()
            try:
                run_in_terminal(_pick)
            finally:
                self._status_bar_visible = was_visible
                self._app.invalidate()
        else:
            _pick()

        return result[0]

    def _prompt_text_input(self, prompt_text: str) -> str | None:
        """Prompt for free-text input safely inside or outside prompt_toolkit."""
        result = [None]

        def _ask():
            try:
                result[0] = input(prompt_text).strip() or None
            except (KeyboardInterrupt, EOFError):
                pass

        if self._app:
            from prompt_toolkit.application import run_in_terminal
            was_visible = self._status_bar_visible
            self._status_bar_visible = False
            self._app.invalidate()
            try:
                run_in_terminal(_ask)
            finally:
                self._status_bar_visible = was_visible
                self._app.invalidate()
        else:
            _ask()
        return result[0]

    def _open_model_picker(self, providers: list, current_model: str, current_provider: str, user_provs=None, custom_provs=None) -> None:
        """Open prompt_toolkit-native /provider picker modal."""
        self._capture_modal_input_snapshot()
        default_idx = next((i for i, p in enumerate(providers) if p.get("is_current")), 0)
        self._model_picker_state = {
            "stage": "provider",
            "providers": providers,
            "selected": default_idx,
            "current_model": current_model,
            "current_provider": current_provider,
            "user_provs": user_provs,
            "custom_provs": custom_provs,
        }
        self._invalidate(min_interval=0.0)

    def _close_model_picker(self) -> None:
        self._model_picker_state = None
        self._restore_modal_input_snapshot()
        self._invalidate(min_interval=0.0)

    @staticmethod
    def _compute_model_picker_viewport(
        selected: int,
        scroll_offset: int,
        n: int,
        term_rows: int,
        reserved_below: int = 6,
        panel_chrome: int = 6,
        min_visible: int = 3,
    ) -> tuple[int, int]:
        """Resolve (scroll_offset, visible) for the /provider picker viewport.

        ``reserved_below`` matches the approval / Wiser (wiser) panels — input area,
        status bar, and separators below the panel. ``panel_chrome`` covers
        this panel's own borders + blanks + hint row. The remaining rows hold
        the scrollable list, with the offset slid to keep ``selected`` on screen.
        """
        max_visible = max(min_visible, term_rows - reserved_below - panel_chrome)
        if n <= max_visible:
            return 0, n
        visible = max_visible
        if selected < scroll_offset:
            scroll_offset = selected
        elif selected >= scroll_offset + visible:
            scroll_offset = selected - visible + 1
        scroll_offset = max(0, min(scroll_offset, n - visible))
        return scroll_offset, visible

    def _apply_model_switch_result(self, result, persist_global: bool) -> None:
        if not result.success:
            _cprint(f"  ✖ {result.error_message}")
            return

        old_model = self.model
        self.model = result.new_model
        self.provider = result.target_provider
        self.requested_provider = result.target_provider
        if result.api_key:
            self.api_key = result.api_key
            self._explicit_api_key = result.api_key
        if result.base_url:
            self.base_url = result.base_url
            self._explicit_base_url = result.base_url
        if result.api_mode:
            self.api_mode = result.api_mode

        if self.agent is not None:
            try:
                self.agent.switch_model(
                    new_model=result.new_model,
                    new_provider=result.target_provider,
                    api_key=result.api_key,
                    base_url=result.base_url,
                    api_mode=result.api_mode,
                )
            except Exception as exc:
                _cprint(f"  ▲ Falha ao trocar modelo no agente ({exc}); alteração vale na próxima sessão.")

        self._pending_model_switch_note = (
            f"[Note: model was just switched from {old_model} to {result.new_model} "
            f"via {result.provider_label or result.target_provider}. "
            f"Adjust your self-identification accordingly.]"
        )

        provider_label = result.provider_label or result.target_provider
        _cprint(f"  ✔ Modelo alterado: {result.new_model}")
        _cprint(f"    Provedor: {provider_label}")

        # Context: always resolve via the provider-aware chain so Codex OAuth,
        # Copilot, and Ector-enforced caps win over the raw models.dev entry
        # (e.g. gpt-5.5 is 1.05M on openai but 272K on Codex OAuth).
        mi = result.model_info
        try:
            from ector_cli.model_switch import resolve_display_context_length
            ctx = resolve_display_context_length(
                result.new_model,
                result.target_provider,
                base_url=result.base_url or self.base_url or "",
                api_key=result.api_key or self.api_key or "",
                model_info=mi,
            )
            if ctx:
                _cprint(f"    Contexto: {ctx:,} tokens")
        except Exception:
            pass
        if mi:
            if mi.max_output:
                _cprint(f"    Saída máx.: {mi.max_output:,} tokens")
            if mi.has_cost_data():
                _cprint(f"    Custo: {mi.format_cost()}")
            _cprint(f"    Recursos: {mi.format_capabilities()}")

        cache_enabled = (
            (base_url_host_matches(result.base_url or "", "openrouter.ai") and "claude" in result.new_model.lower())
            or result.api_mode == "anthropic_messages"
        )
        if cache_enabled:
            _cprint("    Cache de prompt: ativado")
        if result.warning_message:
            _cprint(f"    ▲ {result.warning_message}")
        if persist_global:
            save_config_value("model.default", result.new_model)
            if result.provider_changed:
                save_config_value("model.provider", result.target_provider)
            _cprint("    Salvo em config.yaml (--global)")
        else:
            _cprint("    (apenas nesta sessão — use --global para persistir)")

    def _handle_model_picker_selection(self, persist_global: bool = False) -> None:
        state = self._model_picker_state
        if not state:
            return
        selected = state.get("selected", 0)
        stage = state.get("stage")
        if stage == "provider":
            providers = state.get("providers") or []
            if selected >= len(providers):
                self._close_model_picker()
                return
            provider_data = providers[selected]
            # Use the curated model list from list_authenticated_providers()
            # (same lists as `ector provider` and gateway pickers).
            # Only fall back to the live provider catalog when the curated
            # list is empty (e.g. user-defined endpoints with no curated list).
            model_list = provider_data.get("models", [])
            if not model_list:
                try:
                    from ector_cli.models import provider_model_ids
                    live = provider_model_ids(provider_data["slug"])
                    if live:
                        model_list = live
                except Exception:
                    pass
            state["stage"] = "model"
            state["provider_data"] = provider_data
            state["model_list"] = model_list
            state["selected"] = 0
            self._invalidate(min_interval=0.0)
            return
        if stage == "model":
            provider_data = state.get("provider_data") or {}
            model_list = state.get("model_list") or []
            back_idx = len(model_list)
            cancel_idx = len(model_list) + 1
            if selected == back_idx:
                state["stage"] = "provider"
                state["selected"] = next((i for i, p in enumerate(state.get("providers") or []) if p.get("slug") == provider_data.get("slug")), 0)
                self._invalidate(min_interval=0.0)
                return
            if selected >= cancel_idx:
                self._close_model_picker()
                return
            if selected < len(model_list):
                from ector_cli.model_switch import switch_model
                chosen_model = model_list[selected]
                result = switch_model(
                    raw_input=chosen_model,
                    current_provider=self.provider or "",
                    current_model=self.model or "",
                    current_base_url=self.base_url or "",
                    current_api_key=self.api_key or "",
                    is_global=persist_global,
                    explicit_provider=provider_data.get("slug"),
                    user_providers=state.get("user_provs"),
                    custom_providers=state.get("custom_provs"),
                )
                self._close_model_picker()
                self._apply_model_switch_result(result, persist_global)
                return
            self._close_model_picker()

    def _handle_model_switch(self, cmd_original: str):
        """Handle /provider command — switch model for this session.

        Supports:
          /provider                              — show current model + usage hints
          /provider <name>                       — switch for this session only
          /provider <name> --global              — switch and persist to config.yaml
          /provider <name> --provider <provider> — switch provider + model
          /provider --provider <provider>        — switch to provider, auto-detect model
        """
        from ector_cli.model_switch import switch_model, parse_model_flags, list_authenticated_providers
        from ector_cli.providers import get_label

        # Parse args from the original command
        parts = cmd_original.split(None, 1)  # split off '/provider'
        raw_args = parts[1].strip() if len(parts) > 1 else ""

        # Parse --provider and --global flags
        model_input, explicit_provider, persist_global = parse_model_flags(raw_args)

        # Load providers for switch_model (picker path needs them below)
        user_provs = None
        custom_provs = None
        try:
            from ector_cli.config import get_compatible_custom_providers, load_config
            cfg = load_config()
            user_provs = cfg.get("providers")
            custom_provs = get_compatible_custom_providers(cfg)
        except Exception:
            pass

        # No args at all: open prompt_toolkit-native picker modal
        if not model_input and not explicit_provider:
            model_display = self.model or "unknown"
            provider_display = get_label(self.provider) if self.provider else "unknown"

            try:
                providers = list_authenticated_providers(
                    current_provider=self.provider or "",
                    user_providers=user_provs,
                    custom_providers=custom_provs,
                    max_models=50,
                )
            except Exception:
                providers = []

            if not providers:
                _cprint("  Nenhum provedor autenticado encontrado.")
                _cprint("")
                _cprint("  /provider <nome>                        trocar modelo")
                _cprint("  /provider --provider <slug>             trocar provedor")
                return

            self._open_model_picker(
                providers,
                model_display,
                provider_display,
                user_provs=user_provs,
                custom_provs=custom_provs,
            )
            return

        # Perform the switch
        result = switch_model(
            raw_input=model_input,
            current_provider=self.provider or "",
            current_model=self.model or "",
            current_base_url=self.base_url or "",
            current_api_key=self.api_key or "",
            is_global=persist_global,
            explicit_provider=explicit_provider,
            user_providers=user_provs,
            custom_providers=custom_provs,
        )

        if not result.success:
            _cprint(f"  ✖ {result.error_message}")
            return

        # Apply to CLI state.
        # Update requested_provider so _ensure_runtime_credentials() doesn't
        # overwrite the switch on the next turn (it re-resolves from this).
        old_model = self.model
        self.model = result.new_model
        self.provider = result.target_provider
        self.requested_provider = result.target_provider
        if result.api_key:
            self.api_key = result.api_key
            self._explicit_api_key = result.api_key
        if result.base_url:
            self.base_url = result.base_url
            self._explicit_base_url = result.base_url
        if result.api_mode:
            self.api_mode = result.api_mode

        # Apply to running agent (in-place swap)
        if self.agent is not None:
            try:
                self.agent.switch_model(
                    new_model=result.new_model,
                    new_provider=result.target_provider,
                    api_key=result.api_key,
                    base_url=result.base_url,
                    api_mode=result.api_mode,
                )
            except Exception as exc:
                _cprint(f"  ▲ Falha ao trocar modelo no agente ({exc}); alteração vale na próxima sessão.")

        # Store a note to prepend to the next user message so the model
        # knows a switch occurred (avoids injecting system messages mid-history
        # which breaks providers and prompt caching).
        self._pending_model_switch_note = (
            f"[Note: model was just switched from {old_model} to {result.new_model} "
            f"via {result.provider_label or result.target_provider}. "
            f"Adjust your self-identification accordingly.]"
        )

        # Display confirmation with full metadata
        provider_label = result.provider_label or result.target_provider
        _cprint(f"  ✔ Modelo alterado: {result.new_model}")
        _cprint(f"    Provedor: {provider_label}")

        # Context: always resolve via the provider-aware chain so Codex OAuth,
        # Copilot, and Ector-enforced caps win over the raw models.dev entry
        # (e.g. gpt-5.5 is 1.05M on openai but 272K on Codex OAuth).
        mi = result.model_info
        from ector_cli.model_switch import resolve_display_context_length
        ctx = resolve_display_context_length(
            result.new_model,
            result.target_provider,
            base_url=result.base_url or self.base_url or "",
            api_key=result.api_key or self.api_key or "",
            model_info=mi,
        )
        if ctx:
            _cprint(f"    Context: {ctx:,} tokens")
        if mi:
            if mi.max_output:
                _cprint(f"    Saída máx.: {mi.max_output:,} tokens")
            if mi.has_cost_data():
                _cprint(f"    Custo: {mi.format_cost()}")
            _cprint(f"    Recursos: {mi.format_capabilities()}")

        # Cache notice
        cache_enabled = (
            (base_url_host_matches(result.base_url or "", "openrouter.ai") and "claude" in result.new_model.lower())
            or result.api_mode == "anthropic_messages"
        )
        if cache_enabled:
            _cprint("    Cache de prompt: ativado")

        # Warning from validation
        if result.warning_message:
            _cprint(f"    ▲ {result.warning_message}")

        # Persistence
        if persist_global:
            save_config_value("model.default", result.new_model)
            if result.provider_changed:
                save_config_value("model.provider", result.target_provider)
            _cprint("    Salvo em config.yaml (--global)")
        else:
            _cprint("    (apenas nesta sessão — use --global para persistir)")

    def _should_handle_model_command_inline(self, text: str, has_images: bool = False) -> bool:
        """Return True when /provider should be handled immediately on the UI thread."""
        if not text or has_images or not _looks_like_slash_command(text):
            return False
        try:
            from ector_cli.commands import resolve_command
            base = text.split(None, 1)[0].lower().lstrip('/')
            cmd = resolve_command(base)
            return bool(cmd and cmd.name == "model")
        except Exception:
            return False

    def _should_handle_steer_command_inline(self, text: str, has_images: bool = False) -> bool:
        """Return True when /steer should be dispatched immediately while the agent is running.

        /steer MUST bypass the normal _pending_input → process_loop path when
        the agent is active, because process_loop is blocked inside
        self.chat() for the duration of the run.  By the time the queued
        command is pulled from _pending_input, _agent_running has already
        flipped back to False, and process_command() takes the idle
        fallback — delivering the steer as a next-turn message instead of
        injecting it mid-run.  Dispatching inline on the UI thread calls
        agent.steer() directly, which is thread-safe (uses _pending_steer_lock).
        """
        if not text or has_images or not _looks_like_slash_command(text):
            return False
        if not getattr(self, "_agent_running", False):
            return False
        try:
            from ector_cli.commands import resolve_command
            base = text.split(None, 1)[0].lower().lstrip('/')
            cmd = resolve_command(base)
            return bool(cmd and cmd.name == "steer")
        except Exception:
            return False

    def _output_console(self):
        """Use prompt_toolkit-safe Rich rendering once the TUI is live."""
        if getattr(self, "_app", None):
            return ChatConsole()
        return self.console

    def _console_print(self, *args, **kwargs):
        """Print through the active command-safe console."""
        self._output_console().print(*args, **kwargs)

    @staticmethod
    def _resolve_personality_prompt(value) -> str:
        """Accept string or dict personality value; return system prompt string."""
        if isinstance(value, dict):
            parts = [value.get("system_prompt", "")]
            if value.get("tone"):
                parts.append(f'Tone: {value["tone"]}' )
            if value.get("style"):
                parts.append(f'Style: {value["style"]}' )
            return "\n".join(p for p in parts if p)
        return str(value)

    def _handle_gquota_command(self, cmd_original: str) -> None:
        """Show Google Gemini Code Assist quota usage for the current OAuth account."""
        try:
            from agent.google_oauth import get_valid_access_token, GoogleOAuthError, load_credentials
            from agent.google_code_assist import retrieve_user_quota, CodeAssistError
        except ImportError as exc:
            self._console_print(f"  [red]Gemini modules unavailable: {exc}[/]")
            return

        try:
            access_token = get_valid_access_token()
        except GoogleOAuthError as exc:
            self._console_print(f"  [yellow]{exc}[/]")
            self._console_print("  Run [bold]/provider[/] and pick 'Google Gemini (OAuth)' to sign in.")
            return

        creds = load_credentials()
        project_id = (creds.project_id if creds else "") or ""

        try:
            buckets = retrieve_user_quota(access_token, project_id=project_id)
        except CodeAssistError as exc:
            self._console_print(f"  [red]Quota lookup failed:[/] {exc}")
            return

        if not buckets:
            self._console_print("  [dim]No quota buckets reported (account may be on legacy/unmetered tier).[/]")
            return

        # Sort for stable display, group by model
        buckets.sort(key=lambda b: (b.model_id, b.token_type))
        self._console_print()
        self._console_print(f"  [bold]Gemini Code Assist quota[/]  (project: {project_id or '(auto / free-tier)'})")
        self._console_print()
        for b in buckets:
            pct = max(0.0, min(1.0, b.remaining_fraction))
            width = 20
            filled = int(round(pct * width))
            bar = "▓" * filled + "░" * (width - filled)
            pct_str = f"{int(pct * 100):3d}%"
            header = b.model_id
            if b.token_type:
                header += f" [{b.token_type}]"
            self._console_print(f"    {header:40s}  {bar}  {pct_str}")
        self._console_print()

    def _handle_personality_command(self, cmd: str):
        """Handle the /personality command to set predefined personalities."""
        parts = cmd.split(maxsplit=1)
        
        if len(parts) > 1:
            # Set personality
            personality_name = parts[1].strip().lower()
            
            if personality_name in ("none", "default", "neutral"):
                self.system_prompt = ""
                self.agent = None  # Force re-init
                if save_config_value("agent.system_prompt", ""):
                    save_config_value("display.personality", "")
                    print("b Personalidade removida (salva na config)")
                else:
                    print(" Personalidade removida (apenas nesta sessão)")
                print("  Sem overlay de personalidade — comportamento base do agente.")
            elif personality_name in self.personalities:
                self.system_prompt = self._resolve_personality_prompt(self.personalities[personality_name])
                self.agent = None  # Force re-init
                if save_config_value("agent.system_prompt", self.system_prompt):
                    save_config_value("display.personality", personality_name)
                    print(f"b Personalidade definida como '{personality_name}' (salva na config)")
                else:
                    print(f" Personalidade definida como '{personality_name}' (apenas nesta sessão)")
                print(f"  \"{self.system_prompt[:60]}{'...' if len(self.system_prompt) > 60 else ''}\"")
            else:
                print(f"(._.) Personalidade desconhecida: {personality_name}")
                print(f"  Disponíveis: none, {', '.join(self.personalities.keys())}")
        else:
            # Show available personalities
            print()
            print("+" + "-" * 50 + "+")
            print("|" + " " * 12 + "(^o^)/ Personalidades" + " " * 14 + "|")
            print("+" + "-" * 50 + "+")
            print()
            print(f"  {'none':<12} - (sem overlay de personalidade)")
            for name, prompt in self.personalities.items():
                if isinstance(prompt, dict):
                    preview = prompt.get("description") or prompt.get("system_prompt", "")[:50]
                else:
                    preview = str(prompt)[:50]
                print(f"  {name:<12} - {preview}")
            print()
            print("  Uso: /personality <nome>")
            print()
    
    def _handle_cron_command(self, cmd: str):
        """Handle the /cron command to manage scheduled tasks."""
        import shlex
        from ector_constants import get_ector_home
        from tools.cronjob_tools import cronjob as cronjob_tool

        def _cron_api(**kwargs):
            return json.loads(cronjob_tool(**kwargs))

        def _normalize_skills(values):
            normalized = []
            for value in values:
                text = str(value or "").strip()
                if text and text not in normalized:
                    normalized.append(text)
            return normalized

        def _parse_flags(tokens):
            opts = {
                "name": None,
                "deliver": None,
                "repeat": None,
                "skills": [],
                "add_skills": [],
                "remove_skills": [],
                "clear_skills": False,
                "all": False,
                "prompt": None,
                "schedule": None,
                "positionals": [],
            }
            i = 0
            while i < len(tokens):
                token = tokens[i]
                if token == "--name" and i + 1 < len(tokens):
                    opts["name"] = tokens[i + 1]
                    i += 2
                elif token == "--deliver" and i + 1 < len(tokens):
                    opts["deliver"] = tokens[i + 1]
                    i += 2
                elif token == "--repeat" and i + 1 < len(tokens):
                    try:
                        opts["repeat"] = int(tokens[i + 1])
                    except ValueError:
                        print("(._.) --repeat precisa ser um número inteiro")
                        return None
                    i += 2
                elif token == "--skill" and i + 1 < len(tokens):
                    opts["skills"].append(tokens[i + 1])
                    i += 2
                elif token == "--add-skill" and i + 1 < len(tokens):
                    opts["add_skills"].append(tokens[i + 1])
                    i += 2
                elif token == "--remove-skill" and i + 1 < len(tokens):
                    opts["remove_skills"].append(tokens[i + 1])
                    i += 2
                elif token == "--clear-skills":
                    opts["clear_skills"] = True
                    i += 1
                elif token == "--all":
                    opts["all"] = True
                    i += 1
                elif token == "--prompt" and i + 1 < len(tokens):
                    opts["prompt"] = tokens[i + 1]
                    i += 2
                elif token == "--schedule" and i + 1 < len(tokens):
                    opts["schedule"] = tokens[i + 1]
                    i += 2
                else:
                    opts["positionals"].append(token)
                    i += 1
            return opts

        tokens = shlex.split(cmd)

        if len(tokens) == 1:
            print()
            print("+" + "-" * 68 + "+")
            print("|" + " " * 20 + " Tarefas agendadas (cron)" + " " * 18 + "|")
            print("+" + "-" * 68 + "+")
            print()
            print("  Comandos:")
            print("    /cron list")
            print("    /cron parity [--limit N]")
            print('    /cron add "every 2h" "Verificar status do servidor" [--skill blogwatcher]')
            print('    /cron edit <job_id> --schedule "every 4h" --prompt "Nova tarefa"')
            print("    /cron edit <job_id> --skill blogwatcher --skill maps")
            print("    /cron edit <job_id> --remove-skill blogwatcher")
            print("    /cron edit <job_id> --clear-skills")
            print("    /cron pause <job_id>")
            print("    /cron resume <job_id>")
            print("    /cron run <job_id>")
            print("    /cron remove <job_id>")
            print()
            result = _cron_api(action="list")
            jobs = result.get("jobs", []) if result.get("success") else []
            if jobs:
                print("  Jobs atuais:")
                print("  " + "-" * 63)
                for job in jobs:
                    repeat_str = job.get("repeat", "?")
                    print(f"    {job['job_id'][:12]:<12} | {job['schedule']:<15} | {repeat_str:<8}")
                    if job.get("skills"):
                        print(f"      Skills: {', '.join(job['skills'])}")
                    print(f"      {job.get('prompt_preview', '')}")
                    if job.get("next_run_at"):
                        print(f"      Próximo: {job['next_run_at']}")
                    print()
            else:
                print("  Nenhum job agendado. Use '/cron add' para criar um.")
            print()
            return

        subcommand = tokens[1].lower()
        opts = _parse_flags(tokens[2:])
        if opts is None:
            return

        if subcommand == "list":
            result = _cron_api(action="list", include_disabled=opts["all"])
            jobs = result.get("jobs", []) if result.get("success") else []
            if not jobs:
                print("Nenhum cron agendado")
                return

            print()
            print("Jobs agendados:")
            print("-" * 80)
            for job in jobs:
                print(f"  ID: {job['job_id']}")
                print(f"  Nome: {job['name']}")
                print(f"  Estado: {job.get('state', '?')}")
                print(f"  Agenda: {job['schedule']} ({job.get('repeat', '?')})")
                print(f"  Próxima execução: {job.get('next_run_at', 's/n')}")
                if job.get("skills"):
                    print(f"  Skills: {', '.join(job['skills'])}")
                print(f"  Prompt: {job.get('prompt_preview', '')}")
                if job.get("last_run_at"):
                    print(f"  Última execução: {job['last_run_at']} ({job.get('last_status', '?')})")
                print()
            return

        if subcommand == "parity":
            positionals = opts["positionals"]
            limit = 20
            if "--limit" in positionals:
                try:
                    idx = positionals.index("--limit")
                    if idx + 1 < len(positionals):
                        limit = max(1, min(500, int(positionals[idx + 1])))
                except (ValueError, TypeError):
                    print("(._.) --limit inválido. Exemplo: /cron parity --limit 50")
                    return

            parity_file = get_ector_home() / "cron" / "scheduler-parity.jsonl"
            if not parity_file.exists():
                print("(._.) Sem dados de paridade ainda.")
                print("  Ative cron.engine=shadow ou cron.engine=apscheduler para coletar métricas.")
                return

            events = []
            try:
                with open(parity_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                print(f"(x_x) Falha ao ler paridade: {e}")
                return

            if not events:
                print("(._.) Arquivo de paridade está vazio.")
                return

            sample = events[-limit:]
            by_mode = {}
            total_jobs = 0
            drift_max = 0.0
            legacy_only = 0
            aps_only = 0
            for ev in sample:
                mode = str(ev.get("mode", "unknown"))
                by_mode[mode] = by_mode.get(mode, 0) + 1
                total_jobs += int(ev.get("jobs_executed", 0) or 0)
                drift_max = max(drift_max, float(ev.get("max_drift_seconds", 0) or 0))
                legacy_only += len(ev.get("legacy_only_due_ids", []) or [])
                aps_only += len(ev.get("aps_only_due_ids", []) or [])

            print()
            print("Paridade do scheduler (cron):")
            print("-" * 80)
            print(f"  Arquivo: {parity_file}")
            print(f"  Eventos lidos: {len(sample)} de {len(events)} total")
            print(f"  Modo(s): {', '.join(f'{k}={v}' for k, v in sorted(by_mode.items()))}")
            print(f"  Jobs executados no recorte: {total_jobs}")
            print(f"  Drift máximo (segundos): {drift_max:.2f}")
            print(f"  Divergência due-set (legacy_only): {legacy_only}")
            print(f"  Divergência due-set (aps_only): {aps_only}")

            last = sample[-1]
            print()
            print("Último evento:")
            print(f"  ts={last.get('ts')} mode={last.get('mode')} jobs={last.get('jobs_executed', 0)}")
            print(f"  drift_count={last.get('drift_count', 0)} max_drift={float(last.get('max_drift_seconds', 0) or 0):.2f}s")
            if last.get("legacy_only_due_ids") or last.get("aps_only_due_ids"):
                print(f"  legacy_only_due_ids={last.get('legacy_only_due_ids', [])}")
                print(f"  aps_only_due_ids={last.get('aps_only_due_ids', [])}")
            print()
            return

        if subcommand in {"add", "create"}:
            positionals = opts["positionals"]
            if not positionals:
                print("(._.) Uso: /cron add <agenda> <prompt>")
                return
            schedule = opts["schedule"] or positionals[0]
            prompt = opts["prompt"] or " ".join(positionals[1:])
            skills = _normalize_skills(opts["skills"])
            if not prompt and not skills:
                print("(._.) Informe um prompt ou pelo menos uma skill")
                return
            result = _cron_api(
                action="create",
                schedule=schedule,
                prompt=prompt or None,
                name=opts["name"],
                deliver=opts["deliver"],
                repeat=opts["repeat"],
                skills=skills or None,
            )
            if result.get("success"):
                print(f"b Job criado: {result['job_id']}")
                print(f"  Agenda: {result['schedule']}")
                if result.get("skills"):
                    print(f"  Skills: {', '.join(result['skills'])}")
                print(f"  Próxima execução: {result['next_run_at']}")
            else:
                print(f"(x_x) Falha ao criar o job: {result.get('error')}")
            return

        if subcommand == "edit":
            positionals = opts["positionals"]
            if not positionals:
                print("(._.) Uso: /cron edit <job_id> [--schedule ...] [--prompt ...] [--skill ...]")
                return
            job_id = positionals[0]
            existing = get_job(job_id)
            if not existing:
                print(f"(._.) Job não encontrado: {job_id}")
                return

            final_skills = None
            replacement_skills = _normalize_skills(opts["skills"])
            add_skills = _normalize_skills(opts["add_skills"])
            remove_skills = set(_normalize_skills(opts["remove_skills"]))
            existing_skills = list(existing.get("skills") or ([] if not existing.get("skill") else [existing.get("skill")]))
            if opts["clear_skills"]:
                final_skills = []
            elif replacement_skills:
                final_skills = replacement_skills
            elif add_skills or remove_skills:
                final_skills = [skill for skill in existing_skills if skill not in remove_skills]
                for skill in add_skills:
                    if skill not in final_skills:
                        final_skills.append(skill)

            result = _cron_api(
                action="update",
                job_id=job_id,
                schedule=opts["schedule"],
                prompt=opts["prompt"],
                name=opts["name"],
                deliver=opts["deliver"],
                repeat=opts["repeat"],
                skills=final_skills,
            )
            if result.get("success"):
                job = result["job"]
                print(f"b Job atualizado: {job['job_id']}")
                print(f"  Agenda: {job['schedule']}")
                if job.get("skills"):
                    print(f"  Skills: {', '.join(job['skills'])}")
                else:
                    print("  Skills: nenhuma")
            else:
                print(f"(x_x) Falha ao atualizar o job: {result.get('error')}")
            return

        if subcommand in {"pause", "resume", "run", "remove", "rm", "delete"}:
            positionals = opts["positionals"]
            if not positionals:
                print(f"(._.) Uso: /cron {subcommand} <job_id>")
                return
            job_id = positionals[0]
            action = "remove" if subcommand in {"remove", "rm", "delete"} else subcommand
            result = _cron_api(action=action, job_id=job_id, reason="paused from /cron" if action == "pause" else None)
            if not result.get("success"):
                _act_pt = {"pause": "pausar", "resume": "retomar", "run": "disparar", "remove": "remover"}
                print(f"(x_x) Falha ao {_act_pt.get(action, action)} o job: {result.get('error')}")
                return
            if action == "pause":
                print(f"b Job pausado: {result['job']['name']} ({job_id})")
            elif action == "resume":
                print(f"b Job retomado: {result['job']['name']} ({job_id})")
                print(f"  Próxima execução: {result['job'].get('next_run_at')}")
            elif action == "run":
                print(f"b Job disparado: {result['job']['name']} ({job_id})")
                print("  Será executado no próximo tick do agendador.")
            else:
                removed = result.get("removed_job", {})
                print(f"b Job removido: {removed.get('name', job_id)} ({job_id})")
            return

        print(f"(._.) Comando cron desconhecido: {subcommand}")
        print("  Disponíveis: list, parity, add, edit, pause, resume, run, remove")

    def _handle_reset_command(self, cmd: str):
        """Handle /reset slash command."""
        from ector_cli.reset import run_reset
        from types import SimpleNamespace

        parts = cmd.split()
        hard = "--hard" in parts
        yes = "-y" in parts or "--yes" in parts

        # We need to simulate the argparse Namespace
        args = SimpleNamespace(hard=hard, yes=yes)
        run_reset(args)
        
        # After reset, we must ensure the UI reflects the new state if possible
        # or just exit if things are too broken. Usually we just stay in the CLI.
        if yes or "--hard" in parts:
            # If it was a hard reset, many things might be invalid now.
            # But let's assume the user knows what they are doing.
            pass
    
    def _handle_skills_command(self, cmd: str):
        """Handle /skills slash command — delegates to ector_cli.skills_hub."""
        from ector_cli.skills_hub import handle_skills_slash
        handle_skills_slash(cmd, ChatConsole())

    def _show_gateway_status(self):
        """Estado do gateway e plataformas de mensagem (Rich, pt-BR)."""
        from gateway.config import load_gateway_config, Platform
        from ector_constants import display_ector_home

        console = getattr(self, "console", None) or Console()
        platform_rows = {
            Platform.TELEGRAM: ("Telegram", "TELEGRAM_BOT_TOKEN"),
            Platform.DISCORD: ("Discord", "DISCORD_BOT_TOKEN"),
            Platform.WHATSAPP: ("WhatsApp", "WHATSAPP_ENABLED"),
        }

        try:
            config = load_gateway_config()
            tbl = _RichTable(
                box=rich_box.ROUNDED,
                show_header=True,
                header_style="bold",
                expand=True,
            )
            tbl.add_column("Plataforma", style="cyan", no_wrap=True)
            tbl.add_column("Estado", overflow="fold")
            tbl.add_column("Detalhe", overflow="fold")
            for platform, (name, env_var) in platform_rows.items():
                pconfig = config.platforms.get(platform)
                if pconfig and pconfig.enabled:
                    home = config.get_home_channel(platform)
                    home_str = f"Canal: {home.name}" if home else "—"
                    tbl.add_row(name, "[green]Ativada[/]", home_str)
                else:
                    tbl.add_row(
                        name,
                        "[dim]Não configurada[/]",
                        f"Defina [bold]{env_var}[/] ou habilite em config.yaml",
                    )

            policy = config.default_reset_policy
            pol = _RichTable(
                box=rich_box.ROUNDED,
                show_header=True,
                header_style="bold",
                title="[bold]Política de reinício de sessão[/]",
                expand=True,
            )
            pol.add_column("Campo", style="dim", no_wrap=False)
            pol.add_column("Valor", overflow="fold")
            pol.add_row("Modo", str(policy.mode))
            pol.add_row("Reinício diário (hora UTC)", f"{policy.at_hour}:00")
            pol.add_row("Tempo ocioso (minutos)", str(policy.idle_minutes))

            hint = (
                f"[dim]Iniciar o gateway: [bold]ector gateway run[/bold]. "
                f"Arquivo de configuração: [bold]{display_ector_home()}/config.yaml[/bold][/dim]"
            )

            body = Group(tbl, pol, _RichText.from_markup(hint))
            console.print()
            console.print(
                Panel(
                    body,
                    title="[bold](✿◠‿◠) Gateway[/]",
                    border_style="bright_blue",
                    padding=(1, 1),
                )
            )
            console.print()
        except Exception as e:
            console.print()
            console.print(f"[red]Erro ao carregar config do gateway:[/] {_escape(str(e))}")
            console.print(
                "[dim]1) Variáveis de ambiente, ex.: TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN\n"
                f"2) Ou ajuste em {display_ector_home()}/config.yaml[/dim]"
            )
            console.print()
    
    def process_command(self, command: str) -> bool:
        """
        Process a slash command.
        
        Args:
            command: The command string (starting with /)
            
        Returns:
            bool: True to continue, False to exit
        """
        # Lowercase only for dispatch matching; preserve original case for arguments
        cmd_lower = command.lower().strip()
        cmd_original = command.strip()

        # Resolve aliases via central registry so adding an alias is a one-line
        # change in ector_cli/commands.py instead of touching every dispatch site.
        from ector_cli.commands import resolve_command as _resolve_cmd
        _base_word = cmd_lower.split()[0].lstrip("/")
        _cmd_def = _resolve_cmd(_base_word)
        canonical = _cmd_def.name if _cmd_def else _base_word
        
        if canonical in ("quit", "exit", "q"):
            return False
        elif canonical == "help":
            self.show_help()
        elif canonical == "profile":
            self._handle_profile_command()
        elif canonical == "tools":
            self._handle_tools_command(cmd_original)
        elif canonical == "toolsets":
            self.show_toolsets()
        elif canonical == "config":
            self.show_config()
        elif canonical == "redraw":
            # Manual recovery for terminal buffer drift from multiplexer
            # tab switches, subshell ``clear``, SSH window restores, etc.
            # See issue #8688 (cmux). Ctrl+L is bound to the same helper.
            self._force_full_redraw()
            _cprint(f"  {_DIM}✔ UI redrawn{_RST}")
        elif canonical == "clear":
            self.new_session(silent=True)
            self._force_full_redraw()
        elif canonical == "reset":
            self._handle_reset_command(cmd_original)
            return True
        elif canonical == "history":
            self.show_history()
        elif canonical == "title":
            parts = cmd_original.split(maxsplit=1)
            if len(parts) > 1:
                raw_title = parts[1].strip()
                if raw_title:
                    if self._session_db:
                        # Sanitize the title early so feedback matches what gets stored
                        try:
                            from ector_state import SessionDB
                            new_title = SessionDB.sanitize_title(raw_title)
                        except ValueError as e:
                            _cprint(f"  {e}")
                            new_title = None
                        if not new_title:
                            _cprint("  O título ficou vazio após a limpeza. Use caracteres imprimíveis.")
                        elif self._session_db.get_session(self.session_id):
                            # Session exists in DB — set title directly
                            try:
                                if self._session_db.set_session_title(
                                    self.session_id, new_title, user_set=True
                                ):
                                    _cprint(f"  Título da sessão definido: {new_title}")
                                else:
                                    _cprint("  Sessão não encontrada no banco de dados.")
                            except ValueError as e:
                                _cprint(f"  {e}")
                        else:
                            # Session not created yet — defer the title
                            # Check uniqueness proactively with the sanitized title
                            existing = self._session_db.get_session_by_title(new_title)
                            if existing:
                                _cprint(f"  O título '{new_title}' já está em uso pela sessão {existing['id']}")
                            else:
                                self._pending_title = new_title
                                _cprint(f"  Título da sessão enfileirado: {new_title} (será salvo na primeira mensagem)")
                    else:
                        _cprint("  Banco de sessões indisponível.")
                else:
                    _cprint("  Uso: /title <título da sessão>")
            else:
                # Show current title and session ID if no argument given
                if self._session_db:
                    _cprint(f"  Session ID: {self.session_id}")
                    session = self._session_db.get_session(self.session_id)
                    if session and session.get("title"):
                        _cprint(f"  Title: {session['title']}")
                    elif self._pending_title:
                        _cprint(f"  Title (pending): {self._pending_title}")
                    else:
                        _cprint("  Sem título. Uso: /title <título da sessão>")
                else:
                    _cprint("  Banco de sessões indisponível.")
        elif canonical == "new":
            self.new_session()
        elif canonical == "resume":
            self._handle_resume_command(cmd_original)
        elif canonical == "provider":
            self._handle_model_switch(cmd_original)
        elif canonical == "gquota":
            self._handle_gquota_command(cmd_original)

        elif canonical == "personality":
            # Use original case (handler lowercases the personality name itself)
            self._handle_personality_command(cmd_original)
        elif canonical == "retry":
            retry_msg = self.retry_last()
            if retry_msg and hasattr(self, '_pending_input'):
                # Re-queue the message so process_loop sends it to the agent
                self._pending_input.put(retry_msg)
        elif canonical == "undo":
            self.undo_last()
        elif canonical == "branch":
            self._handle_branch_command(cmd_original)
        elif canonical == "save":
            self.save_conversation()
        elif canonical == "cron":
            self._handle_cron_command(cmd_original)
        elif canonical == "skills":
            with self._busy_command(self._slow_command_status(cmd_original)):
                self._handle_skills_command(cmd_original)
        elif canonical == "platforms":
            self._show_gateway_status()
        elif canonical == "status":
            self._show_session_status()
        elif canonical == "statusbar":
            self._status_bar_visible = not self._status_bar_visible
            state = "visible" if self._status_bar_visible else "hidden"
            self._console_print(f"  Status bar {state}")
        elif canonical == "verbose":
            self._toggle_verbose()
        elif canonical == "yolo":
            self._toggle_yolo()
        elif canonical == "reasoning":
            self._handle_reasoning_command(cmd_original)
        elif canonical == "fast":
            self._handle_fast_command(cmd_original)
        elif canonical == "compress":
            self._manual_compress(cmd_original)
        elif canonical == "usage":
            self._show_usage()
        elif canonical == "stats":
            self._show_stats(cmd_original)
        elif canonical == "copy":
            self._handle_copy_command(cmd_original)
        elif canonical == "debug":
            self._handle_debug_command()
        elif canonical == "paste":
            self._handle_paste_command()
        elif canonical == "image":
            self._handle_image_command(cmd_original)
        elif canonical == "reload":
            from ector_cli.config import reload_env
            count = reload_env()
            print(f"  Reloaded .env ({count} var(s) updated)")
        elif canonical == "reload-mcp":
            with self._busy_command(self._slow_command_status(cmd_original)):
                self._reload_mcp()
        elif canonical == "browser":
            self._handle_browser_command(cmd_original)
        elif canonical == "plugins":
            try:
                from ector_cli.plugins import get_plugin_manager
                mgr = get_plugin_manager()
                plugins = mgr.list_plugins()
                if not plugins:
                    print("No plugins installed.")
                    print(f"Drop plugin directories into {display_ector_home()}/plugins/ to get started.")
                else:
                    print(f"Plugins ({len(plugins)}):")
                    for p in plugins:
                        status = "✔" if p["enabled"] else "✖"
                        version = f" v{p['version']}" if p["version"] else ""
                        tools = f"{p['tools']} tools" if p["tools"] else ""
                        hooks = f"{p['hooks']} hooks" if p["hooks"] else ""
                        commands = f"{p['commands']} commands" if p.get("commands") else ""
                        parts = [x for x in [tools, hooks, commands] if x]
                        detail = f" ({', '.join(parts)})" if parts else ""
                        error = f" — {p['error']}" if p["error"] else ""
                        print(f"  {status} {p['name']}{version}{detail}{error}")
            except Exception as e:
                print(f"Plugin system error: {e}")
        elif canonical == "rollback":
            self._handle_rollback_command(cmd_original)
        elif canonical == "snapshot":
            self._handle_snapshot_command(cmd_original)
        elif canonical == "stop":
            self._handle_stop_command()
        elif canonical == "agents":
            self._handle_agents_command()
        elif canonical == "background":
            self._handle_background_command(cmd_original)
        elif canonical == "queue":
            # Extract prompt after "/queue " or "/q "
            parts = cmd_original.split(None, 1)
            payload = parts[1].strip() if len(parts) > 1 else ""
            if not payload:
                _cprint("  Uso: /queue <prompt>")
            else:
                self._pending_input.put(payload)
                if self._agent_running:
                    _cprint(f"  Queued for the next turn: {payload[:80]}{'...' if len(payload) > 80 else ''}")
                else:
                    _cprint(f"  Queued: {payload[:80]}{'...' if len(payload) > 80 else ''}")
        elif canonical == "steer":
            # Inject a message after the next tool call without interrupting.
            # If the agent is actively running, push the text into the agent's
            # pending_steer slot — the drain hook in _execute_tool_calls_*
            # will append it to the next tool result's content. If no agent
            # is running, fall back to queue semantics (same as /queue).
            parts = cmd_original.split(None, 1)
            payload = parts[1].strip() if len(parts) > 1 else ""
            if not payload:
                _cprint("  Uso: /steer <prompt>")
            elif self._agent_running and self.agent is not None and hasattr(self.agent, "steer"):
                try:
                    accepted = self.agent.steer(payload)
                except Exception as exc:
                    _cprint(f"  Steer failed: {exc}")
                else:
                    if accepted:
                        _cprint(f"  ⏩ Steer queued — arrives after the next tool call: {payload[:80]}{'...' if len(payload) > 80 else ''}")
                    else:
                        _cprint("  Steer rejeitado (payload vazio).")
            else:
                # No active run — treat as a normal next-turn message.
                self._pending_input.put(payload)
                _cprint(f"  No agent running; queued as next turn: {payload[:80]}{'...' if len(payload) > 80 else ''}")
        elif canonical == "voice":
            self._handle_voice_command(cmd_original)
        elif canonical == "busy":
            self._handle_busy_command(cmd_original)
        elif canonical == "rag":
            self._handle_rag_command(cmd_original)
        else:
            # Check for user-defined quick commands (bypass agent loop, no LLM call)
            base_cmd = cmd_lower.split()[0]
            quick_commands = self.config.get("quick_commands", {})
            if base_cmd.lstrip("/") in quick_commands:
                qcmd = quick_commands[base_cmd.lstrip("/")]
                if qcmd.get("type") == "exec":
                    import subprocess
                    exec_cmd = qcmd.get("command", "")
                    if exec_cmd:
                        try:
                            result = subprocess.run(
                                exec_cmd, shell=True, capture_output=True,
                                text=True, timeout=30
                            )
                            output = result.stdout.strip() or result.stderr.strip()
                            if output:
                                self._console_print(_rich_text_from_ansi(output))
                            else:
                                self._console_print("[dim]Command returned no output[/]")
                        except subprocess.TimeoutExpired:
                            self._console_print("[bold red]Quick command timed out (30s)[/]")
                        except Exception as e:
                            self._console_print(f"[bold red]Quick command error: {e}[/]")
                    else:
                        self._console_print(f"[bold red]Quick command '{base_cmd}' has no command defined[/]")
                elif qcmd.get("type") == "alias":
                    target = qcmd.get("target", "").strip()
                    if target:
                        target = target if target.startswith("/") else f"/{target}"
                        user_args = cmd_original[len(base_cmd):].strip()
                        aliased_command = f"{target} {user_args}".strip()
                        return self.process_command(aliased_command)
                    else:
                        self._console_print(f"[bold red]Quick command '{base_cmd}' has no target defined[/]")
                else:
                    self._console_print(f"[bold red]Quick command '{base_cmd}' has unsupported type (supported: 'exec', 'alias')[/]")
            # Check for plugin-registered slash commands
            elif base_cmd.lstrip("/") in _get_plugin_cmd_handler_names():
                from ector_cli.plugins import get_plugin_command_handler
                plugin_handler = get_plugin_command_handler(base_cmd.lstrip("/"))
                if plugin_handler:
                    user_args = cmd_original[len(base_cmd):].strip()
                    try:
                        result = plugin_handler(user_args)
                        if result:
                            _cprint(str(result))
                    except Exception as e:
                        _cprint(f"\033[1;31mPlugin command error: {e}{_RST}")
            # Check for skill slash commands (/gif-search, /axolotl, etc.)
            elif base_cmd in _skill_commands:
                user_instruction = cmd_original[len(base_cmd):].strip()
                msg = build_skill_invocation_message(
                    base_cmd, user_instruction, task_id=self.session_id
                )
                if msg:
                    skill_name = _skill_commands[base_cmd]["name"]
                    print(f"\n⚡ Loading skill: {skill_name}")
                    if hasattr(self, '_pending_input'):
                        self._pending_input.put(msg)
                else:
                    ChatConsole().print(f"[bold red]Falha ao carregar skill para {base_cmd}[/]")
            else:
                # Prefix matching: if input uniquely identifies one command, execute it.
                # Matches against both built-in COMMANDS and installed skill commands so
                # that execution-time resolution agrees with tab-completion.
                from ector_cli.commands import COMMANDS
                typed_base = cmd_lower.split()[0]
                all_known = set(COMMANDS) | set(_skill_commands)
                matches = [c for c in all_known if c.startswith(typed_base)]
                if len(matches) > 1:
                    # Prefer an exact match (typed the full command name)
                    exact = [c for c in matches if c == typed_base]
                    if len(exact) == 1:
                        matches = exact
                    else:
                        # Prefer the unique shortest match:
                        # /qui → /quit (5) wins over /quint-pipeline (15)
                        min_len = min(len(c) for c in matches)
                        shortest = [c for c in matches if len(c) == min_len]
                        if len(shortest) == 1:
                            matches = shortest
                if len(matches) == 1:
                    # Expand the prefix to the full command name, preserving arguments.
                    # Guard against redispatching the same token to avoid infinite
                    # recursion when the expanded name still doesn't hit an exact branch
                    # (e.g. /config with extra args that are not yet handled above).
                    full_name = matches[0]
                    if full_name == typed_base:
                        # Already an exact token — no expansion possible; fall through
                        _cprint(f"\033[1;31mUnknown command: {cmd_lower}{_RST}")
                        _cprint(f"{_DIM}{_ACCENT}Type /help for available commands{_RST}")
                    else:
                        remainder = cmd_original.strip()[len(typed_base):]
                        full_cmd = full_name + remainder
                        return self.process_command(full_cmd)
                elif len(matches) > 1:
                    _cprint(f"{_ACCENT}Ambiguous command: {cmd_lower}{_RST}")
                    _cprint(f"{_DIM}Did you mean: {', '.join(sorted(matches))}?{_RST}")
                else:
                    _cprint(f"\033[1;31mUnknown command: {cmd_lower}{_RST}")
                    _cprint(f"{_DIM}{_ACCENT}Type /help for available commands{_RST}")
        
        return True
    
    def _handle_background_command(self, cmd: str):
        """Handle /background <prompt> — run a prompt in a separate background session.

        Spawns a new AIAgent in a background thread with its own session.
        When it completes, prints the result to the CLI without modifying
        the active session's conversation history.
        """
        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            _cprint("  Uso: /background <prompt>")
            _cprint("  Exemplo: /background Resumir as principais histórias do HN hoje")
            _cprint("  A tarefa roda em outra sessão e o resultado aparece aqui quando terminar.")
            return

        prompt = parts[1].strip()
        self._background_task_counter += 1
        task_num = self._background_task_counter
        task_id = f"bg_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # Make sure we have valid credentials
        if not self._ensure_runtime_credentials():
            _cprint("  (>_<) Não foi possível iniciar tarefa em segundo plano: credenciais inválidas.")
            return

        _cprint(f"  🔄 Background task #{task_num} started: \"{prompt[:60]}{'...' if len(prompt) > 60 else ''}\"")
        _cprint(f"  Task ID: {task_id}")
        _cprint("  Você pode continuar conversando — o resultado aparecerá aqui quando estiver pronto.\n")

        turn_route = self._resolve_turn_agent_config(prompt)

        def run_background():
            set_sudo_password_callback(self._sudo_password_callback)
            set_approval_callback(self._approval_callback)
            try:
                set_secret_capture_callback(self._secret_capture_callback)
            except Exception:
                pass
            try:
                bg_agent = AIAgent(
                    model=turn_route["model"],
                    api_key=turn_route["runtime"].get("api_key"),
                    base_url=turn_route["runtime"].get("base_url"),
                    provider=turn_route["runtime"].get("provider"),
                    api_mode=turn_route["runtime"].get("api_mode"),
                    acp_command=turn_route["runtime"].get("command"),
                    acp_args=turn_route["runtime"].get("args"),
                    max_iterations=self.max_turns,
                    enabled_toolsets=self.enabled_toolsets,
                    quiet_mode=True,
                    verbose_logging=False,
                    session_id=task_id,
                    platform="cli",
                    session_db=self._session_db,
                    reasoning_config=self.reasoning_config,
                    service_tier=self.service_tier,
                    request_overrides=turn_route.get("request_overrides"),
                    providers_allowed=self._providers_only,
                    providers_ignored=self._providers_ignore,
                    providers_order=self._providers_order,
                    provider_sort=self._provider_sort,
                    provider_require_parameters=self._provider_require_params,
                    provider_data_collection=self._provider_data_collection,
                    fallback_model=self._fallback_model,
                )
                # Silence raw spinner; route thinking through TUI widget when no foreground agent is active.
                bg_agent._print_fn = lambda *_a, **_kw: None

                def _bg_thinking(text: str) -> None:
                    # Concurrent bg tasks may race on _spinner_text; acceptable for best-effort UI.
                    if not self._agent_running:
                        self._spinner_text = text
                        if self._app:
                            self._app.invalidate()

                bg_agent.thinking_callback = _bg_thinking

                result = bg_agent.run_conversation(
                    user_message=prompt,
                    task_id=task_id,
                )

                response = result.get("final_response", "") if result else ""
                if not response and result and result.get("error"):
                    response = f"Error: {result['error']}"

                # Display result in the CLI (thread-safe via patch_stdout).
                # Force a TUI refresh first so spinner/status bar don't overlap
                # with the output (fixes #2718).
                if self._app:
                    self._app.invalidate()
                    time.sleep(0.05)  # brief pause for refresh
                print()
                ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
                _cprint(f"  ✔ Background task #{task_num} complete")
                _cprint(f"  Prompt: \"{prompt[:60]}{'...' if len(prompt) > 60 else ''}\"")
                ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
                if response:
                    label = " ECTOR "
                    _resp_color = "#00D1FF"
                    _resp_text = "#E6E6FA"

                    _chat_console = ChatConsole()
                    _chat_console.print(Panel(
                        _render_final_assistant_content(response, mode=self.final_response_markdown),
                        title=f"[{_resp_color} bold]{label} (background #{task_num})[/]",
                        title_align="left",
                        border_style=_resp_color,
                        style=_resp_text,
                        box=rich_box.HORIZONTALS,
                        padding=(1, 4),
                    ))
                else:
                    _cprint("  (Nenhuma resposta gerada)")

                # Play bell if enabled
                if self.bell_on_complete:
                    sys.stdout.write("\a")
                    sys.stdout.flush()

            except Exception as e:
                # Same TUI refresh pattern as success path (#2718)
                if self._app:
                    self._app.invalidate()
                    time.sleep(0.05)
                print()
                _cprint(f"  ✖ Background task #{task_num} failed: {e}")
            finally:
                try:
                    set_sudo_password_callback(None)
                    set_approval_callback(None)
                    set_secret_capture_callback(None)
                except Exception:
                    pass
                self._background_tasks.pop(task_id, None)
                # Clear spinner only if no foreground agent owns it
                if not self._agent_running:
                    self._spinner_text = ""
                if self._app:
                    self._invalidate(min_interval=0)

        thread = threading.Thread(target=run_background, daemon=True, name=f"bg-task-{task_id}")
        self._background_tasks[task_id] = thread
        thread.start()

    @staticmethod
    def _try_launch_chrome_debug(port: int, system: str) -> bool:
        """Try to launch Chrome/Chromium with remote debugging enabled.

        Uses a dedicated user-data-dir so the debug instance doesn't conflict
        with an already-running Chrome using the default profile.

        Returns True if a launch command was executed (doesn't guarantee success).
        """
        import subprocess as _sp

        candidates = _get_chrome_debug_candidates(system)

        if not candidates:
            return False

        # Dedicated profile dir so debug Chrome won't collide with normal Chrome
        data_dir = str(_ector_home / "chrome-debug")
        os.makedirs(data_dir, exist_ok=True)

        chrome = candidates[0]
        try:
            _sp.Popen(
                [
                    chrome,
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={data_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
                start_new_session=True,  # detach from terminal
            )
            return True
        except Exception:
            return False

    def _handle_browser_command(self, cmd: str):
        """Handle /browser connect|disconnect|status — manage live Chrome CDP connection."""
        import platform as _plat

        parts = cmd.strip().split(None, 1)
        sub = parts[1].lower().strip() if len(parts) > 1 else "status"

        _DEFAULT_CDP = "http://127.0.0.1:9222"
        current = os.environ.get("BROWSER_CDP_URL", "").strip()

        if sub.startswith("connect"):
            # Optionally accept a custom CDP URL: /browser connect ws://host:port
            connect_parts = cmd.strip().split(None, 2)  # ["/browser", "connect", "ws://..."]
            cdp_url = connect_parts[2].strip() if len(connect_parts) > 2 else _DEFAULT_CDP

            # Clear any existing browser sessions so the next tool call uses the new backend
            try:
                from tools.browser_tool import cleanup_all_browsers
                cleanup_all_browsers()
            except Exception:
                pass

            print()

            # Extract port for connectivity checks
            _port = 9222
            try:
                _port = int(cdp_url.rsplit(":", 1)[-1].split("/")[0])
            except (ValueError, IndexError):
                pass

            # Check if Chrome is already listening on the debug port
            import socket
            _already_open = False
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(("127.0.0.1", _port))
                s.close()
                _already_open = True
            except (OSError, socket.timeout):
                pass

            if _already_open:
                print(f"   ✔ Chrome is already listening on port {_port}")
            elif cdp_url == _DEFAULT_CDP:
                # Try to auto-launch Chrome with remote debugging
                print("   Chrome isn't running with remote debugging — attempting to launch...")
                _launched = self._try_launch_chrome_debug(_port, _plat.system())
                if _launched:
                    # Wait for the port to come up
                    for _wait in range(10):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(1)
                            s.connect(("127.0.0.1", _port))
                            s.close()
                            _already_open = True
                            break
                        except (OSError, socket.timeout):
                            time.sleep(0.5)
                    if _already_open:
                        print(f"   ✔ Chrome launched and listening on port {_port}")
                    else:
                        print(f"   ▲ Chrome launched but port {_port} isn't responding yet")
                        print("     Try again in a few seconds — the debug instance may still be starting")
                else:
                    print("   ▲ Could not auto-launch Chrome")
                    # Show manual instructions as fallback
                    _data_dir = str(_ector_home / "chrome-debug")
                    sys_name = _plat.system()
                    if sys_name == "Darwin":
                        chrome_cmd = (
                            'open -a "Google Chrome" --args'
                            f" --remote-debugging-port=9222"
                            f' --user-data-dir="{_data_dir}"'
                            " --no-first-run --no-default-browser-check"
                        )
                    elif sys_name == "Windows":
                        chrome_cmd = (
                            f'chrome.exe --remote-debugging-port=9222'
                            f' --user-data-dir="{_data_dir}"'
                            f" --no-first-run --no-default-browser-check"
                        )
                    else:
                        chrome_cmd = (
                            f"google-chrome --remote-debugging-port=9222"
                            f' --user-data-dir="{_data_dir}"'
                            f" --no-first-run --no-default-browser-check"
                        )
                    print(f"     Launch Chrome manually:")
                    print(f"     {chrome_cmd}")
            else:
                print(f"   ▲ Port {_port} is not reachable at {cdp_url}")

            os.environ["BROWSER_CDP_URL"] = cdp_url
            # Eagerly start the CDP supervisor so pending_dialogs + frame_tree
            # show up in the next browser_snapshot.  No-op if already started.
            try:
                from tools.browser_tool import _ensure_cdp_supervisor  # type: ignore[import-not-found]
                _ensure_cdp_supervisor("default")
            except Exception:
                pass
            print()
            print("🌐 Browser connected to live Chrome via CDP")
            print(f"   Endpoint: {cdp_url}")
            print()

            # Inject context message so the model knows
            if hasattr(self, '_pending_input'):
                self._pending_input.put(
                    "[System note: The user has connected your browser tools to their live Chrome browser "
                    "via Chrome DevTools Protocol. Your browser_navigate, browser_snapshot, browser_click, "
                    "and other browser tools now control their real browser — including any pages they have "
                    "open, logged-in sessions, and cookies. They likely opened specific sites or logged into "
                    "services before connecting. Please await their instruction before attempting to operate "
                    "the browser. When you do act, be mindful that your actions affect their real browser — "
                    "don't close tabs or navigate away from pages without asking.]"
                )

        elif sub == "disconnect":
            if current:
                os.environ.pop("BROWSER_CDP_URL", None)
                try:
                    from tools.browser_tool import cleanup_all_browsers, _stop_cdp_supervisor
                    _stop_cdp_supervisor("default")
                    cleanup_all_browsers()
                except Exception:
                    pass
                print()
                print("🌐 Browser disconnected from live Chrome")
                print("   Browser tools reverted to default mode (local headless or cloud provider)")
                print()

                if hasattr(self, '_pending_input'):
                    self._pending_input.put(
                        "[System note: The user has disconnected the browser tools from their live Chrome. "
                        "Browser tools are back to default mode (headless local browser or cloud provider).]"
                    )
            else:
                print()
                print("Browser is not connected to live Chrome (already using default mode)")
                print()

        elif sub == "status":
            print()
            if current:
                print("🌐 Browser: connected to live Chrome via CDP")
                print(f"   Endpoint: {current}")

                _port = 9222
                try:
                    _port = int(current.rsplit(":", 1)[-1].split("/")[0])
                except (ValueError, IndexError):
                    pass
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1)
                    s.connect(("127.0.0.1", _port))
                    s.close()
                    print("   Status: ✔ reachable")
                except (OSError, Exception):
                    print("   Status: ▲ not reachable (Chrome may not be running)")
            else:
                try:
                    from tools.browser_tool import _get_cloud_provider
                    provider = _get_cloud_provider()
                except Exception:
                    provider = None

                if provider is not None:
                    print(f"🌐 Browser: {provider.provider_name()} (cloud)")
                else:
                    print("🌐 Browser: local headless Chromium (agent-browser)")
            print()
            print("   /browser connect      — connect to your live Chrome")
            print("   /browser disconnect   — revert to default")
            print()

        else:
            print()
            print("Uso: /browser connect|disconnect|status")
            print()
            print("   connect      Connect browser tools to your live Chrome session")
            print("   disconnect   Revert to default browser backend")
            print("   status       Show current browser mode")
            print()


    def _toggle_verbose(self):
        """Cycle tool progress mode: off → new → all → verbose → off."""
        cycle = ["off", "new", "all", "verbose"]
        try:
            idx = cycle.index(self.tool_progress_mode)
        except ValueError:
            idx = 2  # default to "all"
        self.tool_progress_mode = cycle[(idx + 1) % len(cycle)]
        self.verbose = self.tool_progress_mode == "verbose"

        if self.agent:
            self.agent.verbose_logging = self.verbose
            self.agent.quiet_mode = not self.verbose
            self.agent.reasoning_callback = self._current_reasoning_callback()

        # Use raw ANSI codes via _cprint so the output is routed through
        # prompt_toolkit's renderer.  self.console.print() with Rich markup
        # writes directly to stdout which patch_stdout's StdoutProxy mangles
        # into garbled sequences like '?[33mTool progress: NEW?[0m' (#2262).
        from ector_cli.colors import Colors as _Colors
        labels = {
            "off": f"{_Colors.DIM}Tool progress: OFF{_Colors.RESET} — silent mode, just the final response.",
            "new": f"{_Colors.YELLOW}Tool progress: NEW{_Colors.RESET} — show each new tool (skip repeats).",
            "all": f"{_Colors.GREEN}Tool progress: ALL{_Colors.RESET} — show every tool call.",
            "verbose": f"{_Colors.BOLD}{_Colors.GREEN}Tool progress: VERBOSE{_Colors.RESET} — full args, results, think blocks, and debug logs.",
        }
        _cprint(labels.get(self.tool_progress_mode, ""))

    def _toggle_yolo(self):
        """Toggle YOLO mode — skip all dangerous command approval prompts."""
        import os
        from ector_cli.colors import Colors as _Colors

        current = bool(os.environ.get("ECTOR_YOLO_MODE"))
        if current:
            os.environ.pop("ECTOR_YOLO_MODE", None)
            _cprint(
                f"  ▲ YOLO mode {_Colors.BOLD}{_Colors.RED}OFF{_Colors.RESET}"
                " — dangerous commands will require approval."
            )
        else:
            os.environ["ECTOR_YOLO_MODE"] = "1"
            _cprint(
                f"  ⚡ YOLO mode {_Colors.BOLD}{_Colors.GREEN}ON{_Colors.RESET}"
                " — all commands auto-approved. Use with caution."
            )

    def _handle_reasoning_command(self, cmd: str):
        """Handle /reasoning — manage effort level and display toggle.

        Usage:
            /reasoning              Show current effort level and display state
            /reasoning <level>      Set reasoning effort (none, minimal, low, medium, high, xhigh)
            /reasoning show|on      Show model thinking/reasoning in output
            /reasoning hide|off     Hide model thinking/reasoning from output
        """
        parts = cmd.strip().split(maxsplit=1)

        if len(parts) < 2:
            # Show current state
            rc = self.reasoning_config
            if rc is None:
                level = "medium (default)"
            elif rc.get("enabled") is False:
                level = "none (disabled)"
            else:
                level = rc.get("effort", "medium")
            display_state = "on ✔" if self.show_reasoning else "off"
            _cprint(f"  {_ACCENT}Reasoning effort:  {level}{_RST}")
            _cprint(f"  {_ACCENT}Reasoning display: {display_state}{_RST}")
            _cprint(f"  {_DIM}Uso: /reasoning <none|minimal|low|medium|high|xhigh|show|hide>{_RST}")
            return

        arg = parts[1].strip().lower()

        # Display toggle
        if arg in ("show", "on"):
            self.show_reasoning = True
            if self.agent:
                self.agent.reasoning_callback = self._current_reasoning_callback()
            save_config_value("display.show_reasoning", True)
            _cprint(f"  {_ACCENT}✔ Reasoning display: ON (saved){_RST}")
            _cprint(f"  {_DIM}  Model thinking will be shown during and after each response.{_RST}")
            return
        if arg in ("hide", "off"):
            self.show_reasoning = False
            if self.agent:
                self.agent.reasoning_callback = self._current_reasoning_callback()
            save_config_value("display.show_reasoning", False)
            _cprint(f"  {_ACCENT}✔ Reasoning display: OFF (saved){_RST}")
            return

        # Effort level change
        parsed = _parse_reasoning_config(arg)
        if parsed is None:
            _cprint(f"  {_DIM}(._.) Unknown argument: {arg}{_RST}")
            _cprint(f"  {_DIM}Valid levels: none, minimal, low, medium, high, xhigh{_RST}")
            _cprint(f"  {_DIM}Display:      show, hide{_RST}")
            return

        self.reasoning_config = parsed
        self.agent = None  # Force agent re-init with new reasoning config

        if save_config_value("agent.reasoning_effort", arg):
            _cprint(f"  {_ACCENT}✔ Reasoning effort set to '{arg}' (saved to config){_RST}")
        else:
            _cprint(f"  {_ACCENT}✔ Reasoning effort set to '{arg}' (session only){_RST}")

    def _handle_busy_command(self, cmd: str):
        """Handle /busy — control what Enter does while ECTOR is working.

        Usage:
            /busy               Show current busy input mode
            /busy status        Show current busy input mode
            /busy queue         Queue input for the next turn instead of interrupting
            /busy steer         Inject Enter mid-run via /steer (after next tool call)
            /busy interrupt     Interrupt the current run on Enter (default)
        """
        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or parts[1].strip().lower() == "status":
            _cprint(f"  {_ACCENT}Busy input mode: {self.busy_input_mode}{_RST}")
            if self.busy_input_mode == "queue":
                _behavior = "queues for next turn"
            elif self.busy_input_mode == "steer":
                _behavior = "steers into current run (after next tool call)"
            else:
                _behavior = "interrupts current run"
            _cprint(f"  {_DIM}Enter while busy: {_behavior}{_RST}")
            _cprint(f"  {_DIM}Uso: /busy [queue|steer|interrupt|status]{_RST}")
            return

        arg = parts[1].strip().lower()
        if arg not in {"queue", "interrupt", "steer"}:
            _cprint(f"  {_DIM}(._.) Unknown argument: {arg}{_RST}")
            _cprint(f"  {_DIM}Uso: /busy [queue|steer|interrupt|status]{_RST}")
            return

        self.busy_input_mode = arg
        if save_config_value("display.busy_input_mode", arg):
            if arg == "queue":
                behavior = "Enter will queue follow-up input while ECTOR is busy."
            elif arg == "steer":
                behavior = "Enter will steer your message into the current run (after the next tool call)."
            else:
                behavior = "Enter will interrupt the current run while ECTOR is busy."
            _cprint(f"  {_ACCENT}✔ Busy input mode set to '{arg}' (saved to config){_RST}")
            _cprint(f"  {_DIM}{behavior}{_RST}")
        else:
            _cprint(f"  {_ACCENT}✔ Busy input mode set to '{arg}' (session only){_RST}")

    def _handle_fast_command(self, cmd: str):
        """Handle /fast — toggle fast mode (OpenAI Priority Processing / Anthropic Fast Mode)."""
        if not self._fast_command_available():
            _cprint("  (._.) /fast só está disponível em modelos com modo rápido (OpenAI Priority Processing ou Anthropic Fast Mode).")
            return

        # Determine the branding for the current model
        try:
            from ector_cli.models import _is_anthropic_fast_model
            agent = getattr(self, "agent", None)
            model = getattr(agent, "model", None) or getattr(self, "model", None)
            feature_name = "Anthropic Fast Mode" if _is_anthropic_fast_model(model) else "Priority Processing"
        except Exception:
            feature_name = "Fast mode"

        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or parts[1].strip().lower() == "status":
            status = "fast" if self.service_tier == "priority" else "normal"
            _cprint(f"  {_ACCENT}{feature_name}: {status}{_RST}")
            _cprint(f"  {_DIM}Uso: /fast [normal|fast|status]{_RST}")
            return

        arg = parts[1].strip().lower()

        if arg in {"fast", "on"}:
            self.service_tier = "priority"
            saved_value = "fast"
            label = "FAST"
        elif arg in {"normal", "off"}:
            self.service_tier = None
            saved_value = "normal"
            label = "NORMAL"
        else:
            _cprint(f"  {_DIM}(._.) Unknown argument: {arg}{_RST}")
            _cprint(f"  {_DIM}Uso: /fast [normal|fast|status]{_RST}")
            return

        self.agent = None  # Force agent re-init with new service-tier config
        if save_config_value("agent.service_tier", saved_value):
            _cprint(f"  {_ACCENT}✔ {feature_name} set to {label} (saved to config){_RST}")
        else:
            _cprint(f"  {_ACCENT}✔ {feature_name} set to {label} (session only){_RST}")

    def _handle_rag_command(self, cmd: str):
        """Handle /rag — toggle and tune session-retrieval RAG."""
        from ector_cli.config import load_config

        def _show_status() -> None:
            cfg = load_config() or {}
            rag = cfg.get("rag", {}) if isinstance(cfg, dict) else {}
            enabled = bool(rag.get("enabled", True))
            max_results = int(rag.get("max_results", 4) or 4)
            max_chars = int(rag.get("max_chars", 2500) or 2500)
            min_query_chars = int(rag.get("min_query_chars", 8) or 8)
            state = "on ✔" if enabled else "off"
            _cprint(f"  {_ACCENT}RAG: {state}{_RST}")
            _cprint(f"  {_DIM}max-results: {max_results} | max-chars: {max_chars} | min-query-chars: {min_query_chars}{_RST}")
            _cprint(f"  {_DIM}Uso: /rag [on|off|status|max-results <n>|max-chars <n>|min-query-chars <n>]{_RST}")

        parts = cmd.strip().split()
        if len(parts) == 1 or (len(parts) >= 2 and parts[1].lower() == "status"):
            _show_status()
            return

        action = parts[1].strip().lower()
        if action in {"on", "off"}:
            enabled = action == "on"
            if save_config_value("rag.enabled", enabled):
                self.agent = None  # Re-init to apply retrieval behavior immediately next turn
                state_label = "ON" if enabled else "OFF"
                _cprint(f"  {_ACCENT}✔ RAG {state_label} (salvo na config){_RST}")
            else:
                _cprint(f"  {_DIM}(._.) Não foi possível salvar rag.enabled no config.yaml{_RST}")
            return

        if action not in {"max-results", "max-chars", "min-query-chars"}:
            _cprint(f"  {_DIM}(._.) Argumento desconhecido: {action}{_RST}")
            _show_status()
            return

        if len(parts) < 3:
            _cprint(f"  {_DIM}(._.) Informe um valor numérico para {action}.{_RST}")
            return

        try:
            raw_value = int(parts[2])
        except ValueError:
            _cprint(f"  {_DIM}(._.) Valor inválido: {parts[2]}{_RST}")
            return

        if action == "max-results":
            value = max(1, min(raw_value, 10))
            key = "rag.max_results"
        elif action == "max-chars":
            value = max(600, min(raw_value, 12000))
            key = "rag.max_chars"
        else:
            value = max(1, min(raw_value, 80))
            key = "rag.min_query_chars"

        if save_config_value(key, value):
            self.agent = None  # Re-init to apply new limits next turn
            _cprint(f"  {_ACCENT}✔ {key} = {value} (salvo na config){_RST}")
        else:
            _cprint(f"  {_DIM}(._.) Não foi possível salvar {key}.{_RST}")

    def _on_reasoning(self, reasoning_text: str):
        """Callback for intermediate reasoning display during tool-call loops."""
        if not reasoning_text:
            return
        self._reasoning_preview_buf = getattr(self, "_reasoning_preview_buf", "") + reasoning_text
        self._flush_reasoning_preview(force=False)

    def _manual_compress(self, cmd_original: str = ""):
        """Manually trigger context compression on the current conversation.

        Accepts an optional focus topic: ``/compress <focus>`` guides the
        summariser to preserve information related to *focus* while being
        more aggressive about discarding everything else.  Inspired by
        Claude Code's ``/compact <focus>`` feature.
        """
        if not self.conversation_history or len(self.conversation_history) < 4:
            print("(._.) Conversa curta demais para comprimir (são necessárias pelo menos 4 mensagens).")
            return

        if not self.agent:
            print("(._.) Nenhum agente ativo — envie uma mensagem primeiro.")
            return

        if not self.agent.compression_enabled:
            print("(._.) A compressão está desativada na configuração.")
            return

        # Extract optional focus topic from the command (e.g. "/compress database schema")
        focus_topic = ""
        if cmd_original:
            parts = cmd_original.strip().split(None, 1)
            if len(parts) > 1:
                focus_topic = parts[1].strip()

        original_count = len(self.conversation_history)
        with self._busy_command("Comprimindo contexto..."):
            try:
                from agent.model_metadata import estimate_messages_tokens_rough
                from agent.manual_compression_feedback import summarize_manual_compression
                original_history = list(self.conversation_history)
                approx_tokens = estimate_messages_tokens_rough(original_history)
                if focus_topic:
                    print(f"🗜️  Comprimindo {original_count} mensagens (~{approx_tokens:,} tokens), "
                          f"foco: \"{focus_topic}\"...")
                else:
                    print(f"🗜️  Comprimindo {original_count} mensagens (~{approx_tokens:,} tokens)...")

                compressed, _ = self.agent._compress_context(
                    original_history,
                    self.agent._cached_system_prompt or "",
                    approx_tokens=approx_tokens,
                    focus_topic=focus_topic or None,
                )
                self.conversation_history = compressed
                # _compress_context ends the old session and creates a new child
                # session on the agent (run_agent.py::_compress_context). Sync the
                # CLI's session_id so /status, /resume, exit summary, and title
                # generation all point at the live continuation session, not the
                # ended parent. Without this, subsequent end_session() calls target
                # the already-closed parent and the child is orphaned.
                if (
                    getattr(self.agent, "session_id", None)
                    and self.agent.session_id != self.session_id
                ):
                    self.session_id = self.agent.session_id
                    self._pending_title = None
                new_tokens = estimate_messages_tokens_rough(self.conversation_history)
                summary = summarize_manual_compression(
                    original_history,
                    self.conversation_history,
                    approx_tokens,
                    new_tokens,
                )
                icon = "🗜️" if summary["noop"] else "✔"
                print(f"  {icon} {summary['headline']}")
                print(f"     {summary['token_line']}")
                if summary["note"]:
                    print(f"     {summary['note']}")

            except Exception as e:
                print(f"  ✖ Falha na compressão: {e}")

    def _handle_debug_command(self):
        """Handle /debug — upload debug report + logs and print paste URLs."""
        from ector_cli.debug import run_debug_share
        from types import SimpleNamespace

        args = SimpleNamespace(lines=200, expire=7, local=False)
        run_debug_share(args)

    def _show_usage(self):
        """Show rate limits (if available) and session token usage."""
        if not self.agent:
            print("(._.) Nenhum agente ativo — envie uma mensagem primeiro.")
            return

        agent = self.agent
        calls = agent.session_api_calls

        if calls == 0:
            print("(._.) Ainda não houve chamadas à API nesta sessão.")
            return

        # ── Rate limits (shown first when available) ────────────────
        rl_state = agent.get_rate_limit_state()
        if rl_state and rl_state.has_data:
            from agent.rate_limit_tracker import format_rate_limit_display
            print()
            print(format_rate_limit_display(rl_state))
            print()

        # ── Session token usage ─────────────────────────────────────
        input_tokens = getattr(agent, "session_input_tokens", 0) or 0
        output_tokens = getattr(agent, "session_output_tokens", 0) or 0
        cache_read_tokens = getattr(agent, "session_cache_read_tokens", 0) or 0
        cache_write_tokens = getattr(agent, "session_cache_write_tokens", 0) or 0
        prompt = agent.session_prompt_tokens
        completion = agent.session_completion_tokens
        total = agent.session_total_tokens

        compressor = agent.context_compressor
        last_prompt = compressor.last_prompt_tokens
        ctx_len = compressor.context_length
        pct = min(100, (last_prompt / ctx_len * 100)) if ctx_len else 0
        compressions = compressor.compression_count

        msg_count = len(self.conversation_history)
        cost_result = estimate_usage_cost(
            agent.model,
            CanonicalUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            ),
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )
        elapsed = format_duration_compact((datetime.now() - self.session_start).total_seconds())

        _custo_status_pt = {
            "actual": "real",
            "estimated": "estimado",
            "included": "incluso",
            "unknown": "desconhecido",
        }
        _custo_fonte_pt = {
            "none": "nenhuma",
            "provider_cost_api": "API de custo",
            "provider_generation_api": "API de geração",
            "provider_models_api": "API de modelos",
            "official_docs_snapshot": "docs oficiais",
            "user_override": "usuário",
            "custom_contract": "contrato",
        }
        st_vis = _custo_status_pt.get(cost_result.status, cost_result.status)
        src_vis = _custo_fonte_pt.get(cost_result.source, cost_result.source)

        lw = 28
        print("  Uso de tokens da sessão")
        print(f"  {'─' * 40}")
        print(f"  {'Modelo:':<{lw}}{agent.model}")
        print(f"  {'Tokens de entrada:':<{lw}}{input_tokens:>10,}")
        print(f"  {'Tokens lidos (cache):':<{lw}}{cache_read_tokens:>10,}")
        print(f"  {'Tokens gravados (cache):':<{lw}}{cache_write_tokens:>10,}")
        print(f"  {'Tokens de saída:':<{lw}}{output_tokens:>10,}")
        print(f"  {'Tokens de prompt (total):':<{lw}}{prompt:>10,}")
        print(f"  {'Tokens de conclusão:':<{lw}}{completion:>10,}")
        print(f"  {'Total de tokens:':<{lw}}{total:>10,}")
        print(f"  {'Chamadas à API:':<{lw}}{calls:>10,}")
        aux_in = getattr(agent, "session_auxiliary_input_tokens", 0) or 0
        aux_out = getattr(agent, "session_auxiliary_output_tokens", 0) or 0
        aux_calls = getattr(agent, "session_auxiliary_api_calls", 0) or 0
        if aux_calls:
            print(f"  {'Auxiliar (compressão):':<{lw}}{aux_in + aux_out:>10,}  ({aux_calls} chamadas)")
        print(f"  {'Duração da sessão:':<{lw}}{elapsed:>10}")
        print(f"  {'Estado do custo:':<{lw}}{st_vis:>10}")
        print(f"  {'Fonte do custo:':<{lw}}{src_vis:>10}")
        actual_cost = getattr(agent, "session_actual_cost_usd", 0) or 0
        if actual_cost > 0:
            print(f"  {'Custo total (USD):':<{lw}}{float(actual_cost):>10.4f}")
        elif cost_result.amount_usd is not None:
            prefix = "~" if cost_result.status == "estimated" else ""
            print(f"  {'Custo total (USD):':<{lw}}{prefix}${float(cost_result.amount_usd):>10.4f}")
        elif cost_result.status == "included":
            print(f"  {'Custo total (USD):':<{lw}}{'incluso':>10}")
        else:
            print(f"  {'Custo total (USD):':<{lw}}{'s/n':>10}")
        print(f"  {'─' * 40}")
        print(f"  Contexto atual:   {last_prompt:,} / {ctx_len:,} ({pct:.0f}%)")
        print(f"  Mensagens:        {msg_count}")
        print(f"  Compressões:      {compressions}")
        if cost_result.status == "unknown":
            print(f"  Observação:      Preço desconhecido para {agent.model}")

        # Account limits -- fetched off-thread with a hard timeout so slow
        # provider APIs don't hang the prompt.
        provider = getattr(agent, "provider", None) or getattr(self, "provider", None)
        base_url = getattr(agent, "base_url", None) or getattr(self, "base_url", None)
        api_key = getattr(agent, "api_key", None) or getattr(self, "api_key", None)
        account_snapshot = None
        if provider:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                try:
                    account_snapshot = _pool.submit(
                        fetch_account_usage, provider,
                        base_url=base_url, api_key=api_key,
                    ).result(timeout=10.0)
                except (concurrent.futures.TimeoutError, Exception):
                    account_snapshot = None
        account_lines = [f"  {line}" for line in render_account_usage_lines(account_snapshot)]
        if account_lines:
            print()
            for line in account_lines:
                print(line)

        if self.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            for noisy in ('openai', 'openai._base_client', 'httpx', 'httpcore', 'asyncio', 'hpack', 'grpc', 'modal'):
                logging.getLogger(noisy).setLevel(logging.WARNING)
        else:
            logging.getLogger().setLevel(logging.INFO)
            for quiet_logger in ('tools', 'run_agent', 'trajectory_compressor', 'cron', 'ector_cli'):
                logging.getLogger(quiet_logger).setLevel(logging.ERROR)

    def _show_stats(self, command: str = "/stats"):
        """Show usage statistics and analytics from session history."""
        # Parse optional --days flag
        parts = command.split()
        days = 30
        source = None
        i = 1
        while i < len(parts):
            if parts[i] == "--days" and i + 1 < len(parts):
                try:
                    days = int(parts[i + 1])
                except ValueError:
                    print(f"  Valor inválido para --days: {parts[i + 1]}")
                    return
                i += 2
            elif parts[i] == "--source" and i + 1 < len(parts):
                source = parts[i + 1]
                i += 2
            else:
                i += 1

        try:
            from ector_state import SessionDB
            from agent.stats import StatsEngine
            from ector_cli.stats_cmd import print_stats_report

            db = SessionDB()
            engine = StatsEngine(db)
            report = engine.generate(days=days, source=source)
            print_stats_report(report)
            db.close()
        except Exception as e:
            print(f"  Erro ao gerar estatísticas: {e}")

    def _check_config_mcp_changes(self) -> None:
        """Detect mcp_servers changes in config.yaml and auto-reload MCP connections.

        Called from process_loop every CONFIG_WATCH_INTERVAL seconds.
        Compares config.yaml mtime + mcp_servers section against the last
        known state.  When a change is detected, triggers _reload_mcp() and
        informs the user so they know the tool list has been refreshed.
        """
        import yaml as _yaml

        CONFIG_WATCH_INTERVAL = 5.0  # seconds between config.yaml stat() calls

        now = time.monotonic()
        if now - self._last_config_check < CONFIG_WATCH_INTERVAL:
            return
        self._last_config_check = now

        from ector_cli.config import get_config_path as _get_config_path
        cfg_path = _get_config_path()
        if not cfg_path.exists():
            return

        try:
            mtime = cfg_path.stat().st_mtime
        except OSError:
            return

        if mtime == self._config_mtime:
            return  # File unchanged — fast path

        # File changed — check whether mcp_servers section changed
        self._config_mtime = mtime
        try:
            with open(cfg_path, encoding="utf-8") as f:
                new_cfg = _yaml.safe_load(f) or {}
        except Exception:
            return

        new_mcp = new_cfg.get("mcp_servers") or {}
        if new_mcp == self._config_mcp_servers:
            return  # mcp_servers unchanged (some other section was edited)

        self._config_mcp_servers = new_mcp
        # Notify user and reload.  Run in a separate thread with a hard
        # timeout so a hung MCP server cannot block the process_loop
        # indefinitely (which would freeze the entire TUI).
        print()
        print("🔄 MCP server config changed — reloading connections...")
        _reload_thread = threading.Thread(
            target=self._reload_mcp, daemon=True
        )
        _reload_thread.start()
        _reload_thread.join(timeout=30)
        if _reload_thread.is_alive():
            print("  ▲  MCP reload timed out (30s). Some servers may not have reconnected.")

    def _reload_mcp(self):
        """Reload MCP servers: disconnect all, re-read config.yaml, reconnect.

        After reconnecting, refreshes the agent's tool list so the model
        sees the updated tools on the next turn.
        """
        try:
            from tools.mcp_tool import shutdown_mcp_servers, discover_mcp_tools, _servers, _lock

            # Capture old server names
            with _lock:
                old_servers = set(_servers.keys())

            if not self._command_running:
                print("🔄 Reloading MCP servers...")

            # Shutdown existing connections
            shutdown_mcp_servers()

            # Reconnect (reads config.yaml fresh)
            new_tools = discover_mcp_tools()

            # Compute what changed
            with _lock:
                connected_servers = set(_servers.keys())

            added = connected_servers - old_servers
            removed = old_servers - connected_servers
            reconnected = connected_servers & old_servers

            if reconnected:
                print(f"  ♻️  Reconnected: {', '.join(sorted(reconnected))}")
            if added:
                print(f"  ➕ Added: {', '.join(sorted(added))}")
            if removed:
                print(f"  ➖ Removed: {', '.join(sorted(removed))}")
            if not connected_servers:
                print("  No MCP servers connected.")
            else:
                print(f"  🔧 {len(new_tools)} tool(s) available from {len(connected_servers)} server(s)")

            # Refresh the agent's tool list so the model can call new tools
            if self.agent is not None:
                self.agent.tools = get_tool_definitions(
                    enabled_toolsets=self.agent.enabled_toolsets
                    if hasattr(self.agent, "enabled_toolsets") else None,
                    quiet_mode=True,
                )
                self.agent.valid_tool_names = {
                    tool["function"]["name"] for tool in self.agent.tools
                } if self.agent.tools else set()

            # Inject a message at the END of conversation history so the
            # model knows tools changed.  Appended after all existing
            # messages to preserve prompt-cache for the prefix.
            change_parts = []
            if added:
                change_parts.append(f"Added servers: {', '.join(sorted(added))}")
            if removed:
                change_parts.append(f"Removed servers: {', '.join(sorted(removed))}")
            if reconnected:
                change_parts.append(f"Reconnected servers: {', '.join(sorted(reconnected))}")
            tool_summary = f"{len(new_tools)} MCP tool(s) now available" if new_tools else "No MCP tools available"
            change_detail = ". ".join(change_parts) + ". " if change_parts else ""
            self.conversation_history.append({
                "role": "user",
                "content": f"[IMPORTANT: MCP servers have been reloaded. {change_detail}{tool_summary}. The tool list for this conversation has been updated accordingly.]",
            })

            # Persist session immediately so the session log reflects the
            # updated tools list (self.agent.tools was refreshed above).
            if self.agent is not None:
                try:
                    self.agent._persist_session(
                        self.conversation_history,
                        self.conversation_history,
                    )
                except Exception:
                    pass  # Best-effort

            print(f"  ✔ Agent updated — {len(self.agent.tools if self.agent else [])} tool(s) available")

        except Exception as e:
            print(f"  ✖ MCP reload failed: {e}")

    # ====================================================================
    # Tool-call generation indicator (shown during streaming)
    # ====================================================================

    def _on_tool_gen_start(self, tool_name: str) -> None:
        """Called when the model begins generating tool-call arguments.

        Closes any open streaming boxes (reasoning / response) exactly once,
        then prints a short status line so the user sees activity instead of
        a frozen screen while a large payload (e.g. 45 KB write_file) streams.
        """
        if getattr(self, "_stream_box_opened", False):
            self._flush_stream()
            self._stream_box_opened = False
        self._close_reasoning_box()

        from agent.tool_name_aliases import canonical_wiser_tool_name

        if canonical_wiser_tool_name(tool_name or "") == "wiser":
            self._invalidate()
            return

        from agent.display import get_tool_emoji
        emoji = get_tool_emoji(tool_name, default="⚡")
        _cprint(f"  ┊ {emoji} preparing {tool_name}…")

    # ====================================================================
    # Tool progress callback (audio cues for voice mode)
    # ====================================================================

    def _on_tool_progress(self, event_type: str, function_name: str = None, preview: str = None, function_args: dict = None, **kwargs):
        """Called on tool lifecycle events (tool.started, tool.completed, reasoning.available, etc.).

        Updates the TUI spinner widget so the user can see what the agent
        is doing during tool execution (fills the gap between thinking
        spinner and next response).  Also plays audio cue in voice mode.

        On tool.started, records a monotonic timestamp so get_spinner_text()
        can show a live elapsed timer (the TUI poll loop already invalidates
        every ~0.15s, so the counter updates automatically).

        When tool_progress_mode is "all" or "new", also prints a persistent
        stacked line to scrollback on tool.completed so users can see the
        full history of tool calls (not just the current one in the spinner).
        """
        from agent.tool_name_aliases import canonical_wiser_tool_name

        _fn = canonical_wiser_tool_name(function_name or "")
        # ``memory`` and ``wiser``: dedicated UI already shows context; skip
        # spinner + scrollback lines that duplicate prompts / questions.
        hidden_tool_progress = {"memory", "wiser"}
        if _fn in hidden_tool_progress:
            if event_type == "tool.completed":
                self._tool_start_time = 0.0
            self._invalidate()
            return

        if event_type == "tool.completed":
            self._tool_start_time = 0.0
            # Print stacked scrollback line for "all" / "new" modes
            if function_name and self.tool_progress_mode in ("all", "new"):
                duration = kwargs.get("duration", 0.0)
                is_error = kwargs.get("is_error", False)
                # Pop stored args from tool.started for this function
                stored = self._pending_tool_info.get(function_name)
                stored_args = stored.pop(0) if stored else {}
                if stored is not None and not stored:
                    del self._pending_tool_info[function_name]
                # "new" mode: skip consecutive repeats of the same tool
                if self.tool_progress_mode == "new" and function_name == self._last_scrollback_tool:
                    self._invalidate()
                    return
                self._last_scrollback_tool = function_name
                try:
                    from agent.display import get_cute_tool_message
                    tool_result = kwargs.get("result")
                    line = get_cute_tool_message(
                        function_name, stored_args, duration, result=tool_result
                    )
                    # When the tool result is passed in, get_cute_tool_message already
                    # appends a failure suffix (e.g. send_message API error text).
                    if is_error and tool_result is None:
                        line = f"{line} [error]"
                    _cprint(f"  {line}")
                    _cprint("")
                except Exception:
                    pass
                # First-touch onboarding: on the first tool in this process
                # that takes longer than the threshold while we're in the
                # noisiest progress mode, print a one-time hint about
                # /verbose.  Latched on self so it fires at most once per
                # process; persisted to config.yaml so it never fires again
                # across processes either.
                try:
                    if (
                        not getattr(self, "_long_tool_hint_fired", False)
                        and self.tool_progress_mode == "all"
                        and duration >= 30.0
                    ):
                        from agent.onboarding import (
                            TOOL_PROGRESS_FLAG,
                            is_seen,
                            mark_seen,
                            tool_progress_hint_cli,
                        )
                        if not is_seen(CLI_CONFIG, TOOL_PROGRESS_FLAG):
                            self._long_tool_hint_fired = True
                            _cprint(f"  {_DIM}{tool_progress_hint_cli()}{_RST}")
                            mark_seen(_ector_home / "config.yaml", TOOL_PROGRESS_FLAG)
                            CLI_CONFIG.setdefault("onboarding", {}).setdefault("seen", {})[TOOL_PROGRESS_FLAG] = True
                except Exception:
                    pass
            self._invalidate()
            return
        if event_type != "tool.started":
            return
        if function_name and not function_name.startswith("_"):
            from agent.display import get_tool_emoji
            emoji = get_tool_emoji(function_name)
            label = preview or function_name
            from agent.display import get_tool_preview_max_len
            _pl = get_tool_preview_max_len()
            if _pl > 0 and len(label) > _pl:
                label = label[:_pl - 3] + "..."
            self._spinner_text = f"{emoji} {label}"
            self._tool_start_time = time.monotonic()
            # Store args for stacked scrollback line on completion
            self._pending_tool_info.setdefault(function_name, []).append(
                function_args if function_args is not None else {}
            )
            self._invalidate()

        if not self._voice_mode:
            return
        if not function_name or function_name.startswith("_"):
            return
        try:
            from tools.voice_mode import play_beep
            threading.Thread(
                target=play_beep,
                kwargs={"frequency": 1200, "duration": 0.06, "count": 1},
                daemon=True,
            ).start()
        except Exception:
            pass

    def _on_tool_start(self, tool_call_id: str, function_name: str, function_args: dict):
        """Capture local before-state for write-capable tools."""
        try:
            from agent.display import capture_local_edit_snapshot

            snapshot = capture_local_edit_snapshot(function_name, function_args)
            if snapshot is not None:
                self._pending_edit_snapshots[tool_call_id] = snapshot
        except Exception:
            logger.debug("Edit snapshot capture failed for %s", function_name, exc_info=True)

    def _on_tool_complete(self, tool_call_id: str, function_name: str, function_args: dict, function_result: str):
        """Render file edits with inline diff after write-capable tools complete."""
        snapshot = self._pending_edit_snapshots.pop(tool_call_id, None)
        try:
            from agent.display import render_edit_diff_with_delta

            render_edit_diff_with_delta(
                function_name,
                function_result,
                function_args=function_args,
                snapshot=snapshot,
                print_fn=_cprint,
            )
        except Exception:
            logger.debug("Edit diff preview failed for %s", function_name, exc_info=True)

    # ====================================================================
    # Voice mode methods
    # ====================================================================

    def _voice_start_recording(self):
        """Start capturing audio from the microphone."""
        if getattr(self, '_should_exit', False):
            return
        from tools.voice_mode import create_audio_recorder, check_voice_requirements

        reqs = check_voice_requirements()
        if not reqs["audio_available"]:
            if _is_termux_environment():
                details = reqs.get("details", "")
                if "Termux:API Android app is not installed" in details:
                    raise RuntimeError(
                        "Termux:API command package detected, but the Android app is missing.\n"
                        "Install/update the Termux:API Android app, then retry /voice on.\n"
                        "Fallback: pkg install python-numpy portaudio && python -m pip install sounddevice"
                    )
                raise RuntimeError(
                    "Voice mode requires either Termux:API microphone access or Python audio libraries.\n"
                    "Option 1: pkg install termux-api and install the Termux:API Android app\n"
                    "Option 2: pkg install python-numpy portaudio && python -m pip install sounddevice"
                )
            raise RuntimeError(
                "Voice mode requires sounddevice and numpy.\n"
                f"Install with: {sys.executable} -m pip install sounddevice numpy"
            )
        if not reqs.get("stt_available", reqs.get("stt_key_set")):
            raise RuntimeError(
                "Voice mode requires an STT provider for transcription.\n"
                "Option 1: pip install faster-whisper  (free, local)\n"
                "Option 2: Set GROQ_API_KEY (free tier)\n"
                "Option 3: Set VOICE_TOOLS_OPENAI_KEY (paid)"
            )

        # Prevent double-start from concurrent threads (atomic check-and-set)
        with self._voice_lock:
            if self._voice_recording:
                return
            self._voice_recording = True

        # Load silence detection params from config
        voice_cfg = {}
        try:
            from ector_cli.config import load_config
            voice_cfg = load_config().get("voice", {})
        except Exception:
            pass

        if self._voice_recorder is None:
            self._voice_recorder = create_audio_recorder()

        # Apply config-driven silence params
        self._voice_recorder._silence_threshold = voice_cfg.get("silence_threshold", 200)
        self._voice_recorder._silence_duration = voice_cfg.get("silence_duration", 3.0)

        def _on_silence():
            """Called by AudioRecorder when silence is detected after speech."""
            with self._voice_lock:
                if not self._voice_recording:
                    return
            _cprint(f"\n{_DIM}Silence detected, auto-stopping...{_RST}")
            if hasattr(self, '_app') and self._app:
                self._app.invalidate()
            self._voice_stop_and_transcribe()

        # Audio cue: single beep BEFORE starting stream (avoid CoreAudio conflict)
        if self._voice_beeps_enabled():
            try:
                from tools.voice_mode import play_beep
                play_beep(frequency=880, count=1)
            except Exception:
                pass

        try:
            self._voice_recorder.start(on_silence_stop=_on_silence)
        except Exception:
            with self._voice_lock:
                self._voice_recording = False
            raise
        if getattr(self._voice_recorder, "supports_silence_autostop", True):
            _recording_hint = "auto-stops on silence | Ctrl+B to stop & exit continuous"
        elif _is_termux_environment():
            _recording_hint = "Termux:API capture | Ctrl+B to stop"
        else:
            _recording_hint = "Ctrl+B to stop"
        _cprint(f"\n{_ACCENT}● Recording...{_RST} {_DIM}({_recording_hint}){_RST}")

        # Periodically refresh prompt to update audio level indicator
        def _refresh_level():
            while True:
                with self._voice_lock:
                    still_recording = self._voice_recording
                if not still_recording:
                    break
                if hasattr(self, '_app') and self._app:
                    self._app.invalidate()
                time.sleep(0.15)
        threading.Thread(target=_refresh_level, daemon=True).start()

    def _voice_stop_and_transcribe(self):
        """Stop recording, transcribe via STT, and queue the transcript as input."""
        # Atomic guard: only one thread can enter stop-and-transcribe.
        # Set _voice_processing immediately so concurrent Ctrl+B presses
        # don't race into the START path while recorder.stop() holds its lock.
        with self._voice_lock:
            if not self._voice_recording:
                return
            self._voice_recording = False
            self._voice_processing = True

        submitted = False
        wav_path = None
        try:
            if self._voice_recorder is None:
                return

            wav_path = self._voice_recorder.stop()

            # Audio cue: double beep after stream stopped (no CoreAudio conflict)
            if self._voice_beeps_enabled():
                try:
                    from tools.voice_mode import play_beep
                    play_beep(frequency=660, count=2)
                except Exception:
                    pass

            if wav_path is None:
                _cprint(f"{_DIM}No speech detected.{_RST}")
                return

            # _voice_processing is already True (set atomically above)
            if hasattr(self, '_app') and self._app:
                self._app.invalidate()
            _cprint(f"{_DIM}Transcribing...{_RST}")

            # Get STT model from config
            stt_model = None
            try:
                from ector_cli.config import load_config
                stt_config = load_config().get("stt", {})
                stt_model = stt_config.get("model")
            except Exception:
                pass

            from tools.voice_mode import transcribe_recording
            result = transcribe_recording(wav_path, model=stt_model)

            if result.get("success") and result.get("transcript", "").strip():
                transcript = result["transcript"].strip()
                self._attached_images.clear()
                if hasattr(self, '_app') and self._app:
                    self._app.invalidate()
                self._pending_input.put(transcript)
                submitted = True
            elif result.get("success"):
                _cprint(f"{_DIM}No speech detected.{_RST}")
            else:
                error = result.get("error", "Unknown error")
                _cprint(f"\n{_DIM}Transcription failed: {error}{_RST}")

        except Exception as e:
            _cprint(f"\n{_DIM}Voice processing error: {e}{_RST}")
        finally:
            with self._voice_lock:
                self._voice_processing = False
            if hasattr(self, '_app') and self._app:
                self._app.invalidate()
            # Clean up temp file
            try:
                if wav_path and os.path.isfile(wav_path):
                    os.unlink(wav_path)
            except Exception:
                pass

            # Track consecutive no-speech cycles to avoid infinite restart loops.
            if not submitted:
                self._no_speech_count = getattr(self, '_no_speech_count', 0) + 1
                if self._no_speech_count >= 3:
                    self._voice_continuous = False
                    self._no_speech_count = 0
                    _cprint(f"{_DIM}No speech detected 3 times, continuous mode stopped.{_RST}")
                    return
            else:
                self._no_speech_count = 0

            # If no transcript was submitted but continuous mode is active,
            # restart recording so the user can keep talking.
            # (When transcript IS submitted, process_loop handles restart
            # after chat() completes.)
            if self._voice_continuous and not submitted and not self._voice_recording:
                def _restart_recording():
                    try:
                        self._voice_start_recording()
                        if hasattr(self, '_app') and self._app:
                            self._app.invalidate()
                    except Exception as e:
                        _cprint(f"{_DIM}Voice auto-restart failed: {e}{_RST}")
                threading.Thread(target=_restart_recording, daemon=True).start()

    def _voice_speak_response(self, text: str):
        """Speak the agent's response aloud using TTS (runs in background thread)."""
        if not self._voice_tts:
            return
        self._voice_tts_done.clear()
        try:
            from tools.tts_tool import text_to_speech_tool
            from tools.voice_mode import play_audio_file

            # Strip markdown and non-speech content for cleaner TTS
            tts_text = text[:4000] if len(text) > 4000 else text
            tts_text = re.sub(r'```[\s\S]*?```', ' ', tts_text)   # fenced code blocks
            tts_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', tts_text)  # [text](url) -> text
            tts_text = re.sub(r'https?://\S+', '', tts_text)      # URLs
            tts_text = re.sub(r'\*\*(.+?)\*\*', r'\1', tts_text)  # bold
            tts_text = re.sub(r'\*(.+?)\*', r'\1', tts_text)      # italic
            tts_text = re.sub(r'`(.+?)`', r'\1', tts_text)        # inline code
            tts_text = re.sub(r'^#+\s*', '', tts_text, flags=re.MULTILINE)  # headers
            tts_text = re.sub(r'^\s*[-*]\s+', '', tts_text, flags=re.MULTILINE)  # list items
            tts_text = re.sub(r'---+', '', tts_text)              # horizontal rules
            tts_text = re.sub(r'\n{3,}', '\n\n', tts_text)        # excessive newlines
            tts_text = tts_text.strip()
            if not tts_text:
                return

            # Use MP3 output for CLI playback (afplay doesn't handle OGG well).
            # The TTS tool may auto-convert MP3->OGG, but the original MP3 remains.
            os.makedirs(os.path.join(tempfile.gettempdir(), "ector_voice"), exist_ok=True)
            mp3_path = os.path.join(
                tempfile.gettempdir(), "ector_voice",
                f"tts_{time.strftime('%Y%m%d_%H%M%S')}.mp3",
            )

            text_to_speech_tool(text=tts_text, output_path=mp3_path)

            # Play the MP3 directly (the TTS tool returns OGG path but MP3 still exists)
            if os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
                play_audio_file(mp3_path)
                # Clean up
                try:
                    os.unlink(mp3_path)
                    ogg_path = mp3_path.rsplit(".", 1)[0] + ".ogg"
                    if os.path.isfile(ogg_path):
                        os.unlink(ogg_path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning("Voice TTS playback failed: %s", e)
            _cprint(f"{_DIM}TTS playback failed: {e}{_RST}")
        finally:
            self._voice_tts_done.set()

    def _handle_voice_command(self, command: str):
        """Handle /voice [on|off|tts|status] command."""
        parts = command.strip().split(maxsplit=1)
        subcommand = parts[1].lower().strip() if len(parts) > 1 else ""

        if subcommand == "on":
            self._enable_voice_mode()
        elif subcommand == "off":
            self._disable_voice_mode()
        elif subcommand == "tts":
            self._toggle_voice_tts()
        elif subcommand == "status":
            self._show_voice_status()
        elif subcommand == "":
            # Toggle
            if self._voice_mode:
                self._disable_voice_mode()
            else:
                self._enable_voice_mode()
        else:
            _cprint(f"Unknown voice subcommand: {subcommand}")
            _cprint("Uso: /voice [on|off|tts|status]")

    def _voice_beeps_enabled(self) -> bool:
        """Return whether CLI voice mode should play record start/stop beeps."""
        try:
            from ector_cli.config import load_config
            voice_cfg = load_config().get("voice", {})
            if isinstance(voice_cfg, dict):
                return bool(voice_cfg.get("beep_enabled", True))
        except Exception:
            pass
        return True

    def _enable_voice_mode(self):
        """Enable voice mode after checking requirements."""
        if self._voice_mode:
            _cprint(f"{_DIM}Voice mode is already enabled.{_RST}")
            return

        from tools.voice_mode import check_voice_requirements, detect_audio_environment

        # Environment detection -- warn and block in incompatible environments
        env_check = detect_audio_environment()
        if not env_check["available"]:
            _cprint(f"\n{_ACCENT}Voice mode unavailable in this environment:{_RST}")
            for warning in env_check["warnings"]:
                _cprint(f"  {_DIM}{warning}{_RST}")
            return

        reqs = check_voice_requirements()
        if not reqs["available"]:
            _cprint(f"\n{_ACCENT}Voice mode requirements not met:{_RST}")
            for line in reqs["details"].split("\n"):
                _cprint(f"  {_DIM}{line}{_RST}")
            if reqs["missing_packages"]:
                if _is_termux_environment():
                    _cprint(f"\n  {_BOLD}Option 1: pkg install termux-api{_RST}")
                    _cprint(f"  {_DIM}Then install/update the Termux:API Android app for microphone capture{_RST}")
                    _cprint(f"  {_BOLD}Option 2: pkg install python-numpy portaudio && python -m pip install sounddevice{_RST}")
                else:
                    _cprint(f"\n  {_BOLD}Install: {sys.executable} -m pip install {' '.join(reqs['missing_packages'])}{_RST}")
            return

        with self._voice_lock:
            self._voice_mode = True

        # Check config for auto_tts
        try:
            from ector_cli.config import load_config
            voice_config = load_config().get("voice", {})
            if voice_config.get("auto_tts", False):
                with self._voice_lock:
                    self._voice_tts = True
        except Exception:
            pass

        # Voice mode instruction is injected as a user message prefix (not a
        # system prompt change) to avoid invalidating the prompt cache.  See
        # _voice_message_prefix property and its usage in _process_message().

        tts_status = " (TTS enabled)" if self._voice_tts else ""
        try:
            from ector_cli.config import load_config
            _raw_ptt = load_config().get("voice", {}).get("record_key", "ctrl+b")
            _ptt_key = _raw_ptt.lower().replace("ctrl+", "c-").replace("alt+", "a-")
        except Exception:
            _ptt_key = "c-b"
        _ptt_display = _ptt_key.replace("c-", "Ctrl+").upper()
        _cprint(f"\n{_ACCENT}Voice mode enabled{tts_status}{_RST}")
        _cprint(f"  {_DIM}{_ptt_display} to start/stop recording{_RST}")
        _cprint(f"  {_DIM}/voice tts  to toggle speech output{_RST}")
        _cprint(f"  {_DIM}/voice off  to disable voice mode{_RST}")

    def _disable_voice_mode(self):
        """Disable voice mode, cancel any active recording, and stop TTS."""
        recorder = None
        with self._voice_lock:
            if self._voice_recording and self._voice_recorder:
                self._voice_recorder.cancel()
                self._voice_recording = False
            recorder = self._voice_recorder
            self._voice_mode = False
            self._voice_tts = False
            self._voice_continuous = False

        # Shut down the persistent audio stream in background
        if recorder is not None:
            def _bg_shutdown(rec=recorder):
                try:
                    rec.shutdown()
                except Exception:
                    pass
            threading.Thread(target=_bg_shutdown, daemon=True).start()
            self._voice_recorder = None

        # Stop any active TTS playback
        try:
            from tools.voice_mode import stop_playback
            stop_playback()
        except Exception:
            pass
        self._voice_tts_done.set()

        _cprint(f"\n{_DIM}Voice mode disabled.{_RST}")

    def _toggle_voice_tts(self):
        """Toggle TTS output for voice mode."""
        if not self._voice_mode:
            _cprint(f"{_DIM}Enable voice mode first: /voice on{_RST}")
            return

        with self._voice_lock:
            self._voice_tts = not self._voice_tts
        status = "enabled" if self._voice_tts else "disabled"

        if self._voice_tts:
            from tools.tts_tool import check_tts_requirements
            if not check_tts_requirements():
                _cprint(f"{_DIM}Aviso: nenhum provedor de TTS disponível. Instale edge-tts ou configure chaves de API.{_RST}")

        _cprint(f"{_ACCENT}Voice TTS {status}.{_RST}")

    def _show_voice_status(self):
        """Show current voice mode status."""
        from ector_cli.config import load_config
        from tools.voice_mode import check_voice_requirements

        reqs = check_voice_requirements()

        _cprint(f"\n{_BOLD}Voice Mode Status{_RST}")
        _cprint(f"  Mode:      {'ON' if self._voice_mode else 'OFF'}")
        _cprint(f"  TTS:       {'ON' if self._voice_tts else 'OFF'}")
        _cprint(f"  Recording: {'YES' if self._voice_recording else 'no'}")
        _raw_key = load_config().get("voice", {}).get("record_key", "ctrl+b")
        _display_key = _raw_key.replace("ctrl+", "Ctrl+").upper() if "ctrl+" in _raw_key.lower() else _raw_key
        _cprint(f"  Record key: {_display_key}")
        _cprint(f"\n  {_BOLD}Requirements:{_RST}")
        for line in reqs["details"].split("\n"):
            _cprint(f"    {line}")

    def _wiser_callback(self, question, choices):
        """
        Platform callback for the Wiser (``wiser``) tool. Called from the agent thread.

        Always shows numbered choices plus free-text (“Outro”), then blocks until
        the user responds via prompt_toolkit key bindings. If no response arrives
        within the configured timeout the question is dismissed and the agent is
        told to decide on its own.
        """
        import time as _time

        from tools.wiser_tool import (
            WISER_USER_CANCELLED,
            WISER_USER_TIMEOUT,
            get_wiser_timeout_seconds,
        )

        timeout = get_wiser_timeout_seconds(CLI_CONFIG)
        response_queue = queue.Queue()
        opts = [str(c).strip() for c in (choices or []) if str(c).strip()]
        if len(opts) < 2:
            opts = ["Continuar com a melhor opção", "Parar por agora"]
        else:
            opts = opts[:4]

        self._wiser_state = {
            "question": question,
            "choices": opts,
            "selected": 0,
            "response_queue": response_queue,
        }
        self._wiser_deadline = _time.monotonic() + timeout
        # Always start on choice list; free-text is the “Outro” path.
        self._wiser_freetext = False

        # Trigger prompt_toolkit repaint from this (non-main) thread
        self._invalidate()

        # Poll for the user's response.  Refresh countdown every 5s to avoid flicker.
        _last_countdown_refresh = _time.monotonic()
        while True:
            try:
                result = response_queue.get(timeout=1)
                self._wiser_deadline = 0
                return result
            except queue.Empty:
                remaining = self._wiser_deadline - _time.monotonic()
                if remaining <= 0:
                    break
                now = _time.monotonic()
                if now - _last_countdown_refresh >= 5.0:
                    _last_countdown_refresh = now
                    self._invalidate()

        self._wiser_state = None
        self._wiser_freetext = False
        self._wiser_deadline = 0
        self._invalidate()
        _cprint(f"\n{_DIM}(Wiser timed out after {timeout}s — agent will decide){_RST}")
        return WISER_USER_TIMEOUT

    def _sudo_password_callback(self) -> str:
        """
        Prompt for sudo password through the prompt_toolkit UI.
        
        Called from the agent thread when a sudo command is encountered.
        Uses the same Wiser-style mechanism: sets UI state, waits on a
        queue for the user's response via the Enter key binding.
        """
        import time as _time

        timeout = 45
        response_queue = queue.Queue()

        self._capture_modal_input_snapshot()
        self._sudo_state = {
            "response_queue": response_queue,
        }
        self._sudo_deadline = _time.monotonic() + timeout

        self._invalidate()

        while True:
            try:
                result = response_queue.get(timeout=1)
                self._sudo_state = None
                self._sudo_deadline = 0
                self._restore_modal_input_snapshot()
                self._invalidate()
                if result:
                    _cprint(f"\n{_DIM}  ✔ Senha recebida (armazenada para a sessão){_RST}")
                else:
                    _cprint(f"\n{_DIM}  ⏭ Pulado{_RST}")
                return result
            except queue.Empty:
                remaining = self._sudo_deadline - _time.monotonic()
                if remaining <= 0:
                    break
                self._invalidate()

        self._sudo_state = None
        self._sudo_deadline = 0
        self._restore_modal_input_snapshot()
        self._invalidate()
        _cprint(f"\n{_DIM}  ⏱ Tempo esgotado — continuando sem sudo{_RST}")
        return ""

    def _approval_callback(self, command: str, description: str,
                           *, allow_permanent: bool = True) -> str:
        """
        Prompt for dangerous command approval through the prompt_toolkit UI.

        Called from the agent thread. Shows a selection UI similar to Wiser (multi-choice)
        with choices: once / session / always / deny. When allow_permanent
        is False (tirith warnings present), the 'always' option is hidden.
        Long commands also get a 'view' option so the full command can be
        expanded before deciding.

        Uses _approval_lock to serialize concurrent requests (e.g. from
        parallel delegation subtasks) so each prompt gets its own turn
        and the shared _approval_state / _approval_deadline aren't clobbered.
        """
        import time as _time

        with self._approval_lock:
            timeout = 60
            response_queue = queue.Queue()

            self._approval_state = {
                "command": command,
                "description": description,
                "choices": self._approval_choices(command, allow_permanent=allow_permanent),
                "selected": 0,
                "response_queue": response_queue,
            }
            self._approval_deadline = _time.monotonic() + timeout

            self._invalidate()

            _last_countdown_refresh = _time.monotonic()
            while True:
                try:
                    result = response_queue.get(timeout=1)
                    self._approval_state = None
                    self._approval_deadline = 0
                    self._invalidate()
                    return result
                except queue.Empty:
                    remaining = self._approval_deadline - _time.monotonic()
                    if remaining <= 0:
                        break
                    now = _time.monotonic()
                    if now - _last_countdown_refresh >= 5.0:
                        _last_countdown_refresh = now
                        self._invalidate()

            self._approval_state = None
            self._approval_deadline = 0
            self._invalidate()
            _cprint(f"\n{_DIM}  ⏱ Tempo esgotado — negando comando{_RST}")
            return "deny"

    def _approval_choices(self, command: str, *, allow_permanent: bool = True) -> list[str]:
        """Return approval choices for a dangerous command prompt."""
        choices = ["uma vez", "sessão", "sempre", "negar"] if allow_permanent else ["uma vez", "sessão", "negar"]
        if len(command) > 70:
            choices.append("view")
        return choices

    def _handle_approval_selection(self) -> None:
        """Process the currently selected dangerous-command approval choice."""
        state = self._approval_state
        if not state:
            return

        selected = state.get("selected", 0)
        choices = state.get("choices")
        if not isinstance(choices, list):
            choices = []
        if not (0 <= selected < len(choices)):
            return

        chosen = choices[selected]
        if chosen == "view":
            state["show_full"] = True
            state["choices"] = [choice for choice in choices if choice != "view"]
            if state["selected"] >= len(state["choices"]):
                state["selected"] = max(0, len(state["choices"]) - 1)
            self._invalidate()
            return

        state["response_queue"].put(chosen)
        self._approval_state = None
        self._invalidate()

    def _get_approval_display_fragments(self):
        """Render the dangerous-command approval panel for the prompt_toolkit UI.

        Layout priority: title + command + choices must always render, even if
        the terminal is short or the description is long. Description is placed
        at the bottom of the panel and gets truncated to fit the remaining row
        budget. This prevents HSplit from clipping approve/deny off-screen when
        tirith findings produce multi-paragraph descriptions or when the user
        runs in a compact terminal pane.
        """
        state = self._approval_state
        if not state:
            return []

        def _panel_box_width(title_text: str, content_lines: list[str], min_width: int = 46, max_width: int = 76) -> int:
            term_cols = shutil.get_terminal_size((100, 20)).columns
            longest = max([len(title_text)] + [len(line) for line in content_lines] + [min_width - 4])
            inner = min(max(longest + 4, min_width - 2), max_width - 2, max(24, term_cols - 6))
            return inner + 2

        def _wrap_panel_text(text: str, width: int, subsequent_indent: str = "") -> list[str]:
            wrapped = textwrap.wrap(
                text,
                width=max(8, width),
                replace_whitespace=False,
                drop_whitespace=False,
                subsequent_indent=subsequent_indent,
            )
            return wrapped or [""]

        def _append_panel_line(lines, border_style: str, content_style: str, text: str, box_width: int) -> None:
            inner_width = max(0, box_width - 2)
            lines.append((border_style, "│ "))
            lines.append((content_style, text.ljust(inner_width)))
            lines.append((border_style, " │\n"))

        def _append_blank_panel_line(lines, border_style: str, box_width: int) -> None:
            lines.append((border_style, "│" + (" " * box_width) + "│\n"))

        command = state["command"]
        description = state["description"]
        choices = state["choices"]
        selected = state.get("selected", 0)
        show_full = state.get("show_full", False)

        title = "Comando prestes a ser executado"
        cmd_display = command if show_full or len(command) <= 70 else command[:70] + '...'
        choice_labels = {
            "uma vez": "Permitir uma vez",
            "sessão": "Permitir nesta sessão",
            "sempre": "Adicionar à lista permanente",
            "negar": "Negar",
            "view": "Mostrar comando completo",
        }

        preview_lines = _wrap_panel_text(description, 60)
        preview_lines.extend(_wrap_panel_text(cmd_display, 60))
        for i, choice in enumerate(choices):
            prefix = '❯ ' if i == selected else '  '
            preview_lines.extend(_wrap_panel_text(
                f"{prefix}{choice_labels.get(choice, choice)}",
                60,
                subsequent_indent="  ",
            ))

        box_width = _panel_box_width(title, preview_lines)
        inner_text_width = max(8, box_width - 2)

        # Pre-wrap the mandatory content — command + choices must always render.
        cmd_wrapped = _wrap_panel_text(cmd_display, inner_text_width)

        # (choice_index, wrapped_line) so we can re-apply selected styling below
        choice_wrapped: list[tuple[int, str]] = []
        for i, choice in enumerate(choices):
            label = choice_labels.get(choice, choice)
            # Show number prefix for quick selection (1-9 for items 1-9, 0 for 10th item)
            if i < 9:
                num_prefix = str(i + 1)
            elif i == 9:
                num_prefix = '0'
            else:
                num_prefix = ' '  # No number for items beyond 10th
            if i == selected:
                prefix = f'❯ {num_prefix}. '
            else:
                prefix = f'  {num_prefix}. '
            for wrapped in _wrap_panel_text(f"{prefix}{label}", inner_text_width, subsequent_indent="    "):
                choice_wrapped.append((i, wrapped))

        # Budget vertical space so HSplit never clips the command or choices.
        # Panel chrome (full layout with separators):
        #   top border + title + blank_after_title
        #   + blank_between_cmd_choices + bottom border = 5 rows.
        # In tight terminals we collapse to:
        #   top border + title + bottom border = 3 rows (no blanks).
        #
        # reserved_below: rows consumed below the approval panel by the
        # spinner/tool-progress line, status bar, input area, separators, and
        # prompt symbol. Measured at ~6 rows during live PTY approval prompts;
        # budget 6 so we don't overestimate the panel's room.
        term_rows = shutil.get_terminal_size((100, 24)).lines
        chrome_full = 5
        chrome_tight = 3
        reserved_below = 6

        available = max(0, term_rows - reserved_below)
        mandatory_full = chrome_full + len(cmd_wrapped) + len(choice_wrapped)

        # If the full-chrome panel doesn't fit, drop the separator blanks.
        # This keeps the command and every choice on-screen in compact terminals.
        use_compact_chrome = mandatory_full > available
        chrome_rows = chrome_tight if use_compact_chrome else chrome_full

        # If the command itself is too long to leave room for choices (e.g. user
        # hit "view" on a multi-hundred-character command), truncate it so the
        # approve/deny buttons still render. Keep at least 1 row of command.
        max_cmd_rows = max(1, available - chrome_rows - len(choice_wrapped))
        if len(cmd_wrapped) > max_cmd_rows:
            keep = max(1, max_cmd_rows - 1) if max_cmd_rows > 1 else 1
            cmd_wrapped = cmd_wrapped[:keep] + ["… (comando truncado — use /logs ou /debug para o texto completo)"]

        # Allocate any remaining rows to description. The extra -1 in full mode
        # accounts for the blank separator between choices and description.
        mandatory_no_desc = chrome_rows + len(cmd_wrapped) + len(choice_wrapped)
        desc_sep_cost = 0 if use_compact_chrome else 1
        available_for_desc = available - mandatory_no_desc - desc_sep_cost
        # Even on huge terminals, cap description height so the panel stays compact.
        available_for_desc = max(0, min(available_for_desc, 10))

        desc_wrapped = _wrap_panel_text(description, inner_text_width) if description else []
        if available_for_desc < 1 or not desc_wrapped:
            desc_wrapped = []
        elif len(desc_wrapped) > available_for_desc:
            keep = max(1, available_for_desc - 1)
            desc_wrapped = desc_wrapped[:keep] + ["… (descrição truncada)"]

        # Render: title → command → choices → description (description last so
        # any remaining overflow clips from the bottom of the least-critical
        # content, never from the command or choices). Use compact chrome (no
        # blank separators) when the terminal is tight.
        lines = []
        lines.append(('class:approval-border', '╭' + ('─' * box_width) + '╮\n'))
        _append_panel_line(lines, 'class:approval-border', 'class:approval-title', title, box_width)
        if not use_compact_chrome:
            _append_blank_panel_line(lines, 'class:approval-border', box_width)

        for wrapped in cmd_wrapped:
            _append_panel_line(lines, 'class:approval-border', 'class:approval-cmd', wrapped, box_width)
        if not use_compact_chrome:
            _append_blank_panel_line(lines, 'class:approval-border', box_width)

        for i, wrapped in choice_wrapped:
            style = 'class:approval-selected' if i == selected else 'class:approval-choice'
            _append_panel_line(lines, 'class:approval-border', style, wrapped, box_width)

        if desc_wrapped:
            if not use_compact_chrome:
                _append_blank_panel_line(lines, 'class:approval-border', box_width)
            for wrapped in desc_wrapped:
                _append_panel_line(lines, 'class:approval-border', 'class:approval-desc', wrapped, box_width)

        lines.append(('class:approval-border', '╰' + ('─' * box_width) + '╯\n'))
        return lines

    def _secret_capture_callback(self, var_name: str, prompt: str, metadata=None) -> dict:
        return prompt_for_secret(self, var_name, prompt, metadata)

    def _capture_modal_input_snapshot(self) -> None:
        """Temporarily clear the input buffer and save the user's in-progress draft."""
        if self._modal_input_snapshot is not None or not getattr(self, "_app", None):
            return
        try:
            buf = self._app.current_buffer
            self._modal_input_snapshot = {
                "text": buf.text,
                "cursor_position": buf.cursor_position,
            }
            buf.reset()
        except Exception:
            self._modal_input_snapshot = None

    def _restore_modal_input_snapshot(self) -> None:
        """Restore any draft text that was present before a modal prompt opened."""
        snapshot = self._modal_input_snapshot
        self._modal_input_snapshot = None
        if not snapshot or not getattr(self, "_app", None):
            return
        try:
            buf = self._app.current_buffer
            buf.text = snapshot.get("text", "")
            buf.cursor_position = min(snapshot.get("cursor_position", 0), len(buf.text))
        except Exception:
            pass

    def _submit_secret_response(self, value: str) -> None:
        if not self._secret_state:
            return
        self._secret_state["response_queue"].put(value)
        self._secret_state = None
        self._secret_deadline = 0
        self._invalidate()

    def _cancel_secret_capture(self) -> None:
        self._submit_secret_response("")

    def _clear_secret_input_buffer(self) -> None:
        if getattr(self, "_app", None):
            try:
                self._app.current_buffer.reset()
            except Exception:
                pass

    def chat(self, message, images: list = None) -> Optional[str]:
        """
        Send a message to the agent and get a response.
        
        Handles streaming output, interrupt detection (user typing while agent
        is working), and re-queueing of interrupted messages.
        
        Uses a dedicated _interrupt_queue (separate from _pending_input) to avoid
        race conditions between the process_loop and interrupt monitoring. Messages
        typed while the agent is running go to _interrupt_queue; messages typed while
        idle go to _pending_input.
        
        Args:
            message: The user's message (str or multimodal content list)
            images: Optional list of Path objects for attached images
            
        Returns:
            The agent's response, or None on error
        """
        # Single-query and direct chat callers do not go through run(), so
        # register secure secret capture here as well.
        set_secret_capture_callback(self._secret_capture_callback)

        # Refresh provider credentials if needed (handles key rotation transparently)
        if not self._ensure_runtime_credentials():
            return None

        turn_route = self._resolve_turn_agent_config(message)
        if turn_route["signature"] != self._active_agent_route_signature:
            self.agent = None

        # Initialize agent if needed (TTY spinner only on first construction)
        _init_cm = self._agent_init_spinner() if self.agent is None else nullcontext()
        with _init_cm:
            if not self._init_agent(
                model_override=turn_route["model"],
                runtime_override=turn_route["runtime"],
                request_overrides=turn_route.get("request_overrides"),
            ):
                return None
        
        # Pre-process images through the vision tool (Gemini Flash) so the
        # main model receives text descriptions instead of raw base64 image
        # content — works with any model, not just vision-capable ones.
        if images:
            message = self._preprocess_images_with_vision(
                message if isinstance(message, str) else "", images
            )

        # Expand @ context references (e.g. @file:main.py, @diff, @folder:src/)
        if isinstance(message, str) and "@" in message:
            try:
                from agent.context_references import preprocess_context_references
                from agent.model_metadata import get_model_context_length
                _ctx_len = get_model_context_length(
                    self.model, base_url=self.base_url or "", api_key=self.api_key or "")
                _ctx_result = preprocess_context_references(
                    message, cwd=safe_getcwd(), context_length=_ctx_len)
                if _ctx_result.expanded or _ctx_result.blocked:
                    if _ctx_result.references:
                        _cprint(
                            f"  {_DIM}[@ context: {len(_ctx_result.references)} ref(s), "
                            f"{_ctx_result.injected_tokens} tokens]{_RST}")
                    for w in _ctx_result.warnings:
                        _cprint(f"  {_DIM}▲ {w}{_RST}")
                    if _ctx_result.blocked:
                        return "\n".join(_ctx_result.warnings) or "Injeção de contexto recusada."
                    message = _ctx_result.message
            except Exception as e:
                logging.debug("@ context reference expansion failed: %s", e)

        # Sanitize surrogate characters that can arrive via clipboard paste from
        # rich-text editors (Google Docs, Word, etc.).  Lone surrogates are invalid
        # UTF-8 and crash JSON serialization in the OpenAI SDK.
        if isinstance(message, str):
            from run_agent import _sanitize_surrogates
            message = _sanitize_surrogates(message)

        # Add user message to history
        self.conversation_history.append({"role": "user", "content": message})

        ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
        print(flush=True)
        
        try:
            # Run the conversation with interrupt monitoring
            result = None

            # Reset streaming display state for this turn
            self._reset_stream_state()
            # Separate from _reset_stream_state because this must persist
            # across intermediate turn boundaries (tool-calling loops) — only
            # reset at the start of each user turn.
            self._reasoning_shown_this_turn = False

            # --- Streaming TTS setup ---
            # When ElevenLabs is the TTS provider and sounddevice is available,
            # we stream audio sentence-by-sentence as the agent generates tokens
            # instead of waiting for the full response.
            use_streaming_tts = False
            _streaming_box_opened = False
            text_queue = None
            tts_thread = None
            stream_callback = None
            stop_event = None

            if self._voice_tts:
                try:
                    from tools.tts_tool import (
                        _load_tts_config as _load_tts_cfg,
                        _get_provider as _get_prov,
                        _import_elevenlabs,
                        _import_sounddevice,
                        stream_tts_to_speaker,
                    )
                    _tts_cfg = _load_tts_cfg()
                    if _get_prov(_tts_cfg) == "elevenlabs":
                        # Verify both ElevenLabs SDK and audio output are available
                        _import_elevenlabs()
                        _import_sounddevice()
                        use_streaming_tts = True
                except (ImportError, OSError):
                    pass
                except Exception:
                    pass

            if use_streaming_tts:
                text_queue = queue.Queue()
                stop_event = threading.Event()

                def display_callback(sentence: str):
                    """Called by TTS consumer when a sentence is ready to display + speak."""
                    nonlocal _streaming_box_opened
                    if not _streaming_box_opened:
                        _streaming_box_opened = True
                        w = self.console.width
                        label = " ⚡ ECTOR "
                        fill = w - 2 - len(label)
                        _cprint(f"\n{_ACCENT}╭─{label}{'─' * max(fill - 1, 0)}╮{_RST}")
                    _cprint(f"{_STREAM_PAD}{sentence.rstrip()}")

                tts_thread = threading.Thread(
                    target=stream_tts_to_speaker,
                    args=(text_queue, stop_event, self._voice_tts_done),
                    kwargs={"display_callback": display_callback},
                    daemon=True,
                )
                tts_thread.start()

                def stream_callback(delta: str):
                    if text_queue is not None:
                        text_queue.put(delta)

            # When voice mode is active, prepend a brief instruction so the
            # model responds concisely. The prefix is API-call-local only —
            # run_conversation persists the original clean user message.
            _voice_prefix = ""
            if self._voice_mode and isinstance(message, str):
                _voice_prefix = (
                    "[Entrada de voz — responda de forma concisa e conversacional, "
                    "no máximo 2-3 frases. Sem blocos de código ou markdown.] "
                )

            def run_agent():
                nonlocal result
                # Set callbacks inside the agent thread so thread-local storage
                # in terminal_tool is populated for this thread.  The main thread
                # registration (run() line ~9046) is invisible here because
                # _callback_tls is threading.local().  Matches the pattern used
                # by acp_adapter/server.py for ACP sessions.
                set_sudo_password_callback(self._sudo_password_callback)
                set_approval_callback(self._approval_callback)
                try:
                    set_secret_capture_callback(self._secret_capture_callback)
                except Exception:
                    pass
                agent_message = _voice_prefix + message if _voice_prefix else message
                # Prepend pending model switch note so the model knows about the switch
                _msn = getattr(self, '_pending_model_switch_note', None)
                if _msn:
                    agent_message = _msn + "\n\n" + agent_message
                    self._pending_model_switch_note = None
                try:
                    result = self.agent.run_conversation(
                        user_message=agent_message,
                        conversation_history=self.conversation_history[:-1],  # Exclude the message we just added
                        stream_callback=stream_callback,
                        task_id=self.session_id,
                        persist_user_message=message if _voice_prefix else None,
                    )
                except Exception as exc:
                    logging.error("run_conversation raised: %s", exc, exc_info=True)
                    _summary = getattr(self.agent, '_summarize_api_error', lambda e: str(e)[:300])(exc)
                    result = {
                        "final_response": f"Erro: {_summary}",
                        "messages": [],
                        "api_calls": 0,
                        "completed": False,
                        "failed": True,
                        "error": _summary,
                    }
                finally:
                    # Clear thread-local callbacks so a reused thread doesn't
                    # hold stale references to a disposed CLI instance.
                    try:
                        set_sudo_password_callback(None)
                        set_approval_callback(None)
                        set_secret_capture_callback(None)
                    except Exception:
                        pass

            # Start agent in background thread (daemon so it cannot keep the
            # process alive when the user closes the terminal tab — SIGHUP
            # exits the main thread and daemon threads are reaped automatically).
            # Start per-prompt elapsed timer — frozen after the agent thread
            # finishes; reset on the next turn.
            self._prompt_start_time = time.time()
            self._prompt_duration = 0.0
            agent_thread = threading.Thread(target=run_agent, daemon=True)
            agent_thread.start()

            # Monitor the dedicated interrupt queue while the agent runs.
            # _interrupt_queue is separate from _pending_input, so process_loop
            # and chat() never compete for the same queue.
            # When a Wiser (wiser) question is active, user input is handled entirely
            # by the Enter key binding (routed to the wiser response queue),
            # so we skip interrupt processing to avoid stealing that input.
            interrupt_msg = None
            while agent_thread.is_alive():
                if hasattr(self, '_interrupt_queue'):
                    try:
                        interrupt_msg = self._interrupt_queue.get(timeout=0.1)
                        if interrupt_msg:
                            # If Wiser is active, the Enter handler routes
                            # input directly; this queue shouldn't have anything.
                            # But if it does (race condition), don't interrupt.
                            if self._wiser_state or self._wiser_freetext:
                                continue
                            print("\n⚡ Nova mensagem detectada, interrompendo...")
                            # Signal TTS to stop on interrupt
                            if stop_event is not None:
                                stop_event.set()
                            self.agent.interrupt(interrupt_msg)
                            # Debug: log to file (stdout may be devnull from redirect_stdout)
                            try:
                                _dbg = _ector_home / "interrupt_debug.log"
                                with open(_dbg, "a") as _f:
                                    _f.write(f"{time.strftime('%H:%M:%S')} interrupt fired: msg={str(interrupt_msg)[:60]!r}, "
                                             f"children={len(self.agent._active_children)}, "
                                             f"parent._interrupt={self.agent._interrupt_requested}\n")
                                    for _ci, _ch in enumerate(self.agent._active_children):
                                        _f.write(f"  child[{_ci}]._interrupt={_ch._interrupt_requested}\n")
                            except Exception:
                                pass
                            break
                    except queue.Empty:
                        # Force prompt_toolkit to flush any pending stdout
                        # output from the agent thread.  Without this, the
                        # StdoutProxy buffer only flushes on renderer passes
                        # triggered by input events — on macOS this causes
                        # the CLI to appear frozen until the user types. (#1624)
                        self._invalidate(min_interval=0.15)
                else:
                    # Fallback for non-interactive mode (e.g., single-query)
                    agent_thread.join(0.1)

            # Wait for the agent thread to finish.  After an interrupt the
            # agent may take a few seconds to clean up (kill subprocess, persist
            # session).  Poll instead of a blocking join so the process_loop
            # stays responsive — if the user sent another interrupt or the
            # agent gets stuck, we can break out instead of freezing forever.
            if interrupt_msg is not None:
                # Interrupt path: poll briefly, then move on.  The agent
                # thread is daemon — it dies on process exit regardless.
                for _wait_tick in range(50):  # 50 * 0.2s = 10s max
                    agent_thread.join(timeout=0.2)
                    if not agent_thread.is_alive():
                        break
                    # Check if user fired ANOTHER interrupt (Ctrl+C sets
                    # _should_exit which process_loop checks on next pass).
                    if getattr(self, '_should_exit', False):
                        break
                if agent_thread.is_alive():
                    logger.warning(
                        "Agent thread still alive after interrupt "
                        "(thread %s). Daemon thread will be cleaned up "
                        "on exit.",
                        agent_thread.ident,
                    )
            else:
                # Normal completion: agent thread should be done already,
                # but guard against edge cases.
                agent_thread.join(timeout=30)

            # Freeze per-prompt elapsed timer once the agent thread has
            # exited (or been abandoned as a daemon after interrupt).
            if self._prompt_start_time is not None:
                self._prompt_duration = max(0.0, time.time() - self._prompt_start_time)
                self._prompt_start_time = None

            # Proactively clean up async clients whose event loop is dead.
            # The agent thread may have created AsyncOpenAI clients bound
            # to a per-thread event loop; if that loop is now closed, those
            # clients' __del__ would crash prompt_toolkit's loop on GC.
            try:
                from agent.auxiliary_client import cleanup_stale_async_clients
                cleanup_stale_async_clients()
            except Exception:
                pass

            # Flush any remaining streamed text and close the box
            self._flush_stream()

            # Signal end-of-text to TTS consumer and wait for it to finish
            if use_streaming_tts and text_queue is not None:
                text_queue.put(None)  # sentinel
                if tts_thread is not None:
                    tts_thread.join(timeout=120)

            # Drain any remaining agent output still in the StdoutProxy
            # buffer so tool/status lines render ABOVE our response box.
            # The flush pushes data into the renderer queue; the short
            # sleep lets the renderer actually paint it before we draw.
            sys.stdout.flush()
            time.sleep(0.15)

            # Update history with full conversation
            self.conversation_history = result.get("messages", self.conversation_history) if result else self.conversation_history

            # If auto-compression fired mid-turn, the agent created a new
            # continuation session and mutated self.agent.session_id. Sync
            # the CLI's session_id so /status, /resume, title generation,
            # and the exit summary all target the live child session rather
            # than the ended parent. Mirrors the gateway's post-run sync
            # (gateway/run.py around line 9983).
            if (
                self.agent
                and getattr(self.agent, "session_id", None)
                and self.agent.session_id != self.session_id
            ):
                self.session_id = self.agent.session_id
                self._pending_title = None

            # Get the final response
            response = result.get("final_response", "") if result else ""

            # Auto-generate session title after first exchange (non-blocking)
            if response and result and not result.get("failed") and not result.get("partial"):
                try:
                    from agent.title_generator import maybe_auto_title
                    # Route title-generation failures through the agent's
                    # user-visible warning channel so a depleted auxiliary
                    # provider doesn't silently leave sessions untitled
                    # (issue #15775).
                    _title_failure_cb = getattr(
                        self.agent, "_emit_auxiliary_failure", None
                    ) if self.agent else None
                    maybe_auto_title(
                        self._session_db,
                        self.session_id,
                        message,
                        response,
                        self.conversation_history,
                        failure_callback=_title_failure_cb,
                    )
                except Exception:
                    pass

            # Handle failed or partial results (e.g., non-retryable errors, rate limits,
            # truncated output, invalid tool calls). Both "failed" and "partial" with
            # an empty final_response mean the agent couldn't produce a usable answer.
            if result and (result.get("failed") or result.get("partial")) and not response:
                error_detail = result.get("error", "Unknown error")
                response = f"Erro: {error_detail}"
                # Stop continuous voice mode on persistent errors (e.g. 429 rate limit)
                # to avoid an infinite error → record → error loop
                if self._voice_continuous:
                    self._voice_continuous = False
                    _cprint(f"\n{_DIM}Modo de voz contínuo parado devido a um erro.{_RST}")

            # Handle interrupt - check if we were interrupted
            pending_message = None
            if result and result.get("interrupted"):
                pending_message = result.get("interrupt_message") or interrupt_msg
                # Add indicator that we were interrupted
                if response and pending_message:
                    response = response + "\n\n---\n_[Interrompido - processando nova mensagem]_"

            response_previewed = result.get("response_previewed", False) if result else False

            # Display reasoning (thinking) box if enabled and available.
            # Skip when streaming already showed reasoning live.  Use the
            # turn-persistent flag (_reasoning_shown_this_turn) instead of
            # _reasoning_stream_started — the latter gets reset during
            # intermediate turn boundaries (tool-calling loops), which caused
            # the reasoning box to re-render after the final response.
            _reasoning_already_shown = getattr(self, '_reasoning_shown_this_turn', False)
            if self.show_reasoning and result and not _reasoning_already_shown:
                reasoning = result.get("last_reasoning")
                if reasoning:
                    w = shutil.get_terminal_size().columns
                    r_label = " Raciocínio "
                    r_fill = w - 2 - len(r_label)
                    r_top = f"{_DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{_RST}"
                    r_bot = f"{_DIM}└{'─' * (w - 2)}┘{_RST}"
                    # Collapse long reasoning: show first 10 lines
                    lines = reasoning.strip().splitlines()
                    if len(lines) > 10:
                        display_reasoning = "\n".join(lines[:10])
                        display_reasoning += f"\n{_DIM}  ... ({len(lines) - 10} mais linhas){_RST}"
                    else:
                        display_reasoning = reasoning.strip()
                    _cprint(f"\n{r_top}\n{_DIM}{display_reasoning}{_RST}\n{r_bot}")

            if response and not response_previewed:
                # Use skin engine for label/color with fallback
                label = " ECTOR "
                _resp_color = "#00D1FF"
                _resp_text = "#E6E6FA"

                is_error_response = result and (result.get("failed") or result.get("partial"))
                already_streamed = self._stream_started and self._stream_box_opened and not is_error_response
                if use_streaming_tts and _streaming_box_opened and not is_error_response:
                    # Text was already printed sentence-by-sentence; just close the box
                    w = shutil.get_terminal_size().columns
                    _cprint(f"\n{_ACCENT}╰{'─' * (w - 2)}╯{_RST}")
                elif already_streamed:
                    # Response was already streamed token-by-token with box framing;
                    # _flush_stream() already closed the box. Skip Rich Panel.
                    pass
                else:
                    _chat_console = ChatConsole()
                    _chat_console.print(Panel(
                        _render_final_assistant_content(response, mode=self.final_response_markdown),
                        title=f"[{_resp_color} bold]{label}[/]",
                        title_align="left",
                        border_style=_resp_color,
                        style=_resp_text,
                        box=rich_box.HORIZONTALS,
                        padding=(1, 4),
                    ))

            if self.show_cost and result and not result.get("failed"):
                cost_value = result.get("estimated_cost_usd")
                cost_status = str(result.get("cost_status") or "unknown")
                if isinstance(cost_value, (int, float)) and cost_value > 0:
                    prefix = "~" if cost_status == "estimated" else ""
                    _cprint(f"{_DIM}Custo da sessão: {prefix}${float(cost_value):.4f} USD{_RST}")
                elif cost_status == "included":
                    _cprint(f"{_DIM}Custo da sessão: incluso{_RST}")

            # Play terminal bell when agent finishes (if enabled).
            # Works over SSH — the bell propagates to the user's terminal.
            if self.bell_on_complete:
                sys.stdout.write("\a")
                sys.stdout.flush()

            # Notify when iteration budget was hit
            if result and not result.get("completed") and not result.get("interrupted"):
                _api_calls = result.get("api_calls", 0)
                if _api_calls >= getattr(self.agent, "max_iterations", 90):
                    _max_iter = getattr(self.agent, "max_iterations", 90)
                    _cprint(
                        f"▲ Orçamento de iterações atingido "
                        f"({_api_calls}/{_max_iter}) — "
                        f"a resposta pode estar incompleta{_RST}"
                    )

            # Speak response aloud if voice TTS is enabled
            # Skip batch TTS when streaming TTS already handled it
            if self._voice_tts and response and not use_streaming_tts:
                threading.Thread(
                    target=self._voice_speak_response,
                    args=(response,),
                    daemon=True,
                ).start()


            # Re-queue the interrupt message (and any that arrived while we were
            # processing the first) as the next prompt for process_loop.
            # Only reached when busy_input_mode == "interrupt" (the default).
            # In "queue" mode Enter routes directly to _pending_input so this
            # block is never hit.
            if pending_message and hasattr(self, '_pending_input'):
                all_parts = [pending_message]
                while not self._interrupt_queue.empty():
                    try:
                        extra = self._interrupt_queue.get_nowait()
                        if extra:
                            all_parts.append(extra)
                    except queue.Empty:
                        break
                combined = "\n".join(all_parts)
                n = len(all_parts)
                preview = combined[:50] + ("..." if len(combined) > 50 else "")
                if n > 1:
                    print(f"\n⚡ Enviando {n} mensagens após interrupção: '{preview}'")
                else:
                    print(f"\n⚡ Enviando após interrupção: '{preview}'")
                self._pending_input.put(combined)

            # If a /steer was left over (agent finished before another tool
            # batch could absorb it), deliver it as the next user turn.
            _leftover_steer = result.get("pending_steer") if result else None
            if _leftover_steer and hasattr(self, '_pending_input'):
                preview = _leftover_steer[:60] + ("..." if len(_leftover_steer) > 60 else "")
                print(f"\n⏩ Entregando /steer restante como próximo turno: '{preview}'")
                self._pending_input.put(_leftover_steer)

            return response
            
        except Exception as e:
            print(f"Error: {e}")
            return None
        finally:
            # Ensure streaming TTS resources are cleaned up even on error.
            # Normal path sends the sentinel at line ~3568; this is a safety
            # net for exception paths that skip it.  Duplicate sentinels are
            # harmless — stream_tts_to_speaker exits on the first None.
            if text_queue is not None:
                try:
                    text_queue.put_nowait(None)
                except Exception:
                    pass
            if stop_event is not None:
                stop_event.set()
            if tts_thread is not None and tts_thread.is_alive():
                tts_thread.join(timeout=5)
    
    def _print_exit_summary(self):
        """Print session resume info on exit, similar to Claude Code."""
        cc = ChatConsole()
        msg_count = len(self.conversation_history)
        
        if msg_count > 0:
            user_msgs = len([m for m in self.conversation_history if m.get("role") == "user"])
            tool_calls = len([m for m in self.conversation_history if m.get("role") == "tool" or m.get("tool_calls")])
            elapsed = datetime.now() - self.session_start
            
            # Look up session title for resume-by-name hint
            session_title = None
            if self._session_db:
                try:
                    session_title = self._session_db.get_session_title(self.session_id)
                except Exception:
                    pass

            cc.print()
            cc.print(f"[bold #00D1FF]Resumo da Sessão[/]")
            cc.print(f"  [dim]ID:[/][#E6E6FA] {self.session_id}[/]")
            if session_title:
                cc.print(f"  [dim]Título:[/][#E6E6FA] {session_title}[/]")
            cc.print(f"  [dim]Duração:[/][#E6E6FA] {format_duration_compact(elapsed.total_seconds())}[/]")
            cc.print(f"  [dim]Mensagens:[/][#E6E6FA] {msg_count} ({user_msgs} usuário, {tool_calls} chamadas de ferramenta)[/]")
            cc.print()
            cc.print(f"[dim]Para retomar esta sessão:[/]")
            cc.print(f"  [#00D1FF]ector sessions browse[/]")
            cc.print(f"  [dim]ou abra /chat no painel web[/]")
            cc.print()

        try:
            goodbye = "[bold #00D1FF]Até logo![/]"
        except Exception:
            goodbye = "Até logo! ⚡"
        cc.print(goodbye)

    def _get_tui_prompt_symbols(self) -> tuple[str, str]:
        """Return ``(normal_prompt, state_suffix)`` for the active skin.

        ``normal_prompt`` is the full ``branding.prompt_symbol``.
        ``state_suffix`` is what special states (sudo/secret/approval/agent)
        should render after their leading icon.

        When a profile is active (not "default"), the profile name is
        prepended to the prompt symbol: ``coder ❯`` instead of ``❯``.
        """
        try:
            symbol = "✦"
        except Exception:
            symbol = "❯ "

        symbol = (symbol or "❯ ").rstrip() + " "

        # Prepend profile name when not default
        try:
            from ector_cli.profiles import get_active_profile_name
            profile = get_active_profile_name()
            if profile not in ("default", "custom"):
                symbol = f"{profile} {symbol}"
        except Exception:
            pass
        stripped = symbol.rstrip()
        if not stripped:
            return "❯ ", "❯ "

        parts = stripped.split()
        candidate = parts[-1] if parts else ""
        arrow_chars = ("❯", ">", "$", "#", "›", "»", "→")
        if any(ch in candidate for ch in arrow_chars):
            return symbol, candidate.rstrip() + " "

        # Icon-only custom prompts should still remain visible in special states.
        return symbol, symbol

    def _audio_level_bar(self) -> str:
        """Return a visual audio level indicator based on current RMS."""
        _LEVEL_BARS = " ▁▂▃▄▅▆▇"
        rec = getattr(self, "_voice_recorder", None)
        if rec is None:
            return ""
        rms = rec.current_rms
        # Normalize RMS (0-32767) to 0-7 index, with log-ish scaling
        # Typical speech RMS is 500-5000, we cap display at ~8000
        level = min(rms, 8000) * 7 // 8000
        return _LEVEL_BARS[level]

    def _get_tui_prompt_fragments(self):
        """Return the prompt_toolkit fragments for the current interactive state."""
        symbol, state_suffix = self._get_tui_prompt_symbols()
        compact = self._use_minimal_tui_chrome(width=self._get_tui_terminal_width())

        def _state_fragment(style: str, icon: str, extra: str = ""):
            if compact:
                text = icon
                if extra:
                    text = f"{text} {extra.strip()}".rstrip()
                return [(style, text + " ")]
            if extra:
                return [(style, f"{icon} {extra} {state_suffix}")]
            return [(style, f"{icon} {state_suffix}")]

        if self._voice_recording:
            bar = self._audio_level_bar()
            return _state_fragment("class:voice-recording", "●", bar)
        if self._voice_processing:
            return _state_fragment("class:voice-processing", "◉")
        if self._sudo_state:
            return _state_fragment("class:sudo-prompt", "🔐")
        if self._secret_state:
            return _state_fragment("class:sudo-prompt", "🔑")
        if self._approval_state:
            return _state_fragment("class:prompt-working", "▲")
        if self._wiser_freetext:
            return _state_fragment("class:wiser-selected", "✎")
        if self._wiser_state:
            return _state_fragment("class:prompt-working", "?")
        if self._command_running:
            return _state_fragment("class:prompt-working", self._command_spinner_frame())
        if self._agent_running:
            return _state_fragment("class:prompt-working", "⚡")
        if self._voice_mode:
            return _state_fragment("class:voice-prompt", "🎤")
        return [("class:prompt", symbol)]

    def _get_tui_prompt_text(self) -> str:
        """Return the visible prompt text for width calculations."""
        return "".join(text for _, text in self._get_tui_prompt_fragments())

    def _build_tui_style_dict(self) -> dict[str, str]:
        """Return the hardcoded violet TUI style."""
        return dict(getattr(self, "_tui_style_base", {}) or {})

    def _apply_tui_skin_style(self) -> bool:
        """Refresh styling for the running TUI (no-op now skins are removed)."""
        return True

    # --- Protected TUI extension hooks for wrapper CLIs ---

    def _get_extra_tui_widgets(self) -> list:
        """Return extra prompt_toolkit widgets to insert into the TUI layout.

        Wrapper CLIs can override this to inject widgets (e.g. a mini-player,
        overlay menu) into the layout without overriding ``run()``.  Widgets
        are inserted between the spacer and the status bar.
        """
        return []

    def _register_extra_tui_keybindings(self, kb, *, input_area) -> None:
        """Register extra keybindings on the TUI ``KeyBindings`` object.

        Wrapper CLIs can override this to add keybindings (e.g. transport
        controls, modal shortcuts) without overriding ``run()``.

        Parameters
        ----------
        kb : KeyBindings
            The active keybinding registry for the prompt_toolkit application.
        input_area : TextArea
            The main input widget, for wrappers that need to inspect or
            manipulate user input from a keybinding handler.
        """

    def _build_tui_layout_children(
        self,
        *,
        sudo_widget,
        secret_widget,
        approval_widget,
        wiser_widget,
        model_picker_widget=None,
        spinner_widget=None,
        spacer,
        status_bar,
        input_rule_top,
        image_bar,
        input_area,
        input_rule_bot,
        voice_status_bar,
        completions_menu,
    ) -> list:
        """Assemble the ordered list of children for the root ``HSplit``.

        Wrapper CLIs typically override ``_get_extra_tui_widgets`` instead of
        this method.  Override this only when you need full control over widget
        ordering.
        """
        return [
            item for item in [
                Window(height=0),
                sudo_widget,
                secret_widget,
                approval_widget,
                wiser_widget,
                model_picker_widget,
                spinner_widget,
                spacer,
                *self._get_extra_tui_widgets(),
                status_bar,
                input_rule_top,
                image_bar,
                input_area,
                input_rule_bot,
                voice_status_bar,
                completions_menu,
            ] if item is not None
        ]

    def run(self):
        """Legacy REPL removed — use ``ector`` / ``ector chat`` (Ink TUI)."""
        raise NotImplementedError(
            "Interactive REPL was removed. Run `ector` or `ector chat` for the Ink TUI."
        )

# ============================================================================
# Main Entry Point
# ============================================================================

def main(
    query: str = None,
    q: str = None,
    image: str = None,
    toolsets: str = None,
    skills: str | list[str] | tuple[str, ...] = None,
    model: str = None,
    provider: str = None,
    api_key: str = None,
    base_url: str = None,
    max_turns: int = None,
    verbose: bool = False,
    quiet: bool = False,
    list_tools: bool = False,
    list_toolsets: bool = False,
    gateway: bool = False,
    resume: str = None,
    worktree: bool = False,
    w: bool = False,
    checkpoints: bool = False,
    pass_session_id: bool = False,
    ignore_user_config: bool = False,
    ignore_rules: bool = False,
):
    """
    ECTOR Agent CLI - Interactive AI Assistant
    
    Args:
        query: Single query to execute (then exit). Alias: -q
        q: Shorthand for --query
        image: Optional local image path to attach to a single query
        toolsets: Comma-separated list of toolsets to enable (e.g., "web,terminal")
        skills: Comma-separated or repeated list of skills to preload for the session
        model: Model to use (default: anthropic/claude-opus-4-20250514)
        provider: Inference provider ("auto", "openrouter", "ector", "openai-codex", "zai", "kimi-coding", "minimax", "minimax-cn")
        api_key: API key for authentication
        base_url: Base URL for the API
        max_turns: Maximum tool-calling iterations (default: 60)
        verbose: Enable verbose logging
        list_tools: List available tools and exit
        list_toolsets: List available toolsets and exit
        resume: Resume a previous session by its ID (e.g., 20260225_143052_a1b2c3)
        worktree: Run in an isolated git worktree (for parallel agents). Alias: -w
        w: Shorthand for --worktree
    
    Examples:
        python cli.py                            # Start interactive mode
        python cli.py --toolsets web,terminal    # Use specific toolsets
    python cli.py --skills ector-agent-dev,github-auth
        python cli.py -q "What is Python?"       # Single query mode
        python cli.py -q "Describe this" --image ~/storage/shared/Pictures/cat.png
        python cli.py --list-tools               # List tools and exit
        python cli.py --resume 20260225_143052_a1b2c3  # Resume session
        python cli.py -w                         # Start in isolated git worktree
        python cli.py -w -q "Fix issue #123"     # Single query in worktree
    """
    global _active_worktree

    # Signal to terminal_tool that we're in interactive mode
    # This enables interactive sudo password prompts with timeout
    os.environ["ECTOR_INTERACTIVE"] = "1"
    
    # Handle gateway mode (messaging + cron)
    if gateway:
        import asyncio
        from gateway.run import start_gateway
        print("Starting ECTOR Gateway (messaging platforms)...")
        asyncio.run(start_gateway())
        return

    # Skip worktree for list commands (they exit immediately)
    if not list_tools and not list_toolsets:
        # ── Git worktree isolation (#652) ──
        # Create an isolated worktree so this agent instance doesn't collide
        # with other agents working on the same repo.
        use_worktree = worktree or w or CLI_CONFIG.get("worktree", False)
        wt_info = None
        if use_worktree:
            # Prune stale worktrees from crashed/killed sessions
            _repo = _git_repo_root()
            if _repo:
                _prune_stale_worktrees(_repo)
            wt_info = _setup_worktree()
            if wt_info:
                _active_worktree = wt_info
                os.environ["TERMINAL_CWD"] = wt_info["path"]
                atexit.register(_cleanup_worktree, wt_info)
            else:
                # Worktree was explicitly requested but setup failed —
                # don't silently run without isolation.
                return
    else:
        wt_info = None
    
    # Handle query shorthand
    query = query or q
    
    # Parse toolsets - handle both string and tuple/list inputs
    # Default to ector-cli toolset which includes cronjob management tools
    toolsets_list = None
    if toolsets:
        if isinstance(toolsets, str):
            toolsets_list = [t.strip() for t in toolsets.split(",")]
        elif isinstance(toolsets, (list, tuple)):
            # Fire may pass multiple --toolsets as a tuple
            toolsets_list = []
            for t in toolsets:
                if isinstance(t, str):
                    toolsets_list.extend([x.strip() for x in t.split(",")])
                else:
                    toolsets_list.append(str(t))
    else:
        # Use the shared resolver so MCP servers are included at runtime
        from ector_cli.tools_config import _get_platform_tools
        toolsets_list = sorted(_get_platform_tools(CLI_CONFIG, "cli"))
    
    parsed_skills = _parse_skills_argument(skills)

    # Create CLI instance
    cli = EctorCLI(
        model=model,
        toolsets=toolsets_list,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        max_turns=max_turns,
        verbose=verbose,
        resume=resume,
        checkpoints=checkpoints,
        pass_session_id=pass_session_id,
        ignore_rules=ignore_rules,
    )

    if parsed_skills:
        skills_prompt, loaded_skills, missing_skills = build_preloaded_skills_prompt(
            parsed_skills,
            task_id=cli.session_id,
        )
        if missing_skills:
            missing_display = ", ".join(missing_skills)
            raise ValueError(f"Unknown skill(s): {missing_display}")
        if skills_prompt:
            cli.system_prompt = "\n\n".join(
                part for part in (cli.system_prompt, skills_prompt) if part
            ).strip()
            cli.preloaded_skills = loaded_skills

    # Inject worktree context into agent's system prompt
    if wt_info:
        wt_note = (
            f"\n\n[Nota do sistema: Você está trabalhando em um git worktree isolado em "
            f"{wt_info['path']}. Sua branch é `{wt_info['branch']}`. "
            f"As alterações aqui não afetam a árvore de trabalho principal ou outros agentes. "
            f"Lembre-se de commitar e dar push em suas alterações, e criar um PR se apropriado. "
            f"O repositório original está em {wt_info['repo_root']}.]"
        )
        cli.system_prompt = (cli.system_prompt or "") + wt_note
    
    # Handle list commands (don't init agent for these)
    if list_tools:
        # Sem banner: lista longa + pager em show_tools.
        cli.show_tools()
        sys.exit(0)
    
    if list_toolsets:
        # Sem banner: a lista é longa e o banner limpa a tela, o que corta a
        # tabela e some com o scroll-back útil; o pager da tabela cobre a leitura.
        cli.show_toolsets()
        sys.exit(0)
    
    # Register cleanup for single-query mode (interactive mode registers in run())
    atexit.register(_run_cleanup)

    # Also install signal handlers in single-query / `-q` mode.  Interactive
    # mode registers its own inside EctorCLI.run(), but `-q` runs
    # cli.agent.run_conversation() below and AIAgent spawns worker threads
    # for tools — so when SIGTERM arrives on the main thread, raising
    # KeyboardInterrupt only unwinds the main thread, not the worker
    # running _wait_for_process.  Python then exits, the child subprocess
    # (spawned with os.setsid, its own process group) is reparented to
    # init and keeps running as an orphan.
    #
    # Fix: route SIGTERM/SIGHUP through agent.interrupt() which sets the
    # per-thread interrupt flag the worker's poll loop checks every 200 ms.
    # Give the worker a grace window to call _kill_process (SIGTERM to the
    # process group, then SIGKILL after 1 s), then raise KeyboardInterrupt
    # so main unwinds normally.  ECTOR_SIGTERM_GRACE overrides the 1.5 s
    # default for debugging.
    def _signal_handler_q(signum, frame):
        logger.debug("Received signal %s in single-query mode", signum)
        try:
            _agent = getattr(cli, "agent", None)
            if _agent is not None:
                _agent.interrupt(f"received signal {signum}")
                try:
                    _grace = float(os.getenv("ECTOR_SIGTERM_GRACE", "1.5"))
                except (TypeError, ValueError):
                    _grace = 1.5
                if _grace > 0:
                    time.sleep(_grace)
        except Exception:
            pass  # never block signal handling
        raise KeyboardInterrupt()
    try:
        import signal as _signal
        _signal.signal(_signal.SIGTERM, _signal_handler_q)
        if hasattr(_signal, "SIGHUP"):
            _signal.signal(_signal.SIGHUP, _signal_handler_q)
    except Exception:
        pass  # signal handler may fail in restricted environments
    
    # Handle single query mode
    if query or image:
        query, single_query_images = _collect_query_images(query, image)
        if quiet:
            # Quiet mode: suppress banner, spinner, tool previews.
            # Only print the final response and parseable session info.
            cli.tool_progress_mode = "off"
            if cli._ensure_runtime_credentials():
                effective_query = query
                if single_query_images:
                    effective_query = cli._preprocess_images_with_vision(
                        query,
                        single_query_images,
                        announce=False,
                    )
                turn_route = cli._resolve_turn_agent_config(effective_query)
                if turn_route["signature"] != cli._active_agent_route_signature:
                    cli.agent = None
                if cli._init_agent(
                    model_override=turn_route["model"],
                    runtime_override=turn_route["runtime"],
                    request_overrides=turn_route.get("request_overrides"),
                ):
                    cli.agent.quiet_mode = True
                    cli.agent.suppress_status_output = True
                    # Suppress streaming display callbacks so stdout stays
                    # machine-readable (no styled "ECTOR" box, no tool-gen
                    # status lines).  The response is printed once below.
                    cli.agent.stream_delta_callback = None
                    cli.agent.tool_gen_callback = None
                    result = cli.agent.run_conversation(
                        user_message=effective_query,
                        conversation_history=cli.conversation_history,
                    )
                    # Sync session_id if mid-run compression created a
                    # continuation session. The exit line below reports
                    # session_id to stderr for automation wrappers; without
                    # this sync it would point at the ended parent.
                    if (
                        getattr(cli.agent, "session_id", None)
                        and cli.agent.session_id != cli.session_id
                    ):
                        cli.session_id = cli.agent.session_id
                    response = result.get("final_response", "") if isinstance(result, dict) else str(result)
                    if response:
                        print(response)
                    # Session ID goes to stderr so piped stdout is clean.
                    print(f"\nsession_id: {cli.session_id}", file=sys.stderr)
                    
                    # Ensure proper exit code for automation wrappers
                    sys.exit(1 if isinstance(result, dict) and result.get("failed") else 0)
            
            # Exit with error code if credentials or agent init fails
            sys.exit(1)
        else:
            _query_label = query or ("[image attached]" if single_query_images else "")
            if _query_label:
                cli.console.print(f"[bold blue]Pergunta:[/] {_query_label}")
            cli.chat(query, images=single_query_images or None)
            cli._print_exit_summary()
        return
    
    # Run interactive mode
    cli.run()


if __name__ == "__main__":
    from ector_cli.cli_py_shim import run_cli_py_entry

    run_cli_py_entry()
