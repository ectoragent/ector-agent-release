"""Version screen, ASCII art, skills summary, and update check for the CLI.

Moved from `ector_cli/banner.py` to keep the entrypoint simpler while
preserving the same runtime behavior.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from rich.console import Console

from ector_constants import get_ector_home

logger = logging.getLogger(__name__)


# =========================================================================
# ANSI building blocks for conversation display
# =========================================================================

_DIM = "\033[2m"
_RST = "\033[0m"


def cprint(text: str) -> None:
    """Print ANSI-colored text through prompt_toolkit's renderer."""
    _pt_print(_PT_ANSI(text))


# =========================================================================
# ASCII Art & Branding
# =========================================================================

# Ink TUI default banner (frontend/tui/src/content/pixelLogo.ts — ECTOR_ASCII_LINES).
ECTOR_ASCII_LINES: Tuple[str, ...] = (
    "╭─╴   ╭─╴   ╶┬╴   ╭─╮   ╭─╮",
    "├╴    │      │    │ │   ├┬╯",
    "╰─╴   ╰─╴    ╵    ╰─╯   ╵╰╴",
)

# Dashboard dark theme — matches frontend/tui/src/theme.ts (WEB_FG / WEB_ACCENT).
_TUI_BANNER_EDGE = "#EEEBE7"
_TUI_BANNER_PEAK = "#EEEBE7"
_TUI_DIM = "#C5BFB9"
_TUI_WARN = "#F59E0B"

_ANSI_ESCAPE_RE = re.compile(r"\033\[[0-9;]*m")


# =========================================================================
# Skills scanning
# =========================================================================


def get_available_skills() -> Dict[str, List[str]]:
    """Return skills grouped by category, filtered by platform and disabled state."""
    try:
        from tools.skills_tool import _find_all_skills

        all_skills = _find_all_skills()
    except Exception:
        return {}

    skills_by_category: Dict[str, List[str]] = {}
    for skill in all_skills:
        category = skill.get("category") or "general"
        skills_by_category.setdefault(category, []).append(skill["name"])
    return skills_by_category


# =========================================================================
# Update check
# =========================================================================


_UPDATE_CHECK_CACHE_SECONDS = 6 * 3600
_DEFAULT_UPSTREAM = ("origin", "main")


def _resolve_git_upstream(repo_dir: Path) -> tuple[str, str]:
    """Return ``(remote, branch)`` for the tracking branch, else origin/main."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
    except (OSError, subprocess.TimeoutExpired):
        return _DEFAULT_UPSTREAM
    if result.returncode != 0:
        return _DEFAULT_UPSTREAM
    upstream = (result.stdout or "").strip()
    if "/" not in upstream:
        return _DEFAULT_UPSTREAM
    remote, branch = upstream.split("/", 1)
    if not remote or not branch:
        return _DEFAULT_UPSTREAM
    return remote, branch


def get_cached_update_upstream_label() -> str:
    """Human-readable upstream label from the last update check cache."""
    cache_file = get_ector_home() / ".update_check"
    try:
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            label = cached.get("upstream")
            if isinstance(label, str) and label.strip():
                return label.strip()
    except Exception:
        pass
    return "origin/main"


def check_for_updates(*, force_refresh: bool = False) -> Optional[int]:
    """Check how many commits behind the tracking branch the local repo is.

    Does a ``git fetch`` at most once every 6 hours (cached to
    ``ECTOR_HOME/.update_check``).  Returns the number of commits behind, or
    ``None`` if the check fails.  Does not refresh the cache when ``fetch``
    fails (avoids freezing a stale count).

    Pass ``force_refresh=True`` from ``ector update`` so a stale cached
    ``behind=0`` does not skip a newly published release.
    """
    from ector_cli.install_paths import resolve_install_dir

    repo_dir = resolve_install_dir()
    if repo_dir is None:
        return None

    cache_file = get_ector_home() / ".update_check"

    now = time.time()
    if not force_refresh:
        try:
            if cache_file.exists():
                cached = json.loads(cache_file.read_text())
                if now - cached.get("ts", 0) < _UPDATE_CHECK_CACHE_SECONDS:
                    behind = cached.get("behind")
                    if behind is None or isinstance(behind, int):
                        return behind
        except Exception:
            pass

    remote, branch = _resolve_git_upstream(repo_dir)
    upstream_label = f"{remote}/{branch}"

    fetch_ok = False
    try:
        fetch_result = subprocess.run(
            ["git", "fetch", remote, "--quiet"],
            capture_output=True,
            timeout=10,
            cwd=str(repo_dir),
        )
        fetch_ok = fetch_result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        fetch_ok = False

    if not fetch_ok:
        return None

    behind: Optional[int]
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..{remote}/{branch}"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
        behind = int(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        behind = None

    if behind is not None:
        try:
            cache_file.write_text(
                json.dumps({"ts": now, "behind": behind, "upstream": upstream_label})
            )
        except Exception:
            pass

    return behind


def _resolve_repo_dir() -> Optional[Path]:
    """Return the active ECTOR git checkout, or None if this isn't a git install."""
    from ector_cli.install_paths import resolve_install_dir

    return resolve_install_dir()


_RELEASE_URL_BASE = "https://ector.cc/releases/tag"
_latest_release_cache: Optional[tuple] = None  # (tag, url)


