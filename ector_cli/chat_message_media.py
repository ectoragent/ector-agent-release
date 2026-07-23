"""Parse and expose web-chat image attachments stored in session message text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.document_stack.markers import ECTOR_DOCUMENT_MARKER_PREFIX
from agent.vision_prompts import ECTOR_IMAGE_MARKER_PREFIX
from ector_cli.chat_media_paths import rewrite_markdown_image_paths

_IMAGE_MARKER_RE = re.compile(
    re.escape(ECTOR_IMAGE_MARKER_PREFIX) + r"([^>]+)-->",
)

_DOCUMENT_MARKER_RE = re.compile(
    re.escape(ECTOR_DOCUMENT_MARKER_PREFIX) + r"([^>]+)-->",
)

# Internal vision context blocks prepended during enrichment (PT + EN legacy).
_INTERNAL_IMAGE_BLOCK_RE = re.compile(
    r"\[(?:O usuário enviou uma imagem|The user attached an image)"
    r"[\s\S]*?\]\s*",
    re.IGNORECASE,
)

# Internal document/OCR context blocks — see agent/document_stack/markers.py.
# Distinct wording from _INTERNAL_IMAGE_BLOCK_RE (vision pre-analysis); this
# one wraps whatever the OCR fallback extracted and must stay hidden too.
_INTERNAL_DOCUMENT_BLOCK_RE = re.compile(
    r"\[Internal context from attached document[\s\S]*?\]\s*",
    re.IGNORECASE,
)

# Ephemeral RAG injection — never show in the user bubble.
_RAG_CONTEXT_RE = re.compile(
    r"<\s*rag-context\s*>[\s\S]*?</\s*rag-context\s*>\s*",
    re.IGNORECASE,
)

# Gateway reply / attachment notes prepended to the user text.
_REPLY_CONTEXT_RE = re.compile(
    r"\[O usuário está respondendo[^\]]*\]\s*",
    re.IGNORECASE,
)
_DOC_SENT_NOTE_RE = re.compile(
    r"\[O usuário enviou um documento[^\]]*\]\s*",
    re.IGNORECASE,
)

# Short agent-only notes (skill activate, MCP reload) — no nested ].
_AGENT_IMPORTANT_SHORT_RE = re.compile(
    r"\[(?:IMPORTANTE|IMPORTANT):\s*[^\]]*\]\s*",
    re.IGNORECASE,
)

# Entire user turn is a synthetic process/MCP notify (may contain ] in stdout).
_AGENT_IMPORTANT_SOLE_RE = re.compile(
    r"^\s*\[(?:IMPORTANTE|IMPORTANT):\s*"
    r"(?:O processo em segundo plano|Background process|"
    r"Os servidores MCP foram|MCP servers have been)"
    r"[\s\S]*\]\s*$",
    re.IGNORECASE,
)


def display_user_message_content(content: str) -> str:
    """User-visible text with internal agent/vision/OCR context removed."""
    if not content:
        return ""
    if _AGENT_IMPORTANT_SOLE_RE.match(content):
        return ""
    text = _INTERNAL_IMAGE_BLOCK_RE.sub("", content)
    text = _INTERNAL_DOCUMENT_BLOCK_RE.sub("", text)
    text = _RAG_CONTEXT_RE.sub("", text)
    text = _REPLY_CONTEXT_RE.sub("", text)
    text = _DOC_SENT_NOTE_RE.sub("", text)
    text = _AGENT_IMPORTANT_SHORT_RE.sub("", text)
    text = _IMAGE_MARKER_RE.sub("", text)
    text = _DOCUMENT_MARKER_RE.sub("", text)
    return text.strip()


def extract_stored_image_paths(content: str) -> list[str]:
    """Return absolute image paths embedded in a stored user message."""
    if not content:
        return []
    seen: set[str] = set()
    paths: list[str] = []
    for match in _IMAGE_MARKER_RE.finditer(content):
        raw = (match.group(1) or "").strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        paths.append(raw)
    return paths


def chat_image_basename(image_path: str) -> str:
    return Path(str(image_path or "").strip()).name


def chat_image_api_url(image_path: str) -> str:
    """Relative dashboard URL for a persisted chat image."""
    from ector_cli.chat_media_paths import chat_image_api_url as _api_url

    try:
        return _api_url(image_path)
    except ValueError:
        return ""


def attachments_for_stored_user_message(content: str) -> list[dict[str, Any]]:
    """Build dashboard attachment metadata from stored message content."""
    attachments: list[dict[str, Any]] = []
    for index, path in enumerate(extract_stored_image_paths(content)):
        name = chat_image_basename(path) or f"image-{index + 1}"
        url = chat_image_api_url(path)
        if not url:
            continue
        attachments.append(
            {
                "id": f"stored-{index}-{name}",
                "name": name,
                "url": url,
            }
        )
    return attachments


def prepare_session_messages_for_dashboard(
    messages: list[dict[str, Any]],
    *,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Sanitize user messages for the web dashboard history API."""
    prepared: list[dict[str, Any]] = []
    for msg in messages:
        row = dict(msg)
        if row.get("role") == "user":
            raw = row.get("content") or ""
            attachments = attachments_for_stored_user_message(raw)
            if attachments:
                row["attachments"] = attachments
            row["content"] = display_user_message_content(raw)
        elif row.get("role") == "assistant":
            row["content"] = rewrite_markdown_image_paths(
                str(row.get("content") or ""),
                session_id=session_id,
            )
        prepared.append(row)
    return prepared
