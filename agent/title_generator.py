"""Auto-generate short session titles from user/assistant exchanges.

Runs asynchronously after a completed turn so it never adds latency to the
user-facing reply. Titles are set after the first meaningful exchange and
refreshed after each subsequent one so the label tracks how the thread evolves.
"""

import logging
import re
import threading
from typing import Callable, Optional

from agent.auxiliary_client import call_llm

logger = logging.getLogger(__name__)

_MIN_USER_CHARS = 3
_MIN_ASSISTANT_CHARS = 12

# Callback signature: (task_name, exception) -> None. Used to surface
# auxiliary failures to the user through AIAgent._emit_auxiliary_failure
# so silent-drops (e.g. OpenRouter 402 exhausting the fallback chain)
# become visible instead of piling up as NULL session titles.
FailureCallback = Callable[[str, BaseException], None]
TitleCallback = Callable[[str], None]

_TITLE_PROMPT = (
    "Generate a short, descriptive chat title (3-8 words) for the conversation below. "
    "Capture the user's main goal or topic as it stands now — not the assistant's boilerplate. "
    "When multiple turns are shown, reflect the latest direction of the thread, not only the opener. "
    "Prefer concrete nouns/tasks over vague words like 'help', 'question', or 'assistance'. "
    "Write the title in the same language as the user's messages. Do not translate to English. "
    "If the user writes in Portuguese, the title must be in Portuguese. "
    "Return ONLY the title text: no quotes, no markdown, no trailing period, no 'Title:' prefix."
)

_TITLE_CONTEXT_MAX_CHARS = 2400
_TITLE_CONTEXT_MAX_TURNS = 6

