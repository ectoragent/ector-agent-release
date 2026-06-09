"""Shared helper classes for gateway platform adapters.

Extracts common patterns that were duplicated across 5-7 adapters:
message deduplication, text batch aggregation, markdown stripping,
and thread participation tracking.
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from gateway.platforms.base import BasePlatformAdapter, MessageEvent

logger = logging.getLogger(__name__)


# ─── Message Deduplication ────────────────────────────────────────────────────


class MessageDeduplicator:
    """TTL-based message deduplication cache.

    Replaces the identical ``_seen_messages`` / ``_is_duplicate()`` pattern
    previously duplicated in discord, slack, dingtalk, wecom, weixin,
    mattermost, and feishu adapters.

    Usage::

        self._dedup = MessageDeduplicator()

        # In message handler:
        if self._dedup.is_duplicate(msg_id):
            return
    """

    def __init__(self, max_size: int = 2000, ttl_seconds: float = 300):
        self._seen: Dict[str, float] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def is_duplicate(self, msg_id: str) -> bool:
        """Return True if *msg_id* was already seen within the TTL window."""
        if not msg_id:
            return False
        now = time.time()
        if msg_id in self._seen:
            if now - self._seen[msg_id] < self._ttl:
                return True
            # Entry has expired — remove it and treat as new
            del self._seen[msg_id]
        self._seen[msg_id] = now
        if len(self._seen) > self._max_size:
            cutoff = now - self._ttl
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
            if len(self._seen) > self._max_size:
                # TTL pruning alone does not cap the cache when every entry is
                # still fresh. Keep the newest entries so the helper's
                # max_size bound is enforced under sustained traffic.
                newest = sorted(
                    self._seen.items(),
                    key=lambda item: item[1],
                )[-self._max_size:]
                self._seen = dict(newest)
        return False

    def clear(self):
        """Clear all tracked messages."""
        self._seen.clear()


# ─── Text Batch Aggregation ──────────────────────────────────────────────────


class TextBatchAggregator:
    """Aggregates rapid-fire text events into single messages.

    Replaces the ``_enqueue_text_event`` / ``_flush_text_batch`` pattern
    previously duplicated in telegram, discord, matrix, wecom, and feishu.

    Usage::

        self._text_batcher = TextBatchAggregator(
            handler=self._message_handler,
            batch_delay=0.6,
            split_threshold=1900,
        )

        # In message dispatch:
        if msg_type == MessageType.TEXT and self._text_batcher.is_enabled():
            self._text_batcher.enqueue(event, session_key)
            return
    """

    def __init__(
        self,
        handler,
        *,
        batch_delay: float = 0.6,
        split_delay: float = 2.0,
        split_threshold: int = 4000,
    ):
        self._handler = handler
        self._batch_delay = batch_delay
        self._split_delay = split_delay
        self._split_threshold = split_threshold
        self._pending: Dict[str, "MessageEvent"] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}

    def is_enabled(self) -> bool:
        """Return True if batching is active (delay > 0)."""
        return self._batch_delay > 0

    def enqueue(self, event: "MessageEvent", key: str) -> None:
        """Add *event* to the pending batch for *key*."""
        chunk_len = len(event.text or "")
        existing = self._pending.get(key)
        if not existing:
            event._last_chunk_len = chunk_len  # type: ignore[attr-defined]
            self._pending[key] = event
        else:
            existing.text = f"{existing.text}\n{event.text}"
            existing._last_chunk_len = chunk_len  # type: ignore[attr-defined]

        # Cancel prior flush timer, start a new one
        prior = self._pending_tasks.get(key)
        if prior and not prior.done():
            prior.cancel()
        self._pending_tasks[key] = asyncio.create_task(self._flush(key))

    async def _flush(self, key: str) -> None:
        """Wait then dispatch the batched event for *key*."""
        current_task = self._pending_tasks.get(key)
        pending = self._pending.get(key)
        last_len = getattr(pending, "_last_chunk_len", 0) if pending else 0

        # Use longer delay when the last chunk looks like a split message
        delay = self._split_delay if last_len >= self._split_threshold else self._batch_delay
        await asyncio.sleep(delay)

        event = self._pending.pop(key, None)
        if event:
            try:
                await self._handler(event)
            except Exception:
                logger.exception("[TextBatchAggregator] Error dispatching batched event for %s", key)

        if self._pending_tasks.get(key) is current_task:
            self._pending_tasks.pop(key, None)

    def cancel_all(self) -> None:
        """Cancel all pending flush tasks."""
        for task in self._pending_tasks.values():
            if not task.done():
                task.cancel()
        self._pending_tasks.clear()
        self._pending.clear()


# ─── Markdown Stripping & Table Conversion ───────────────────────────────────

# GFM table delimiter row: optional outer pipes, dash cells separated by '|'.
_TABLE_SEPARATOR_RE = re.compile(
    r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*){1,}\|?\s*$'
)

_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_ITALIC_STAR = re.compile(r"\*(.+?)\*", re.DOTALL)
_RE_BOLD_UNDER = re.compile(r"__(.+?)__", re.DOTALL)
_RE_ITALIC_UNDER = re.compile(r"_(.+?)_", re.DOTALL)
_RE_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_RE_SPOILER = re.compile(r"\|\|(.+?)\|\|", re.DOTALL)
_RE_TILDE = re.compile(r"~([^~]+)~")
_RE_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_RE_CODE_BLOCK_OPEN = re.compile(r"```[a-zA-Z0-9_+-]*\n?")
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_RE_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_RE_MDV2_ESCAPE = re.compile(r'\\([_*\[\]()~`>#+\-=|{}.!\\])')
_RE_MULTI_NEWLINE = re.compile(r"\n{3,}")


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and '|' in stripped


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith('|'):
        stripped = stripped[1:]
    if stripped.endswith('|'):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split('|')]


def _strip_cell_inline_markdown(cell: str) -> str:
    cell = cell.strip()
    cell = re.sub(r'\*\*(.+?)\*\*', r'\1', cell)
    cell = re.sub(r'\*(.+?)\*', r'\1', cell)
    cell = re.sub(r'__([^_]+)__', r'\1', cell)
    cell = re.sub(r'_([^_]+)_', r'\1', cell)
    return cell.strip()


def _format_table_row_as_bullet(row: list[str]) -> str:
    """Render one table row as a bullet key/value line."""
    if len(row) >= 2:
        label = _strip_cell_inline_markdown(row[0])
        rest = [cell.strip() for cell in row[1:]]
        if len(rest) == 1:
            return f'• **{label}:** {rest[0]}'
        joined = ' — '.join(rest)
        return f'• **{label}:** {joined}'
    if row:
        cells = [_strip_cell_inline_markdown(c) for c in row]
        return '• ' + ' — '.join(cells)
    return ''


def _emit_table_rows(rows: list[list[str]], out: list[str]) -> None:
    for row in rows:
        bullet = _format_table_row_as_bullet(row)
        if bullet:
            out.append(bullet)


def _count_consecutive_pipe_rows(lines: list[str], start: int) -> int:
    """Count consecutive pipe rows that are not delimiter separators."""
    count = 0
    j = start
    while j < len(lines) and _is_table_row(lines[j]) and not _TABLE_SEPARATOR_RE.match(lines[j]):
        cells = _split_table_cells(lines[j])
        if len(cells) < 2:
            break
        count += 1
        j += 1
    return count


def convert_markdown_tables(text: str) -> str:
    """Convert GFM pipe tables to bullet key/value lines for chat platforms.

    Telegram, Slack, Discord, WhatsApp and SMS clients do not render GFM
    tables; raw ``| col |`` syntax reads as noisy unparsed markdown.

    Supports standard GFM tables (header + ``|---|---|`` separator) and a
    fallback heuristic for models that omit the separator row.
    """
    if '|' not in text:
        return text

    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith('```'):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        if (
            '|' in line
            and i + 1 < len(lines)
            and _TABLE_SEPARATOR_RE.match(lines[i + 1])
        ):
            i += 2  # skip header and separator
            rows: list[list[str]] = []
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append(_split_table_cells(lines[i]))
                i += 1
            _emit_table_rows(rows, out)
            continue

        # Fallback: 2+ consecutive pipe rows without a separator line.
        run = _count_consecutive_pipe_rows(lines, i)
        if run >= 2:
            rows = [_split_table_cells(lines[j]) for j in range(i, i + run)]
            _emit_table_rows(rows, out)
            i += run
            continue

        out.append(line)
        i += 1

    return '\n'.join(out)


def markdown_to_plain_text(text: str) -> str:
    """Convert markdown (or a partially formatted payload) to clean plain text."""
    if not text:
        return text

    cleaned = _RE_MDV2_ESCAPE.sub(r'\1', text)
    cleaned = convert_markdown_tables(cleaned)

    def _unwrap_fence(m: re.Match) -> str:
        inner = m.group(0)
        inner = re.sub(r'^```[A-Za-z0-9_-]*\n?', '', inner)
        inner = re.sub(r'\n?```$', '', inner)
        return inner.strip('\n')

    cleaned = _RE_CODE_BLOCK.sub(_unwrap_fence, cleaned)
    cleaned = _RE_INLINE_CODE.sub(r'\1', cleaned)
    cleaned = _RE_LINK.sub(r'\1', cleaned)
    cleaned = _RE_BOLD.sub(r'\1', cleaned)
    cleaned = _RE_BOLD_UNDER.sub(r'\1', cleaned)
    cleaned = _RE_STRIKE.sub(r'\1', cleaned)
    cleaned = _RE_SPOILER.sub(r'\1', cleaned)
    cleaned = _RE_ITALIC_STAR.sub(r'\1', cleaned)
    cleaned = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', cleaned)
    cleaned = _RE_TILDE.sub(r'\1', cleaned)
    cleaned = _RE_HEADING.sub('', cleaned)
    cleaned = _RE_BLOCKQUOTE.sub('', cleaned)
    cleaned = _RE_MULTI_NEWLINE.sub('\n\n', cleaned)
    return cleaned.strip()


def strip_markdown(text: str) -> str:
    """Strip markdown formatting for plain-text platforms (SMS, iMessage, etc.).

    Replaces the identical ``_strip_markdown()`` functions previously
    duplicated in sms.py, bluebubbles.py, and feishu.py.
    """
    return markdown_to_plain_text(text)


# ─── Thread Participation Tracking ───────────────────────────────────────────


class ThreadParticipationTracker:
    """Persistent tracking of threads the bot has participated in.

    Replaces the identical ``_load/_save_participated_threads`` +
    ``_mark_thread_participated`` pattern previously duplicated in
    discord.py and matrix.py.

    Usage::

        self._threads = ThreadParticipationTracker("discord")

        # Check membership:
        if thread_id in self._threads:
            ...

        # Mark participation:
        self._threads.mark(thread_id)
    """

    _MAX_TRACKED = 500

    def __init__(self, platform_name: str, max_tracked: int = 500):
        self._platform = platform_name
        self._max_tracked = max_tracked
        self._threads: set = self._load()

    def _state_path(self) -> Path:
        from ector_constants import get_ector_home
        return get_ector_home() / f"{self._platform}_threads.json"

    def _load(self) -> set:
        path = self._state_path()
        if path.exists():
            try:
                return set(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return set()

    def _save(self) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        thread_list = list(self._threads)
        if len(thread_list) > self._max_tracked:
            thread_list = thread_list[-self._max_tracked:]
            self._threads = set(thread_list)
        path.write_text(json.dumps(thread_list), encoding="utf-8")

    def mark(self, thread_id: str) -> None:
        """Mark *thread_id* as participated and persist."""
        if thread_id not in self._threads:
            self._threads.add(thread_id)
            self._save()

    def __contains__(self, thread_id: str) -> bool:
        return thread_id in self._threads

    def clear(self) -> None:
        self._threads.clear()


# ─── Phone Number Redaction ──────────────────────────────────────────────────


def redact_phone(phone: str) -> str:
    """Redact a phone number for logging, preserving country code and last 4.

    Replaces the identical ``_redact_phone()`` functions in signal.py,
    sms.py, and bluebubbles.py.
    """
    if not phone:
        return "<none>"
    if len(phone) <= 8:
        return phone[:2] + "****" + phone[-2:] if len(phone) > 4 else "****"
    return phone[:4] + "****" + phone[-4:]
