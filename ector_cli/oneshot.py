"""Oneshot (-z) mode: send a prompt, get the final content block, exit.

Bypasses cli.py entirely.  No banner, no session_id line.
Stdout receives only the agent's final text; stderr shows a single-line
spinner with the current tool preview while the agent works.

Toolsets = whatever the user has configured for "cli" in `ector tools`.
Rules / memory / AGENTS.md / preloaded skills = same as a normal chat turn.
Approvals = auto-bypassed (ECTOR_YOLO_MODE=1 is set for the call).
Working directory = the user's CWD (AGENTS.md etc. resolve from there as usual).

Model / provider selection mirrors `ector chat`:
    - Both optional. If omitted, use the user's configured default.
    - If both given, pair them exactly as given.
    - If only --model given, auto-detect the provider that serves it.
    - If only --provider given, error out (ambiguous — caller must pick a model).

Env var fallbacks (used when the corresponding arg is not passed):
    - ECTOR_INFERENCE_MODEL
    - ECTOR_INFERENCE_PROVIDER  (already read by resolve_runtime_provider)
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from contextlib import redirect_stdout
from typing import Any, Optional, TextIO

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_DEFAULT_PREVIEW = "Pensando…"
_FALLBACK_TERMINAL_WIDTH = 80
_CODE_HINTS = (
    "import ",
    "def ",
    "print(",
    "class ",
    "return ",
    "from ",
    "datetime",
    "timezone",
    "strftime",
)


def _terminal_columns(stream: TextIO) -> int:
    try:
        fd = stream.fileno()
        return max(int(os.get_terminal_size(fd).columns), 20)
    except (OSError, ValueError, AttributeError):
        try:
            return max(int(os.get_terminal_size().columns), 20)
        except OSError:
            return _FALLBACK_TERMINAL_WIDTH


def _sanitize_preview(text: str, *, max_len: int = 200) -> str:
    cleaned = re.sub(r"\*\*", "", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned.replace("\n", " ")).strip()
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1] + "…"
    return cleaned


def _looks_like_code(text: str) -> bool:
    if not text:
        return False
    if text.count("=") >= 2 and text.count("(") >= 2:
        return True
    if text.count(";") >= 1 and any(h in text for h in _CODE_HINTS):
        return True
    return any(h in text for h in _CODE_HINTS)


def _display_preview(
    tool_name: str | None,
    preview: str | None,
    *,
    width: int,
) -> str:
    raw = _sanitize_preview(preview or "")
    if not raw:
        return _DEFAULT_PREVIEW

    name = (tool_name or "").lower()
    if _looks_like_code(raw):
        if name == "execute_code":
            return "Executando código…"
        if name == "terminal":
            return "Comando no terminal…"
        return "Trabalhando…"

    budget = max(width - 2, 16)
    if len(raw) > budget:
        raw = raw[: budget - 1] + "…"
    from agent.display import polish_activity_label

    return polish_activity_label(raw)


def _format_spinner_line(frame: str, message: str, width: int) -> str:
    """Build a fixed-width line so ``\\r`` overwrites always clear the row."""
    budget = max(width - 2, 10)
    text = message
    if len(text) > budget:
        text = text[: budget - 1] + "…"
    line = f"{frame} {text}"
    if len(line) < width:
        return line + (" " * (width - len(line)))
    return line[:width]


class _OneshotLineSpinner:
    """Single-line braille spinner written to stderr."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._message = _DEFAULT_PREVIEW
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame_idx = 0
        self._width = _terminal_columns(stream)
        self._lock = threading.Lock()
        self._last_non_tty_preview: str | None = None

    @property
    def _is_tty(self) -> bool:
        try:
            return hasattr(self._stream, "isatty") and self._stream.isatty()
        except (ValueError, OSError):
            return False

    def start(self, message: str) -> None:
        with self._lock:
            self._message = message
            self._width = _terminal_columns(self._stream)
        if self._running:
            return
        self._running = True
        if not self._is_tty:
            self._write_non_tty(message)
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update(self, message: str) -> None:
        with self._lock:
            self._message = message
            self._width = _terminal_columns(self._stream)
        if not self._is_tty:
            self._write_non_tty(message)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
        if self._is_tty:
            width = max(self._width, 1)
            try:
                self._stream.write("\r" + (" " * width) + "\r")
                self._stream.flush()
            except (ValueError, OSError):
                pass
        self._last_non_tty_preview = None

    def _write_non_tty(self, message: str) -> None:
        if message == self._last_non_tty_preview:
            return
        self._last_non_tty_preview = message
        try:
            self._stream.write(message + "\n")
            self._stream.flush()
        except (ValueError, OSError):
            pass

    def _animate(self) -> None:
        if not self._is_tty:
            while self._running:
                time.sleep(0.2)
            return

        while self._running:
            with self._lock:
                message = self._message
                width = self._width
            frame = _SPINNER_FRAMES[self._frame_idx % len(_SPINNER_FRAMES)]
            line = _format_spinner_line(frame, message, width)
            try:
                self._stream.write("\r" + line)
                self._stream.flush()
            except (ValueError, OSError):
                return
            self._frame_idx += 1
            time.sleep(0.12)


