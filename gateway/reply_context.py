"""Helpers for injecting quoted-reply context into inbound gateway messages."""

from __future__ import annotations

from typing import Callable, Optional


def resolve_quoted_text(
    event,
    *,
    chat_id: str,
    lookup_outbound: Optional[Callable[[str, str], Optional[str]]] = None,
) -> Optional[str]:
    """Return the text the user is replying to, from the event or outbound cache."""
    quoted = (getattr(event, "reply_to_text", None) or "").strip()
    if quoted:
        return quoted

    quote_id = getattr(event, "reply_to_message_id", None)
    if quote_id and lookup_outbound and chat_id:
        cached = (lookup_outbound(chat_id, str(quote_id)) or "").strip()
        if cached:
            return cached
    return None


def inject_reply_unavailable(message_text: str) -> str:
    """Note that the user is replying when the quoted body could not be resolved."""
    note = (
        "[O usuário está respondendo a uma mensagem anterior "
        "(texto da mensagem citada indisponível)]"
    )
    body = (message_text or "").strip()
    if body:
        return f"{note}\n\n{body}"
    return note


def inject_reply_context(message_text: str, quoted_text: str) -> str:
    """Prefix the user message with the quoted message they are responding to."""
    snippet = (quoted_text or "").strip()[:500]
    if not snippet:
        return message_text
    body = (message_text or "").strip()
    if body:
        return (
            f'[O usuário está respondendo à mensagem: «{snippet}»]\n\n'
            f'{body}'
        )
    return f'[O usuário está respondendo à mensagem: «{snippet}»]'