_SLASH_ONLY_RE = re.compile(r"^/[a-z0-9_-]+$", re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"[*_`#]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_title(raw: str) -> Optional[str]:
    """Normalize model output into a safe session title."""
    title = (raw or "").strip()
    if not title:
        return None
    title = _MARKDOWN_RE.sub("", title)
    for prefix in ("title:", "título:", "titulo:"):
        if title.lower().startswith(prefix):
            title = title[len(prefix) :].strip()
    for _ in range(3):
        title = title.strip("\"'“”‘’").strip()
    title = _WHITESPACE_RE.sub(" ", title).strip(" .…")
    if not title:
        return None
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title


def _message_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")).strip())
        return " ".join(p for p in parts if p).strip()
    return str(content or "").strip()


def _recent_exchange_snippet(
    conversation_history: list | None,
    user_message: str,
    assistant_response: str,
    *,
    max_chars: int = _TITLE_CONTEXT_MAX_CHARS,
    max_turns: int = _TITLE_CONTEXT_MAX_TURNS,
) -> str:
    """Compact recent transcript for title generation."""
    turns: list[tuple[str, str]] = []
    pending_user: str | None = None

    for msg in conversation_history or []:
        role = msg.get("role")
        text = _message_text(msg.get("content"))
        if not text:
            continue
        if role == "user":
            pending_user = text
        elif role == "assistant" and pending_user is not None:
            turns.append((pending_user, text))
            pending_user = None

    user_text = (user_message or "").strip()
    assistant_text = (assistant_response or "").strip()
    if user_text and assistant_text:
        if not turns or turns[-1] != (user_text, assistant_text):
            turns.append((user_text, assistant_text))

    if not turns and user_text:
        return f"User: {user_text[:500]}"

    lines: list[str] = []
    for index, (user, assistant) in enumerate(turns[-max_turns:], start=1):
        lines.append(
            f"Turn {index} — User: {user[:400]}\nAssistant: {assistant[:400]}"
        )

    body = "\n\n".join(lines)
    if len(body) > max_chars:
        body = body[-max_chars:].lstrip()
    return body


def fallback_title_from_user_message(user_message: str, *, max_len: int = 56) -> Optional[str]:
    """Heuristic title when the auxiliary model is unavailable."""
    text = (user_message or "").strip()
    if not text or len(text) < _MIN_USER_CHARS:
        return None
    if _SLASH_ONLY_RE.match(text):
        return None
    first_line = text.splitlines()[0].strip()
    clause = re.split(r"[.!?\n]", first_line, maxsplit=1)[0].strip()
    normalized = clause.strip("\"'“”‘’")
    if not normalized or len(normalized) < _MIN_USER_CHARS:
        return None
    if len(normalized) <= max_len:
        return normalized
    truncated = normalized[: max_len - 3].rsplit(" ", 1)[0].strip()
    return (truncated or normalized[: max_len - 3]).rstrip() + "..."


def generate_title(
    user_message: str,
    assistant_response: str,
    conversation_history: list | None = None,
    timeout: float = 30.0,
    failure_callback: Optional[FailureCallback] = None,
) -> Optional[str]:
    """Generate a session title from recent conversation context.

    Uses the auxiliary LLM client (cheapest/fastest available model).
    Returns the title string or None on failure.

    ``failure_callback`` is invoked with ``(task, exception)`` when the
    auxiliary call raises — the caller typically wires this to
    ``AIAgent._emit_auxiliary_failure`` so the user sees a warning instead
    of silently accumulating untitled sessions.
    """
    transcript = _recent_exchange_snippet(
        conversation_history, user_message, assistant_response
    )

    messages = [
        {"role": "system", "content": _TITLE_PROMPT},
        {"role": "user", "content": transcript},
    ]

    try:
        response = call_llm(
            task="title_generation",
            messages=messages,
            max_tokens=500,
            temperature=0.3,
            timeout=timeout,
        )
        title = _sanitize_title(response.choices[0].message.content or "")
        if title:
            return title
    except Exception as e:
        # Log at WARNING so this shows up in agent.log without debug mode.
        # Full detail at debug level for operators who need the stack.
        logger.warning("Title generation failed: %s", e)
        logger.debug("Title generation traceback", exc_info=True)
        if failure_callback is not None:
            try:
                failure_callback("title generation", e)
            except Exception:
                logger.debug("Title generation failure_callback raised", exc_info=True)
    return fallback_title_from_user_message(user_message)


def count_user_messages(conversation_history: list | None) -> int:
    """Count user-role messages in an OpenAI-style message list."""
    return sum(1 for m in (conversation_history or []) if m.get("role") == "user")


def is_meaningful_exchange(user_message: str, assistant_response: str) -> bool:
    """Return True when both sides look like a real chat turn (not noise)."""
    user_text = (user_message or "").strip()
    assistant_text = (assistant_response or "").strip()
    if len(user_text) < _MIN_USER_CHARS or len(assistant_text) < _MIN_ASSISTANT_CHARS:
        return False
    if _SLASH_ONLY_RE.match(user_text):
        return False
    return True


def auto_title_session(
    session_db,
    session_id: str,
    user_message: str,
    assistant_response: str,
    conversation_history: list | None = None,
    failure_callback: Optional[FailureCallback] = None,
    title_callback: Optional[TitleCallback] = None,
    *,
    allow_overwrite: bool = False,
) -> None:
    """Generate and set a session title.

    Called in a background thread after a qualifying exchange completes.
    Silently skips if:
    - session_db is None
    - a title already exists and ``allow_overwrite`` is False
    - title generation fails
    """
    if not session_db or not session_id:
        return

    try:
        if session_db.is_session_title_user_set(session_id):
            return
        existing = session_db.get_session_title(session_id)
        if existing and not allow_overwrite:
            return
    except Exception:
        return

    title = generate_title(
        user_message,
        assistant_response,
        conversation_history=conversation_history,
        failure_callback=failure_callback,
    )
    if not title:
        title = fallback_title_from_user_message(user_message)
    if not title:
        return

    try:
        if session_db.is_session_title_user_set(session_id):
            return
        if not session_db.set_session_title(session_id, title):
            return
        logger.debug(
            "Auto-generated session title: %s (overwrite=%s)", title, allow_overwrite
        )
        if title_callback is not None:
            try:
                title_callback(title)
            except Exception:
                logger.debug("Title generation title_callback raised", exc_info=True)
    except Exception as e:
        logger.debug("Failed to set auto-generated title: %s", e)


def maybe_auto_title(
    session_db,
    session_id: str,
    user_message: str,
    assistant_response: str,
    conversation_history: list,
    failure_callback: Optional[FailureCallback] = None,
    title_callback: Optional[TitleCallback] = None,
) -> Optional[threading.Thread]:
    """Fire-and-forget title generation after a qualifying exchange.

    Sets a title after the first meaningful user→assistant exchange, then
    refreshes it after each later meaningful turn so the label follows the
    thread. Skips empty/noisy turns.
    """
    if not session_db or not session_id:
        return None
    if not is_meaningful_exchange(user_message, assistant_response):
        return None

    user_msg_count = count_user_messages(conversation_history)
    if user_msg_count < 1:
        return None

    allow_overwrite = user_msg_count > 1

    thread = threading.Thread(
        target=auto_title_session,
        args=(session_db, session_id, user_message, assistant_response),
        kwargs={
            "conversation_history": conversation_history,
            "failure_callback": failure_callback,
            "title_callback": title_callback,
            "allow_overwrite": allow_overwrite,
        },
        daemon=True,
        name="auto-title",
    )
    thread.start()
    return thread