class OneshotProgressReporter:
    """Show a single stderr line with spinner + current tool preview."""

    def __init__(self, stream: Optional[TextIO] = None) -> None:
        self._stream = stream or sys.stderr
        self._spinner = _OneshotLineSpinner(self._stream)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._spinner.start(_DEFAULT_PREVIEW)

    def finish(self) -> None:
        if not self._started:
            return
        self._started = False
        self._spinner.stop()

    def _set_preview(self, tool_name: str | None, text: str | None) -> None:
        width = _terminal_columns(self._stream)
        preview = _display_preview(tool_name, text, width=width)
        if not preview:
            return
        if not self._started:
            self.start()
        self._spinner.update(preview)

    def on_tool_progress(
        self,
        event_type: str,
        function_name: str | None = None,
        preview: str | None = None,
        function_args: dict | None = None,
        **kwargs: Any,
    ) -> None:
        del function_args, kwargs
        if event_type == "tool.started":
            self._set_preview(function_name, preview)
            return
        if event_type in ("reasoning.available", "_thinking"):
            self._set_preview(function_name, preview)

    def on_tool_generating(self, tool_name: str) -> None:
        del tool_name

    def on_status(self, kind: str, message: str | None = None) -> None:
        del kind
        if message:
            self._set_preview(None, message)


def _prepare_oneshot_prompt(
    prompt: str, image: Optional[str] = None
) -> tuple[str, Optional[int]]:
    """Resolve optional ``--image`` and enrich the user message (vision pre-pass).

    Returns ``(message, error_code)``; ``error_code`` is set on validation failure.
    """
    from ector_cli.attachments import collect_query_images as _collect_query_images

    try:
        message, image_paths = _collect_query_images(prompt or None, image)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return "", 2

    if not image_paths:
        return message or "", None

    from ector_cli.attachments import enrich_with_attached_images as _enrich_with_attached_images

    return (
        _enrich_with_attached_images(message, [str(p) for p in image_paths]),
        None,
    )


def run_oneshot(
    prompt: str,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    image: Optional[str] = None,
) -> int:
    """Execute a single prompt and print only the final content block.

    Args:
        prompt: The user message to send.
        model: Optional model override. Falls back to ECTOR_INFERENCE_MODEL
            env var, then config.yaml's model.default / model.model.
        provider: Optional provider override. Falls back to
            ECTOR_INFERENCE_PROVIDER env var, then config.yaml's model.provider,
            then "auto".
        image: Optional local image path (``ector chat --image``).

    Returns the exit code.  Caller should sys.exit() with the return.
    """
    effective_prompt, prep_err = _prepare_oneshot_prompt(prompt, image)
    if prep_err is not None:
        return prep_err

    if not (effective_prompt or "").strip():
        sys.stderr.write("ector: prompt or --image required.\n")
        return 2

    # Silence every stdlib logger for the duration.  File handlers from
    # setup_logging() keep working; no log bytes reach the terminal.
    logging.disable(logging.CRITICAL)

    # --provider without --model is ambiguous: carrying the user's configured
    # model across to a different provider is usually wrong (that provider may
    # not host it), and silently picking the provider's catalog default hides
    # the mismatch.  Require the caller to be explicit.  Validate BEFORE the
    # stdout redirect so the message actually reaches the terminal.
    env_model_early = os.getenv("ECTOR_INFERENCE_MODEL", "").strip()
    if provider and not ((model or "").strip() or env_model_early):
        sys.stderr.write(
            "ector -z: --provider requires --model (or ECTOR_INFERENCE_MODEL). "
            "Pass both explicitly, or neither to use your configured defaults.\n"
        )
        return 2

    # Auto-approve any shell / tool approvals.  Non-interactive by
    # definition — a prompt would hang forever.
    os.environ["ECTOR_YOLO_MODE"] = "1"
    os.environ["ECTOR_ACCEPT_HOOKS"] = "1"

    real_stdout = sys.stdout
    progress_reporter = OneshotProgressReporter()
    devnull = open(os.devnull, "w")

    try:
        progress_reporter.start()
        with redirect_stdout(devnull):
            response = _run_agent(
                effective_prompt,
                progress_reporter,
                model=model,
                provider=provider,
            )
    finally:
        try:
            devnull.close()
        except Exception:
            pass
        progress_reporter.finish()

    if response:
        from gateway.platforms.helpers import strip_markdown

        response = strip_markdown(response)
        real_stdout.write(response)
        if not response.endswith("\n"):
            real_stdout.write("\n")
        real_stdout.flush()
    return 0


