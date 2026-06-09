"""Blocking Wiser prompts for the messaging gateway (mirrors tools/approval.py)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Callable, Optional

from tools.wiser_tool import WISER_USER_TIMEOUT

logger = logging.getLogger(__name__)

_lock = threading.Lock()


class _WiserEntry:
    __slots__ = ("event", "data", "result")

    def __init__(self, data: dict):
        self.event = threading.Event()
        self.data = data
        self.result: Optional[str] = None


_gateway_queues: dict[str, list] = {}
_gateway_notify_cbs: dict[str, Callable] = {}


def register_gateway_wiser_notify(session_key: str, cb: Callable) -> None:
    """Register ``cb(data)`` to send a Wiser question to the user (sync, agent thread)."""
    with _lock:
        _gateway_notify_cbs[session_key] = cb


def unregister_gateway_wiser_notify(session_key: str) -> None:
    """Unregister notify callback and unblock any waiting Wiser threads."""
    with _lock:
        _gateway_notify_cbs.pop(session_key, None)
        entries = _gateway_queues.pop(session_key, [])
        for entry in entries:
            entry.result = WISER_USER_TIMEOUT
            entry.event.set()


def resolve_gateway_wiser(session_key: str, answer: str) -> int:
    """Unblock the oldest pending Wiser prompt for *session_key*. Returns count resolved."""
    with _lock:
        queue = _gateway_queues.get(session_key)
        if not queue:
            return 0
        entry = queue.pop(0)
        if not queue:
            _gateway_queues.pop(session_key, None)
    entry.result = answer
    entry.event.set()
    return 1


def has_blocking_wiser(session_key: str) -> bool:
    with _lock:
        return bool(_gateway_queues.get(session_key))


def peek_blocking_wiser(session_key: str) -> Optional[dict]:
    """Return the oldest pending Wiser payload (question, choices, request_id)."""
    with _lock:
        queue = _gateway_queues.get(session_key)
        if not queue:
            return None
        return dict(queue[0].data)


def format_wiser_prompt_text(question: str, choices: Optional[list]) -> str:
    """Plain-text Wiser prompt for platforms without button UI."""
    lines = ["**Wiser** — preciso da sua escolha:", "", question.strip(), ""]
    if choices:
        for i, c in enumerate(choices, 1):
            lines.append(f"{i}. {c}")
        lines.append(f"{len(choices) + 1}. Outro (responda com texto livre)")
        lines.append("")
        lines.append(
            "Responda com o número da opção ou escreva sua resposta em texto livre."
        )
    else:
        lines.append("Responda em texto livre.")
    return "\n".join(lines)


def parse_wiser_reply(text: str, choices: Optional[list]) -> str:
    """Map user reply to a choice label or free text."""
    raw = (text or "").strip()
    if not raw:
        return raw
    if not choices:
        return raw
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
        if idx == len(choices) + 1:
            return raw
    return raw


def make_gateway_wiser_callback(
    session_key: str,
    timeout: int,
    touch_activity: Optional[Callable] = None,
) -> Callable[[str, Optional[list]], str]:
    """Return ``(question, choices) -> str`` for ``AIAgent.wiser_callback``."""

    def _callback(question: str, choices: Optional[list] = None) -> str:
        notify_cb = None
        with _lock:
            notify_cb = _gateway_notify_cbs.get(session_key)

        if notify_cb is None:
            return WISER_USER_TIMEOUT

        request_id = uuid.uuid4().hex[:8]
        data = {
            "question": question,
            "choices": choices,
            "request_id": request_id,
        }
        entry = _WiserEntry(data)
        with _lock:
            _gateway_queues.setdefault(session_key, []).append(entry)

        try:
            notify_cb(data)
        except Exception as exc:
            logger.warning("Gateway Wiser notify failed: %s", exc)
            with _lock:
                queue = _gateway_queues.get(session_key, [])
                if entry in queue:
                    queue.remove(entry)
                if not queue:
                    _gateway_queues.pop(session_key, None)
            return WISER_USER_TIMEOUT

        deadline = time.monotonic() + max(int(timeout), 0)
        activity_state = {"last_touch": time.monotonic(), "start": time.monotonic()}
        resolved = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if entry.event.wait(timeout=min(1.0, remaining)):
                resolved = True
                break
            if touch_activity is not None:
                try:
                    touch_activity(activity_state, "waiting for Wiser answer")
                except Exception:
                    pass

        with _lock:
            queue = _gateway_queues.get(session_key, [])
            if entry in queue:
                queue.remove(entry)
            if not queue:
                _gateway_queues.pop(session_key, None)

        if not resolved or entry.result is None:
            return WISER_USER_TIMEOUT
        return str(entry.result)

    return _callback