def get_latest_release_tag(repo_dir: Optional[Path] = None) -> Optional[tuple]:
    """Return (tag, release_url) for the latest git tag, or None."""
    global _latest_release_cache
    if _latest_release_cache is not None:
        return _latest_release_cache or None

    repo_dir = repo_dir or _resolve_repo_dir()
    if repo_dir is None:
        _latest_release_cache = ()
        return None

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=str(repo_dir),
        )
    except Exception:
        _latest_release_cache = ()
        return None

    if result.returncode != 0:
        _latest_release_cache = ()
        return None

    tag = (result.stdout or "").strip()
    if not tag:
        _latest_release_cache = ()
        return None

    url = f"{_RELEASE_URL_BASE}/{tag}"
    _latest_release_cache = (tag, url)
    return _latest_release_cache


def format_version_label() -> str:
    """Version line aligned with the Ink TUI (``formatBannerVersion``)."""
    from ector_cli.install_paths import running_version_label

    return running_version_label()


def _parse_hex_color(value: str) -> Optional[Tuple[int, int, int]]:
    match = re.match(r"^#?([0-9a-f]{6})$", (value or "").strip(), re.IGNORECASE)
    if not match:
        return None
    number = int(match.group(1), 16)
    return (number >> 16) & 0xFF, (number >> 8) & 0xFF, number & 0xFF


def _mix_hex_color(left: str, right: str, ratio: float) -> str:
    channel_a = _parse_hex_color(left)
    channel_b = _parse_hex_color(right)
    if not channel_a or not channel_b:
        return left if ratio < 0.5 else right
    blend = max(0.0, min(1.0, ratio))
    mixed = tuple(
        round(channel_a[i] + (channel_b[i] - channel_a[i]) * blend) for i in range(3)
    )
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def _reflect_banner_color(edge: str, peak: str, position: float) -> str:
    mirror = 1.0 - abs(2.0 * max(0.0, min(1.0, position)) - 1.0)
    soft = mirror**2
    blue_gray = _mix_hex_color(edge, peak, 0.38)
    return _mix_hex_color(edge, blue_gray, soft * 0.52)


def _truecolor_fg(hex_color: str) -> str:
    rgb = _parse_hex_color(hex_color)
    if rgb is None:
        return ""
    red, green, blue = rgb
    return f"\033[1m\033[38;2;{red};{green};{blue}m"


def paint_tui_banner_lines(
    lines: Sequence[str] = ECTOR_ASCII_LINES,
    edge: str = _TUI_BANNER_EDGE,
    peak: str = _TUI_BANNER_PEAK,
) -> List[str]:
    """Paint the TUI pixel logo with the same gradient as ``paintBannerGradient``."""
    trimmed = [line.rstrip() for line in lines]
    max_width = max((len(line) for line in trimmed), default=1)
    painted: List[str] = []
    for line in trimmed:
        out: List[str] = []
        for col, char in enumerate(line):
            if char == " ":
                out.append(" ")
                continue
            position = 0.0 if max_width <= 1 else col / (max_width - 1)
            color = edge if edge == peak else _reflect_banner_color(edge, peak, position)
            out.append(f"{_truecolor_fg(color)}{char}{_RST}")
        painted.append("".join(out))
    return painted


def _visible_text_width(text: str) -> int:
    return len(_ANSI_ESCAPE_RE.sub("", text))


def _center_ansi_line(line: str, width: int) -> str:
    pad = max(0, (width - _visible_text_width(line)) // 2)
    return (" " * pad) + line


def _optional_update_row() -> Optional[Tuple[str, str]]:
    """Return an update row only when a newer release is available."""
    try:
        behind = check_for_updates()
    except Exception:
        return None
    if not behind or behind <= 0:
        return None

    from ector_cli.config import recommended_update_command

    command = recommended_update_command()
    return (
        "Atualização",
        f"Disponível — execute [bold]{command}[/]",
    )


def print_version_screen() -> None:
    """Print a TUI-aligned version screen (``ector version`` / ``--version``)."""
    console = Console(highlight=False)
    width = shutil.get_terminal_size((80, 24)).columns

    console.print()
    for line in paint_tui_banner_lines():
        # Raw stdout avoids Rich soft-wrap breaking the pixel logo mid-line.
        sys.stdout.write(_center_ansi_line(line, width) + "\n")
    sys.stdout.flush()

    console.print()
    console.print(
        f"[{_TUI_DIM}]{format_version_label()}[/]",
        justify="center",
    )

    update_row = _optional_update_row()
    if update_row:
        console.print()
        console.print(f"[{_TUI_WARN}]{update_row[1]}[/]", justify="center")

    console.print()


_update_result: Optional[int] = None
_update_check_done = threading.Event()


def prefetch_update_check() -> None:
    """Kick off update check in a background daemon thread."""

    def _run() -> None:
        global _update_result
        _update_result = check_for_updates()
        _update_check_done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def get_update_result(timeout: float = 0.5) -> Optional[int]:
    """Get result of prefetched check. Returns None if not ready."""
    _update_check_done.wait(timeout=timeout)
    return _update_result


# =========================================================================
# Formatters
# =========================================================================


def _format_context_length(tokens: int) -> str:
    """Format a token count for display (e.g. 128000 → '128K', 1048576 → '1M')."""
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}M"
        return f"{val:.1f}M"
    if tokens >= 1_000:
        val = tokens / 1_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}K"
        return f"{val:.1f}K"
    return str(tokens)