def _run_agent(
    prompt: str,
    progress: OneshotProgressReporter,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> str:
    """Build an AIAgent exactly like a normal CLI chat turn would, then
    run a single conversation.  Returns the final response string."""
    # Imports are local so they don't run when ector is invoked for
    # other commands (keeps top-level CLI startup cheap).
    from ector_cli.config import load_config
    from ector_cli.models import detect_provider_for_model
    from ector_cli.runtime_provider import resolve_runtime_provider
    from ector_cli.tools_config import _get_platform_tools
    from run_agent import AIAgent

    cfg = load_config()

    # Resolve effective model: explicit arg → env var → config.
    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, str):
        cfg_model = model_cfg
    else:
        cfg_model = model_cfg.get("default") or model_cfg.get("model") or ""

    env_model = os.getenv("ECTOR_INFERENCE_MODEL", "").strip()
    effective_model = (model or "").strip() or env_model or cfg_model

    # Resolve effective provider: explicit arg → (auto-detect from model if
    # model was explicit) → env / config (handled inside resolve_runtime_provider).
    #
    # When --model is given without --provider, auto-detect the provider that
    # serves that model — same semantic as `/provider <name>` in an interactive
    # session.  Without this, resolve_runtime_provider() would fall back to
    # the user's configured default provider, which may not host the model
    # the caller just asked for.
    effective_provider = (provider or "").strip() or None
    if effective_provider is None and (model or env_model):
        # Only auto-detect when the model was explicitly requested via arg or
        # env var (not when it came from config — that's the "use my defaults"
        # path and the configured provider is already correct).
        explicit_model = (model or "").strip() or env_model
        if explicit_model:
            cfg_provider = ""
            if isinstance(model_cfg, dict):
                cfg_provider = str(model_cfg.get("provider") or "").strip().lower()
            current_provider = (
                cfg_provider
                or os.getenv("ECTOR_INFERENCE_PROVIDER", "").strip().lower()
                or "auto"
            )
            detected = detect_provider_for_model(explicit_model, current_provider)
            if detected:
                effective_provider, effective_model = detected

    runtime = resolve_runtime_provider(
        requested=effective_provider,
        target_model=effective_model or None,
    )

    # Pull in whatever toolsets the user has enabled for "cli".
    # sorted() gives stable ordering; set→list for AIAgent's signature.
    toolsets_list = sorted(_get_platform_tools(cfg, "cli"))

    agent = AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=effective_model,
        enabled_toolsets=toolsets_list,
        quiet_mode=True,
        platform="cli",
        credential_pool=runtime.get("credential_pool"),
        tool_progress_callback=progress.on_tool_progress,
        tool_gen_callback=progress.on_tool_generating,
        status_callback=progress.on_status,
        wiser_callback=_oneshot_wiser_callback,
    )

    # Belt-and-braces: make sure AIAgent doesn't invoke any streaming
    # display callbacks that would bypass our stdout capture.
    agent.suppress_status_output = True
    agent.stream_delta_callback = None

    return agent.chat(prompt) or ""


def _oneshot_wiser_callback(question: str, choices=None) -> str:
    """Wiser (wiser) is disabled in oneshot mode — tell the agent to pick a
    default and proceed instead of stalling or erroring."""
    if choices:
        return (
            f"[oneshot mode: no user available. Pick the best option from "
            f"{choices} using your own judgment and continue.]"
        )
    return (
        "[oneshot mode: no user available. Make the most reasonable "
        "assumption you can and continue.]"
    )
