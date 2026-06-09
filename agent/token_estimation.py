"""Token estimation helpers shared by the agent loop and CLI tooling."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_tiktoken_encoder = None
_tiktoken_unavailable = False


def _get_tiktoken_encoder():
    global _tiktoken_encoder, _tiktoken_unavailable
    if _tiktoken_unavailable:
        return None
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    try:
        import tiktoken

        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:
        logger.debug("tiktoken unavailable; using chars/4 fallback")
        _tiktoken_unavailable = True
        _tiktoken_encoder = None
    return _tiktoken_encoder


def count_text_tokens(text: str) -> int:
    """Count tokens in a string; falls back to ~4 chars/token."""
    if not text:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return (len(text) + 3) // 4


def estimate_messages_tokens(
    messages: List[Dict[str, Any]],
    *,
    system_prompt: str = "",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Estimate tokens for a chat-completions request payload."""
    enc = _get_tiktoken_encoder()
    if enc is None:
        from agent.model_metadata import estimate_request_tokens_rough

        return estimate_request_tokens_rough(
            messages,
            system_prompt=system_prompt,
            tools=tools,
        )

    total = 0
    if system_prompt:
        total += len(enc.encode(system_prompt))
    for msg in messages:
        try:
            total += len(enc.encode(json.dumps(msg, ensure_ascii=False, separators=(",", ":"))))
        except (TypeError, ValueError):
            total += len(enc.encode(str(msg)))
    if tools:
        try:
            total += len(enc.encode(json.dumps(tools, ensure_ascii=False, separators=(",", ":"))))
        except (TypeError, ValueError):
            total += len(enc.encode(str(tools)))
    return total


def estimate_tool_schema_tokens(tools: List[Dict[str, Any]]) -> int:
    """Estimate tokens for an OpenAI-style tools list."""
    if not tools:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is None:
        return (len(str(tools)) + 3) // 4
    try:
        payload = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        payload = str(tools)
    return len(enc.encode(payload))
